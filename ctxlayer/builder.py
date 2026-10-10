"""Events -> profile dict. A pure function of (events, now): no I/O, no LLM, deterministic.

Determinism is a deliberate choice: millisecond rebuilds (freshness), identical structure every
time (compactness/reuse), and no hallucinated facts in a file other teams will trust.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta

from . import catalog
from .config import LOOKBACK_DAYS, RESUME_WINDOW_DAYS, SEARCH_INTENT_HOURS
from .util import now, parse_ts

TRUST = {"conversation": 3, "profile": 2}  # buyer-confirmed beats system-of-record


def _ts(e) -> datetime:
    return parse_ts(e["occurred_at"])


def _within(e, days: int, ref: datetime) -> bool:
    return _ts(e) >= ref - timedelta(days=days)


def _qty(q, unit) -> str | None:
    if q in (None, ""):
        return None
    q = int(q) if isinstance(q, float) and q.is_integer() else q
    return f"{q} {unit}".strip() if unit else str(q)


class _Identity:
    """Field-level merge with trust + recency, recording conflicts instead of hiding them."""

    def __init__(self):
        self.v: dict[str, tuple] = {}
        self.conflicts: list[dict] = []

    def offer(self, field, value, trust, ts, source):
        if value in (None, ""):
            return
        cur = self.v.get(field)
        if cur is None:
            self.v[field] = (value, trust, ts, source)
            return
        if str(cur[0]).lower() == str(value).lower():
            if (trust, ts) > (cur[1], cur[2]):
                self.v[field] = (value, trust, ts, source)
            return
        if (trust, ts) >= (cur[1], cur[2]):
            self.conflicts.append({"field": field, "kept": value, "dropped": cur[0], "why": f"{source} newer/more trusted"})
            self.v[field] = (value, trust, ts, source)
        else:
            self.conflicts.append({"field": field, "kept": cur[0], "dropped": value, "why": f"{cur[3]} more trusted"})

    def get(self, field):
        return self.v[field][0] if field in self.v else None

    def source(self, field):
        return self.v[field][3] if field in self.v else None


def _conversations(events, ref, days) -> list[dict]:
    sessions: dict[str, dict] = {}
    for e in events:
        if not e["type"].startswith("conversation."):
            continue
        p = e["payload"]
        sid = p.get("session_id") or e["event_id"]
        rec = sessions.setdefault(sid, {"session_id": sid, "started_at": _ts(e)})
        rec.update({k: v for k, v in p.items() if v is not None})
        rec["at"] = _ts(e)
        rec["ended"] = e["type"] == "conversation.ended"
    out = [s for s in sessions.values() if s["at"] >= ref - timedelta(days=days)]
    return sorted(out, key=lambda s: s["at"], reverse=True)


def _sources_missing(events) -> list[str]:
    status: dict[str, tuple[datetime, str]] = {}
    for e in events:
        if e["type"] == "source.status":
            status[e["payload"]["source"]] = (_ts(e), e["payload"]["status"])
    return sorted(s for s, (_, st) in status.items() if st != "ok")


def _engagement(events, ref, days, initiated_types) -> dict:
    recent = [e for e in events if _within(e, days, ref) and e["type"] in initiated_types]
    if not recent:
        return {"active_days_30d": 0, "last_active": None, "warmth": "cold", "channels": {}}
    active_days = len({_ts(e).date() for e in recent})
    last = max(_ts(e) for e in recent)
    ch = Counter()
    for e in recent:
        p = e["payload"]
        if e["type"].startswith("conversation."):
            ch[p.get("channel", "other")] += 1
        elif e["type"] == "engagement":
            k = p.get("kind", "")
            ch["whatsapp" if k.startswith("wa_") else "email" if k.startswith("email") else "app"] += p.get("count", 1)
        elif e["type"] == "pns.call":
            ch["voice"] += 1
        elif e["type"] == "search":
            ch["app"] += 1
    hours = (ref - last).total_seconds() / 3600
    warmth = "hot" if hours <= 24 else "warm" if hours <= 24 * 7 else "cold"
    return {"active_days_30d": active_days, "last_active": last, "warmth": warmth, "channels": dict(ch)}


# ======================================================================= buyer
BUYER_ACTIVITY = {"search", "pns.call", "enquiry.created", "enquiry.update", "engagement",
                  "conversation.update", "conversation.ended", "product.view", "product.like"}


def build_buyer(glid: str, events: list[dict], ref: datetime | None = None) -> dict:
    ref = ref or now()
    ident = _Identity()
    kyc, threads, by_enq = None, {}, {}
    for e in events:
        p, t, ts = e["payload"], e["type"], _ts(e)
        if t == "profile.update":
            for f in ("name", "city", "state", "language"):
                ident.offer(f, p.get(f), TRUST["profile"], ts, "profile")
        elif t == "kyc.update":
            kyc = {k.replace("_verified", ""): bool(v) for k, v in p.items() if k.endswith("_verified")}
        elif t.startswith("conversation."):
            cap = p.get("captured") or {}
            for f in ("name", "city", "state"):
                ident.offer(f, cap.get(f), TRUST["conversation"], ts, f"{p.get('channel', 'bot')} conversation")
            if p.get("lang"):
                ident.offer("language", p["lang"], TRUST["conversation"], ts, "conversation")
            prod = catalog.canonical_product(p.get("product")) or p.get("product")
            if prod:
                th = threads.setdefault(prod, {"product": prod, "status": "open", "captured": {}, "notes": [],
                                               "first_at": ts, "ref": None})
                th["captured"].update({k: v for k, v in cap.items() if k not in ("name", "city", "state")})
                th["notes"] += [n for n in p.get("notes", []) if n not in th["notes"]]
                th["last_at"], th["last_channel"] = ts, p.get("channel")
                outcome = p.get("outcome")
                if outcome == "transferred":
                    th["status"] = "transferred"
                elif outcome in ("no_requirement", "product_changed", "requirement_withdrawn"):
                    th["status"] = "dropped"
                    th["close_note"] = next((x for x in p.get("notes", []) if x.startswith("Buyer:")), "no longer needed")
                elif outcome == "complaint_resolved" and th["status"] == "open":
                    th["status"] = "closed"
                elif th["status"] in ("open", "dropped") and outcome not in ("complaint_resolved",):
                    th["status"] = "in_progress" if th["captured"] else "open"
        elif t in ("enquiry.created", "enquiry.update", "enquiry.status"):
            enq = p.get("enq_id")
            prod = by_enq.get(enq) or catalog.canonical_product(p.get("product")) or p.get("product")
            if not prod:
                continue
            by_enq[enq] = prod
            th = threads.setdefault(prod, {"product": prod, "status": "open", "captured": {}, "notes": [],
                                           "first_at": ts, "ref": enq})
            th["ref"] = th.get("ref") or enq
            if t == "enquiry.created" and th.get("ref") != enq and th["status"] in ("closed", "dropped"):
                th.update({"ref": enq, "status": "open", "captured": {}, "first_at": ts})
            q = _qty(p.get("quantity"), p.get("unit"))
            if q:
                th["captured"]["quantity"] = q
            th["captured"].update(p.get("specs") or {})
            if t == "enquiry.created":
                th.setdefault("created_at", ts)
                th["created_at"] = min(th.get("created_at", ts), ts)
            if t == "enquiry.status":
                th["status"] = "closed" if p.get("status") in ("closed", "purchased") else p.get("status", th["status"])
                th["close_note"] = p.get("note")
                if th["status"] == "closed":
                    th["closed_at"] = ts
            th["last_at"] = max(th.get("last_at", ts), ts)
            th.setdefault("last_channel", p.get("channel"))
        elif t == "pns.call":
            pass

    # state must agree with the confirmed city, otherwise treat it as unknown (VANI: never assume state)
    city, state = ident.get("city"), ident.get("state")
    if city and state and catalog.state_of(city) and catalog.state_of(city) != state:
        ident.v.pop("state")
    known = {f: ident.get(f) for f in ("name", "city", "state", "language") if ident.get(f)}

    # ---- open thread
    for th in threads.values():
        th["pending"] = [f for f in ["quantity", *catalog.specs(th["product"]).keys()] if f not in th["captured"]]
    candidates = [th for th in threads.values()
                  if th["status"] in ("open", "in_progress", "transferred")
                  and th.get("last_at") and th["last_at"] >= ref - timedelta(days=RESUME_WINDOW_DAYS)]
    open_thread = max(candidates, key=lambda th: th["last_at"]) if candidates else None

    # ---- enquiries (90d)
    enquiries = sorted([th for th in threads.values() if th.get("ref") and th.get("last_at")
                        and th["last_at"] >= ref - timedelta(days=LOOKBACK_DAYS["enquiries"])],
                       key=lambda th: th["last_at"], reverse=True)

    # ---- searches (30d) + recent intent with no requirement thread yet
    searches = [e for e in events if e["type"] == "search" and _within(e, LOOKBACK_DAYS["searches"], ref)]
    by_cat: dict[str, dict] = {}
    for e in searches:
        c = by_cat.setdefault(e["payload"]["mcat"], {"mcat": e["payload"]["mcat"], "count": 0, "last": _ts(e)})
        c["count"] += 1
        c["last"] = max(c["last"], _ts(e))
    cats = sorted(by_cat.values(), key=lambda c: (c["count"], c["last"]), reverse=True)
    thread_mcats = {catalog.mcat(p) for p, th in threads.items()
                    if th.get("last_at") and th["last_at"] >= ref - timedelta(days=30)}
    intent = next((c for c in sorted(cats, key=lambda c: c["last"], reverse=True)
                   if c["last"] >= ref - timedelta(hours=SEARCH_INTENT_HOURS) and c["mcat"] not in thread_mcats), None)
    if intent:
        intent = {**intent, "product": catalog.canonical_product(intent["mcat"]) or intent["mcat"]}

    # ---- interests: what the buyer looked at, where and when (used to probe for other requirements)
    interests: dict[str, dict] = {}
    for e in events:
        p = e["payload"]
        if e["type"] == "search" and _within(e, LOOKBACK_DAYS["searches"], ref):
            key = catalog.canonical_product(p.get("mcat")) or p.get("mcat")
            via = f"{p['platform']} search" if p.get("platform") else "search"
        elif e["type"] == "pns.call" and _within(e, LOOKBACK_DAYS["sellers_contacted"], ref):
            key = catalog.canonical_product(p.get("product")) or p.get("product")
            via = "seller call"
        elif e["type"] in ("product.view", "product.like") and _within(e, LOOKBACK_DAYS["searches"], ref):
            key = catalog.canonical_product(p.get("product")) or p.get("product")
            via = "liked" if e["type"] == "product.like" else "viewed"
        else:
            continue
        if not key:
            continue
        rec = interests.setdefault(key, {"product": key, "n": 0, "last": _ts(e), "via": via})
        rec["n"] += 1
        if _ts(e) >= rec["last"]:
            rec["last"], rec["via"] = _ts(e), via
        if via == "liked":
            rec["liked"] = True   # a like outlasts later plain views of the same product

    # ---- sellers contacted (60d)
    sellers: dict[str, dict] = {}
    for e in events:
        if e["type"] == "pns.call" and _within(e, LOOKBACK_DAYS["sellers_contacted"], ref):
            p = e["payload"]
            s = sellers.setdefault(p["seller_glid"], {"name": p.get("seller_name"), "city": p.get("seller_city"),
                                                      "calls": 0})
            s.update({"product": p.get("product"), "last": _ts(e), "answered": p.get("answered"),
                      "duration_s": p.get("duration_s", 0)})
            s["calls"] += 1

    missing = _sources_missing(events)
    if kyc is None:
        kyc = "unavailable" if "kyc" in missing else "unknown"

    return {
        "glid": glid, "role": "buyer", "known": known, "conflicts": ident.conflicts,
        "kyc": kyc, "open_thread": open_thread, "enquiries": enquiries, "searches": cats,
        "search_intent": intent,
        # what the buyer actually bought (closed as purchased, 90d): repeat-order candidates, newest first
        "purchases": sorted([{"product": th["product"], "last": th.get("closed_at") or th["last_at"],
                              "note": th.get("close_note") or "purchased"}
                             for th in threads.values()
                             if th["status"] == "closed" and "purchas" in str(th.get("close_note") or "purchased")
                             and th.get("last_at") and th["last_at"] >= ref - timedelta(days=LOOKBACK_DAYS["enquiries"])],
                            key=lambda x: x["last"], reverse=True),
        "interests": sorted([i for i in interests.values()
                             if not (threads.get(i["product"], {}).get("status") in ("closed", "dropped")
                                     and threads[i["product"]].get("last_at", ref) >= i["last"])],
                            key=lambda i: i["last"], reverse=True),
        "sellers_contacted": sorted(sellers.values(), key=lambda s: s["last"], reverse=True),
        "conversations": _conversations(events, ref, LOOKBACK_DAYS["conversations"]),
        "engagement": _engagement(events, ref, LOOKBACK_DAYS["engagement"], BUYER_ACTIVITY),
        "sources_missing": missing, "synthetic": any(e.get("synthetic") for e in events),
        "watermark": max((e["seq"] for e in events if "seq" in e), default=0), "empty": not events,
    }


# ======================================================================= seller
SELLER_ACTIVITY = {"lead.response", "engagement", "conversation.update", "conversation.ended", "catalog.update"}
PREF_FIELDS = ("pref_min_qty", "pref_regions")


def _fits(lead: dict, prefs: dict) -> bool:
    ok = True
    mq = prefs.get("pref_min_qty")
    if mq and lead.get("quantity") is not None:
        try:
            n, unit = mq.split(" ", 1)
            if unit.lower() == (lead.get("unit") or "").lower():
                ok &= float(lead["quantity"]) >= float(n)
        except ValueError:
            pass
    regions = prefs.get("pref_regions")
    if regions and lead.get("buyer_state"):
        ok &= lead["buyer_state"].lower() in regions.lower()
    return ok


def build_seller(glid: str, events: list[dict], ref: datetime | None = None) -> dict:
    ref = ref or now()
    ident = _Identity()
    kyc, products, prefs, leads = None, [], {}, {}
    missed = []
    for e in events:
        p, t, ts = e["payload"], e["type"], _ts(e)
        if t == "profile.update":
            for f, k in (("company", "company"), ("contact", "contact_name"), ("city", "city"),
                         ("state", "state"), ("language", "language")):
                ident.offer(f, p.get(k), TRUST["profile"], ts, "profile")
        elif t == "kyc.update":
            kyc = {k.replace("_verified", ""): bool(v) for k, v in p.items() if k.endswith("_verified")}
        elif t == "catalog.update":
            products = p.get("products", [])
        elif t.startswith("conversation."):
            cap = p.get("captured") or {}
            for f in (*PREF_FIELDS, "callback_after"):
                if cap.get(f):
                    prefs[f] = cap[f]
            if cap.get("name"):
                ident.offer("contact", cap["name"], TRUST["conversation"], ts, "conversation")
            for k, v in cap.items():
                if k.startswith("lead_followup:") or k.startswith("lead_feedback:"):
                    lid = k.split(":", 1)[1]
                    if lid in leads:
                        leads[lid].setdefault("bot_notes", []).append(f"{k.split(':')[0]}={v}")
            if p.get("lang"):
                ident.offer("language", p["lang"], TRUST["conversation"], ts, "conversation")
        elif t == "lead.received":
            leads[p["lead_id"]] = {**p, "at": ts, "status": "pending", "_cp": e.get("counterparty")}
        elif t == "lead.response":
            L = leads.get(p["lead_id"])
            if L:
                L.update({"status": p.get("outcome") or p.get("action"), "action": p.get("action"),
                          "responded_at": ts})
        elif t == "pns.call" and not p.get("answered") and _within(e, LOOKBACK_DAYS["missed_calls"], ref):
            missed.append({"at": ts, "product": p.get("product"), "buyer_city": p.get("buyer_city"),
                           "_cp": e.get("counterparty")})

    window = [L for L in leads.values() if L["at"] >= ref - timedelta(days=LOOKBACK_DAYS["leads"])]
    window.sort(key=lambda L: L["at"], reverse=True)
    missed_cps = {m["_cp"] for m in missed if m["_cp"]}
    for L in window:
        L["fits_prefs"] = _fits(L, prefs)
        L["missed_call"] = bool(L.get("_cp") and L["_cp"] in missed_cps)
    responded = [L for L in window if L["status"] != "pending"]
    resp_h = [(L["responded_at"] - L["at"]).total_seconds() / 3600 for L in responded if L.get("responded_at")]
    outcomes = Counter(L["status"] for L in responded)
    stats = {"leads": len(window), "responded": len(responded),
             "response_rate": round(len(responded) / len(window), 2) if window else None,
             "won": outcomes.get("deal_won", 0), "quoted": outcomes.get("quoted", 0),
             "lost": outcomes.get("deal_lost", 0), "not_reachable": outcomes.get("not_reachable", 0),
             "avg_response_h": round(sum(resp_h) / len(resp_h), 1) if resp_h else None}

    open_items = []
    for L in window:
        if L["status"] == "pending" and L["at"] >= ref - timedelta(days=7) and L["fits_prefs"]:
            open_items.append({"kind": "lead_unactioned", "ref": L["lead_id"], "product": L["product"],
                               "qty": _qty(L.get("quantity"), L.get("unit")), "spec": next(iter((L.get("specs") or {}).values()), None),
                               "buyer_city": L.get("buyer_city"), "at": L["at"], "missed_call": L["missed_call"]})
    for m in missed:
        if not any(L.get("_cp") == m["_cp"] for L in window):
            open_items.append({"kind": "missed_call", "product": m["product"], "buyer_city": m["buyer_city"], "at": m["at"]})
    for f in PREF_FIELDS:
        if f not in prefs:
            open_items.append({"kind": "pref_missing", "field": f})
    open_items.sort(key=lambda o: (o["kind"] == "pref_missing", -(o.get("at") or ref).timestamp()))

    cb = prefs.get("callback_after")
    dnd = cb if cb and cb > ref.date().isoformat() else None
    missing = _sources_missing(events)
    if kyc is None:
        kyc = "unavailable" if "kyc" in missing else "unknown"
    known = {f: ident.get(f) for f in ("company", "contact", "city", "state", "language") if ident.get(f)}
    return {
        "glid": glid, "role": "seller", "known": known, "conflicts": ident.conflicts, "kyc": kyc,
        "products": products, "preferences": {k: v for k, v in prefs.items() if k != "callback_after"},
        "callback_after": dnd, "leads": window, "stats": stats, "missed_calls": missed,
        "open_items": open_items,
        "conversations": _conversations(events, ref, LOOKBACK_DAYS["conversations"]),
        "engagement": _engagement(events, ref, LOOKBACK_DAYS["engagement"], SELLER_ACTIVITY),
        "sources_missing": missing, "synthetic": any(e.get("synthetic") for e in events),
        "watermark": max((e["seq"] for e in events if "seq" in e), default=0), "empty": not events,
    }


def build(glid: str, role: str, events: list[dict], ref: datetime | None = None) -> dict:
    return (build_buyer if role == "buyer" else build_seller)(glid, events, ref)
