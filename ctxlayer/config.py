"""Central configuration: paths, lookback windows, size budgets, ask limits, model names.

Every number here is a design decision; the reasoning lives in docs/DESIGN.md.
"""
from __future__ import annotations

import os
from datetime import timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUT_DIR = ROOT / "out"                     # reports land here
WORK_DIR = Path(os.environ.get("IMCTX_WORKDIR", OUT_DIR))  # scripts use their own so they never touch the live demo
CONTEXT_DIR = WORK_DIR / "context"         # <work>/context/<glid>/buyer.md | seller.md
STATE_DIR = WORK_DIR / "state"             # sqlite event store (git-ignored)
DB_PATH = STATE_DIR / "events.db"

IST = timezone(timedelta(hours=5, minutes=30), "IST")
SCHEMA_VERSION = {"buyer": "imctx.buyer/v1", "seller": "imctx.seller/v1"}

# Lookback window per data source, in days (justified in docs/DESIGN.md#lookback).
LOOKBACK_DAYS = {
    # buyer.md
    "enquiries": 90,          # B2B buying cycle: quote -> negotiate -> PO usually closes inside a quarter
    "searches": 30,           # search intent decays fast; older searches are noise
    "sellers_contacted": 60,  # covers re-orders and "the seller I spoke to last month"
    "conversations": 30,      # resumable threads + recent tone; older talk is summarised in enquiries
    "engagement": 30,         # rolling activity window used by every IndiaMART engagement score
    # seller.md
    "leads": 30,              # a lead's commercial value is mostly gone after ~30 days
    "responses": 30,          # same window as leads so response-rate is computed over the same base
    "missed_calls": 7,        # a missed buyer call older than a week is not actionable
}
RESUME_WINDOW_DAYS = 14       # an unfinished requirement younger than this is resumed, not restarted
SEARCH_INTENT_HOURS = 72      # recent searches with no enquiry -> suggest, never quote back

# Size budget (justified in docs/DESIGN.md#size). ~4 chars/token for this mostly-English Markdown.
MAX_BYTES = {"buyer": 2800, "seller": 2800}
CAPS = {  # max items rendered per section before the byte budget kicks in
    "enquiries": 3, "searches": 5, "sellers_contacted": 3, "conversations": 3,
    "leads": 4, "catalog": 6, "missed_calls": 3,
}
# Section trimming order when a file is over budget: first entry is cut first, never below MIN_CAPS.
TRIM_ORDER = ["searches", "missed_calls", "sellers_contacted", "catalog", "enquiries", "leads", "conversations"]
MIN_CAPS = {"enquiries": 1, "searches": 2, "sellers_contacted": 1, "conversations": 2, "leads": 2, "catalog": 3,
            "missed_calls": 1}

# Ask limits mirror VANI "Collection Control".
ASK_LIMITS = {"product": 4, "quantity": 3, "spec": 2, "name": 3, "city": 3, "state": 3, "transfer": 2,
              "seller_item": 2}

# Refresh mechanism (hybrid): event-driven worker + scheduled sweep + read-through watermark check.
DEBOUNCE_MS = 15              # coalesce bursts (e.g. 3 slots captured in one turn -> 1 rebuild)
SWEEP_INTERVAL_S = 300        # ages items out of lookback windows, reconciles missed events


def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


load_env()
SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY", "")
SARVAM_BASE = "https://api.sarvam.ai"
SARVAM_CHAT_MODEL = os.environ.get("SARVAM_CHAT_MODEL", "sarvam-105b-conversations")
SARVAM_TTS_MODEL = os.environ.get("SARVAM_TTS_MODEL", "bulbul:v4-flash")
SARVAM_TTS_FALLBACK_MODEL = "bulbul:v3"   # bulbul:v4-flash has no voices yet for ta, te, kn, ml, pa, od

# The 11 supported languages (Sarvam codes: <code>-IN).
LANGS = {"hi": "Hindi", "en": "English", "bn": "Bengali", "ta": "Tamil", "te": "Telugu", "kn": "Kannada",
         "ml": "Malayalam", "mr": "Marathi", "gu": "Gujarati", "pa": "Punjabi", "od": "Odia"}
# language -> (TTS model, female voice matching the Vani persona)
SARVAM_TTS_ROUTE = {
    "hi": (SARVAM_TTS_MODEL, os.environ.get("SARVAM_TTS_SPEAKER_HI", "kavya_hi_conversational")),
    "en": (SARVAM_TTS_MODEL, os.environ.get("SARVAM_TTS_SPEAKER_EN", "roopa_en_conversational")),
    "bn": (SARVAM_TTS_MODEL, "roopa_bn_conversational"),
    "gu": (SARVAM_TTS_MODEL, "pooja_gu_conversational"),
    "mr": (SARVAM_TTS_MODEL, "ishita_mr_conversational"),
    **{k: (SARVAM_TTS_FALLBACK_MODEL, "priya") for k in ("ta", "te", "kn", "ml", "pa", "od")},
}
SARVAM_TTS_PACE = float(os.environ.get("SARVAM_TTS_PACE", "1.25"))  # bulbul pace: 1.0 = default, 1.25 ~ 20% faster
SARVAM_STT_MODEL = os.environ.get("SARVAM_STT_MODEL", "saaras:v4")
