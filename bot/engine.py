"""Channel-agnostic dialog engine (voice, WhatsApp, chat all use this).

Per session:
  start  -> read-through freshness check -> load buyer.md/seller.md -> map to VANI variables ->
            pre-fill known slots -> deterministic personalised opening
  turn   -> NLU (rules, LLM fallback) -> capture -> intent handling -> VANI Collection Control picks
            the next eligible question -> (optional) Sarvam LLM phrasing -> re-ask guard -> leak guard
            -> emit conversation.update so the file is fresh even if the call drops mid-way
  end    -> conversation.ended (+ cross-party events: live transfer lands in the seller's file)

The policy (what to ask next) is deterministic and mirrors VANI's Collection Control; the LLM only
phrases. That is what makes "never re-ask a known field" a guarantee instead of a hope.
"""
from __future__ import annotations

import random
import re
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field

from ctxlayer import catalog, privacy, reader
from ctxlayer.bridge import live_seller, render_prompt, seller_variables, vani_variables
from ctxlayer.config import ASK_LIMITS
from ctxlayer.opening import ask_text, buyer_opening, seller_ask_text, seller_opening
from ctxlayer.util import iso, now, parse_ts, when_spoken

from ctxlayer.config import LANGS

from .nlu import NO_LONGER, language_request, parse_buyer, parse_seller, script_language
from .translate import translate

FILLER = {"hi": ["Ji.", "Theek hai.", "Achha.", "Samajh gayi."], "en": ["Got it.", "Sure.", "Okay.", "Noted."]}
T = {
    "price": ("Price ke liye main aapki call best seller se connect karwaungi, wo aapko sabse achha rate denge.",
              "For the price, I'll connect you to the best seller; they'll give you the best rate."),
    "price2": ("Price seller hi batayenge.", "The seller will share the price."),
    "ai": ("Ji, main IndiaMART ki virtual assistant hoon.", "Yes, I'm IndiaMART's virtual assistant."),
    "no_contact_buyer": ("Original seller ka number mere paas nahi hota, par end mein doosre best sellers ki details aapko WhatsApp par mil jayengi.",
                         "I don't have the original seller's contact details, but you'll get other best sellers' details on WhatsApp at the end."),
    "no_contact_seller": ("Buyer ka naam aur number aapke Lead Manager mein us lead ke andar hai. Buyer ne aur kis se baat ki, ye main share nahi kar sakti.",
                          "The buyer's name and number are inside that lead in your Lead Manager. I can't share who else the buyer spoke to."),
    "defer": ("Koi baat nahi, ye detail aap seller se directly discuss kar lijiye.",
              "No problem, you can discuss that directly with the seller."),
    "hold_seller": ("Ji, bas ek-do details le loon, phir turant best seller se connect karwa dungi.",
                    "Sure, just one or two details and I'll connect you to the best seller right away."),
    "identity": ("Jo seller aap try kar rahe the wo abhi busy hain, main aapki call IndiaMART ke best seller se connect karwaungi.",
                 "The seller you tried is busy right now; I'll connect you to IndiaMART's best seller."),
    "confirm_product": ("Achha, toh aap {p} ke liye dekh rahe hain, jo {purpose}, sahi hai na?",
                        "So you're looking for {p}, {purpose}, right?"),
    "ask_product": ("Aapko kis product ki requirement hai?", "Which product do you need?"),
    "ask_product2": ("Mujhe product ka naam sahi se samajh nahi aaya, aapko kaunsa product chahiye?",
                     "I didn't quite catch the product, which product do you need?"),
    "offer_live": ("{n}abhi ek seller line par available hai, price aur baaki details aap unse directly discuss kar sakte hain. Kya main aapki call connect kar doon?",
                   "{n}a seller is available on the line right now; you can discuss price and other details directly. Shall I connect your call?"),
    "offer_live_wa": ("{n}{c}, {city} abhi available hain. Kya main unse aapko call karwa doon? Price aur baaki details wo directly bata denge.",
                      "{n}{c} from {city} is available right now. Shall I have them call you? They'll share price and details directly."),
    "transfer": ("Ji, main abhi aapki call {c} se connect kar rahi hoon. IndiaMART ko call karne ke liye dhanyavaad.",
                 "Sure, connecting your call to {c} now. Thank you for calling IndiaMART."),
    "transfer_wa": ("Ji, {c} aapko 2 minute mein call karenge. Dhanyavaad! 🙏", "Done, {c} will call you within 2 minutes. Thank you! 🙏"),
    "close_details": ("Theek hai. Aapki requirement note ho gayi hai. Suitable seller details aapko WhatsApp par share kar diye jayenge. IndiaMART ko call karne ke liye dhanyavaad.",
                      "Alright. Your requirement is noted and suitable seller details will be shared on WhatsApp. Thank you for calling IndiaMART."),
    "close_no_req": ("Theek hai. Agar aage kisi product ki requirement ho toh IndiaMART se zaroor sampark kijiye. Dhanyavaad.",
                     "Alright. Whenever you need a product, do reach out to IndiaMART. Thank you."),
    "ack_withdrawn": ("Koi baat nahi, {p} ki requirement maine hata di hai.", "No problem, I've closed the {p} requirement."),
    "ack_bought": ("Achha, {p} aapne le liya, badhiya.", "Great, glad you already have the {p}."),
    "ack_plain": ("Koi baat nahi.", "No problem."),
    "understood_withdrawn": ("Theek hai, main samajh gayi ki ab aapko {p} ki requirement nahi hai.",
                             "Okay, I understand that you no longer need the {p}."),
    "understood_bought": ("Achha, aapne {p} le liya, yeh achhi baat hai.", "Okay, I understand you've already bought the {p}."),
    "understood_suggested": ("Theek hai, main samajh gayi ki aapko abhi {p} nahi chahiye.",
                             "Okay, I understand that you don't need {p} right now."),
    "seen_intro": ("Maine dekha ki {clauses}.", "I have seen that you were {clauses}."),
    "seen_search": ("aap {when} IndiaMART {where} par {p} dekh rahe the", "looking at {p} on the IndiaMART {where} {when}"),
    "seen_call": ("aapne {when} {p} ke liye ek seller ko call kiya tha", "calling a seller about {p} {when}"),
    "post_one": ("Kya aap iske liye requirement post karna chahenge?", "Do you wish to post a requirement for it?"),
    "post_two": ("Kya aap inme se kisi ke liye requirement post karna chahenge?",
                 "Do you wish to post a requirement for any of these?"),
    "seen_bought": ("Maine dekha ki aapne {when}{frm} {p} liya tha. Kya aapko dobara {p} chahiye?",
                    "I have seen that you bought {p}{frm} {when}. Do you need {p} again?"),
    "probe_two": ("Kya aapko {a} ya {b} jaisi kisi cheez ki zarurat hai, ya koi aur product chahiye?",
                  "Do you need something like {a} or {b}, or any other product?"),
    "probe_one": ("Kya aapko {a} ki zarurat hai, ya koi aur product chahiye?", "Do you need {a}, or any other product?"),
    "probe_generic": ("Kya abhi ya jald hi kisi aur product ki requirement hai?", "Is there any other product you need now or soon?"),
    "probe_pick": ("Inme se kaunsa chahiye, {a} ya {b}?", "Which one do you need, {a} or {b}?"),
    "close_postponed": ("Koi baat nahi. Aapki requirement save hai, agli baar hum wahin se aage badhenge. Dhanyavaad.",
                        "No problem. I've saved your requirement, and next time we'll pick up right where we left off. Thank you."),
    "close_withdrawn": ("Theek hai, koi baat nahi. Jab bhi kisi product ki zarurat ho, IndiaMART par zaroor bataiye. Dhanyavaad.",
                        "Alright, no problem. Whenever you need a product, just reach out to IndiaMART. Thank you."),
    "lang_ack": ("Ji, ab main {L} mein baat karungi.", "Sure, I'll continue in {L}."),
    "lang_same": ("Ji, main {L} mein hi baat kar rahi hoon.", "Sure, I'm speaking in {L}."),
    "lang_unsupported": ("Maaf kijiye, main abhi {X} mein baat nahi kar sakti. Main Hindi, English, Bengali, Tamil, Telugu, "
                         "Kannada, Malayalam, Marathi, Gujarati, Punjabi aur Odia mein baat kar sakti hoon.",
                         "Sorry, I can't speak {X} yet. I can talk in Hindi, English, Bengali, Tamil, Telugu, Kannada, "
                         "Malayalam, Marathi, Gujarati, Punjabi and Odia."),
    "feedback_thanks": ("Dhanyavaad batane ke liye. Aur sellers chahiye toh unki details main WhatsApp par bhej doongi.",
                        "Thanks for letting me know. If you want more sellers, I'll send their details on WhatsApp."),
    "leak_block": ("Maaf kijiye, main doosre buyers ya sellers ki jaankari share nahi kar sakti.",
                   "Sorry, I can't share information about other buyers or sellers."),
    "clarify": ("Main ye pooch rahi thi:", "I was asking:"),
    # seller side
    "s_ask_outcome": ("Achha, phir kya hua, quotation diya ya order mil gaya?", "Great, what happened, did you quote or win the order?"),
    "s_offer_resend": ("Koi baat nahi. Kya main us buyer ki details aapko WhatsApp par dobara bhej doon?",
                       "No problem. Shall I resend that buyer's details on WhatsApp?"),
    "s_resent": ("Ji, details WhatsApp par bhej di hain. Jaldi call kar lijiye, buyer abhi active hain.",
                 "Done, the details are on your WhatsApp. Please call soon, the buyer is active."),
    "s_noted": ("Bahut badhiya, note kar liya.", "Great, noted."),
    "s_close": ("Dhanyavaad {n} ji. Aapko sahi leads milti rahengi. IndiaMART ke saath bane rahne ke liye shukriya.",
                "Thank you {n}. We'll keep sending you the right leads. Thanks for being with IndiaMART."),
    "s_close_dnd": ("Bas itna hi tha, {n} ji. {d} ke baad baaki baat karenge. Dhanyavaad.",
                    "That's all for now, {n}. We'll talk about the rest after {d}. Thank you."),
    "s_help": ("Main aapki leads, missed calls aur lead preferences mein madad kar sakti hoon. Kya aap apni lead preferences update karna chahenge?",
               "I can help with your leads, missed calls and lead preferences. Would you like to update your lead preferences?"),
}
REASK_KEYWORDS = {"name": ["naam", "name"], "city": ["city", "shahar", "kahan se", "which city"],
                  "state": ["state", "rajya"], "quantity": ["kitne", "how many", "quantity"],
                  "product": ["kis product", "which product", "kaunsa product"],
                  "pref_min_qty": ["minimum", "kam se kam"], "pref_regions": ["kin states", "which states", "regions"]}


