"""Sarvam speech for the voice channel, all 11 supported languages.

TTS: bulbul:v4-flash conversational voices where they exist (hi, en, bn, gu, mr), bulbul:v3 for
ta, te, kn, ml, pa, od. STT: saaras:v4 with language auto-detection; Hindi sessions use translit mode
(Roman Hinglish), all others native script. The detected language lets the bot follow a buyer who
simply starts speaking another language.
"""
from __future__ import annotations

import re

import httpx

from ctxlayer.config import LANGS, SARVAM_API_KEY, SARVAM_BASE, SARVAM_STT_MODEL, SARVAM_TTS_PACE, SARVAM_TTS_ROUTE

LANG_CODE = {k: f"{k}-IN" for k in LANGS}
_EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")


def tts(text: str, lang: str = "hi", pace: float | None = None) -> str | None:
    """Returns base64 WAV or None. `pace` speeds speech up (>1) or slows it down (<1)."""
    if not SARVAM_API_KEY or not text:
        return None
    text = _EMOJI.sub("", text).strip()
    model, speaker = SARVAM_TTS_ROUTE.get(lang, SARVAM_TTS_ROUTE["hi"])
    try:
        r = httpx.post(f"{SARVAM_BASE}/text-to-speech", timeout=30,
                       headers={"api-subscription-key": SARVAM_API_KEY},
                       json={"text": text[:1500], "target_language_code": LANG_CODE.get(lang, "hi-IN"),
                             "model": model, "speaker": speaker,
                             "pace": max(0.5, min(2.0, pace or SARVAM_TTS_PACE))})
        r.raise_for_status()
        return r.json()["audios"][0]
    except (httpx.HTTPError, KeyError, IndexError):
        return None


def stt(audio: bytes, filename: str = "audio.wav", lang: str = "hi") -> tuple[str | None, str | None]:
    """Returns (transcript, detected language code like 'ta'), or (None, None)."""
    if not SARVAM_API_KEY:
        return None, None
    try:
        r = httpx.post(f"{SARVAM_BASE}/speech-to-text", timeout=30,
                       headers={"api-subscription-key": SARVAM_API_KEY},
                       files={"file": (filename, audio, "audio/wav")},
                       data={"model": SARVAM_STT_MODEL, "language_code": "unknown",
                             "mode": "translit" if lang == "hi" else "transcribe"})
        r.raise_for_status()
        j = r.json()
        detected = (j.get("language_code") or "")[:2] or None
        return j.get("transcript"), (detected if detected in LANGS else None)
    except (httpx.HTTPError, KeyError):
        return None, None
