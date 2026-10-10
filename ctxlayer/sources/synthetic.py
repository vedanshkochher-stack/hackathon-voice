from __future__ import annotations

import json
from datetime import datetime

from ..config import DATA_DIR
from ..util import iso, now, resolve_ago
from .base import Source


def _resolve_rel(v, ref: datetime):
    if isinstance(v, str) and v.startswith("@rel:"):
        return resolve_ago(v[5:], ref).date().isoformat()
    if isinstance(v, dict):
        return {k: _resolve_rel(x, ref) for k, x in v.items()}
    if isinstance(v, list):
        return [_resolve_rel(x, ref) for x in v]
    return v


class SyntheticSource(Source):
    """Clearly-labelled synthetic events (data/synthetic/events.json). Relative timestamps are
    anchored to the moment of loading so the demo story is always current."""

    name = "synthetic"

    def __init__(self, path=DATA_DIR / "synthetic" / "events.json"):
        self.path = path

    def pull(self, glid: str | None = None, since: datetime | None = None) -> list[dict]:
        ref = now()
        raw = json.loads(self.path.read_text(encoding="utf-8"))["events"]
        out = []
        for e in raw:
            if glid and e["glid"] != glid:
                continue
            out.append({
                "event_id": f"syn-{e['id']}",
                "glid": e["glid"], "role": e["role"], "type": e["type"],
                "occurred_at": iso(resolve_ago(e["ago"], ref)),
                "source": e.get("source", "synthetic"),
                "counterparty": e.get("counterparty"),
                "synthetic": True,
                "payload": _resolve_rel(e.get("payload", {}), ref),
            })
        return out


def personas() -> list[dict]:
    return json.loads((DATA_DIR / "synthetic" / "personas.json").read_text(encoding="utf-8"))["personas"]
