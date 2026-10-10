"""Reply translation for the 9 languages that have no hand-written templates.

The dialog policy drafts every reply in Hinglish (hi) or English (everything else); this module turns
the fixed draft into the buyer's language. Sarvam LLM first (one ~0.5 s call, colloquial, keeps product /
brand names), Sarvam Translate API as fallback, the untranslated draft as last resort. Cached, since the
same question templates repeat across sessions.
"""
from __future__ import annotations

import httpx

from ctxlayer.config import LANGS, SARVAM_API_KEY, SARVAM_BASE

_CACHE: dict[tuple[str, str], str] = {}


def _target_desc(lang: str) -> str:
    if lang == "hi":
        return "Hinglish: Hindi written in Roman script, casual and polite (e.g. 'Aapko kitne piece chahiye?')"
    if lang == "en":
        return "simple Indian English"
    return f"natural spoken {LANGS[lang]} written in {LANGS[lang]} script"


def translate(text: str, lang: str, llm=None) -> str:
    if not text or lang not in LANGS:
        return text
    key = (text, lang)
    if key in _CACHE:
        return _CACHE[key]
    out = None
    if llm is not None and llm.available:
        out = llm.chat([
            {"role": "system", "content": (
                f"Translate the message into {_target_desc(lang)}. The message may mix Hindi (Roman script) and English. "
                "Keep product names, brand names, company names, people's names, numbers and units exactly as written "
                "(e.g. PVC Pipe, IndiaMART, 500, kg, ENQ-731204). Keep it short and polite, suitable for a phone call. "
                "Output only the translation.")},
            {"role": "user", "content": text}], max_tokens=400, temperature=0.1)
        if out and (len(out) > 4 * len(text) + 80 or "{" in out):
            out = None
    if not out and SARVAM_API_KEY and lang not in ("hi",):
        try:
            r = httpx.post(f"{SARVAM_BASE}/translate", timeout=20, headers={"api-subscription-key": SARVAM_API_KEY},
                           json={"input": text[:1000], "source_language_code": "auto", "target_language_code": f"{lang}-IN",
                                 "model": "sarvam-translate:v1", "speaker_gender": "Female", "numerals_format": "international"})
            r.raise_for_status()
            out = r.json().get("translated_text")
        except (httpx.HTTPError, ValueError):
            out = None
    out = (out or text).strip().strip('"')
    _CACHE[key] = out
    return out
