"""Privacy by construction + a runtime leak guard.

1. Ingestion whitelist: each event type keeps only the fields the files need. Phone, email,
   address, GSTIN, buyer names inside seller leads etc. are dropped *before* they reach the store,
   so no downstream consumer (bot, dashboard, campaign) can leak what it never had.
2. Free-text scrubbing: summaries, notes and search queries are regex-scrubbed for phone, email,
   GSTIN, PAN and Aadhaar-like numbers.
3. Runtime leak guard: before a bot reply is spoken/sent, it is checked against entities that
   belong to *other* GLIDs' files (names, companies) and against contact-detail patterns.
"""
from __future__ import annotations

import re
from collections import Counter

ALLOWED_FIELDS: dict[str, set[str]] = {
    "profile.update": {"name", "city", "state", "language", "company", "contact_name"},
    "kyc.update": {"mobile_verified", "email_verified", "gst_verified", "bank_verified"},
    "source.status": {"source", "status"},
    "search": {"query", "mcat", "platform"},
    "product.view": {"product", "mcat", "platform"},   # buyer opened a product page
    "product.like": {"product", "mcat", "platform"},   # buyer liked / shortlisted a product
    "enquiry.created": {"enq_id", "product", "quantity", "unit", "specs", "city", "channel"},
    "enquiry.update": {"enq_id", "quantity", "unit", "specs"},
    "enquiry.status": {"enq_id", "status", "note"},
    "pns.call": {"seller_glid", "seller_name", "seller_city", "product", "answered", "duration_s",
                 "buyer_city", "buyer_state"},
    "conversation.update": {"session_id", "channel", "bot", "product", "captured", "pending", "notes",
                            "outcome", "summary", "lang"},
    "conversation.ended": {"session_id", "channel", "bot", "product", "captured", "pending", "notes",
                           "outcome", "summary", "lang"},
    "lead.received": {"lead_id", "product", "quantity", "unit", "specs", "buyer_city", "buyer_state", "via"},
    "lead.response": {"lead_id", "action", "outcome"},
    "catalog.update": {"products"},
    "engagement": {"kind", "count"},
}
CAPTURED_KEYS_DENY = {"mobile", "phone", "email", "address", "gstin", "pan", "aadhaar"}
FIRST_NAME_ONLY = {"name", "contact_name"}

_PATTERNS = [
    ("phone", re.compile(r"(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}\b")),
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    ("gstin", re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b")),
    ("pan", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("aadhaar", re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")),
]

audit = Counter()  # field/pattern -> how many times it was dropped (shown in the demo UI)


def scrub_text(text: str | None) -> str | None:
    if not text:
        return text
    for name, pat in _PATTERNS:
        text, n = pat.subn("[redacted]", text)
        if n:
            audit[f"text:{name}"] += n
    return text


def _first(name: str | None) -> str | None:
    return name.split()[0] if name else name


def sanitize(ev: dict) -> dict:
    """Return a copy of a raw source event that only carries whitelisted, scrubbed fields."""
    ev = dict(ev)
    allowed = ALLOWED_FIELDS.get(ev["type"])
    payload = dict(ev.get("payload") or {})
    if allowed is not None:
        for k in list(payload):
            if k not in allowed:
                audit[f"field:{k}"] += 1
                payload.pop(k)
    for k in FIRST_NAME_ONLY & payload.keys():
        payload[k] = _first(payload[k])
    for k in ("summary", "query", "note"):
        if isinstance(payload.get(k), str):
            payload[k] = scrub_text(payload[k])
    if isinstance(payload.get("notes"), list):
        payload["notes"] = [scrub_text(n) for n in payload["notes"]]
    if isinstance(payload.get("captured"), dict):
        cap = {}
        for k, v in payload["captured"].items():
            if k.lower() in CAPTURED_KEYS_DENY:
                audit[f"field:captured.{k}"] += 1
                continue
            v = _first(v) if k == "name" and isinstance(v, str) else v
            cap[k] = scrub_text(v) if isinstance(v, str) else v
        payload["captured"] = cap
    ev["payload"] = payload
    return ev


# ---------------- runtime leak guard ----------------
_CONTACT = [p for n, p in _PATTERNS if n in ("phone", "email", "gstin")]


def foreign_entities(own_text: str, all_entities: dict[str, set[str]], own_glid: str) -> set[str]:
    """Entities that appear in other GLIDs' files but not in this GLID's own file."""
    deny = set()
    low = own_text.lower()
    for glid, ents in all_entities.items():
        if glid == own_glid:
            continue
        for e in ents:
            if e and len(e) > 2 and e.lower() not in low:
                deny.add(e)
    return deny


def leak_check(reply: str, deny: set[str]) -> list[str]:
    hits = [e for e in deny if re.search(r"\b" + re.escape(e) + r"\b", reply, re.I)]
    hits += [m.group(0) for p in _CONTACT for m in p.finditer(reply)]
    return hits
