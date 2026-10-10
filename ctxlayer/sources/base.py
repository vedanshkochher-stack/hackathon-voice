from __future__ import annotations

from datetime import datetime


class Source:
    """A data source produces *normalised* events: {event_id, glid, role, type, occurred_at,
    source, counterparty?, payload}. Sources are pulled on a schedule (reconciliation) and can also
    push via the /api/events webhook. Missing sources must degrade gracefully: raise
    SourceUnavailable and the builder marks that section 'unavailable' instead of 'none'."""

    name = "base"

    def pull(self, glid: str | None, since: datetime | None) -> list[dict]:
        raise NotImplementedError


class SourceUnavailable(RuntimeError):
    pass
