"""Profile dict -> buyer.md / seller.md.

Layout contract (schema imctx.*/v1, see docs/SCHEMA.md):
  * YAML frontmatter = machine contract (bots map it to prompt variables; dashboards/campaigns
    read it with any YAML parser). Keys are stable; new keys are additive.
  * Markdown body = the same facts, one line each, newest first, in a fixed section order so an LLM
    (or a human executive) can scan it. Absolute dates only, so a file never "ages" wrongly.
  * Hard byte budget; sections are trimmed in a fixed priority order, never truncated mid-line.
"""
from __future__ import annotations

from datetime import datetime

import yaml

from .config import CAPS, LOOKBACK_DAYS, MAX_BYTES, MIN_CAPS, SCHEMA_VERSION, TRIM_ORDER
from .util import day, iso, now

from .config import LANGS as LANG
STATUS = {"open": "open", "in_progress": "in progress", "transferred": "connected to seller",
          "closed": "closed", "dropped": "dropped"}
OUTCOME = {"live_call": "live call", "deal_won": "won", "deal_lost": "lost", "quoted": "quoted", "not_reachable": "not reachable",
           "connected": "connected", "called": "called", "whatsapp": "whatsapped", "pending": "NOT ACTIONED"}
CH = {"voice": "Voice", "whatsapp": "WhatsApp", "chat": "Chat", "app": "App"}
PREF_LABEL = {"pref_min_qty": "minimum order", "pref_regions": "preferred buyer regions"}
ST_ABBR = {"Madhya Pradesh": "MP", "Maharashtra": "MH", "Gujarat": "GJ", "Uttar Pradesh": "UP",
           "Telangana": "TS", "Andhra Pradesh": "AP", "Tamil Nadu": "TN", "Karnataka": "KA"}


def _iso(v):
    """Minute precision is enough for facts; only generated_at keeps milliseconds (freshness)."""
    return v.strftime("%Y-%m-%dT%H:%M%z")[:-2] + ":" + v.strftime("%z")[-2:] if isinstance(v, datetime) else v


CORE_KEYS = {"schema", "glid", "role", "generated_at", "watermark", "synthetic", "known", "kyc", "next", "never_ask"}


def _prune(d, top=True):
    """Drop empty optional keys to save bytes; core keys stay so the machine contract is stable."""
    if isinstance(d, dict):
        return {k: _prune(v, False) for k, v in d.items() if (top and k in CORE_KEYS) or v not in (None, [], {}, "")}
    return d


_Dumper = getattr(yaml, "CSafeDumper", yaml.SafeDumper)
_FM_CACHE: dict[int, str] = {}


def _fm(d: dict) -> str:
    """Frontmatter does not depend on section caps, so the budget loop dumps it only once."""
    key = id(d.get("_profile"))
    if key in _FM_CACHE:
        return _FM_CACHE[key]
    d = {k: v for k, v in d.items() if k != "_profile"}
    out = yaml.dump(_prune(d), Dumper=_Dumper, sort_keys=False, allow_unicode=True, default_flow_style=None, width=1000).strip()
    _FM_CACHE.clear()
    _FM_CACHE[key] = out
    return out


def _cap_text(cap: dict) -> str:
    return ", ".join(f"{'qty' if k == 'quantity' else k} {v}" for k, v in cap.items())


# ======================================================================= buyer
def buyer_next(p: dict) -> tuple[list[str], list[str]]:
    """Machine-readable next actions + fields that must never be asked again."""
    never = [k for k in ("name", "city", "state") if k in p["known"]]
    th = p["open_thread"]
    nxt: list[str] = []
    if th:
        never += ["product", *th["captured"].keys()]
        if th["status"] == "transferred":
            nxt.append(f"followup:{th['product']}")
        else:
            nxt += [f"ask:{f}" for f in th["pending"]]
            nxt.append("offer:live_seller")
    elif p.get("search_intent"):
        nxt.append(f"suggest:{p['search_intent']['product']}")
    else:
        nxt.append("ask:product")
    for f in ("name", "city", "state"):
        if f not in p["known"]:
            nxt.append(f"ask:{f}")
    return nxt, list(dict.fromkeys(never))


