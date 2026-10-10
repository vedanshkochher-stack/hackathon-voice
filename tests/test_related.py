import hashlib
from datetime import timedelta

import numpy as np

import relprod
from ctxlayer import reader
from ctxlayer.util import iso, now
from relprod import RelatedStore
from tests.test_bot import _run

NAMES = ["Sintex Water Storage Tank 1000 L", "Overhead Water Tank", "Plastic Water Tank 500 Litre",
         "Water Level Controller", "Automatic Water Level Controller", "Float Valve 1 inch", "Water Filter Cartridge",
         "Submersible Pump 1 HP", "Cotton T Shirt", "PVC Pipe 4 inch", "Solvent Cement 100 ml", "PVC Pipe Fittings Tee",
         "Corrugated Box 5 Ply", "BOPP Packaging Tape"]
SYN = {"tank": "water", "controller": "water", "valve": "water", "cartridge": "water", "pump": "water",
       "cement": "pipe", "fittings": "pipe", "tape": "box"}


def fake_encode(texts, dim=64):
    """Deterministic bag-of-words vectors: shared words (plus a family word per part) = similar."""
    out = np.zeros((len(texts), dim), np.float32)
    for i, t in enumerate(texts):
        for w in t.lower().replace(",", " ").split():
            for x in (w, SYN.get(w)):
                if x:
                    out[i, int(hashlib.md5(x.encode()).hexdigest(), 16) % dim] += 1
    return out / np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-9)


def fake_store():
    return RelatedStore.from_vectors(NAMES, fake_encode(NAMES), encode=fake_encode)


def test_search_skips_the_lead_itself_duplicates_and_unrelated():
    got = fake_store().search([("Water Storage Tank", 1.0, "lead")], k=3, exclude=["water storage tank"])
    names = [r["name"] for r in got]
    assert len(names) == 3 and not any("Tank" in n for n in names)      # the same product again is not "related"
    assert sum("Level Controller" in n for n in names) <= 1             # one entry per kind of product
    assert "Cotton T Shirt" not in names and all(r["matched_by"] == "lead" for r in got)


def test_short_name_and_same_product():
    assert relprod.short_name("Sintex Water Tank 1000 L (Triple Layer)") == "Sintex Water Tank"
    assert relprod.same_product("Overhead Water Tank", "Water Storage Tank")
    assert not relprod.same_product("PVC Pipe Fittings Tee", "PVC Pipe")
    assert relprod.same_product("Corrugated Packaging Boxes", "Corrugated Box")       # -es plural
    assert relprod.same_product("Solvent Storage Tank", "Water Storage Tank")         # no fuzzy catalogue alias
    assert not relprod.same_product("CPVC Pipe", "PVC Pipe")                          # distinct catalogue products


def _csv(path, rows):
    path.write_text("PC_ITEM_NAME,PC_IMG_SMALL_100X100\n" + "".join(f"{r},\n" for r in rows), encoding="utf-8")
    return path


def test_store_is_built_from_the_csv_saved_and_loaded_back(tmp_path):
    from relprod import store

    path = _csv(tmp_path / "pc_items.csv", ["Water Level Controller", "Float  Valve 1 inch",
                                            "water level controller", ""])   # header case as Oracle exports it
    out = tmp_path / "idx"
    assert RelatedStore.load(path, out, fake_encode) is None
    built = RelatedStore.build(path, out, encode=fake_encode)
    assert built.names == ["Water Level Controller", "Float Valve 1 inch"] and len(built) == 2
    loaded = RelatedStore.load(path, out, fake_encode)
    assert loaded.names == built.names and len(loaded) == 2
    q = [("Water Storage Tank", 1.0, "lead")]
    assert loaded.search(q, exclude=["water storage tank"]) == built.search(q, exclude=["water storage tank"])
    _csv(path, ["Ball Valve"])                                   # CSV changed: the saved store is stale
    assert RelatedStore.load(path, out, fake_encode) is None
    path.write_text('"glcat_mcat_name"\nWater Level Controller\n"Float Valve"\n', encoding="utf-8")  # MCAT export
    assert RelatedStore.build(path, out, encode=fake_encode).names == ["Water Level Controller", "Float Valve"]
    (tmp_path / "bad.csv").write_text("id,city\n1,Pune\n", encoding="utf-8")
    try:
        RelatedStore.build(tmp_path / "bad.csv", tmp_path / "bad", encode=fake_encode)
        raise AssertionError("expected a missing-column error")
    except ValueError as e:
        assert "glcat_mcat_name" in str(e)
    _csv(path, ["Ball Valve"])
    assert RelatedStore.load(path, out, fake_encode) is None
    store._build(tmp_path / "missing.csv")
    assert relprod.status()["state"] == "missing"


