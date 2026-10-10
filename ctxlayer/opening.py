"""Personalised first line, built only from facts in the context file.

Deterministic on purpose: the opening is spoken before the LLM has seen a single user word, it must
be instant (no LLM round trip on the critical path), and it must never state a fact that is not in
the file. Every opening returns the facts it used, so "lift" can be measured.

Tone rules: search behaviour is used to *guess* the need, never quoted back ("you searched X");
relative dates ("kal") are computed now, so a file built yesterday still speaks correctly today.
"""
from __future__ import annotations

import re
from datetime import datetime

from . import catalog
from .config import LANGS
from .config import LANGS
from .reader import Context
from .util import now, parse_ts, when_spoken

BOT = "Vani"
CH_HI = {"voice": "call", "whatsapp": "WhatsApp", "chat": "chat"}
CH_EN = {"voice": "a call", "whatsapp": "WhatsApp", "chat": "chat"}


def speakable(v: str) -> str:
    v = str(v).replace("kg/cm2", "kg").replace("LPH", "litre per hour")
    return re.sub(r"(\d) L\b", r"\1 litre", v)


def _opts(product: str, field: str, n: int = 2) -> list[str]:
    return [speakable(o) for o in catalog.specs(product).get(field, [])[:n]]


def ask_text(product: str, field: str, lang: str, unit: str | None = None) -> str:
    """The canonical question for a collection field (VANI phrasing rules: unit, 2 options + 'or else')."""
    if field == "quantity":
        u = unit or (catalog.units(product) or ["piece"])[0]
        return f"Aapko kitne {u.lower()} chahiye?" if lang == "hi" else f"How many {u.lower()}s do you need?"
    if field in catalog.specs(product):
        o = _opts(product, field)
        if lang == "hi":
            return f"{field} mein kya chahiye, {o[0]} ya {o[1]}, ya kuch aur?" if len(o) > 1 else f"{field} mein kya chahiye?"
        return f"Which {field.lower()} do you need, {o[0]} or {o[1]}, or something else?" if len(o) > 1 else f"Which {field.lower()} do you need?"
    q = {
        "name": ("Best seller se connect karne se pehle, aapka naam jaan sakti hoon?",
                 "Before I connect you to the best seller, may I know your name?"),
        "city": ("Aap kis city se call kar rahe hain?", "Which city are you calling from?"),
        "state": ("Aur aapka state kaunsa hai?", "And which state is that in?"),
    }.get(field)
    return q[0 if lang == "hi" else 1] if q else field


def _req_desc(th: dict, lang: str) -> str:
    cap = th.get("captured") or {}
    bits = []
    if cap.get("quantity"):
        bits.append(speakable(cap["quantity"]).lower())
    bits += [speakable(v) for k, v in cap.items() if k != "quantity"][:2]
    joined = ", ".join(bits)
    return f"{joined} {th['product']}".strip() if joined else th["product"]


def _greet(name: str | None, lang: str) -> str:
    if lang == "hi":
        return f"Namaste {name} ji, IndiaMART se {BOT} bol rahi hoon." if name else f"Namaste, IndiaMART se {BOT} bol rahi hoon."
    return f"Hello {name}, this is {BOT} from IndiaMART." if name else f"Hello, this is {BOT} from IndiaMART."