def render_buyer(p: dict, caps: dict | None = None, ref: datetime | None = None) -> str:
    caps, ref = caps or CAPS, ref or now()
    k, th, eng = p["known"], p["open_thread"], p["engagement"]
    nxt, never = buyer_next(p)
    fm = {
        "_profile": p, "schema": SCHEMA_VERSION["buyer"], "glid": p["glid"], "role": "buyer",
        "generated_at": iso(ref), "watermark": p["watermark"], "synthetic": p["synthetic"],
        "sources_missing": p["sources_missing"],
        "known": k,
        "kyc": p["kyc"],
        "open_thread": None if not th else {
            "product": th["product"], "ref": th.get("ref"), "status": th["status"],
            "last_channel": th.get("last_channel"), "last_at": _iso(th.get("last_at")),
            "captured": th["captured"], "pending": th["pending"], "notes": th["notes"] or None,
        },
        "interests": [{"product": i["product"], "last": i["last"].date().isoformat(), "n": i["n"], "via": i["via"],
                       **({"liked": True} if i.get("liked") else {})}
                      for i in p.get("interests", [])[:4]],
        "purchases": [{"product": x["product"], "last": x["last"].date().isoformat(), "note": x["note"]}
                      for x in p.get("purchases", [])[:2]],
        "intent": None if not p.get("search_intent") else {
            "product": p["search_intent"]["product"], "mcat": p["search_intent"]["mcat"],
            "last_search_at": _iso(p["search_intent"]["last"])},
        "signals": {"warmth": eng["warmth"], "last_active": _iso(eng["last_active"]),
                    "active_days_30d": eng["active_days_30d"],
                    "preferred_channel": max(eng["channels"], key=eng["channels"].get) if eng["channels"] else None},
        "next": nxt, "never_ask": never,
    }

    L = []
    loc = ", ".join(x for x in (k.get("city"), k.get("state")) if x) or "location unknown"
    L.append(f"# Buyer {p['glid']} · {k.get('name', 'name unknown')} · {loc}")
    if p["empty"]:
        L.append("> New buyer: no IndiaMART history. Use the generic opening and collect everything.")
    else:
        head = f"{eng['warmth'].capitalize()} buyer"
        if th and th["status"] == "transferred":
            head += f"; connected to a seller for {th['product']} on {day(th['last_at'])}, outcome unknown."
        elif th and th["pending"]:
            got = ", ".join("qty" if f == "quantity" else f for f in th["captured"]) or "requirement confirmed"
            head += (f", mid-way on {th['product']} ({CH.get(th.get('last_channel'), 'web')}, {day(th['last_at'])}):"
                     f" {got} given; {', '.join(th['pending'])} pending.")
        elif th:
            head += f"; {th['product']} requirement fully captured, not yet connected to a seller."
        elif p.get("search_intent"):
            head += f", browsing {p['search_intent']['mcat']} since {day(p['search_intent']['last'])} with no enquiry yet."
        if k.get("language"):
            head += f" Speaks {LANG.get(k['language'], k['language'])}."
        L.append("> " + head)

    if p["enquiries"][: caps["enquiries"]]:
        L.append(f"\n## Enquiries ({LOOKBACK_DAYS['enquiries']}d)")
        for e in p["enquiries"][: caps["enquiries"]]:
            cap = e["captured"]
            bits = [day(e.get("created_at") or e["first_at"]), e["product"], cap.get("quantity")]
            bits += [v for f, v in cap.items() if f != "quantity"][:2]
            status = STATUS.get(e["status"], e["status"])
            if e["status"] in ("closed", "dropped") and e.get("close_note"):
                status += f": {e['close_note']}"
            L.append("- " + " · ".join(str(b) for b in bits if b) + f" · {status} ({e['ref']})")

    if p["searches"][: caps["searches"]]:
        L.append(f"\n## Categories searched ({LOOKBACK_DAYS['searches']}d)")
        L.append(" · ".join(f"{c['mcat']} ×{c['count']} (last {day(c['last'])})" for c in p["searches"][: caps["searches"]]))

    if p["sellers_contacted"][: caps["sellers_contacted"]]:
        L.append(f"\n## Sellers contacted ({LOOKBACK_DAYS['sellers_contacted']}d)")
        for s in p["sellers_contacted"][: caps["sellers_contacted"]]:
            res = f"talked {max(1, round(s['duration_s'] / 60))} min" if s["answered"] else "missed, sent to VANI"
            L.append(f"- {s['name']}, {s['city']} · {s['product']} · {day(s['last'])} · {res}")

    L.append("\n## KYC")
    if isinstance(p["kyc"], dict):
        L.append(" · ".join(f"{f.upper() if f == 'gst' else f} {'verified' if v else 'not verified'}" for f, v in p["kyc"].items()))
    else:
        L.append(f"{p['kyc']} (source {'down at build time' if p['kyc'] == 'unavailable' else 'has no record'}); treat as unknown")

    convs = p["conversations"][: caps["conversations"]]
    if convs:
        L.append(f"\n## Conversations ({LOOKBACK_DAYS['conversations']}d, newest first)")
        for c in convs:
            pend = f" Pending: {', '.join(c['pending'])}." if c.get("pending") and not c.get("outcome") == "transferred" else ""
            L.append(f"- {day(c['at'])} {CH.get(c.get('channel'), c.get('channel'))} ({c.get('bot', 'bot')}) · "
                     f"{c.get('product') or 'general'} · {c.get('summary', '').rstrip('.')}.{pend}")

    L.append(f"\n## Engagement ({LOOKBACK_DAYS['engagement']}d)")
    if eng["last_active"]:
        L.append(f"Active {eng['active_days_30d']} of 30 days · last active {day(eng['last_active'])} "
                 f"{eng['last_active'].strftime('%H:%M')} · prefers {CH.get(fm['signals']['preferred_channel'], fm['signals']['preferred_channel'])} · {eng['warmth']}")
    else:
        L.append("No activity in window · cold")

    notes = []
    for c in p["conflicts"]:
        if c["field"] in ("city", "state", "name"):
            notes.append(f"{c['field']}: kept '{c['kept']}' over '{c['dropped']}' ({c['why']})")
    if p["sources_missing"]:
        notes.append(f"sources unavailable at build: {', '.join(p['sources_missing'])}")
    if notes:
        L.append("\n## Data notes")
        L += [f"- {n}" for n in notes]

    L.append("\n## Next best action")
    if th and th["status"] == "transferred":
        L.append(f"- Ask how the {th['product']} talk with the seller went; offer more sellers if it did not work out.")
    elif th and th["pending"]:
        L.append(f"- Resume {th['product']}: ask only {', then '.join(th['pending'])}; then offer a live seller.")
    elif th:
        L.append(f"- Nothing left to ask for {th['product']}: offer a live seller now.")
    elif p.get("search_intent"):
        L.append(f"- Ask if they need {p['search_intent']['product']}.")
    else:
        L.append("- Ask what product they need today.")
    if never:
        L.append(f"- Never ask again: {', '.join('qty' if f == 'quantity' else f for f in never)}.")
    if th and any("price" in n.lower() for n in th["notes"]):
        L.append("- Asked price before: the seller quotes; never state a price.")
    if any(c.get("outcome", "").startswith("complaint") for c in p["conversations"]):
        c = next(c for c in p["conversations"] if c.get("outcome", "").startswith("complaint"))
        L.append(f"- Past complaint ({day(c['at'])}, resolved): be empathetic if raised.")
    L.append("- Never reveal other parties' data; never read out KYC.")

    return f"---\n{_fm(fm)}\n---\n" + "\n".join(L) + "\n"


