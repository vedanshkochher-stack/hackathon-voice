"""GLID context layer: events from any source -> compact, always-fresh buyer.md / seller.md."""
from __future__ import annotations

from .refresher import Refresher, freshness_stats
from .sources.synthetic import SyntheticSource, personas
from .store import EventStore

__all__ = ["EventStore", "Refresher", "SyntheticSource", "personas", "freshness_stats", "bootstrap"]


def bootstrap(reset: bool = False, start_threads: bool = True) -> tuple[EventStore, Refresher]:
    """Open the store, seed synthetic history if empty, build every file."""
    store = EventStore()
    if reset:
        store.reset()
        from .config import CONTEXT_DIR
        for f in CONTEXT_DIR.glob("*/*.*"):
            f.unlink(missing_ok=True)
    ref = Refresher(store)
    if not store.keys():
        ref.ingest(SyntheticSource().pull(), trigger="seed")
        ref.rebuild_all("seed")  # seed rows are tagged 'seed' and excluded from the live freshness metric
    if start_threads:
        ref.start()
    return store, ref