TARGET_KW = {"name": ["naam", "name"], "city": ["city", "shahar", "sheher"], "state": ["state", "rajya", "pradesh"],
             "quantity": ["kitne", "kitna", "how many", "quantity"], "product": ["product", "kya chahiye", "need"],
             "product_confirm": ["sahi", "right", "chahiye", "?"]}
OFF_SCRIPT = ["pincode", "pin code", "email", "address", "gst", "budget", "anything else", "kuch aur chahiye",
              "aur kuch", "delivery date", "kab tak"]


def tl(lang: str) -> str:
    """Template language: drafts exist in Hinglish (hi) and English; every other language is translated from English."""
    return "hi" if lang == "hi" else "en"


def t(key: str, lang: str, **kw) -> str:
    s = T[key][0 if lang == "hi" else 1]
    return s.format(**kw) if kw else s


@dataclass
class Session:
    id: str
    glid: str
    role: str
    channel: str
    warm: bool
    persist: bool
    reply_mode: str
    lang: str = "hi"
    phase: str = "identify"
    expect: str | None = None
    product: str | None = None
    candidate: str | None = None
    slots: dict = field(default_factory=dict)
    prefilled: set = field(default_factory=set)
    shadow_known: set = field(default_factory=set)   # what the file knew (even in cold mode) -> re-ask metric
    closed: set = field(default_factory=set)
    asks: Counter = field(default_factory=Counter)
    notes: list = field(default_factory=list)
    transcript: list = field(default_factory=list)
    captured_session: dict = field(default_factory=dict)
    thread_ref: str | None = None
    live: dict | None = None
    call_seller: str | None = None
    identity_revealed: bool = False
    outcome: str | None = None
    ended: bool = False
    opening: dict = field(default_factory=dict)
    vars: dict = field(default_factory=dict)
    deny: set = field(default_factory=set)
    lead: dict | None = None
    dnd: str | None = None
    price_told: int = 0
    seller_asks: int = 0
    metrics: Counter = field(default_factory=Counter)
    started_at: float = field(default_factory=time.time)
    ctx_info: dict = field(default_factory=dict)
    last_values: list = field(default_factory=list)
    last_draft: str = ""                                # last bot question before phrasing (to re-ask after a switch)
    languages: list = field(default_factory=list)       # language history in this session, e.g. ['hi', 'ta', 'en']
    ctx_meta: dict = field(default_factory=dict)      # frontmatter used for cross-sell suggestions
    probed: bool = False                               # VANI: probe for another requirement only once
    suggestions: list = field(default_factory=list)
    suggestion_meta: dict = field(default_factory=dict)  # product -> {via, last, personal}: where/when we saw it
    dropped: list = field(default_factory=list)        # products the buyer withdrew in this session


