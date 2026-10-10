from __future__ import annotations

import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

from .config import IST

_AGO = re.compile(r"(\d+(?:\.\d+)?)\s*([dhm])")


def now() -> datetime:
    return datetime.now(IST)


def iso(dt: datetime) -> str:
    return dt.astimezone(IST).isoformat(timespec="milliseconds")


def parse_ts(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=IST)


def resolve_ago(spec: str, ref: datetime) -> datetime:
    """'1d4h' -> ref - 1 day 4 hours. A leading '+' means in the future ('+6d')."""
    sign = -1
    if spec.startswith("+"):
        sign, spec = 1, spec[1:]
    delta = timedelta()
    for n, u in _AGO.findall(spec):
        n = float(n)
        delta += {"d": timedelta(days=n), "h": timedelta(hours=n), "m": timedelta(minutes=n)}[u]
    return ref + sign * delta


def day(dt: datetime) -> str:
    return dt.astimezone(IST).strftime("%d %b")


def ago_text(dt: datetime, ref: datetime | None = None) -> str:
    ref = ref or now()
    secs = (ref - dt).total_seconds()
    if secs < 3600:
        return f"{max(1, int(secs // 60))}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    return f"{int(secs // 86400)}d ago"


def when_spoken(dt: datetime, lang: str, ref: datetime | None = None) -> str:
    """Natural relative day for speech. Computed at read time, never stored in the file."""
    ref = ref or now()
    d = (ref.astimezone(IST).date() - dt.astimezone(IST).date()).days
    if lang == "hi":
        if d <= 0:
            return "aaj" if (ref - dt).total_seconds() > 3 * 3600 else "abhi thodi der pehle"
        if d < 7:
            return {1: "kal", 2: "parson"}.get(d, f"{d} din pehle")
        if d < 14:
            return "pichhle hafte"
        if d < 30:
            return f"{d // 7} hafte pehle"
        return "pichhle mahine" if d < 60 else f"{d // 30} mahine pehle"
    if d <= 0:
        return "earlier today" if (ref - dt).total_seconds() > 3 * 3600 else "a little while ago"
    if d < 7:
        return {1: "yesterday"}.get(d, f"{d} days ago")
    if d < 14:
        return "last week"
    if d < 30:
        return f"{d // 7} weeks ago"
    return "last month" if d < 60 else f"{d // 30} months ago"


def atomic_write(path: Path, text: str) -> None:
    """Readers never see a half-written file. Retries because OneDrive/AV can briefly lock files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.005 * (attempt + 1))
    os.replace(tmp, path)


def approx_tokens(text: str) -> int:
    return round(len(text) / 4)
