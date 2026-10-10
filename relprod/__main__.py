"""Build (or load) the pc_item vector store and try a match.

    python -m relprod                         build once (~70 min for 1.89M names), resumable; then load in seconds
    python -m relprod "Water Storage Tank"    ... and print the top 3 related items for that lead
"""
from __future__ import annotations

import logging
import sys
import time

from ctxlayer.config import PC_ITEM_CSV

from .store import for_buyer, load_or_build, set_store


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    t0 = time.perf_counter()
    st = load_or_build(PC_ITEM_CSV)
    print(f"{len(st):,} names in memory ({time.perf_counter() - t0:.1f}s) from {PC_ITEM_CSV}", flush=True)
    set_store(st)
    for lead in argv:   # same lookup as the API: lead + complements (Sarvam / Google when configured)
        t = time.perf_counter()
        res = for_buyer({"open_thread": {"product": lead}})
        print(f"\n{lead}  ({(time.perf_counter() - t) * 1000:.0f} ms)  complements: {res['grounding']['llm']}")
        for r in res["items"]:
            print(f"  {r['score']:.3f}  {r['product']:<32} <- {r['matched_by']}")


if __name__ == "__main__":
    main()