def test_a_stopped_build_resumes_from_its_checkpoint(tmp_path, monkeypatch):
    from relprod import store

    monkeypatch.setattr(store, "CHUNK", 2)
    monkeypatch.setattr(store, "CHECKPOINT_EVERY", 1)
    path = _csv(tmp_path / "pc_items.csv", NAMES)
    out, seen = tmp_path / "idx", []

    def dies_after_two_chunks(texts):
        if len(seen) == 2:
            raise RuntimeError("killed")
        seen.append(texts)
        return fake_encode(texts)

    try:
        RelatedStore.build(path, out, encode=dies_after_two_chunks)
    except RuntimeError:
        pass
    assert RelatedStore.load(path, out, fake_encode) is None             # unfinished: never served
    resumed = []
    st = RelatedStore.build(path, out, encode=lambda t: resumed.append(t) or fake_encode(t))
    assert len(st) == len(NAMES) and sum(map(len, resumed)) == len(NAMES) - 4    # first 4 names not redone
    assert RelatedStore.load(path, out, fake_encode).names == NAMES


def test_liked_and_viewed_products_from_the_context_drive_the_match(env):
    relprod.set_store(fake_store())
    _, ref, _ = env
    t = now()
    ev = lambda typ, ago_h, **p: {"glid": "50113001", "role": "buyer", "type": typ, "source": "app_events",
                                  "occurred_at": iso(t - timedelta(hours=ago_h)), "payload": p}
    ref.ingest([ev("profile.update", 50, name="Neha", city="Pune", language="hi"),
                ev("enquiry.created", 20, enq_id="ENQ-1", product="PVC Pipe", quantity=100, unit="Piece",
                   channel="website"),
                ev("product.view", 10, product="Corrugated Box", platform="app"),
                ev("product.like", 5, product="Float Valve", platform="app", mobile="+91 90000 11111")], trigger="live")
    ref.wait_idle(5)
    meta = reader.read("50113001", "buyer").meta
    assert {"product": "Float Valve", "via": "liked", "liked": True}.items() <= meta["interests"][0].items()
    assert "90000" not in reader.read("50113001", "buyer").raw                  # privacy whitelist on new events
    res = relprod.for_buyer(meta)
    assert (res["lead"], res["liked"], res["viewed"]) == ("PVC Pipe", ["Float Valve"], ["Corrugated Box"])
    assert res["source"] == "vector_store" and len(res["items"]) == 3
    labels = {r["matched_by"] for r in res["items"]}
    assert "lead" in labels and labels & {"liked: Float Valve", "viewed: Corrugated Box"}
    assert not any(relprod.same_product(r["name"], "PVC Pipe") for r in res["items"])


def test_api_takes_a_glid_and_reads_the_buyer_context():
    from fastapi.testclient import TestClient

    from server.app import app

    relprod.set_store(fake_store())
    with TestClient(app) as client:
        r = client.get("/api/related/50112004").json()      # Sunita: BL for Water Storage Tank, nothing else
        assert r["lead"] == "Water Storage Tank" and r["liked"] == r["viewed"] == []
        assert len(r["items"]) == 3 and r["store"]["state"] == "ready"
        assert client.get("/api/related/50119999").status_code == 404     # no buyer context
        assert client.get("/api/related/50112004?k=0").status_code == 400


def test_bl_only_buyer_says_no_and_hears_related_products(env):
    relprod.set_store(fake_store())
    _, _, eng = env
    r, s, replies = _run(eng, "50112004", "buyer", "voice", ["No", "doosra wala", "4 piece"])
    assert r["scenario"] == "resume_pending" and "Water Storage Tank" in r["opening"]
    assert "Water Storage Tank ki requirement nahi hai" in replies[0] and "se jude products" in replies[0]
    a, b = s.suggestions
    assert a in replies[0] and b in replies[0] and "Tank" not in a + b
    assert len(s.related) == 3 and eng._state(s)["related"] == s.related
    assert s.product == b and s.slots["quantity"] == "4 Piece"     # picked by ordinal, no re-confirmation
    assert "name" not in s.asks and "city" not in s.asks             # Sunita, Jaipur are known
    assert s.metrics["reasks_of_known"] == 0


