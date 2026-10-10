"""In-memory FAISS store of pc_item names, and for_buyer(): the top related products for one buyer.

The queries come from the buyer's own context (buyer.md frontmatter), nothing else:
  current lead     open_thread.product, or the BL the buyer just withdrew on a call     weight 1.0
  liked products   interests[] liked                                                     weight 0.9
  viewed products  interests[] viewed, searched or called a seller about                 weight 0.8
  complements of the lead named by the Sarvam LLM (when SARVAM_API_KEY is set)          weight 0.85
  (optional) Google result titles for the lead, when GOOGLE_API_KEY / GOOGLE_CSE_ID are set    0.8
Each pc_item keeps its best weighted cosine over the queries. Related means a *different* product from the
lead: embeddings rank "Sintex Water Storage Tank" (0.87) above "Water Level Controller" (0.83) for a "Water
Storage Tank" lead, so no threshold separates them, and an item whose head noun or catalogue product is the
lead's is skipped instead.
"""
from __future__ import annotations

import csv
import fcntl
import json
import logging
import re
import threading
import time
from pathlib import Path

import faiss
import numpy as np

from ctxlayer import catalog
from ctxlayer.config import ITEM_NAME_COLUMNS, NAME_MODEL, PC_ITEM_CSV, PC_ITEM_DIR, RELATED_TOP_K

from . import grounding
from .encoders import embed_names

log = logging.getLogger(__name__)
WEIGHTS = {"lead": 1.0, "liked": 0.9, "llm": 0.85, "viewed": 0.8, "google": 0.8}
POOLS = (200, 2000)   # candidates per query; the wider pool only when filters leave fewer than k
NEAR_DUP = 0.95       # cosine between two picked names above this = the same item listed twice
MIN_COS = 0.25        # below this a match is unrelated (a T-shirt scores 0.16 for a PVC pipe)
CHUNK = 20_000        # names embedded per step
CHECKPOINT_EVERY = 10  # chunks between checkpoints: a stopped build resumes, it does not start over

_UNIT = (r"(mm|cm|m|mtr|meter|metre|inch|inches|in|ft|feet|kg|kgs|g|gm|gms|ml|l|ltr|litre|liter|lph|hp|kw|kva|"
         r"w|watt|v|volt|pcs|pc|piece|pieces|nos|gsm|micron|ply|sq|ton|tons)")


def short_name(name: str) -> str:
    """Speakable product name: 'Sintex Water Tank 1000 L (Triple Layer)' -> 'Sintex Water Tank'."""
    s = re.sub(r"\(.*?\)|\[.*?\]", " ", name)
    s = re.sub(rf"\b\d+(\.\d+)?\s*{_UNIT}?\b", " ", s, flags=re.I)
    s = re.sub(r"[^A-Za-z&\s]", " ", s)
    words = s.split()[:4]
    return " ".join(w if w.isupper() else w.capitalize() for w in words) or name.strip()


def _singular(w: str) -> str:
    if len(w) > 4 and w.endswith(("xes", "ches", "shes", "sses", "zes")):
        return w[:-2]                    # boxes -> box, benches -> bench, glasses -> glass
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def _words(name: str) -> list[str]:
    return [_singular(w) for w in short_name(name).lower().split()]


def _catalog_name(name: str) -> str | None:
    """The catalogue product this exact name is. No fuzzy aliases: on real item names they misfire
    ('Solvent Storage Tank' would read as Solvent Cement)."""
    return {p.lower(): p for p in catalog.product_names()}.get(name.strip().lower())


def same_product(cand: str, other: str) -> bool:
    """Same head noun = same product ('Solvent Storage Tank' for a Water Storage Tank lead), unless both are
    distinct catalogue products ('CPVC Pipe' is related to 'PVC Pipe', not the same)."""
    cc, co = _catalog_name(cand), _catalog_name(other)
    if cc and co:
        return cc == co
    a, b = _words(cand), _words(other)
    return bool(a and b and a[-1] == b[-1])