def buyer_opening(ctx: Context | None, channel: str, call_product: str | None = None,
                  ref: datetime | None = None, lang: str | None = None) -> dict:
    ref = ref or now()
    m = ctx.meta if ctx else {}
    known = m.get("known") or {}
    lang = lang or known.get("language") or "hi"
    lang = lang if lang in LANGS else "hi"  # drafts are Hinglish for hi, English otherwise; engine translates
    name = known.get("name")
    th = m.get("open_thread")
    intent = m.get("intent")
    call_product = catalog.canonical_product(call_product) or call_product
    facts, expect = [], None
    if name:
        facts.append("name")

    # A buyer calling about a *different* product than the open thread: lead with the called product.
    if th and call_product and catalog.canonical_product(th["product"]) != call_product:
        th = None

    if th and th.get("status") == "transferred":
        when = when_spoken(parse_ts(th["last_at"]), lang, ref)
        facts += ["product", "transfer"]
        text = (f"{_greet(name, lang)} {when.capitalize()} aapki {th['product']} ke liye seller se baat karwayi thi. "
                f"Kya aapko unse quotation mil gaya?" if lang == "hi" else
                f"{_greet(name, lang)} {when.capitalize()} we connected you with a seller for {th['product']}. "
                f"Did you get a quotation from them?")
        scenario, expect = "followup_transfer", "transfer_feedback"
    elif th:
        when = when_spoken(parse_ts(th["last_at"]), lang, ref)
        ch = th.get("last_channel") or "call"
        desc = _req_desc(th, lang)
        facts += ["product", "last_channel", "when", *th.get("captured", {}).keys()]
        dropped = ch == "voice" and channel == "voice"
        if lang == "hi":
            past = (f"{when.capitalize()} hamari call beech mein kat gayi thi, aapne {desc} ki requirement batayi thi."
                    if dropped else f"{when.capitalize()} aapne {CH_HI.get(ch, ch)} par {desc} ki requirement batayi thi.")
        else:
            past = (f"Our call {when} got cut while we were noting your {desc} requirement."
                    if dropped else f"{when.capitalize()} on {CH_EN.get(ch, ch)} you shared a requirement for {desc}.")
        if th.get("pending"):
            expect = th["pending"][0]
            q = ask_text(th["product"], expect, lang)
            text = f"{_greet(name, lang)} {past} " + (f"Bas ek baat, {q}" if lang == "hi" else f"Just one thing: {q[0].lower() + q[1:]}")
            scenario = "resume_pending"
            facts.append(f"pending:{expect}")
        else:
            expect = "transfer"
            text = (f"{_greet(name, lang)} {past} Aapki poori requirement note hai. Kya main abhi ek available seller se aapki baat karwa doon?"
                    if lang == "hi" else
                    f"{_greet(name, lang)} {past} I have everything I need. Shall I connect you to an available seller now?")
            scenario = "resume_complete"
    elif call_product or (intent and intent.get("product") and catalog.product(intent["product"])):
        prod = call_product or intent["product"]
        facts.append("called_product" if call_product else "intent")
        purpose = catalog.purpose(prod, lang)
        if lang == "hi":
            text = f"{_greet(name, lang)} Kya aap {prod} ke liye dekh rahe hain, jo {purpose}?"
        else:
            text = f"{_greet(name, lang)} Are you looking for {prod}, {purpose}?"
        scenario, expect = ("called_product" if call_product else "intent_suggest"), "product_confirm"
    else:
        text = (f"{_greet(name, lang)} Bataiye, aaj aapko kis product ki requirement hai?" if lang == "hi"
                else f"{_greet(name, lang)} Which product are you looking for today?")
        scenario, expect = ("known_buyer" if name else "cold_start"), "product"

    if channel == "whatsapp":
        text = text.replace(" bol rahi hoon.", " 🙏").replace(f"this is {BOT} from IndiaMART.", f"{BOT} from IndiaMART here 👋")
    return {"text": text, "scenario": scenario, "facts": facts, "expect": expect, "lang": lang,
            "personalised": len(facts) > 0, "product": (th or {}).get("product") or call_product
            or ((intent or {}).get("product") if scenario == "intent_suggest" else None)}


