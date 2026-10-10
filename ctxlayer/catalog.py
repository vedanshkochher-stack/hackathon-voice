from __future__ import annotations

import json
import re
from functools import lru_cache

from .config import DATA_DIR


@lru_cache(maxsize=1)
def _cat() -> dict:
    return json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))


def product(name: str | None) -> dict | None:
    if not name:
        return None
    return _cat()["products"].get(canonical_product(name) or "", None)


def _has(term: str, text: str) -> bool:
    if term.isascii():  # word boundaries so "pvc pipe" does not match inside "cpvc pipe"
        return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"s?(?![a-z0-9])", text) is not None
    return term in text


def canonical_product(text: str | None) -> str | None:
    if not text:
        return None
    t = text.strip().lower()
    prods = _cat()["products"]
    for p in prods:
        if p.lower() == t:
            return p
    hits = [p for p in prods if _has(p.lower(), t)]
    if hits:
        return max(hits, key=len)
    for alias in sorted(_cat()["aliases"], key=len, reverse=True):  # "water tank" before "tank"
        if _has(alias, t):
            return _cat()["aliases"][alias]
    return None


def product_names() -> list[str]:
    return list(_cat()["products"])


def units(name: str) -> list[str]:
    p = product(name)
    return p["units"] if p else []


def specs(name: str) -> dict[str, list[str]]:
    p = product(name)
    return p["specs"] if p else {}


def purpose(name: str, lang: str) -> str:
    p = product(name)
    if not p:
        return ""
    return p["purpose"].get(lang, p["purpose"]["en"])


def related(name: str | None) -> list[str]:
    """Products commonly bought with this one (MCAT co-purchase stand-in)."""
    p = product(name)
    return list(p.get("related", [])) if p else []


def mcat(name: str) -> str:
    p = product(name)
    return p["mcat"] if p else name


def cities() -> dict[str, str]:
    return _cat()["cities"]


def city_aliases() -> dict[str, str]:
    return _cat()["city_aliases"]


def state_of(city: str | None) -> str | None:
    return cities().get(city or "")


def all_states() -> list[str]:
    return sorted(set(cities().values()))
