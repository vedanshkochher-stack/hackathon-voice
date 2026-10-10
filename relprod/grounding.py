"""Complement grounding: what a buyer of the lead needs alongside it.

Embedding similarity alone finds *similar* items (other tanks for a tank). Two sources name the
*complementary* ones (level controller, float valve), and each name becomes an extra retrieval query,
so the answer is always a real item from the store:
  - Sarvam LLM (on when SARVAM_API_KEY is set): accessories, spares, consumables, services for the lead;
  - Google Programmable Search (on when GOOGLE_API_KEY + GOOGLE_CSE_ID are set): result titles.
Results are cached on disk per lead. Failures and timeouts return nothing and are retried next time.
"""
from __future__ import annotations

import json
import re
import threading

import httpx

from ctxlayer.config import (GOOGLE_API_KEY, GOOGLE_CSE_ID, GROUNDING_TIMEOUT_S, PC_ITEM_DIR, RELATED_LLM,
                             RELATED_LLM_TIMEOUT_S, SARVAM_API_KEY)

CACHE = PC_ITEM_DIR / "grounding_cache.json"
_lock = threading.Lock()
_mem: dict[str, dict] | None = None
_llm = None
LLM_SYSTEM = (
    "You are an IndiaMART B2B catalogue expert. Given a product a buyer asked for, list other products the same "
    "buyer commonly needs with it: accessories, spare parts, consumables, complementary equipment or installation "
    "services. Never list the product itself or its sizes, brands or variants. Use short generic Indian B2B "
    'catalogue names of 2-4 words. Reply with JSON only: {"products": ["...", "..."]}')


def available() -> bool:
    return bool(GOOGLE_API_KEY and GOOGLE_CSE_ID)


def llm_available() -> bool:
    return RELATED_LLM == "sarvam" and bool(SARVAM_API_KEY)


def _sarvam():
    global _llm
    if _llm is None:
        from bot.llm import SarvamLLM
        _llm = SarvamLLM(timeout=RELATED_LLM_TIMEOUT_S)
    return _llm


def _cache() -> dict[str, dict]:
    global _mem
    if _mem is None:
        try:
            _mem = json.loads(CACHE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _mem = {}
    return _mem


def _title(t: str) -> str:
    """'Water Level Controller - Automatic | Brand' -> 'Water Level Controller'"""
    return re.split(r"\s*[|•·:]\s+|\s+[-–—]\s+", t)[0].rstrip(". ").strip()  # 'T-Shirt' stays whole


def _remember(key: str, value):
    with _lock:
        _cache()[key] = value
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_cache(), ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(CACHE)


def llm_complements(product: str, n: int = 5) -> list[str]:
    """Up to n complementary product names for `product` from the Sarvam LLM; [] when off or failed."""
    key = "llm:" + product.strip().lower()
    with _lock:
        if key in _cache():
            return _cache()[key]
    if not llm_available():
        return []
    j = _sarvam().extract_json(LLM_SYSTEM, f"Product: {product}\nList {n} products.")
    raw = (j or {}).get("products")
    if not isinstance(raw, list):
        return []  # not cached: try again next time
    names = []
    for p in raw:
        if not isinstance(p, str):
            continue
        p = " ".join(p.split()).strip(" .-")
        if p and 1 <= len(p.split()) <= 6 and p.lower() != product.strip().lower() and p.lower() not in map(str.lower, names):
            names.append(p)
    _remember(key, names[:n])
    return names[:n]


def complements(product: str) -> dict:
    """{"llm": [names], "google": [titles], "sources": [links]} for the lead."""
    g = google_related(product)
    return {"llm": llm_complements(product), "google": g["queries"], "sources": g["sources"]}


def google_related(product: str, n: int = 6) -> dict:
    """{"queries": [result titles], "sources": [links]}; empty when not configured, failed or timed out."""
    key = product.strip().lower()
    with _lock:
        if key in _cache():
            return _cache()[key]
    if not available():
        return {"queries": [], "sources": []}
    try:
        r = httpx.get("https://www.googleapis.com/customsearch/v1", timeout=GROUNDING_TIMEOUT_S,
                      params={"key": GOOGLE_API_KEY, "cx": GOOGLE_CSE_ID, "num": n, "gl": "in",
                              "q": f"{product} accessories and related products"})
        r.raise_for_status()
        items = r.json().get("items", [])
    except (httpx.HTTPError, ValueError):
        return {"queries": [], "sources": []}  # not cached: try again next time
    out = {"queries": list(dict.fromkeys(q for q in (_title(i.get("title", "")) for i in items) if q)),
           "sources": [i.get("link") for i in items if i.get("link")]}
    _remember(key, out)
    return out
