"""Understanding one user turn: fast rules first, Sarvam LLM extraction only when the rules miss
the field that was just asked (keeps most turns at zero LLM latency for understanding)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ctxlayer import catalog

# ---------------------------------------------------------------- lexicons
def _rx(words: list[str]) -> re.Pattern:
    ascii_w = [w for w in words if w.isascii()]
    uni_w = [w for w in words if not w.isascii()]
    parts = []
    if ascii_w:
        parts.append(r"(?<![a-z])(?:" + "|".join(sorted(map(re.escape, ascii_w), key=len, reverse=True)) + r")(?![a-z])")
    if uni_w:
        parts.append("(?:" + "|".join(map(re.escape, uni_w)) + ")")
    return re.compile("|".join(parts), re.I)


AFFIRM = _rx(["haan", "haa", "han", "ha", "ji", "jee", "yes", "yeah", "yep", "yup", "bilkul", "sahi", "theek", "thik",
              "ok", "okay", "zaroor", "jarur", "right", "correct", "sure", "kar do", "kardo", "kar dijiye", "kijiye",
              "chalega", "done", "please", "हाँ", "हां", "जी", "बिल्कुल", "सही", "ठीक", "ज़रूर",
              "ஆமாம்", "சரி", "అవును", "సరే", "হ্যাঁ", "ঠিক আছে", "ಹೌದು", "ಸರಿ", "അതെ", "ശരി", "होय", "हो", "હા", "બરાબર",
              "ਹਾਂ", "ਠੀਕ", "ହଁ", "ଠିକ"])
DENY = _rx(["nahi", "nahin", "nai", "no", "nope", "mat", "not now", "abhi nahi", "baad mein", "later",
            "नहीं", "ना", "मत", "இல்லை", "வேண்டாம்", "లేదు", "వద్దు", "না", "ಇಲ್ಲ", "ಬೇಡ", "ഇല്ല", "വേണ്ട", "नाही", "નહીં", "ના",
            "ਨਹੀਂ", "ନା", "ନାହିଁ"])
DONT_KNOW = _rx(["pata nahi", "nahi pata", "malum nahi", "maloom nahi", "don't know", "dont know", "not sure",
                 "seller se baat", "seller decide", "seller bata", "seller hi bata", "पता नहीं"])
ANY = _rx(["koi bhi", "kuch bhi", "any", "anything", "aap suggest", "jo bhi", "कोई भी"])
PRICE = _rx(["price", "rate", "kitne ka", "kitne ki", "kitna", "daam", "cost", "quotation", "quote", "bhav", "keemat",
             "discount", "budget", "रेट", "कीमत", "भाव", "दाम"])
AI = _rx(["robot", "bot", "ai", "machine", "insaan", "human", "computer", "recorded", "real person", "रोबोट"])
SELLER_CONTACT = _rx(["number do", "number dijiye", "number de", "unka number", "uska number", "contact number",
                      "mobile number", "phone number", "number kya", "address", "naam kya", "uska naam", "unka naam",
                      "kis kis", "kis-kis", "kaun kaun", "who else", "other sellers", "aur kisse", "kiske saath"])
CONNECT = _rx(["connect", "baat karao", "baat karwa", "baat kara", "transfer", "seller se baat", "call karwa",
               "jod do", "milwa do"])
END = _rx(["bye", "rakhta", "rakhti", "rakh raha", "band karo", "call cut", "baad mein baat", "busy hoon", "busy hun",
           "abhi busy", "time nahi"])
NO_LONGER = _rx(["nahi chahiye", "nahin chahiye", "nai chahiye", "kuch nahi chahiye", "kuchh nahi chahiye",
                 "koi requirement nahi", "requirement nahi", "requirement khatam", "zarurat nahi", "zaroorat nahi",
                 "jarurat nahi", "need nahi", "don't need", "dont need", "do not need", "no longer", "not required",
                 "not needed", "cancel", "rehne do", "rahne do", "नहीं चाहिए", "ज़रूरत नहीं", "जरूरत नहीं"])
BOUGHT = _rx(["le liya", "le chuka", "le chuke", "kharid liya", "khareed liya", "already bought", "already purchased",
              "bought it", "purchased it", "order kar diya", "order de diya", "kahin aur se le", "ले लिया", "खरीद लिया"])
POSTPONE = _rx(["later", "maybe later", "not now", "abhi nahi", "baad mein", "baad me", "kal baat", "call later",
                "call back", "callback", "some other time", "thodi der baad", "phir kabhi", "बाद में", "अभी नहीं"])
CLARIFY = _rx(["samjha nahi", "samajh nahi", "kya bola", "kya kaha", "repeat", "dobara bolo", "phir se", "pardon",
               "what do you mean", "didn't get", "matlab"])

NUM_WORDS = {"ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5, "chhe": 6, "chhah": 6,
             "che": 6, "saat": 7, "aath": 8, "nau": 9, "das": 10, "bees": 20, "pachaas": 50, "pachas": 50,
             "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
             "ten": 10, "twenty": 20, "fifty": 50, "dedh": 1.5, "dhai": 2.5,
             "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5, "पाँच": 5, "छह": 6, "छः": 6, "सात": 7, "आठ": 8,
             "नौ": 9, "दस": 10, "बीस": 20, "पचास": 50}
MULT = {"sau": 100, "so": 100, "hundred": 100, "hazaar": 1000, "hazar": 1000, "hajar": 1000, "thousand": 1000,
        "lakh": 100000, "सौ": 100, "हज़ार": 1000, "हजार": 1000, "लाख": 100000}
DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

UNIT_SYN = {
    "piece": ["pieces", "piece", "pcs", "pc", "nos", "pis", "peace", "पीस"],
    "meter": ["meters", "meter", "metre", "mtr", "m", "मीटर"],
    "roll": ["rolls", "roll", "रोल"], "kg": ["kgs", "kg", "kilo", "kilogram", "किलो"],
    "unit": ["units", "unit", "plant", "machine", "set", "nag"], "box": ["boxes", "box", "carton", "dabba"],
    "inch": ["inches", "inch", "\"", "इंच"], "lph": ["lph", "litre per hour", "liter per hour"],
    "micron": ["microns", "micron"], "ply": ["ply", "प्लाई"], "l": ["litres", "litre", "liters", "liter", "ltr", "l", "लीटर"],
}
WORD_OPT_SYN = {"ss 304": ["ss", "steel", "stainless", "स्टील"], "frp": ["frp", "fibre", "fiber", "plastic body"],
                "small": ["chhota", "small"], "medium": ["medium", "beech"], "large": ["bada", "large", "big"]}
INVALID_NAMES = {"batman", "harry", "potter", "elon", "musk", "sachin", "tendulkar", "modi", "superman", "test", "abc",
                 "king", "boss", "sir", "madam", "bhai", "ji", "haan", "nahi", "hello", "hi"}
STOP = {"mera", "naam", "hai", "my", "name", "is", "i", "am", "main", "mai", "this", "ji", "sir", "bol", "raha",
        "rahi", "hoon", "hu", "se", "me", "mein", "aur", "and", "the", "from", "calling", "speaking"}


@dataclass
class NLU:
    text: str
    intents: set = field(default_factory=set)
    slots: dict = field(default_factory=dict)
    new_product: str | None = None
    llm_used: bool = False

    def has(self, *names) -> bool:
        return any(n in self.intents for n in names)


LANG_WORDS = {
    "hi": ["hindi", "हिंदी", "हिन्दी"], "en": ["english", "angrezi", "angreji", "अंग्रेज़ी", "अंग्रेजी", "इंग्लिश"],
    "bn": ["bengali", "bangla", "बांग्ला", "বাংলা"], "ta": ["tamil", "तमिल", "தமிழ்", "தமிழில்"],
    "te": ["telugu", "तेलुगु", "తెలుగు", "తెలుగులో"], "kn": ["kannada", "कन्नड़", "ಕನ್ನಡ", "ಕನ್ನಡದಲ್ಲಿ"],
    "ml": ["malayalam", "मलयालम", "മലയാളം", "മലയാളത്തിൽ"], "mr": ["marathi", "मराठी", "मराठीत"],
    "gu": ["gujarati", "gujrati", "गुजराती", "ગુજરાતી", "ગુજરાતીમાં"], "pa": ["punjabi", "panjabi", "पंजाबी", "ਪੰਜਾਬੀ", "ਪੰਜਾਬੀ ਵਿੱਚ"],
    "od": ["odia", "oriya", "ओड़िया", "उड़िया", "ଓଡ଼ିଆ", "ଓଡିଆ"],
}
UNSUPPORTED_LANGS = ["urdu", "assamese", "sanskrit", "nepali", "konkani", "kashmiri", "sindhi", "maithili", "bhojpuri",
                     "french", "german", "arabic", "spanish", "chinese", "japanese"]
LANG_CUES = _rx(["mein", "me", "main", "mai", "in", "bolo", "boliye", "bol", "baat", "speak", "talk", "language",
                 "bhasha", "please", "pls", "switch", "continue", "chalega", "samjhao", "भाषा", "बोलिए", "बोलो", "बात",
                 "பேசு", "பேசுங்கள்", "మాట్లాడ", "ಮಾತನಾಡ", "സംസാരിക്ക", "बोला", "બોલો", "ਬੋਲ", "କୁହ", "କଥା", "বলুন", "বলো"])
SCRIPTS = [("bn", "\u0980", "\u09FF"), ("pa", "\u0A00", "\u0A7F"), ("gu", "\u0A80", "\u0AFF"),
           ("od", "\u0B00", "\u0B7F"), ("ta", "\u0B80", "\u0BFF"), ("te", "\u0C00", "\u0C7F"),
           ("kn", "\u0C80", "\u0CFF"), ("ml", "\u0D00", "\u0D7F")]
INDIC = re.compile("[\u0900-\u0D7F]")


def _mentions(low: str, word: str) -> int:
    """Index of the last mention of a language word not negated right after ('Tamil nahi aati'), else -1."""
    pat = (r"(?<![a-z])" + re.escape(word) + r"(?![a-z])") if word.isascii() else re.escape(word)
    pos = -1
    for m in re.finditer(pat, low):
        after = low[m.end(): m.end() + 14]
        if not re.match(r"\s*(nahi|nahin|not|no |nai|नहीं)", after):
            pos = m.start()
    return pos


def language_request(text: str) -> tuple[str | None, str | None]:
    """Explicit request to change language -> (supported code or None, unsupported language name or None)."""
    low = re.sub(r"tamil\s*nadu|तमिलनाडु|தமிழ்நாடு", " ", text.lower())
    short = len(text.split()) <= 3
    cue = bool(LANG_CUES.search(low))
    hits = [(pos, code) for code, words in LANG_WORDS.items() for pos in [max(_mentions(low, w) for w in words)] if pos >= 0]
    if hits and (cue or short):
        return max(hits)[1], None
    bad = [w for w in UNSUPPORTED_LANGS if _mentions(low, w) >= 0]
    if bad and (cue or short):
        return None, bad[0].capitalize()
    return None, None


def script_language(text: str) -> str | None:
    """Language implied by the script of typed text (non-Devanagari Indic scripts only: hi/mr share Devanagari)."""
    counts = {}
    for code, lo, hi in SCRIPTS:
        n = len(re.findall(f"[{lo}-{hi}]", text))
        if n:
            counts[code] = n
    return max(counts, key=counts.get) if counts else None


LANG_WORDS = {
    "hi": ["hindi", "हिंदी", "हिन्दी"], "en": ["english", "angrezi", "angreji", "अंग्रेज़ी", "अंग्रेजी", "इंग्लिश"],
    "bn": ["bengali", "bangla", "बांग्ला", "বাংলা"], "ta": ["tamil", "तमिल", "தமிழ்", "தமிழில்"],
    "te": ["telugu", "तेलुगु", "తెలుగు", "తెలుగులో"], "kn": ["kannada", "कन्नड़", "ಕನ್ನಡ", "ಕನ್ನಡದಲ್ಲಿ"],
    "ml": ["malayalam", "मलयालम", "മലയാളം", "മലയാളത്തിൽ"], "mr": ["marathi", "मराठी", "मराठीत"],
    "gu": ["gujarati", "gujrati", "गुजराती", "ગુજરાતી", "ગુજરાતીમાં"], "pa": ["punjabi", "panjabi", "पंजाबी", "ਪੰਜਾਬੀ", "ਪੰਜਾਬੀ ਵਿੱਚ"],
    "od": ["odia", "oriya", "ओड़िया", "उड़िया", "ଓଡ଼ିଆ", "ଓଡିଆ"],
}
UNSUPPORTED_LANGS = ["urdu", "assamese", "sanskrit", "nepali", "konkani", "kashmiri", "sindhi", "maithili", "bhojpuri",
                     "french", "german", "arabic", "spanish", "chinese", "japanese"]
LANG_CUES = _rx(["mein", "me", "main", "mai", "in", "bolo", "boliye", "bol", "baat", "speak", "talk", "language",
                 "bhasha", "please", "pls", "switch", "continue", "chalega", "samjhao", "भाषा", "बोलिए", "बोलो", "बात",
                 "பேசு", "பேசுங்கள்", "మాట్లాడ", "ಮಾತನಾಡ", "സംസാരിക്ക", "बोला", "બોલો", "ਬੋਲ", "କୁହ", "କଥା", "বলুন", "বলো"])
SCRIPTS = [("bn", "\u0980", "\u09FF"), ("pa", "\u0A00", "\u0A7F"), ("gu", "\u0A80", "\u0AFF"),
           ("od", "\u0B00", "\u0B7F"), ("ta", "\u0B80", "\u0BFF"), ("te", "\u0C00", "\u0C7F"),
           ("kn", "\u0C80", "\u0CFF"), ("ml", "\u0D00", "\u0D7F")]
INDIC = re.compile("[\u0900-\u0D7F]")


def _mentions(low: str, word: str) -> int:
    """Index of the last mention of a language word not negated right after ('Tamil nahi aati'), else -1."""
    pat = (r"(?<![a-z])" + re.escape(word) + r"(?![a-z])") if word.isascii() else re.escape(word)
    pos = -1
    for m in re.finditer(pat, low):
        after = low[m.end(): m.end() + 14]
        if not re.match(r"\s*(nahi|nahin|not|no |nai|नहीं)", after):
            pos = m.start()
    return pos


def language_request(text: str) -> tuple[str | None, str | None]:
    """Explicit request to change language -> (supported code or None, unsupported language name or None)."""
    low = re.sub(r"tamil\s*nadu|तमिलनाडु|தமிழ்நாடு", " ", text.lower())
    short = len(text.split()) <= 3
    cue = bool(LANG_CUES.search(low))
    hits = [(pos, code) for code, words in LANG_WORDS.items() for pos in [max(_mentions(low, w) for w in words)] if pos >= 0]
    if hits and (cue or short):
        return max(hits)[1], None
    bad = [w for w in UNSUPPORTED_LANGS if _mentions(low, w) >= 0]
    if bad and (cue or short):
        return None, bad[0].capitalize()
    return None, None


def script_language(text: str) -> str | None:
    """Language implied by the script of typed text (non-Devanagari Indic scripts only: hi/mr share Devanagari)."""
    counts = {}
    for code, lo, hi in SCRIPTS:
        n = len(re.findall(f"[{lo}-{hi}]", text))
        if n:
            counts[code] = n
    return max(counts, key=counts.get) if counts else None


def normalize_numbers(t: str) -> str:
    t = t.translate(DEV_DIGITS)
    t = re.sub(r"(\d),(\d{2,3})", r"\1\2", t)
    toks = re.split(r"(\s+)", t)
    out, i = [], 0
    while i < len(toks):
        w = toks[i].lower().strip(",.?!")
        if w in NUM_WORDS or w in MULT:
            val, cur, j = 0, 0, i
            while j < len(toks):
                ww = toks[j].lower().strip(",.?!")
                if not ww.strip():
                    j += 1
                    continue
                if ww in NUM_WORDS:
                    cur += NUM_WORDS[ww]
                elif ww in MULT:
                    cur = (cur or 1) * MULT[ww]
                    if MULT[ww] >= 1000:
                        val, cur = val + cur, 0
                else:
                    break
                j += 1
            n = val + cur
            # "do" alone is usually the verb ("kar do"), "ek" alone is usually "a"
            if n and not (toks[i].lower().strip(",.?!") in ("do", "ek", "na", "so") and j == i + 1):
                out.append(str(int(n) if float(n).is_integer() else n) + " ")
                i = j
                continue
        out.append(toks[i])
        i += 1
    return "".join(out)


def _unit_alt(unit_key: str) -> str:
    syn = UNIT_SYN.get(unit_key, [unit_key])
    return "|".join(re.escape(s) for s in sorted(syn, key=len, reverse=True))


def _unit_key(word: str) -> str | None:
    w = word.lower()
    for k, syns in UNIT_SYN.items():
        if w == k or w in syns:
            return k
    return None


def match_spec(t: str, options: list[str]) -> tuple[str | None, tuple[int, int] | None]:
    low = t.lower()
    for opt in options:
        o = opt.lower()
        if o in low:
            i = low.index(o)
            return opt, (i, i + len(o))
        num = re.search(r"\d+(?:\.\d+)?", o)
        if num:
            n = num.group(0)
            rest = o.replace(n, "", 1).strip()
            ukey = _unit_key(rest.split("/")[0].split()[0]) if rest else None
            if rest and not ukey:  # "sdr 11"
                if re.search(re.escape(rest) + r"\s*" + re.escape(n), low):
                    m = re.search(re.escape(rest) + r"\s*" + re.escape(n), low)
                    return opt, m.span()
                continue
            alt = _unit_alt(ukey) if ukey else ""
            pat = r"(?<![\d.])" + re.escape(n) + (r"\s*(?:" + alt + r")(?![a-z])" if alt else r"(?![\d.])")
            m = re.search(pat, low)
            if m:
                return opt, m.span()
        else:
            for syn in WORD_OPT_SYN.get(o, [o]):
                m = re.search(r"(?<![a-z])" + re.escape(syn) + r"(?![a-z])", low)
                if m:
                    return opt, m.span()
    # custom numeric value in the same unit family, e.g. "3 inch" when options are 2/4/6 inch
    units = set()
    for opt in options:
        num = re.search(r"\d+(?:\.\d+)?", opt)
        rest = opt.lower().replace(num.group(0), "", 1).strip() if num else ""
        k = _unit_key(rest.split("/")[0].split()[0]) if rest else None
        if k:
            units.add((k, opt.replace(num.group(0), "", 1).strip()))
    for k, label in units:
        m = re.search(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:" + _unit_alt(k) + r")(?![a-z])", low)
        if m:
            return f"{m.group(1)} {label}", m.span()
    return None, None


def match_quantity(t: str, units: list[str], bare_ok: bool) -> str | None:
    low = t.lower()
    keys = [(u, _unit_key(u) or u.lower()) for u in units]
    rng = r"(\d+(?:\.\d+)?)(?:\s*(?:se|to|-|–|or|ya)\s*(\d+(?:\.\d+)?))?"
    for label, k in keys:
        m = re.search(r"(?<![\d.])" + rng + r"\s*(?:" + _unit_alt(k) + r")(?![a-z])", low)
        if m:
            n = max(float(m.group(1)), float(m.group(2) or 0))
            return f"{int(n) if n.is_integer() else n} {label}"
    if bare_ok:
        m = re.search(r"(?<![\d.])" + rng + r"(?![\d.])", low)
        if m:
            n = max(float(m.group(1)), float(m.group(2) or 0))
            return f"{int(n) if n.is_integer() else n} {units[0] if units else 'Piece'}"
    return None


def match_city(t: str) -> tuple[str | None, str | None]:
    low = t.lower()
    for alias, city in catalog.city_aliases().items():
        if alias in low:
            return city, catalog.state_of(city)
    for city, state in sorted(catalog.cities().items(), key=lambda kv: -len(kv[0])):
        if re.search(r"(?<![a-z])" + re.escape(city.lower()) + r"(?![a-z])", low):
            return city, state
    return None, None


def match_states(t: str) -> list[str]:
    low = t.lower()
    abbr = {"mp": "Madhya Pradesh", "up": "Uttar Pradesh", "mh": "Maharashtra", "gj": "Gujarat", "ap": "Andhra Pradesh",
            "tn": "Tamil Nadu", "ts": "Telangana", "cg": "Chhattisgarh"}
    found = [s for s in catalog.all_states() + ["Chhattisgarh", "Rajasthan", "Punjab", "Bihar"]
             if re.search(r"(?<![a-z])" + re.escape(s.lower()) + r"(?![a-z])", low)]
    found += [v for k, v in abbr.items() if re.search(r"(?<![a-z])" + k + r"(?![a-z])", low)]
    return list(dict.fromkeys(found))


def match_name(t: str) -> str | None:
    m = re.search(r"(?:mera naam|my name is|naam hai|i am|i'm|this is|main|mai)\s+([A-Za-z]+(?:\s+[A-Za-z]+)?)", t, re.I)
    cand = m.group(1) if m else None
    if not cand:
        words = [w for w in re.findall(r"[A-Za-z]+", t) if w.lower() not in STOP]
        if 1 <= len(words) <= 2 and len(t.split()) <= 5:
            cand = " ".join(words)
    if not cand:
        return None
    cand = " ".join(w for w in cand.split() if w.lower() not in STOP)
    if not cand or any(w.lower() in INVALID_NAMES for w in cand.split()) or len(cand) < 2:
        return None
    return cand.split()[0].capitalize()


def _intents(t: str) -> set:
    it = set()
    if CLARIFY.search(t):
        it.add("ASK_FOR_CLARIFICATION")
    if DONT_KNOW.search(t):
        it.add("DONT_KNOW")
    elif DENY.search(t):
        it.add("DENY")
    if AFFIRM.search(t) and "DENY" not in it:
        it.add("AFFIRM")
    if ANY.search(t):
        it.add("ANY")
    if PRICE.search(t):
        it.add("PRICE_QUERY")
    if AI.search(t):
        it.add("TALKING_TO_AI")
    if SELLER_CONTACT.search(t):
        it.add("ASK_FOR_SELLER")
    if CONNECT.search(t):
        it.add("ASK_FOR_ALTERNATE_SELLER")
    if END.search(t):
        it.add("END_CALL")
    if NO_LONGER.search(t):
        it.add("NO_LONGER_NEEDED")
    if BOUGHT.search(t):
        it.add("ALREADY_BOUGHT")
    if POSTPONE.search(t):
        it.add("POSTPONE")
    return it


# ---------------------------------------------------------------- buyer
def parse_buyer(text: str, product: str | None, expect: str | None, llm=None) -> NLU:
    t = normalize_numbers(text)
    n = NLU(text=text, intents=_intents(t))
    work = t
    if product:
        for fld, opts in catalog.specs(product).items():
            val, span = match_spec(work, opts)
            if val:
                n.slots[fld] = val
                work = work[: span[0]] + " " + work[span[1]:]
        q = match_quantity(work, catalog.units(product), bare_ok=(expect == "quantity"))
        if q:
            n.slots["quantity"] = q
        if expect in catalog.specs(product) and expect not in n.slots and "ANY" in n.intents:
            n.slots[expect] = "Any"
    city, _ = match_city(t)
    if city:
        n.slots["city"] = city  # VANI: never auto-fill the state from the city; the buyer must say it
    states = match_states(t)
    if states and expect in ("state", "city"):
        n.slots["state"] = states[0]
    if expect == "name":
        nm = match_name(text)
        if nm and not city:
            n.slots["name"] = nm
    mentioned = catalog.canonical_product(text)
    if mentioned and (not product or catalog.canonical_product(product) != mentioned):
        n.new_product = mentioned
    # LLM extraction when the asked field is still missing and the turn has content
    needs = expect and expect not in n.slots and expect not in ("transfer", "product_confirm") \
        and not (n.intents & {"DONT_KNOW", "ANY", "NO_LONGER_NEEDED", "ALREADY_BOUGHT"}) and len(text.split()) >= 1
    indic = bool(INDIC.search(text))
    if llm is not None and llm.available and (needs or indic or (expect == "product" and not mentioned)):
        _llm_fill(n, text, product, expect, llm)
    if product and expect in catalog.specs(product) and expect not in n.slots and "quantity" in n.slots:
        num = re.match(r"(\d+(?:\.\d+)?)", n.slots["quantity"])
        for opt in catalog.specs(product)[expect]:
            m = re.match(r"(\d+(?:\.\d+)?)", opt)
            if num and m and float(num.group(1)) == float(m.group(1)):
                n.slots[expect] = opt   # "chhah kilo" while Pressure Rating is pending -> 6 kg/cm2
                n.slots.pop("quantity")
                break
    return n


def _llm_fill(n: NLU, text: str, product: str | None, expect: str | None, llm):
    specs = catalog.specs(product) if product else {}
    fields = []
    if product:
        fields.append(f"quantity (how many items; unit one of {', '.join(catalog.units(product))})")
        fields += [f"{k} (options: {', '.join(v)})" for k, v in specs.items()]
    fields += ["name (buyer's own first name)", "city", "state"]
    system = (
        "Extract structured data from ONE buyer utterance in an IndiaMART call. Output ONLY a JSON object.\n"
        f"Product in discussion: {product or 'unknown'}. Question just asked: {expect or 'none'}.\n"
        f"Fillable fields: {'; '.join(fields)}.\n"
        "Rules: fill a field only if the buyer explicitly said it. Quantity is how many items, never size or capacity. "
        "Map to an option when equivalent, else keep the buyer's value. The utterance may be in any Indian language or "
        "script: convert number words in any language to digits and map values to the English options.\n"
        "intents: any of AFFIRM, DENY, DONT_KNOW, PRICE_QUERY, ASK_FOR_SELLER, ASK_FOR_ALTERNATE_SELLER, PRODUCT_CHANGE, "
        "NO_LONGER_NEEDED (buyer no longer needs the product in discussion), ALREADY_BOUGHT, "
        "TALKING_TO_AI, END_CALL, ASK_FOR_CLARIFICATION, OFF_TOPIC.\n"
        'If the buyer wants a different product, put its English name in "new_product".\n'
        'Format: {"slots": {}, "intents": [], "new_product": null}')
    j = llm.extract_json(system, text)
    if not j:
        return
    n.llm_used = True
    for k, v in (j.get("slots") or {}).items():
        if isinstance(v, dict):
            v = f"{v.get('value')} {v.get('unit') or ''}".strip() if v.get("value") not in (None, "") else None
        if v in (None, "", "null", "None") or (isinstance(v, str) and not v.strip()):
            continue
        key = {"Quantity": "quantity"}.get(k, k)
        if key == "quantity" and product:
            v = match_quantity(normalize_numbers(str(v)), catalog.units(product), bare_ok=True) or str(v)
        if key in ("quantity", "name", "city", "state", *specs.keys()) and key not in n.slots:
            n.slots[key] = str(v).strip()
    n.intents |= {i for i in (j.get("intents") or []) if isinstance(i, str)}
    np = j.get("new_product")
    if np and isinstance(np, str):
        cp = catalog.canonical_product(np) or np.strip().title()
        if not product or catalog.canonical_product(product) != cp:
            n.new_product = cp


# ---------------------------------------------------------------- seller
OUTCOMES = [("deal_won", ["deal ho gayi", "deal done", "order mil gaya", "order mila", "order confirm", "deal won",
                          "sauda", "final ho gaya", "won", "booked"]),
            ("deal_lost", ["deal nahi hui", "lost", "mana kar diya", "nahi liya", "price zyada", "kahin aur se"]),
            ("quoted", ["quotation", "quote", "rate bhej", "rate de", "price bhej", "rate bata", "quoted"]),
            ("not_reachable", ["phone nahi utha", "nahi utha", "not reachable", "switch off", "busy tha",
                               "number band", "not picking", "nahi lag"]),
            ("connected", ["baat ho gayi", "baat hui", "connected", "spoke", "talked", "baat kar li", "baat ki"])]


def parse_seller(text: str, expect: str | None, llm=None) -> NLU:
    t = normalize_numbers(text)
    n = NLU(text=text, intents=_intents(t))
    low = t.lower()
    is_question = "?" in text or n.has("ASK_FOR_SELLER", "ASK_FOR_CLARIFICATION")
    for outcome, kws in OUTCOMES:
        if not is_question and any(k in low for k in kws):
            n.slots["outcome"] = outcome
            break
    if expect == "pref_min_qty":
        m = re.search(r"(\d+(?:\.\d+)?)\s*([a-z]+)?", low)
        if m:
            unit = _unit_key(m.group(2) or "") or "piece"
            n.slots["pref_min_qty"] = f"{m.group(1)} {unit.capitalize()}"
    if expect == "pref_regions":
        st = match_states(t)
        if st:
            n.slots["pref_regions"] = ", ".join(st)
        elif re.search(r"(?<![a-z])(all india|poore india|pan india|sab|everywhere)(?![a-z])", low):
            n.slots["pref_regions"] = "All India"
    needs = expect and ((expect.startswith("lead_outcome") and "outcome" not in n.slots)
                        or (expect.startswith("pref_") and expect not in n.slots))
    if llm is not None and llm.available and needs and not (n.intents & {"DONT_KNOW"}):
        system = (
            "Extract from ONE seller utterance (IndiaMART seller assistant call). Output ONLY JSON.\n"
            f"Question just asked: {expect}.\n"
            "Fields: outcome (one of deal_won, deal_lost, quoted, not_reachable, connected, not_contacted), "
            "pref_min_qty (number + unit), pref_regions (comma separated Indian states).\n"
            "intents: any of AFFIRM, DENY, DONT_KNOW, ASK_FOR_SELLER, END_CALL, TALKING_TO_AI.\n"
            'Format: {"slots": {}, "intents": []}')
        j = llm.extract_json(system, text)
        if j:
            n.llm_used = True
            for k, v in (j.get("slots") or {}).items():
                if v not in (None, "", "null") and k in ("outcome", "pref_min_qty", "pref_regions") and k not in n.slots:
                    n.slots[k] = str(v)
            n.intents |= {i for i in (j.get("intents") or []) if isinstance(i, str)}
    return n
