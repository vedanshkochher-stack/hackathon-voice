"""Non-bot use #1: a 30-second call-prep card for a human executive (sales / buyer care).

    python -m consumers.exec_call_prep 70221003 seller
"""
from __future__ import annotations

import sys

from ctxlayer.reader import Context, read


def _seller_card(c: Context) -> dict:
    m = c.meta
    k, st, sig = m.get("known", {}), m.get("stats_30d", {}), m.get("signals", {})
    risks = []
    if isinstance(m.get("kyc"), dict) and m["kyc"].get("gst") is False:
        risks.append("GST not verified: lower buyer trust, push KYC")
    if sig.get("warmth") == "cold":
        risks.append(f"Low engagement: active {sig.get('active_days_30d', 0)}/30 days")
    if st.get("response_rate") is not None and st["response_rate"] < 0.5:
        risks.append(f"Responds to only {round(st['response_rate'] * 100)}% of leads")
    if m.get("callback_after"):
        risks.append(f"Do not call before {m['callback_after']} (seller's request)")
    agenda = []
    for o in m.get("open_items", []):
        if o["kind"] == "lead_unactioned":
            agenda.append(f"Fresh {o['product']} lead from {o['buyer_city']} ({o.get('qty', '')}) not actioned"
                          + (" and the buyer's call was missed" if o.get("missed_call") else ""))
        elif o["kind"] == "pref_missing":
            agenda.append(f"Capture lead preference: {o['field'].replace('pref_', '').replace('_', ' ')}")
    return {
        "title": f"{k.get('company', 'Seller')} · {k.get('contact', '')} · {k.get('city', '')}",
        "one_liner": c.headline,
        "kpis": {"Leads (30d)": st.get("leads"), "Response rate": f"{round(st['response_rate'] * 100)}%" if st.get("response_rate") is not None else "-",
                 "Won": st.get("won"), "Quoted": st.get("quoted"), "Warmth": sig.get("warmth")},
        "agenda": agenda or ["Check satisfaction with lead quality"],
        "risks": risks,
        "do_not_ask": m.get("never_ask", []),
        "preferences": m.get("preferences", {}),
        "talk_in": k.get("language"),
    }


def _buyer_card(c: Context) -> dict:
    m = c.meta
    k, th, sig = m.get("known", {}), m.get("open_thread"), m.get("signals", {})
    agenda, risks = [], []
    if th:
        if th.get("pending"):
            agenda.append(f"Finish {th['product']} requirement: only {', '.join(th['pending'])} missing")
        elif th.get("status") == "transferred":
            agenda.append(f"Follow up: was the {th['product']} seller helpful?")
        else:
            agenda.append(f"{th['product']} requirement complete: connect to a seller")
    if m.get("intent"):
        agenda.append(f"Possible new need: {m['intent']['product']}")
    for line in c.sections.get("Next best action", []):
        if "complaint" in line.lower():
            risks.append(line.lstrip("- "))
    if m.get("kyc") in ("unknown", "unavailable"):
        risks.append("KYC status unknown")
    return {
        "title": f"{k.get('name', 'Buyer')} · {k.get('city', '')}, {k.get('state', '')}",
        "one_liner": c.headline,
        "kpis": {"Warmth": sig.get("warmth"), "Active days (30d)": sig.get("active_days_30d"),
                 "Prefers": sig.get("preferred_channel"), "Open requirement": th["product"] if th else "-"},
        "agenda": agenda or ["Ask what they need today"],
        "risks": risks, "do_not_ask": m.get("never_ask", []),
        "captured": (th or {}).get("captured", {}), "talk_in": k.get("language"),
    }


def prep_card(glid: str, role: str) -> dict | None:
    c = read(glid, role)
    if not c:
        return None
    card = _seller_card(c) if role == "seller" else _buyer_card(c)
    card.update({"glid": glid, "role": role, "source_file": str(c.path), "generated_at": c.meta.get("generated_at")})
    return card


def as_text(card: dict) -> str:
    out = [card["title"], card["one_liner"], ""]
    out += [f"{k}: {v}" for k, v in card["kpis"].items()]
    out += ["", "Agenda:"] + [f"  - {a}" for a in card["agenda"]]
    if card["risks"]:
        out += ["Watch out:"] + [f"  - {r}" for r in card["risks"]]
    out += [f"Already known, don't ask: {', '.join(card['do_not_ask']) or '-'}"]
    return "\n".join(out)


if __name__ == "__main__":
    c = prep_card(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "buyer")
    print(as_text(c) if c else "no context file")