def read_names(path) -> list[str]:
    """Unique item names (case-insensitive) from the first ITEM_NAME_COLUMNS column in the header, in file order."""
    seen, out = set(), []
    csv.field_size_limit(1 << 27)   # some export columns are long; only the name is kept
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        header = {h.strip().lower(): h for h in reader.fieldnames or []}
        col = next((header[c] for c in ITEM_NAME_COLUMNS if c in header), None)
        if col is None:
            raise ValueError(f"{path}: no {' / '.join(ITEM_NAME_COLUMNS)} column in {list(header)}")
        for row in reader:
            name = " ".join((row.get(col) or "").split())
            if name and name.lower() not in seen:
                seen.add(name.lower())
                out.append(name)
    return out


def _new_index(dim: int):
    """fp16 vectors, exact inner-product search: 1.89M names in ~1.45 GB instead of 2.9 GB, cosines to ~3 decimals."""
    return faiss.IndexScalarQuantizer(dim, faiss.ScalarQuantizer.QT_fp16, faiss.METRIC_INNER_PRODUCT)


def _files(out_dir: Path) -> tuple[Path, Path, Path]:
    return out_dir / "names.faiss", out_dir / "names.txt", out_dir / "names.json"


def _fingerprint(csv_path: Path) -> dict:
    st = csv_path.stat()
    return {"csv": str(csv_path), "csv_size": st.st_size, "csv_mtime": int(st.st_mtime), "model": NAME_MODEL}


def _save(out_dir: Path, index, meta: dict):
    idx_path, _, meta_path = _files(out_dir)
    faiss.write_index(index, str(idx_path.with_suffix(".tmp")))
    idx_path.with_suffix(".tmp").replace(idx_path)
    meta_path.write_text(json.dumps({**meta, "done": index.ntotal}))   # written last: it vouches for the index


class RelatedStore:
    def __init__(self, names: list[str], index, encode=embed_names):
        self.names, self.index, self.encode = list(names), index, encode

    @classmethod
    def from_vectors(cls, names: list[str], vectors: np.ndarray, encode=embed_names) -> RelatedStore:
        index = _new_index(vectors.shape[1])
        index.add(np.ascontiguousarray(vectors, dtype=np.float32))
        return cls(names, index, encode)

    @classmethod
    def load(cls, csv_path=PC_ITEM_CSV, out_dir=PC_ITEM_DIR, encode=embed_names) -> RelatedStore | None:
        """The saved store, or None when it is missing, unfinished, or built from another CSV or model."""
        idx_path, names_path, meta_path = _files(out_dir)
        try:
            meta = json.loads(meta_path.read_text())
        except (OSError, ValueError):
            return None
        if not meta.get("complete") or {k: meta.get(k) for k in ("csv_size", "csv_mtime", "model")} != \
                {k: v for k, v in _fingerprint(csv_path).items() if k != "csv"}:
            return None
        names = names_path.read_text(encoding="utf-8").split("\n")
        index = faiss.read_index(str(idx_path))
        return cls(names, index, encode) if index.ntotal == len(names) else None

    @classmethod
    def build(cls, csv_path=PC_ITEM_CSV, out_dir=PC_ITEM_DIR, encode=embed_names, progress=None) -> RelatedStore:
        """Embed every name chunk by chunk into the index, checkpointing to out_dir; resumes a stopped build."""
        out_dir.mkdir(parents=True, exist_ok=True)
        idx_path, names_path, meta_path = _files(out_dir)
        fp = _fingerprint(csv_path)
        names = read_names(csv_path)
        index = None
        try:
            meta = json.loads(meta_path.read_text())
            if {**fp, "items": len(names)} == {k: meta.get(k) for k in (*fp, "items")} and not meta.get("complete"):
                index = faiss.read_index(str(idx_path))
                log.info("relprod: resuming the build at %d/%d", index.ntotal, len(names))
        except (OSError, ValueError, RuntimeError):
            index = None
        if index is None:
            meta_path.unlink(missing_ok=True)
            names_path.write_text("\n".join(names), encoding="utf-8")
        meta = {**fp, "items": len(names), "complete": False}
        t0, start = time.perf_counter(), index.ntotal if index else 0
        for n, i in enumerate(range(start, len(names), CHUNK), 1):
            vecs = encode(names[i:i + CHUNK])
            index = index or _new_index(vecs.shape[1])
            index.add(np.ascontiguousarray(vecs, dtype=np.float32))
            if progress:
                progress(index.ntotal, len(names), (index.ntotal - start) / (time.perf_counter() - t0))
            if n % CHECKPOINT_EVERY == 0:
                _save(out_dir, index, meta)
        index = index or _new_index(encode(["x"]).shape[1])
        _save(out_dir, index, {**meta, "complete": True})
        return cls(names, index, encode)

    def __len__(self):
        return self.index.ntotal

    def search(self, queries: list[tuple[str, float, str]], k: int = RELATED_TOP_K, exclude=()) -> list[dict]:
        """queries: (text, weight, label). Best weighted cosine per item, minus excluded and duplicate kinds."""
        vecs = np.ascontiguousarray(self.encode([q for q, _, _ in queries]), dtype=np.float32)
        for pool in POOLS:   # a lead with many same-product neighbours ('... Box') needs a wider pool
            out = self._pick(queries, vecs, min(pool, len(self)), k, exclude)
            if len(out) == k or pool >= len(self):
                break
        return out

    def _pick(self, queries, vecs, pool: int, k: int, exclude) -> list[dict]:
        best: dict[int, tuple[float, float, str]] = {}   # item -> (weighted score, cosine, label)
        sims, ids = self.index.search(vecs, pool)   # all queries in one scan
        for (_, w, label), row_s, row_i in zip(queries, sims.tolist(), ids.tolist()):
            for c, j in zip(row_s, row_i):
                if j >= 0 and (j not in best or w * c > best[j][0]):
                    best[j] = (w * c, c, label)
        out, kinds, picked = [], set(), []
        for j in sorted(best, key=lambda j: best[j][0], reverse=True):
            score, cos, label = best[j]
            name = self.names[j]
            kind = " ".join(_words(name)[-2:])   # 'level controller': one entry per kind of product
            if cos < MIN_COS or kind in kinds or any(same_product(name, e) for e in exclude):
                continue
            vec = self.index.reconstruct(j)
            if any(float(vec @ p) > NEAR_DUP for p in picked):
                continue
            kinds.add(kind)
            picked.append(vec)
            out.append({"product": short_name(name), "name": name, "score": round(score, 3), "matched_by": label})
            if len(out) == k:
                break
        return out


