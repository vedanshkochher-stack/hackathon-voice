"""Non-bot use #2: WhatsApp campaign audience + message builder, straight from the context files.

Segments are selected from frontmatter only (stable machine contract), messages use known fields,
and suppression rules (do-not-disturb, cold users, missing name) are applied before anything goes out.

    python -m consumers.wa_campaign            # prints the plan and writes out/campaign_<date>.csv
"""
from __future__ import annotations

import csv
from datetime import datetime

from ctxlayer.config import OUT_DIR
from ctxlayer.reader import read_all
from ctxlayer.util import now, parse_ts


def plan(ref: datetime | None = None) -> dict:
    ref = ref or now()
    send, suppressed = [], []
    for c in read_all():
        m = c.meta
        k = m.get("known") or {}
        sig = m.get("signals") or {}
        g = str(m["glid"])
        if m["role"] == "buyer":
            th, name = m.get("open_thread"), k.get("name")
            hi = k.get("language", "hi") == "hi"
            greet = (f"Namaste {name} ji" if hi else f"Hi {name}") if name else ("Namaste" if hi else "Hi")
            if th and th.get("pending") and th.get("status") != "transferred":
                age_d = (ref - parse_ts(th["last_at"])).days if th.get("last_at") else 99
                if age_d > 7:
                    suppressed.append({"glid": g, "segment": "resume_nudge", "reason": f"thread is {age_d}d old"})
                    continue
                msg = (f"{greet}, aapki {th['product']} requirement bas ek step door hai: {th['pending'][0]} bata dijiye, "
                       f"hum turant best seller se jod denge." if hi else
                       f"{greet}, your {th['product']} requirement is one step away: tell us the {th['pending'][0].lower()} "
                       f"and we'll connect you to the best seller.")
                send.append({"glid": g, "role": "buyer", "segment": "resume_nudge", "message": msg,
                             "why": f"open thread, pending {th['pending']}"})
            elif th and th.get("status") == "transferred":
                send.append({"glid": g, "role": "buyer", "segment": "transfer_followup",
                             "message": f"{greet}, {th['product']} ke seller se baat kaisi rahi? Aur options chahiye toh 'Haan' likhiye."
                             if hi else f"{greet}, how did it go with the {th['product']} seller? Reply 'Yes' for more options.",
                             "why": "connected to a seller, outcome unknown"})
            elif m.get("intent"):
                p = m["intent"]["product"]
                send.append({"glid": g, "role": "buyer", "segment": "category_interest",
                             "message": f"{greet}, {k.get('city', 'aapke shehar')} ke verified {p} sellers ke rates ek jagah dekhiye."
                             if hi else f"{greet}, compare verified {p} sellers near {k.get('city', 'you')} in one place.",
                             "why": f"recent interest in {m['intent']['mcat']} (search not quoted in message)"})
            elif sig.get("warmth") == "cold" or not m.get("known"):
                suppressed.append({"glid": g, "segment": "-", "reason": "cold or no history: no targeted message"})
        else:
            if m.get("callback_after"):
                suppressed.append({"glid": g, "segment": "any", "reason": f"seller asked for no contact before {m['callback_after']}"})
                continue
            contact = k.get("contact", "")
            lead = next((o for o in m.get("open_items", []) if o["kind"] == "lead_unactioned"), None)
            if lead:
                send.append({"glid": g, "role": "seller", "segment": "unactioned_lead",
                             "message": f"Namaste {contact} ji, {lead['buyer_city']} se {lead.get('qty', '')} {lead['product']} ki lead abhi active hai. "
                                        f"Lead Manager mein {lead['ref']} kholkar buyer ko call kijiye.",
                             "why": "fresh lead, no response yet"})
            elif isinstance(m.get("kyc"), dict) and m["kyc"].get("gst") is False:
                send.append({"glid": g, "role": "seller", "segment": "kyc_gst",
                             "message": f"Namaste {contact} ji, GST verify karke apne catalog par trust badge paaiye.",
                             "why": "GST not verified"})
    return {"generated_at": ref.isoformat(), "send": send, "suppressed": suppressed}


def write_csv(p: dict) -> str:
    path = OUT_DIR / f"campaign_{now().strftime('%Y%m%d')}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["glid", "role", "segment", "message", "why"])
        w.writeheader()
        w.writerows(p["send"])
    return str(path)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    p = plan()
    for r in p["send"]:
        print(f"[{r['segment']}] {r['glid']}: {r['message']}")
    for r in p["suppressed"]:
        print(f"[suppressed] {r['glid']}: {r['reason']}")
    print("csv:", write_csv(p))