# ======================================================================= seller
def seller_next(p: dict) -> tuple[list[str], list[str]]:
    nxt = []
    if p.get("callback_after"):
        nxt.append(f"respect:callback_after:{p['callback_after']}")
    for o in p["open_items"]:
        if o["kind"] == "lead_unactioned":
            nxt.append(f"followup:{o['ref']}")
        elif o["kind"] == "missed_call":
            nxt.append("followup:missed_call")
        elif o["kind"] == "pref_missing":
            nxt.append(f"ask:{o['field']}")
    never = [k for k in ("contact",) if k in p["known"]] + list(p["preferences"].keys())
    return nxt[:4], never


def _lead_line(L: dict) -> str:
    st = ST_ABBR.get(L.get("buyer_state"), L.get("buyer_state") or "")
    q = L.get("quantity")
    q = int(q) if isinstance(q, float) and q.is_integer() else q
    bits = [day(L["at"]), L["product"], f"{q} {L.get('unit') or ''}".strip() if q else None]
    bits += list((L.get("specs") or {}).values())[:1]
    bits += [f"{L.get('buyer_city')}, {st}".strip(", "), L.get("via")]
    status = OUTCOME.get(L["status"], L["status"])
    if L["status"] != "pending" and L.get("action") and L.get("action") != L["status"]:
        status = f"{OUTCOME.get(L['action'], L['action'])} → {status}"
    flags = (" · buyer also called (missed)" if L.get("missed_call") else "") + ("" if L["fits_prefs"] else " · outside prefs")
    return "- " + " · ".join(str(b) for b in bits if b) + f" · {status}{flags} ({L['lead_id']})"