def _same_item(a: str, b: str | None) -> bool:
    if not b:
        return False
    ca = catalog.canonical_product(a)
    return a.lower() == b.lower() or (ca is not None and ca == catalog.canonical_product(b))


def buyer_inputs(meta: dict, lead: str | None = None) -> dict:
    """What the match is built from, straight from the buyer's context file."""
    lead = lead or (meta.get("open_thread") or {}).get("product")
    liked, viewed = [], []
    for i in meta.get("interests") or []:
        p = i.get("product")
        if p and not _same_item(p, lead):
            (liked if i.get("liked") or i.get("via") == "liked" else viewed).append(p)
    return {"lead": lead, "liked": liked, "viewed": viewed}


def _queries(inp: dict, g: dict | None = None) -> list[tuple[str, float, str]]:
    """Weighted queries: the lead, what the buyer liked / viewed, and complements of the lead (LLM, Google)."""
    g = g or {}
    q = [(inp["lead"], WEIGHTS["lead"], "lead")] if inp["lead"] else []
    q += [(p, WEIGHTS["liked"], f"liked: {p}") for p in inp["liked"]]
    q += [(p, WEIGHTS["viewed"], f"viewed: {p}") for p in inp["viewed"]]
    q += [(p, WEIGHTS["llm"], f"llm: {p}") for p in g.get("llm", [])]
    return q + [(t, WEIGHTS["google"], f"google: {t}") for t in g.get("google", [])]


_store: RelatedStore | None = None
_status = {"state": "idle", "items": 0, "total": None, "rate": None, "csv": str(PC_ITEM_CSV), "seconds": None}
_lock = threading.Lock()
_cache: dict[tuple, dict] = {}