def seller_opening(ctx: Context | None, channel: str, ref: datetime | None = None,
                   outbound: bool = False, lang: str | None = None) -> dict:
    ref = ref or now()
    m = ctx.meta if ctx else {}
    known = m.get("known") or {}
    lang = lang or known.get("language") or "hi"
    lang = lang if lang in LANGS else "hi"  # drafts are Hinglish for hi, English otherwise; engine translates
    contact = known.get("contact")
    cb = m.get("callback_after")
    if outbound and cb:
        return {"text": None, "suppress": True, "scenario": "do_not_disturb", "facts": ["callback_after"],
                "reason": f"Seller asked not to be called before {cb}", "lang": lang, "personalised": True, "expect": None}
    facts = ["contact"] if contact else []
    pre = ""
    if cb:
        facts.append("callback_after")
        pre = (" Aap abhi festive orders mein busy hain, isliye bas ek zaroori baat." if lang == "hi"
               else " I know you're busy right now, so just one quick thing.")
    items = m.get("open_items") or []
    top = next((o for o in items if o["kind"] in ("lead_unactioned", "missed_call")), None)
    greet = (f"Namaste {contact} ji, IndiaMART se {BOT} bol rahi hoon." if (contact and lang == "hi") else
             f"Hello {contact}, this is {BOT} from IndiaMART." if contact else
             f"Namaste, IndiaMART se {BOT} bol rahi hoon." if lang == "hi" else f"Hello, this is {BOT} from IndiaMART.")
    if top and top["kind"] == "lead_unactioned":
        when = when_spoken(parse_ts(top["at"]), lang, ref)
        desc = " ".join(speakable(x) for x in (top.get("qty"), top.get("spec"), top["product"]) if x)
        facts += ["lead", "buyer_city", "product", "when"] + (["missed_call"] if top.get("missed_call") else [])
        if lang == "hi":
            extra = " aur us buyer ki call bhi aapse miss ho gayi thi" if top.get("missed_call") else ""
            text = f"{greet}{pre} {when.capitalize()} aapko {top['buyer_city']} se {desc} ki lead mili thi{extra}. Kya aapki unse baat ho payi?"
        else:
            extra = ", and their call to you was missed" if top.get("missed_call") else ""
            text = f"{greet}{pre} {when.capitalize()} you got a lead from {top['buyer_city']} for {desc}{extra}. Were you able to speak to the buyer?"
        scenario, expect = "lead_followup", f"lead_followup:{top['ref']}"
    elif top:
        when = when_spoken(parse_ts(top["at"]), lang, ref)
        facts += ["missed_call", "buyer_city", "product"]
        text = (f"{greet}{pre} {when.capitalize()} {top['buyer_city']} ke ek buyer ne {top['product']} ke liye call kiya tha jo miss ho gaya. Kya main unki details WhatsApp par bhej doon?"
                if lang == "hi" else
                f"{greet}{pre} {when.capitalize()} a buyer from {top['buyer_city']} called you for {top['product']} and it was missed. Shall I send their details on WhatsApp?")
        scenario, expect = "missed_call", "missed_call"
    elif any(o["kind"] == "pref_missing" for o in items) and m:
        f = next(o["field"] for o in items if o["kind"] == "pref_missing")
        facts.append("pref_missing")
        q = seller_ask_text(f, lang)
        text = f"{greet}{pre} " + (f"Aapko sahi leads milein, iske liye ek baat: {q}" if lang == "hi" else f"To send you better leads, one question: {q}")
        scenario, expect = "pref_collect", f
    else:
        text = (f"{greet} Main aapki kya madad kar sakti hoon?" if lang == "hi" else f"{greet} How can I help you today?")
        scenario, expect = ("known_seller" if contact else "cold_start"), None
    if channel == "whatsapp":
        text = text.replace(" bol rahi hoon.", " 🙏").replace(f"this is {BOT} from IndiaMART.", f"{BOT} from IndiaMART here 👋")
    return {"text": text, "scenario": scenario, "facts": facts, "expect": expect, "lang": lang,
            "personalised": len(facts) > 0, "suppress": False}


def seller_ask_text(field: str, lang: str) -> str:
    if field == "pref_min_qty":
        return "aap kam se kam kitne order ki leads lena chahenge?" if lang == "hi" else "what is the minimum order size you want leads for?"
    if field == "pref_regions":
        return "aapko kin states ke buyers ki leads chahiye?" if lang == "hi" else "buyers from which states should we send you?"
    return field