def render_seller(p: dict, caps: dict | None = None, ref: datetime | None = None) -> str:
    caps, ref = caps or CAPS, ref or now()
    k, st, eng = p["known"], p["stats"], p["engagement"]
    nxt, never = seller_next(p)
    fm = {
        "_profile": p, "schema": SCHEMA_VERSION["seller"], "glid": p["glid"], "role": "seller",
        "generated_at": iso(ref), "watermark": p["watermark"], "synthetic": p["synthetic"],
        "sources_missing": p["sources_missing"],
        "known": k, "kyc": p["kyc"], "products": p["products"],
        "preferences": p["preferences"], "callback_after": p["callback_after"],
        "open_items": [{kk: _iso(v) for kk, v in o.items() if v not in (None, False)} for o in p["open_items"][:4]],
        "stats_30d": st,
        "signals": {"warmth": eng["warmth"], "last_active": _iso(eng["last_active"]),
                    "active_days_30d": eng["active_days_30d"]},
        "next": nxt, "never_ask": never,
    }
    L = []
    loc = ", ".join(x for x in (k.get("city"), k.get("state")) if x) or "location unknown"
    L.append(f"# Seller {p['glid']} · {k.get('company', 'company unknown')} · {loc}")
    if p["empty"]:
        L.append("> New seller: no history. Use the generic opening.")
    else:
        head = f"Contact {k.get('contact', 'unknown')}"
        if k.get("language"):
            head += f" ({LANG.get(k['language'], k['language'])})"
        leads_open = [o for o in p["open_items"] if o["kind"] == "lead_unactioned"]
        if leads_open:
            o = leads_open[0]
            head += (f". {len(leads_open)} fresh lead{'s' if len(leads_open) > 1 else ''} not actioned; top: "
                     f"{o['buyer_city']} {o['product']} {o.get('qty') or ''}{' + missed call' if o.get('missed_call') else ''}".rstrip())
        if st["response_rate"] is not None:
            head += f". Responds to {round(st['response_rate'] * 100)}% of leads (30d)"
        if p.get("callback_after"):
            head += f". Asked not to be called before {p['callback_after']}"
        if isinstance(p["kyc"], dict) and p["kyc"].get("gst") is False:
            head += ". GST not verified"
        L.append("> " + head + ".")

    if p["leads"]:
        L.append(f"\n## Leads received ({LOOKBACK_DAYS['leads']}d)")
        for Ld in p["leads"][: caps["leads"]]:
            L.append(_lead_line(Ld))
        if len(p["leads"]) > caps["leads"]:
            L.append(f"- (+{len(p['leads']) - caps['leads']} older)")
        L.append(f"\n## Responses & outcomes ({LOOKBACK_DAYS['responses']}d)")
        L.append(f"Responded {st['responded']}/{st['leads']}"
                 + (f" ({round(st['response_rate'] * 100)}%)" if st["response_rate"] is not None else "")
                 + (f" · avg first response {st['avg_response_h']}h" if st["avg_response_h"] is not None else "")
                 + f" · won {st['won']} · quoted {st['quoted']} · lost {st['lost']} · not reachable {st['not_reachable']}")
    if p["missed_calls"]:
        L.append(f"\n## Missed buyer calls ({LOOKBACK_DAYS['missed_calls']}d)")
        for m in sorted(p["missed_calls"], key=lambda m: m["at"], reverse=True)[: caps["missed_calls"]]:
            L.append(f"- {day(m['at'])} · {m['product']} · {m['buyer_city']} buyer")
        if len(p["missed_calls"]) > caps["missed_calls"]:
            L.append(f"- (+{len(p['missed_calls']) - caps['missed_calls']} more)")
    if p["products"]:
        L.append("\n## Products")
        L.append(" · ".join(p["products"][: caps["catalog"]]))
    if p["preferences"]:
        L.append("\n## Lead preferences (said in conversation)")
        L.append(" · ".join(f"{PREF_LABEL.get(f, f)}: {v}" for f, v in p["preferences"].items()))
    L.append("\n## KYC")
    if isinstance(p["kyc"], dict):
        L.append(" · ".join(f"{f.upper() if f == 'gst' else f} {'verified' if v else 'NOT verified'}" for f, v in p["kyc"].items()))
    else:
        L.append(f"{p['kyc']}; treat as unknown")
    convs = p["conversations"][: caps["conversations"]]
    if convs:
        L.append(f"\n## Conversations ({LOOKBACK_DAYS['conversations']}d, newest first)")
        for c in convs:
            L.append(f"- {day(c['at'])} {CH.get(c.get('channel'), c.get('channel'))} ({c.get('bot', 'bot')}) · "
                     f"{c.get('summary', '').rstrip('.')}.")
    L.append(f"\n## Engagement ({LOOKBACK_DAYS['engagement']}d)")
    if eng["last_active"]:
        L.append(f"Active {eng['active_days_30d']} of 30 days · last active {day(eng['last_active'])} · {eng['warmth']}")
    else:
        L.append("No activity in window · cold")
    L.append("\n## Next best action")
    if p.get("callback_after"):
        L.append(f"- Do not call before {p['callback_after']}; if they call in, keep it to one point.")
    for o in p["open_items"][:2]:
        if o["kind"] == "lead_unactioned":
            L.append(f"- Ask if they reached the {o['buyer_city']} buyer for {o['product']} ({o['ref']}); offer the details on WhatsApp.")
        elif o["kind"] == "missed_call":
            L.append(f"- Tell them a {o['buyer_city']} buyer called for {o['product']} and missed them.")
        elif o["kind"] == "pref_missing":
            L.append(f"- Ask once for {PREF_LABEL[o['field']]}.")
    if never:
        L.append(f"- Never ask again: {', '.join(PREF_LABEL.get(f, 'contact name' if f == 'contact' else f) for f in never)}.")
    L.append("- Never reveal buyer names, contacts, or what buyers did with other sellers.")
    return f"---\n{_fm(fm)}\n---\n" + "\n".join(L) + "\n"


def render(p: dict, ref: datetime | None = None) -> str:
    """Render under the byte budget, trimming list sections in TRIM_ORDER."""
    fn = render_buyer if p["role"] == "buyer" else render_seller
    caps = dict(CAPS)
    ref = ref or now()
    _FM_CACHE.clear()
    text = fn(p, caps, ref)
    while len(text.encode("utf-8")) > MAX_BYTES[p["role"]]:
        for sec in TRIM_ORDER:
            if caps.get(sec, 0) > MIN_CAPS.get(sec, 1):
                caps[sec] -= 1
                break
        else:
            break
        text = fn(p, caps, ref)
    return text