def start_loading(path=PC_ITEM_CSV):
    """Load (or build) the store in a background thread, once per process (the server calls this at start)."""
    with _lock:
        if _status["state"] != "idle":
            return
        _status.update(state="loading", csv=str(path))
    threading.Thread(target=_build, args=(path,), daemon=True).start()


def _progress(done: int, total: int, rate: float):
    _status.update(items=done, total=total, rate=round(rate))
    log.info("relprod: embedded %d/%d names, %.0f/s, ~%.0f min left", done, total, rate, (total - done) / rate / 60)


def load_or_build(path=PC_ITEM_CSV, out_dir=PC_ITEM_DIR, progress=_progress) -> RelatedStore:
    """Saved store if it matches the CSV + model; otherwise build it. One builder at a time across processes:
    a second process waits for the first one's build and then loads it."""
    st = RelatedStore.load(path, out_dir)
    if st is not None:
        return st
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "build.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _status["state"] = "waiting for another build"
            fcntl.flock(lock, fcntl.LOCK_EX)
        st = RelatedStore.load(path, out_dir)
        if st is None:
            _status["state"] = "building"
            st = RelatedStore.build(path, out_dir, progress=progress)
    return st


def _build(path):
    global _store
    if not path.exists():
        log.warning("relprod: %s missing; using catalogue co-purchase fallback", path)
        _status["state"] = "missing"
        return
    t0 = time.perf_counter()
    try:
        st = load_or_build(path)
    except Exception:
        log.exception("relprod: loading / building the store from %s failed", path)
        _status["state"] = "failed"
        return
    with _lock:
        _store = st
        _status.update(state="ready", items=len(st), total=len(st), seconds=round(time.perf_counter() - t0, 1))
        _cache.clear()   # drop catalogue-fallback answers given while building
    log.info("relprod: %d items in memory in %.1fs", len(st), _status["seconds"])


def get_store() -> RelatedStore | None:
    """The in-memory store, or None while it is still building (or the CSV is missing). Never blocks."""
    start_loading()
    return _store


def status() -> dict:
    return dict(_status)


def set_store(store: RelatedStore | None):
    """Tests / tools: use this store instead of building one from the CSV."""
    global _store
    with _lock:
        _store = store
        _status.update(state="ready" if store is not None else "missing", items=len(store) if store else 0)
        _cache.clear()


def for_buyer(meta: dict, lead: str | None = None, k: int = RELATED_TOP_K, exclude=()) -> dict:
    """Top-k related products for a buyer from their context: {"lead", "liked", "viewed", "items", "source",
    "grounding"}. `lead` overrides open_thread (e.g. the BL just withdrawn on a call). Never raises."""
    inp = buyer_inputs(meta or {}, lead)
    excl = sorted({e.strip().lower() for e in (inp["lead"], *exclude) if e})
    key = (tuple(_queries(inp)), k, tuple(excl))
    if key in _cache:
        return _cache[key]
    empty = {"llm": [], "google": [], "sources": []}
    try:
        g = grounding.complements(inp["lead"]) if inp["lead"] else empty
        queries = _queries(inp, g)
        st = get_store()
        if not queries:
            res = {**inp, "items": [], "source": "none", "grounding": g}
        elif st is not None and len(st):
            res = {**inp, "items": st.search(queries, k, excl), "source": "vector_store", "grounding": g}
        else:   # store not ready: MCAT co-purchases of the lead and of what they liked / viewed
            items, seen = [], set()
            for q, _, _ in queries:
                for p in catalog.related(q):
                    if p not in seen and not any(same_product(p, e) for e in excl):
                        seen.add(p)
                        items.append({"product": p, "name": p, "score": None, "matched_by": f"catalog: {q}"})
            res = {**inp, "items": items[:k], "source": "catalog" if items else "none", "grounding": g}
    except Exception:  # never break a live call over a suggestion
        log.exception("relprod lookup failed for %r", inp)
        return {**inp, "items": [], "source": "none", "grounding": empty}
    _cache[key] = res
    return res


def prefetch(meta: dict, lead: str | None = None):
    """Warm the cache in the background at call start, so the 'no' turn answers instantly."""
    threading.Thread(target=for_buyer, args=(meta, lead), daemon=True).start()