class Engine:
    def __init__(self, store, refresher, llm=None):
        self.store, self.refresher, self.llm = store, refresher, llm
        self.sessions: dict[str, Session] = {}

    # ================================================================ lifecycle
    def start(self, glid: str, role: str, channel: str, warm: bool = True, persist: bool | None = None,
              reply_mode: str = "llm", call_product: str | None = None, call_seller: str | None = None,
              outbound: bool = False) -> dict:
        t0 = time.perf_counter()
        refreshed = self.refresher.ensure_fresh(glid, role) if self.store.max_seq(glid, role) else None
        ctx = reader.read(glid, role)
        load_ms = (time.perf_counter() - t0) * 1000
        s = Session(id=uuid.uuid4().hex[:10], glid=glid, role=role, channel=channel, warm=warm,
                    persist=warm if persist is None else persist,
                    reply_mode=reply_mode if (self.llm and self.llm.available) else "template")
        s.call_seller = call_seller
        if ctx:
            s.shadow_known = set(ctx.meta.get("never_ask") or [])
            s.ctx_info = {"path": str(ctx.path), "bytes": len(ctx.raw.encode()), "generated_at": ctx.meta.get("generated_at"),
                          "watermark": ctx.meta.get("watermark")}
        use = ctx if warm else None
        s.ctx_meta = (ctx.meta if ctx and warm else {}) or {}
        s.deny = self._deny_set(glid, ctx)
        if role == "buyer":
            op = self._start_buyer(s, use, call_product)
        else:
            op = self._start_seller(s, use, outbound)
        s.opening = op
        if op.get("expect"):  # the opening itself asks something: count it (VANI Collection Control)
            s.metrics["questions"] += 1
            key = "product" if op["expect"] in ("product", "product_confirm") else op["expect"]
            if key in s.shadow_known and not warm:
                s.metrics["reasks_of_known"] += 1
        self.sessions[s.id] = s
        s.languages = [s.lang]
        if op.get("text"):
            s.last_draft = op["text"]
            if s.lang not in ("hi", "en"):
                op["text"] = translate(op["text"], s.lang, self.llm)
            s.transcript.append({"who": "bot", "text": op["text"], "at": iso(now())})
        return {"session_id": s.id, "opening": op.get("text"), "scenario": op.get("scenario"),
                "facts": op.get("facts", []), "personalised": op.get("personalised", False),
                "suppressed": op.get("suppress", False), "reason": op.get("reason"),
                "lang": s.lang, "warm": warm, "context": s.ctx_info if warm else None,
                "load_ms": round(load_ms, 2), "refreshed": refreshed, "state": self._state(s),
                "prompt_chars": len(self.prompt(s.id))}

    def _start_buyer(self, s: Session, ctx, call_product):
        base = {"product_name": call_product or "", "seller_glid": s.call_seller or ""}
        s.vars = vani_variables(ctx, base, s.channel)
        op = buyer_opening(ctx, s.channel, call_product=call_product)
        s.lang = op["lang"]
        known = (ctx.meta.get("known") if ctx else None) or {}
        for f in ("name", "city", "state"):
            if known.get(f):
                s.slots[f] = known[f]
                s.prefilled.add(f)
        th = ctx.meta.get("open_thread") if ctx else None
        s.product = op.get("product")
        if th and s.product and catalog.canonical_product(th["product"]) == catalog.canonical_product(s.product):
            for k, v in th["captured"].items():
                s.slots[k] = v
                s.prefilled.add(k)
            s.thread_ref = th.get("ref")
            s.prefilled.add("product")
        s.identity_revealed = True  # every opening introduces IndiaMART
        sc = op["scenario"]
        if sc == "resume_pending":
            s.phase, s.expect = "collect", op["expect"]
            s.asks[s.expect] += 1
        elif sc == "resume_complete":
            s.phase, s.expect = "offer", "transfer"
            s.asks["transfer"] += 1
        elif sc == "followup_transfer":
            s.phase, s.expect = "feedback", "transfer_feedback"
        elif sc in ("called_product", "intent_suggest"):
            s.phase, s.expect, s.candidate = "confirm", "product_confirm", s.product
            s.asks["product"] += 1
        else:
            s.phase, s.expect = "identify", "product"
            s.asks["product"] += 1
        s.live = live_seller(s.product, exclude=s.call_seller) if s.product else None
        return op

    def _start_seller(self, s: Session, ctx, outbound):
        op = seller_opening(ctx, s.channel, outbound=outbound)
        s.lang = op["lang"]
        s.vars = seller_variables(ctx, s.channel)
        if op.get("suppress"):
            s.ended, s.outcome = True, "suppressed_dnd"
            return op
        m = ctx.meta if ctx else {}
        for k, v in (m.get("preferences") or {}).items():
            s.slots[k] = v
            s.prefilled.add(k)
        if (m.get("known") or {}).get("contact"):
            s.slots["contact"] = m["known"]["contact"]
            s.prefilled.add("contact")
        s.dnd = m.get("callback_after")
        sc = op["scenario"]
        if sc == "lead_followup":
            s.lead = next(o for o in m["open_items"] if o["kind"] == "lead_unactioned")
            s.phase, s.expect = "lead_followup", op["expect"]
            s.asks["lead"] += 1
        elif sc == "missed_call":
            s.phase, s.expect = "missed_call", "missed_call"
            s.asks["lead"] += 1
        elif sc == "pref_collect":
            s.phase, s.expect = "prefs", op["expect"]
            s.asks[s.expect] += 1
        else:
            s.phase, s.expect = "open", None
        return op

    def end(self, sid: str, reason: str = "hangup") -> dict:
        s = self.sessions[sid]
        if not s.ended:
            s.outcome = s.outcome or ("dropped" if reason in ("hangup", "drop") else reason)
            self._finish(s)
        return {"ended": True, "outcome": s.outcome, "state": self._state(s)}

    # ================================================================ turns
    def message(self, sid: str, text: str, detected_lang: str | None = None) -> dict:
        s = self.sessions[sid]
        if s.ended:
            return {"reply": None, "ended": True, "state": self._state(s)}
        t0 = time.perf_counter()
        s.transcript.append({"who": "user", "text": text, "at": iso(now())})
        llm_before = self.llm.total_ms if self.llm else 0
        switched = self._language_turn(s, text, detected_lang)
        if switched:
            switched["ms"] = {"total": round((time.perf_counter() - t0) * 1000),
                              "llm": round((self.llm.total_ms - llm_before) if self.llm else 0), "nlu_llm": 0}
            return switched
        if s.role == "buyer":
            draft, kind, nlu = self._buyer_turn(s, text)
        else:
            draft, kind, nlu = self._seller_turn(s, text)
        nlu_ms = (self.llm.total_ms - llm_before) if self.llm else 0
        s.last_values = [str(s.captured_session.get(f) or s.slots.get(f) or "") for f in nlu.get("captured", [])]
        if kind != "close":
            s.last_draft = draft
        reply = self._phrase(s, draft, kind)
        reply = self._leak_guard(s, reply)
        s.transcript.append({"who": "bot", "text": reply, "at": iso(now())})
        if s.ended:
            self._finish(s)
        elif s.persist and (nlu["captured"] or kind == "confirmed"):
            self._emit_update(s)
        return {"reply": reply, "ended": s.ended, "outcome": s.outcome, "kind": kind, "nlu": nlu,
                "state": self._state(s), "ms": {"total": round((time.perf_counter() - t0) * 1000),
                                                "llm": round((self.llm.total_ms - llm_before) if self.llm else 0),
                                                "nlu_llm": round(nlu_ms)}}

    # ---------------------------------------------------------------- language switching
    def _language_turn(self, s: Session, text: str, detected: str | None) -> dict | None:
        """Explicit request ('Tamil mein baat kijiye', 'English please', 'తెలుగులో మాట్లాడండి') or implicit switch
        (buyer starts typing/speaking another supported language). Any number of times per conversation."""
        req, unsupported = language_request(text)
        implicit = None
        if not req and not unsupported:
            implicit = script_language(text)
            if not implicit and detected and detected != s.lang and detected not in ("hi", "en") \
                    and not (detected == "mr" and s.lang == "hi") and len(text.split()) >= 2:
                implicit = detected  # STT heard another language (hi/en/mr confusions need an explicit request)
        if unsupported:
            draft = f"{t('lang_unsupported', tl(s.lang), X=unsupported)} {s.last_draft}".strip()
            return self._say(s, draft, "language", translate_all=True)
        target = req or implicit
        if not target:
            return None
        if target == s.lang:
            if req and len(text.split()) <= 7:
                return self._say(s, f"{t('lang_same', tl(s.lang), L=LANGS[target])} {self._requestion(s)}",
                                 "language", translate_all=True)
            return None
        old, s.lang = s.lang, target
        s.languages.append(target)
        s.metrics["language_switches"] += 1
        s.notes.append(f"Language {LANGS[old]} -> {LANGS[target]}")
        if s.persist:
            self._emit_update(s)  # saved now: the next call/chat opens in this language
        if req and len(text.split()) <= 7:  # pure request: confirm and repeat the pending question
            return self._say(s, f"{t('lang_ack', tl(s.lang), L=LANGS[target])} {self._requestion(s)}",
                             "language", translate_all=True)
        return None  # implicit switch (or request + content): handle the turn normally, reply in the new language

    def _requestion(self, s: Session) -> str:
        d = s.last_draft or ""
        if sum(1 for x in s.transcript if x["who"] == "user") <= 1:  # still on the opening: drop the greeting
            d = re.sub(r"^(Namaste[^.]*?(hoon|🙏)\.?|Hello[^.]*?(IndiaMART|here 👋)\.?)\s*", "", d)
        return d

    def _say(self, s: Session, draft: str, kind: str, translate_all: bool = False) -> dict:
        reply = self._leak_guard(s, translate(draft, s.lang, self.llm) if translate_all else self._phrase(s, draft, kind))
        s.transcript.append({"who": "bot", "text": reply, "at": iso(now())})
        return {"reply": reply, "ended": s.ended, "outcome": s.outcome, "kind": kind,
                "nlu": {"intents": ["LANGUAGE_SWITCH"], "slots": {}, "captured": [], "llm_used": False},
                "state": self._state(s)}

    # ---------------------------------------------------------------- buyer policy
    def _fields(self, s: Session) -> list[str]:
        return (["quantity", *catalog.specs(s.product).keys()] if s.product else []) + ["name", "city", "state"]

    def _limit(self, s: Session, f: str) -> int:
        return ASK_LIMITS["spec"] if f in catalog.specs(s.product or "") else ASK_LIMITS.get(f, 2)

    def _next_field(self, s: Session) -> str | None:
        for f in self._fields(s):
            if f in s.slots or f in s.closed:
                continue
            if s.asks[f] >= self._limit(s, f):
                s.closed.add(f)
                continue
            return f
        return None

    def _ask(self, s: Session, f: str) -> str:
        s.asks[f] += 1
        s.expect = f
        s.metrics["questions"] += 1
        if f in s.shadow_known:
            s.metrics["reasks_of_known"] += 1
        return ask_text(s.product or "", f, s.lang)

    def _capture(self, s: Session, slots: dict) -> list[str]:
        allowed = set(self._fields(s))
        got = []
        for k, v in slots.items():
            if k not in allowed or not v:
                continue
            if s.slots.get(k) == v:
                continue
            if k in s.prefilled:
                s.notes.append(f"{k} corrected to {v}")
            s.slots[k] = v
            s.captured_session[k] = v
            got.append(k)
        return got

    def _buyer_turn(self, s: Session, text: str):
        n = parse_buyer(text, s.candidate or s.product, s.expect, self.llm if s.reply_mode == "llm" else None)
        lang, pre = s.lang, []
        got = self._capture(s, n.slots) if s.phase in ("collect", "offer", "confirm") or s.product else []
        info = {"intents": sorted(n.intents), "slots": n.slots, "captured": got, "llm_used": n.llm_used,
                "new_product": n.new_product}
        if n.has("TALKING_TO_AI"):
            pre.append(t("ai", lang))
        if n.has("ASK_FOR_SELLER"):
            pre.append(t("no_contact_buyer", lang))
        if n.has("PRICE_QUERY") and not n.has("ALREADY_BOUGHT", "NO_LONGER_NEEDED"):
            if "Price asked" not in s.notes:
                s.notes.append("Price asked")
            pre.append(t("price" if s.price_told == 0 else "price2", lang))
            s.price_told += 1
        if n.has("ASK_FOR_CLARIFICATION") and not got and s.expect and s.phase == "collect":
            return f"{t('clarify', lang)} {ask_text(s.product or '', s.expect, lang)}", "clarify", info

        # ---- product change (VANI PRODUCT_CHANGE: confirm before switching)
        if n.new_product and s.phase in ("collect", "offer", "confirm") and \
                catalog.canonical_product(n.new_product) != catalog.canonical_product(s.product or ""):
            if s.asks["product"] < ASK_LIMITS["product"]:
                s.candidate, s.phase, s.expect = n.new_product, "confirm", "product_confirm"
                s.asks["product"] += 1
                s.metrics["questions"] += 1
                s.metrics["reasks_of_known"] += int("product" in s.shadow_known and not s.warm)
                return self._join(pre, _confirm_text(n.new_product, lang)), "ask", info

        # ---- requirement withdrawn / already bought -> close it, then probe ONCE using the context file
        no_longer_said = bool(n.has("NO_LONGER_NEEDED") and (NO_LONGER.search(text) or not n.has("POSTPONE")))
        withdrew = n.has("ALREADY_BOUGHT") or (no_longer_said and not n.has("ASK_FOR_ALTERNATE_SELLER"))
        suggested_and_denied = (s.phase == "confirm" and n.has("DENY") and not s.dropped
                                and s.opening.get("scenario") in ("intent_suggest", "called_product"))
        if (withdrew or suggested_and_denied) and not got and not n.new_product \
                and s.phase in ("collect", "offer", "confirm", "feedback") and (s.product or s.candidate):
            return self._withdraw(s, n, pre, info)

        if s.phase == "probe":
            prod = n.new_product
            if not prod and n.has("AFFIRM") and len(s.suggestions) == 1:
                prod = s.suggestions[0]
            if prod:
                if catalog.product(prod):  # buyer named it in answer to our probe: requirement confirmed
                    return self._accept_product(s, prod, text, pre, info)
                s.candidate, s.phase, s.expect = prod, "confirm", "product_confirm"
                s.asks["product"] += 1
                s.metrics["questions"] += 1
                return self._join(pre, _confirm_text(prod, lang)), "ask", info
            if n.has("AFFIRM") and not n.has("DENY", "NO_LONGER_NEEDED") and len(s.suggestions) > 1 and not s.asks["probe_pick"]:
                s.asks["probe_pick"] += 1
                s.metrics["questions"] += 1
                return self._join(pre, t("probe_pick", lang, a=s.suggestions[0], b=s.suggestions[1])), "ask", info
            return self._close(s, "requirement_withdrawn", pre, info)

        if s.phase == "identify":
            prod = n.new_product
            if prod:
                s.candidate, s.phase, s.expect = prod, "confirm", "product_confirm"
                s.asks["product"] += 1
                s.metrics["questions"] += 1
                s.metrics["reasks_of_known"] += int("product" in s.shadow_known and not s.warm)
                return self._join(pre, _confirm_text(prod, lang)), "ask", info
            if n.has("DENY", "END_CALL") or s.asks["product"] >= ASK_LIMITS["product"]:
                return self._close(s, "no_requirement", pre, info)
            s.asks["product"] += 1
            s.metrics["questions"] += 1
            s.metrics["reasks_of_known"] += int("product" in s.shadow_known and not s.warm)
            return self._join(pre, t("ask_product2", lang)), "ask", info

        if s.phase == "confirm":
            prod = s.candidate or s.product
            if n.has("AFFIRM") or got or (n.new_product and catalog.canonical_product(n.new_product) == catalog.canonical_product(prod)):
                return self._accept_product(s, prod, text, pre, info, got=got)
            if n.has("DENY"):
                s.phase, s.expect = "identify", "product"
                if s.asks["product"] >= ASK_LIMITS["product"]:
                    return self._close(s, "no_requirement", pre, info)
                s.asks["product"] += 1
                s.metrics["questions"] += 1
                s.metrics["reasks_of_known"] += int("product" in s.shadow_known and not s.warm)
                return self._join(pre, t("ask_product", lang)), "ask", info
            if s.asks["product"] >= ASK_LIMITS["product"]:
                return self._close(s, "no_requirement", pre, info)
            s.asks["product"] += 1
            s.metrics["questions"] += 1
            s.metrics["reasks_of_known"] += int("product" in s.shadow_known and not s.warm)
            purpose = catalog.purpose(prod, lang)
            return self._join(pre, (f"{prod}, jo {purpose}, kya aapko wahi chahiye?" if lang == "hi"
                                    else f"{prod}, {purpose}, is that what you need?")), "ask", info

        if s.phase == "feedback":
            s.captured_session["transfer_feedback"] = text[:120]
            s.outcome = "feedback_given"
            s.ended = True
            return self._join(pre, t("feedback_thanks", lang)), "close", info

        if s.phase == "collect":
            if n.has("POSTPONE") and not got and not n.has("AFFIRM"):
                return self._close(s, "postponed", pre, info)   # requirement stays open; next call resumes it
            if n.has("END_CALL") and not got:
                return self._close(s, "buyer_left", pre, info)
            if n.has("ASK_FOR_ALTERNATE_SELLER") and not got:
                s.seller_asks += 1
                if s.seller_asks > 2:
                    return self._offer(s, pre, info)
                pre.append(t("hold_seller", lang))
            e = s.expect
            if e and e in self._fields(s) and e not in got and e not in s.slots:
                if n.has("DONT_KNOW"):
                    s.closed.add(e)
                    s.notes.append(f"{e}: buyer will discuss with seller")
                    pre.append(t("defer", lang))
                elif s.asks[e] >= self._limit(s, e) and not pre:
                    s.closed.add(e)
                    pre.append(t("defer", lang))
            return self._next_or_offer(s, pre, "ask", info, filler=bool(got))

        if s.phase == "offer":
            if n.has("AFFIRM", "ASK_FOR_ALTERNATE_SELLER") and not n.has("DENY"):
                return self._transfer(s, pre, info)
            if n.has("DENY", "END_CALL"):
                return self._close(s, "transfer_refused", pre, info)
            if s.asks["transfer"] >= ASK_LIMITS["transfer"]:
                return self._close(s, "transfer_unanswered", pre, info)
            return self._offer(s, pre, info)
        return self._join(pre, t("ask_product", lang)), "ask", info

    def _accept_product(self, s: Session, prod: str, text: str, pre, info, got=None):
        """Requirement confirmed for `prod`: switch context if needed, capture its slots, ask what is missing."""
        switched = catalog.canonical_product(prod) != catalog.canonical_product(s.product or "")
        if switched:  # new requirement: drop product-specific slots, keep name/city/state
            for k in list(s.slots):
                if k not in ("name", "city", "state"):
                    s.slots.pop(k)
                    s.prefilled.discard(k)
            s.captured_session = {k: v for k, v in s.captured_session.items() if k in ("name", "city", "state")}
            s.shadow_known = {k for k in s.shadow_known if k in ("name", "city", "state")}
            s.thread_ref = None
            if s.product:
                s.notes.append(f"Switched from {s.product} to {prod}")
        s.product, s.candidate, s.phase = prod, None, "collect"
        got = (got or []) + self._capture(s, parse_buyer(text, prod, None, None).slots)  # e.g. "haan, 200 elbow chahiye"
        info["captured"] = list(dict.fromkeys(info.get("captured", []) + got))
        s.live = live_seller(prod, exclude=s.call_seller)
        if s.persist and not s.thread_ref:
            s.thread_ref = f"ENQ-{random.randint(732000, 739999)}"
            self._emit(s, "enquiry.created", {"enq_id": s.thread_ref, "product": prod,
                                              "city": s.slots.get("city"), "channel": s.channel})
        if (not s.warm or not s.ctx_info) and s.channel == "voice" and not got and not s.dropped:
            pre.append(t("identity", s.lang))
        return self._next_or_offer(s, pre, "confirmed", info, filler=bool(got))

    def _withdraw(self, s: Session, n, pre, info):
        old = s.product or s.candidate
        bought = n.has("ALREADY_BOUGHT")
        reason = "already bought" if bought else "no longer needed"
        had_thread = bool(s.thread_ref or "product" in s.prefilled or s.phase in ("collect", "offer"))
        s.dropped.append(old)
        if had_thread:
            s.notes.append(f"{old}: {reason}")
            if s.persist:  # close the old thread in the file so no channel tries to resume it again
                self._emit(s, "conversation.update", {
                    "session_id": f"{s.channel[0].upper()}-{s.id}-{len(s.dropped)}", "channel": s.channel,
                    "bot": "VANI" if s.channel == "voice" else "IM WhatsApp", "product": old, "captured": {},
                    "pending": [], "notes": [f"Buyer: {reason}"], "outcome": "requirement_withdrawn",
                    "summary": f"Buyer said the {old} requirement is {reason}", "lang": s.lang})
                if s.thread_ref:
                    self._emit(s, "enquiry.status", {"enq_id": s.thread_ref, "status": "dropped", "note": reason})
        for k in list(s.slots):
            if k not in ("name", "city", "state"):
                s.slots.pop(k)
                s.prefilled.discard(k)
        s.captured_session = {k: v for k, v in s.captured_session.items() if k in ("name", "city", "state")}
        s.prefilled.discard("product")
        s.shadow_known = {k for k in s.shadow_known if k in ("name", "city", "state")}
        s.product = s.candidate = s.thread_ref = s.live = None
        if s.probed:
            return self._close(s, "requirement_withdrawn", pre, info)
        s.probed, s.suggestions = True, self._suggest(s)
        s.phase, s.expect = "probe", "product"
        s.asks["product"] += 1
        s.metrics["questions"] += 1
        ack = t("understood_bought" if bought else "understood_withdrawn" if had_thread else "understood_suggested",
                s.lang, p=old)
        return self._join([*pre, ack], self._probe_text(s, old)), "ask", info

    def _probe_text(self, s: Session, old: str) -> str:
        """'I've seen you were looking at X on the IndiaMART app yesterday... want to post a requirement?'
        Every suggestion is cited with its source and timeline from the buyer's own file."""
        lang, sg = s.lang, s.suggestions
        if not sg:
            return t("probe_generic", lang)
        personal = [p for p in sg if s.suggestion_meta[p]["personal"]]
        if personal:
            items = []
            for p in personal:
                m = s.suggestion_meta[p]
                where = "website" if m["via"] == "web search" else "app"
                items.append((p, when_spoken(parse_ts(m["last"]), lang), where, m["via"] == "seller call"))
            if lang == "hi" and len(items) == 2 and not items[0][3] and not items[1][3]:
                # both from search: one sentence, "aap kal website par X, aur parson app par Y dekh rahe the"
                (p1, w1, x1, _), (p2, w2, x2, _) = items
                joined = f"aap {w1} IndiaMART {x1} par {p1}, aur {w2} IndiaMART {x2} par {p2} dekh rahe the"
            else:
                joined = (", aur " if lang == "hi" else ", and ").join(
                    t("seen_call", lang, p=p, when=w) if call else t("seen_search", lang, p=p, when=w, where=x)
                    for p, w, x, call in items)
            return f"{t('seen_intro', lang, clauses=joined)} {t('post_two' if len(personal) > 1 else 'post_one', lang)}"
        p = sg[0]  # repeat order: what the buyer actually bought, with when and from whom
        m = s.suggestion_meta[p]
        seller = re.search(r"from (.+)$", m.get("note") or "")
        frm = ((f" {seller.group(1)} se" if lang == "hi" else f" from {seller.group(1)}") if seller else "")
        return t("seen_bought", lang, p=p, when=when_spoken(parse_ts(m["last"]), lang), frm=frm)

    def _suggest(self, s: Session) -> list[str]:
        """Products to probe for, only from the buyer's own history in the file, each with source and date:
        1. what they checked recently on IndiaMART (searches, calls to sellers), up to two, newest first;
        2. otherwise what they actually bought (repeat order), the latest one;
        3. otherwise nothing, and the probe is a plain "any other requirement?" question."""
        m = s.ctx_meta or {}
        excl = {catalog.canonical_product(p) for p in s.dropped if p}
        out, meta = [], {}
        for i in m.get("interests") or []:
            c = catalog.canonical_product(i.get("product"))
            if c and catalog.product(c) and c not in excl and c not in out:
                out.append(c)
                meta[c] = {"via": i.get("via", "search"), "last": str(i.get("last")), "personal": True}
        out = out[:2]
        if not out:
            for x in m.get("purchases") or []:
                c = catalog.canonical_product(x.get("product"))
                if c and catalog.product(c) and c not in excl:
                    out, meta[c] = [c], {"via": "purchase", "last": str(x.get("last")), "note": x.get("note"),
                                         "personal": False}
                    break
        s.suggestion_meta = meta
        return out

    def _next_or_offer(self, s: Session, pre, kind, info, filler: bool = False):
        f = self._next_field(s)
        if f:
            q = self._ask(s, f)
            if filler and not pre:
                pre = [random.choice(FILLER[tl(s.lang)])]
            return self._join(pre, q), kind if kind == "confirmed" else "ask", info
        return self._offer(s, pre, info, filler=filler)

    def _offer(self, s: Session, pre, info, filler: bool = False):
        if not s.live:  # VANI: no live seller -> close with WhatsApp seller-details line
            return self._close(s, "no_live_seller", pre, info)
        s.phase, s.expect = "offer", "transfer"
        s.asks["transfer"] += 1
        s.metrics["questions"] += 1
        name = s.slots.get("name")
        n = (f"{name} ji, " if s.lang == "hi" else f"{name}, ") if name else ""
        key = "offer_live_wa" if s.channel != "voice" else "offer_live"
        if filler and not pre:
            pre = [random.choice(FILLER[tl(s.lang)])]
        return self._join(pre, t(key, s.lang, n=n, c=s.live["company"], city=s.live["city"])), "offer", info

    def _transfer(self, s: Session, pre, info):
        s.outcome, s.ended = "transferred", True
        key = "transfer_wa" if s.channel != "voice" else "transfer"
        return self._join(pre, t(key, s.lang, c=s.live["company"])), "close", info

    def _close(self, s: Session, outcome: str, pre, info=None):
        s.outcome, s.ended = outcome, True
        key = {"no_requirement": "close_no_req", "requirement_withdrawn": "close_withdrawn",
               "postponed": "close_postponed"}.get(outcome, "close_details")
        return self._join(pre, t(key, s.lang)), "close", info or {"intents": [], "slots": {}, "captured": [], "llm_used": False}

    # ---------------------------------------------------------------- seller policy
    def _seller_turn(self, s: Session, text: str):
        n = parse_seller(text, s.expect, self.llm if s.reply_mode == "llm" else None)
        lang, pre, got = s.lang, [], []
        info = {"intents": sorted(n.intents), "slots": n.slots, "captured": got, "llm_used": n.llm_used}
        if n.has("ASK_FOR_SELLER"):
            pre.append(t("no_contact_seller", lang))
            s.metrics["privacy_refusals"] += 1
        if n.has("TALKING_TO_AI"):
            pre.append(t("ai", lang))
        ref = (s.lead or {}).get("ref")

        def record_outcome(outcome):
            s.captured_session[f"lead_feedback:{ref}"] = outcome
            got.append("lead_feedback")
            if s.persist and outcome != "not_contacted":
                self._emit(s, "lead.response", {"lead_id": ref, "action": "called", "outcome": outcome})

        if s.phase == "lead_followup":
            if n.slots.get("outcome") and n.slots["outcome"] != "not_contacted":
                record_outcome(n.slots["outcome"])
                pre.append(t("s_noted", lang))
                return self._seller_next(s, pre, info)
            if n.has("AFFIRM") and not n.has("DENY"):
                s.phase, s.expect = "lead_outcome", f"lead_outcome:{ref}"
                s.asks["lead_outcome"] += 1
                s.metrics["questions"] += 1
                return self._join(pre, t("s_ask_outcome", lang)), "ask", info
            if n.has("DENY", "DONT_KNOW") or n.slots.get("outcome") == "not_contacted":
                s.phase, s.expect = "resend", "resend"
                s.metrics["questions"] += 1
                return self._join(pre, t("s_offer_resend", lang)), "ask", info
            if pre or s.asks["lead"] < ASK_LIMITS["seller_item"]:
                s.asks["lead"] += 1
                return self._join(pre, seller_opening_q(s)), "ask", info
            return self._seller_next(s, pre, info)
        if s.phase == "lead_outcome":
            if n.slots.get("outcome"):
                record_outcome(n.slots["outcome"])
                pre.append(t("s_noted", lang))
            elif s.asks["lead_outcome"] < 2 and not n.has("DONT_KNOW", "DENY"):
                s.asks["lead_outcome"] += 1
                return self._join(pre, t("s_ask_outcome", lang)), "ask", info
            return self._seller_next(s, pre, info)
        if s.phase in ("resend", "missed_call"):
            if n.has("AFFIRM") and not n.has("DENY"):
                key = f"lead_followup:{ref}" if ref else "missed_call"
                s.captured_session[key] = "details resent on WhatsApp"
                got.append(key)
                pre.append(t("s_resent", lang))
            return self._seller_next(s, pre, info)
        if s.phase == "prefs":
            e = s.expect
            if n.slots.get(e):
                s.slots[e] = n.slots[e]
                s.captured_session[e] = n.slots[e]
                got.append(e)
            elif n.has("DONT_KNOW", "DENY") or s.asks[e] >= ASK_LIMITS["seller_item"]:
                s.closed.add(e)
            else:
                s.asks[e] += 1
                return self._join(pre, seller_ask_text(e, lang).capitalize()), "ask", info
            return self._seller_next(s, pre, info, filler=bool(got))
        if s.phase == "open":
            if n.has("AFFIRM") and s.expect == "help":
                return self._seller_next(s, pre, info)
            if s.expect != "help":
                s.expect = "help"
                return self._join(pre, t("s_help", lang)), "ask", info
            return self._seller_close(s, pre, info)
        return self._seller_close(s, pre, info)

    def _seller_next(self, s: Session, pre, info, filler: bool = False):
        if s.dnd:  # asked not to be disturbed: one point only
            return self._seller_close(s, pre, info)
        for f in ("pref_min_qty", "pref_regions"):
            if f in s.slots or f in s.closed:
                continue
            if s.asks[f] >= ASK_LIMITS["seller_item"]:
                s.closed.add(f)
                continue
            s.phase, s.expect = "prefs", f
            s.asks[f] += 1
            s.metrics["questions"] += 1
            if f in s.shadow_known:
                s.metrics["reasks_of_known"] += 1
            if filler and not pre:
                pre = [random.choice(FILLER[tl(s.lang)])]
            lead_in = "Ek aur baat, " if s.lang == "hi" else "One more thing, "
            return self._join(pre, lead_in + seller_ask_text(f, s.lang)), "ask", info
        return self._seller_close(s, pre, info)

    def _seller_close(self, s: Session, pre, info):
        s.ended = True
        s.outcome = s.outcome or ("feedback_given" if s.captured_session else "no_action")
        name = s.slots.get("contact", "")
        if s.dnd:
            return self._join(pre, t("s_close_dnd", s.lang, n=name, d=s.dnd)), "close", info
        return self._join(pre, t("s_close", s.lang, n=name)), "close", info

    # ================================================================ phrasing + guards
    @staticmethod
    def _join(pre: list[str], main: str) -> str:
        return " ".join([*pre, main]).strip()

    def prompt(self, sid: str) -> str:
        s = self.sessions[sid]
        v = dict(s.vars)
        if s.role == "buyer":
            spec_keys = catalog.specs(s.product or "").keys()
            v.update({"product_name": s.product or "", "quantity": s.slots.get("quantity", ""),
                      "specifications": {k: s.slots[k] for k in spec_keys if k in s.slots},
                      "buyer_name": s.slots.get("name", ""), "buyer_city": s.slots.get("city", ""),
                      "quantity_unit_options": catalog.units(s.product or ""),
                      "specification_options": catalog.specs(s.product or ""),
                      "current_phase": {"collect": "REQUIREMENT COLLECTION", "offer": "FINALISATION"}.get(s.phase, "REQUIREMENT CONFIRMATION")})
        return render_prompt(s.role, v)

    def _phrase(self, s: Session, draft: str, kind: str) -> str:
        if s.lang not in ("hi", "en"):
            return translate(self._leak_guard(s, draft), s.lang, self.llm)
        if s.reply_mode != "llm" or kind == "close" or not self.llm or not self.llm.available:
            return draft
        lang_name = "Hinglish (Hindi written in Roman script)" if s.lang == "hi" else "English"
        directive = (
            "TURN INSTRUCTION (follow exactly). Your next message must convey exactly this and nothing more:\n"
            f"\"{draft}\"\n"
            f"Rephrase it naturally in {lang_name} as a {'WhatsApp message' if s.channel != 'voice' else 'spoken phone reply'}: "
            "at most 2 short sentences, keep the same question at the end, keep numbers, units and product names exactly, "
            "do not greet, do not add any other question. Never restate, confirm or summarise details the user just gave "
            "(no 'X note kar liya', no 'you said X'); a one-word acknowledgement like 'Ji' is enough. Output only the message.")
        msgs = [{"role": "system", "content": self.prompt(s.id) + "\n\n" + directive}]
        for turn in s.transcript[-6:]:
            msgs.append({"role": "assistant" if turn["who"] == "bot" else "user", "content": turn["text"]})
        if msgs[-1]["role"] != "user":
            msgs.append({"role": "user", "content": "(continue)"})
        out = self.llm.chat(msgs, max_tokens=160, temperature=0.4)
        if not out or len(out) > 360 or "{" in out or out.count("?") > 1:
            return draft
        out = out.strip().strip('"')
        low, dlow = out.lower(), draft.lower()
        if not self._on_target(s, low, dlow, kind):
            s.metrics["offscript_blocked"] += 1
            return draft
        for v in getattr(s, "last_values", []):  # VANI no-echo rule: never read back what was just said
            if v and len(v) > 1 and v.lower() in low and v.lower() not in dlow:
                s.metrics["echo_blocked"] += 1
                return draft
        for f in s.prefilled | (s.shadow_known if s.warm else set()):
            for kw in REASK_KEYWORDS.get(f, [f.lower()] if f not in ("product",) else []):
                if kw in low and kw not in dlow and "?" in out:
                    s.metrics["reask_blocked"] += 1
                    return draft
        return out

    @staticmethod
    def _on_target(s: Session, low: str, dlow: str, kind: str) -> bool:
        """The LLM may only rephrase: it must still ask what the policy asked, and nothing VANI forbids."""
        if any(w in low and w not in dlow for w in OFF_SCRIPT):
            return False
        e = s.expect or ""
        if kind in ("ask", "confirmed") and e:
            if e in TARGET_KW:
                kws = TARGET_KW[e]
            elif e in catalog.specs(s.product or ""):
                kws = [e.lower(), *[o.split()[0].lower() for o in catalog.specs(s.product)[e][:2]]]
            else:
                return True
            return any(k in low for k in kws)
        if kind == "offer":
            return any(k in low for k in ("connect", "call", "baat"))
        return True

    def _deny_set(self, glid: str, own) -> set:
        ents: dict[str, set] = {}
        for c in reader.read_all():
            k = c.meta.get("known") or {}
            e = {k.get("name"), k.get("company"), k.get("contact")}
            for line in c.sections.get("Sellers contacted", []):
                e.add(line[2:].split(",")[0].strip())
            ents[str(c.meta.get("glid"))] = {x for x in e if x}
        return privacy.foreign_entities(own.raw if own else "", ents, glid)

    def _leak_guard(self, s: Session, reply: str) -> str:
        allowed = {s.live["company"]} if s.live else set()
        hits = privacy.leak_check(reply, s.deny - allowed)
        if hits:
            s.metrics["leak_blocked"] += 1
            s.notes.append(f"leak guard blocked: {', '.join(sorted(set(hits)))[:80]}")
            nxt = ask_text(s.product or "", s.expect, s.lang) if s.role == "buyer" and s.expect in self._fields(s) else ""
            return f"{t('leak_block', s.lang)} {nxt}".strip()
        return reply

    # ================================================================ events
    def _emit(self, s: Session, typ: str, payload: dict, glid: str | None = None, role: str | None = None,
              counterparty: str | None = None):
        src = ("vani_voice" if s.channel == "voice" else "whatsapp_bot") if s.role == "buyer" else f"seller_assist_{s.channel}"
        self.refresher.ingest([{"glid": glid or s.glid, "role": role or s.role, "type": typ, "source": src,
                                "occurred_at": iso(now()), "counterparty": counterparty, "payload": payload}],
                              trigger="live")

    def _conv_payload(self, s: Session, outcome: str) -> dict:
        bot = ("VANI" if s.channel == "voice" else "IM WhatsApp") if s.role == "buyer" else "Seller Assist"
        pending = [f for f in self._fields(s) if f not in s.slots] if s.role == "buyer" else []
        return {"session_id": f"{s.channel[0].upper()}-{s.id}", "channel": s.channel, "bot": bot,
                "product": s.product if s.role == "buyer" else (s.lead or {}).get("product"),
                "captured": dict(s.captured_session), "pending": pending, "notes": list(dict.fromkeys(s.notes)),
                "outcome": outcome, "summary": self._summary(s), "lang": s.lang}

    def _emit_update(self, s: Session):
        self._emit(s, "conversation.update", self._conv_payload(s, "in_progress"))

    def _finish(self, s: Session):
        if not s.persist or s.outcome == "suppressed_dnd":
            return
        self._emit(s, "conversation.ended", self._conv_payload(s, s.outcome))
        if s.role == "buyer" and s.outcome == "transferred" and s.live:
            # cross-party: the live transfer lands in the receiving seller's file (only lead fields)
            lid = f"L-{(s.thread_ref or 'X').split('-')[-1]}"
            specs = {k: s.slots[k] for k in catalog.specs(s.product or "") if k in s.slots}
            q = (s.slots.get("quantity") or "").split(" ", 1)
            qn = float(q[0]) if q and q[0].replace(".", "").isdigit() else None
            self._emit(s, "lead.received", {"lead_id": lid, "product": s.product,
                                            "quantity": int(qn) if qn is not None and qn.is_integer() else qn,
                                            "unit": q[1] if len(q) > 1 else None, "specs": specs,
                                            "buyer_city": s.slots.get("city"), "buyer_state": s.slots.get("state"),
                                            "via": "Live transfer"},
                       glid=s.live["glid"], role="seller", counterparty=s.glid)
            self._emit(s, "lead.response", {"lead_id": lid, "action": "live_call", "outcome": "connected"},
                       glid=s.live["glid"], role="seller")
            if s.thread_ref:
                self._emit(s, "enquiry.status", {"enq_id": s.thread_ref, "status": "transferred",
                                                 "note": f"live call with {s.live['company']}"})

    def _summary(self, s: Session) -> str:
        parts = []
        if s.role == "buyer":
            gave = [f"{'qty' if k == 'quantity' else k} {v}" for k, v in s.captured_session.items() if k != "transfer_feedback"]
            if gave:
                parts.append("Gave " + ", ".join(gave))
            if "Price asked" in s.notes:
                parts.append("asked price (seller will quote)")
            parts += [n for n in s.notes if n.endswith(("no longer needed", "already bought"))]
            for n in s.notes:
                if n.startswith("Switched"):
                    parts.append(n.lower())
            parts.append({"transferred": f"connected live to {(s.live or {}).get('company', 'a seller')}",
                          "transfer_refused": "declined live transfer; seller details to go on WhatsApp",
                          "no_live_seller": "no live seller free; seller details to go on WhatsApp",
                          "transfer_unanswered": "did not answer transfer offer; details to go on WhatsApp",
                          "no_requirement": "no product requirement", "buyer_left": "buyer ended the conversation",
                          "requirement_withdrawn": "no other requirement right now",
                          "postponed": "asked to continue later; requirement kept open",
                          "feedback_given": f"feedback on seller: {s.captured_session.get('transfer_feedback', '')[:60]}",
                          "dropped": "conversation dropped", "in_progress": "in progress"}.get(s.outcome or "in_progress", s.outcome or ""))
        else:
            for k, v in s.captured_session.items():
                parts.append(f"{k.replace('lead_feedback:', 'lead ').replace('lead_followup:', 'lead ')}: {v}")
            parts.append({"dropped": "call dropped"}.get(s.outcome or "", ""))
        txt = "; ".join(p for p in parts if p)
        return (txt[0].upper() + txt[1:]) if txt else "Opened, no details exchanged"

    # ================================================================ state for UI / tests
    def _state(self, s: Session) -> dict:
        return {"phase": s.phase, "expect": s.expect, "product": s.product, "slots": s.slots,
                "lang": s.lang, "languages": s.languages,
                "prefilled": sorted(s.prefilled), "closed": sorted(s.closed), "asks": dict(s.asks),
                "notes": s.notes, "outcome": s.outcome, "ended": s.ended, "metrics": dict(s.metrics),
                "live_seller": s.live, "channel": s.channel, "warm": s.warm, "glid": s.glid, "role": s.role,
                "turns": sum(1 for x in s.transcript if x["who"] == "user")}


def seller_opening_q(s: Session) -> str:
    return "Kya aapki us buyer se baat ho payi?" if s.lang == "hi" else "Were you able to speak to that buyer?"


def _confirm_text(prod: str, lang: str) -> str:
    purpose = catalog.purpose(prod, lang)
    if purpose:
        return t("confirm_product", lang, p=prod, purpose=purpose)
    return f"Achha, toh aapko {prod} chahiye, sahi?" if lang == "hi" else f"So you need {prod}, right?"