def test_buyer_can_name_the_third_item_that_was_not_read_out(env):
    relprod.set_store(fake_store())
    _, _, eng = env
    r = eng.start("50112004", "buyer", "voice", reply_mode="template")
    s = eng.sessions[r["session_id"]]
    first = eng.message(s.id, "nahi chahiye ab")["reply"]
    unspoken = s.related[2]["product"]
    assert unspoken not in first and unspoken not in s.suggestions
    second = eng.message(s.id, f"{unspoken.lower()} chahiye")["reply"]
    assert s.product == unspoken and not s.ended and "kitne" in second


def test_while_the_store_is_not_ready_it_falls_back_to_catalogue_co_purchase():
    relprod.set_store(None)
    res = relprod.for_buyer({"open_thread": {"product": "Water Storage Tank"}})
    assert res["source"] == "catalog" and [x["product"] for x in res["items"]] == ["PVC Pipe", "Pipe Fittings"]


def test_buyer_with_history_still_hears_only_their_own_history(env):
    relprod.set_store(fake_store())
    _, _, eng = env
    _, s, replies = _run(eng, "50112003", "buyer", "whatsapp", ["nahi"])
    assert not s.related and "se jude products" not in replies[0]


def test_google_grounding_titles_cached_and_failures_ignored(tmp_path, monkeypatch):
    import httpx

    from relprod import grounding as g

    calls = []

    def fake_get(url, params, timeout):
        calls.append(params["q"])
        if "Broken" in params["q"]:
            raise httpx.ConnectTimeout("slow")
        return httpx.Response(200, request=httpx.Request("GET", url), json={"items": [
            {"title": "Water Level Controller - Automatic | Brand", "link": "https://a"},
            {"title": "Float Valve: Buy Online...", "link": "https://b"}]})

    monkeypatch.setattr(g, "CACHE", tmp_path / "g.json")
    monkeypatch.setattr(g, "_mem", None)
    monkeypatch.setattr(g, "available", lambda: True)
    monkeypatch.setattr(g.httpx, "get", fake_get)
    first = g.google_related("Water Storage Tank")
    assert first == {"queries": ["Water Level Controller", "Float Valve"], "sources": ["https://a", "https://b"]}
    assert g.google_related("water storage tank ") == first and len(calls) == 1      # cached per product
    assert g.google_related("Broken Thing") == {"queries": [], "sources": []}         # timeout: skipped


def test_sarvam_complements_are_matched_to_real_items(tmp_path, monkeypatch):
    from relprod import grounding as g

    calls = []

    class FakeSarvam:
        def __init__(self, reply):
            self.reply = reply

        def extract_json(self, system, user):
            calls.append(user)
            return self.reply

    monkeypatch.setattr(g, "CACHE", tmp_path / "g.json")
    monkeypatch.setattr(g, "_mem", None)
    monkeypatch.setattr(g, "llm_available", lambda: True)
    monkeypatch.setattr(g, "_llm", FakeSarvam({"products": ["Water Level Controller", "water storage tank",
                                                            "Float Valve", "Float Valve", "x" * 0, 42]}))
    assert g.llm_complements("Water Storage Tank") == ["Water Level Controller", "Float Valve"]
    assert g.llm_complements("water storage tank ") == ["Water Level Controller", "Float Valve"]
    assert len(calls) == 1                                                          # cached per lead
    monkeypatch.setattr(g, "_llm", FakeSarvam(None))                                 # LLM down / timed out
    assert g.llm_complements("Solar Panel") == [] and "llm:solar panel" not in g._cache()

    relprod.set_store(fake_store())
    monkeypatch.setattr(g, "_llm", FakeSarvam({"products": ["Submersible Pump"]}))
    res = relprod.for_buyer({"open_thread": {"product": "Pressure Pump Tank"}})
    assert res["grounding"]["llm"] == ["Submersible Pump"]
    assert any(r["matched_by"] == "llm: Submersible Pump" and r["name"] == "Submersible Pump 1 HP" for r in res["items"])
