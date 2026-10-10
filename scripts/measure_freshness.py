"""Freshness evidence: delay between a new activity and the updated context file.

Fires N realistic events (Poisson arrivals, mixed types, both single- and two-party) into the live
event-driven pipeline, then measures for each event:
  ingest -> file rewritten (pipeline delay)   and   activity -> file (includes source delivery)
It also verifies the read-through guarantee: a bot reading immediately after an event never sees
a stale file. Writes out/freshness_report.md and .json.

    python scripts/measure_freshness.py [--n 300] [--rate 20]
"""
from __future__ import annotations

import argparse
import os
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("IMCTX_WORKDIR", str(Path(__file__).resolve().parent.parent / "out" / "runs" / "freshness"))
sys.stdout.reconfigure(encoding="utf-8")

from ctxlayer import bootstrap, freshness_stats, reader  # noqa: E402
from ctxlayer.config import DEBOUNCE_MS, OUT_DIR  # noqa: E402
from ctxlayer.util import iso, now  # noqa: E402

BUYERS = ["50112001", "50112002", "50112003"]
SELLERS = ["70221001", "70221002", "70221003", "70221004"]


def random_event(i: int) -> list[dict]:
    k = random.random()
    b, s = random.choice(BUYERS), random.choice(SELLERS)
    ts = iso(now())
    if k < 0.35:
        return [{"glid": b, "role": "buyer", "type": "search", "occurred_at": ts, "source": "bench",
                 "payload": {"query": f"bench query {i}", "mcat": random.choice(["PVC Pipes", "Bubble Wrap", "Industrial RO Plants"])}}]
    if k < 0.55:
        return [{"glid": s, "role": "seller", "type": "lead.received", "occurred_at": ts, "source": "bench",
                 "payload": {"lead_id": f"L-B{i}", "product": "PVC Pipe", "quantity": 100 + i, "unit": "Piece",
                             "specs": {}, "buyer_city": "Indore", "buyer_state": "Madhya Pradesh", "via": "BL purchase"}}]
    if k < 0.75:  # one PNS call = two files
        return [{"glid": b, "role": "buyer", "type": "pns.call", "occurred_at": ts, "source": "bench", "counterparty": s,
                 "payload": {"seller_glid": s, "seller_name": "Bench Seller", "seller_city": "Pune", "product": "PVC Pipe",
                             "answered": False, "duration_s": 0}},
                {"glid": s, "role": "seller", "type": "pns.call", "occurred_at": ts, "source": "bench", "counterparty": b,
                 "payload": {"buyer_city": "Indore", "buyer_state": "Madhya Pradesh", "product": "PVC Pipe", "answered": False}}]
    return [{"glid": b, "role": "buyer", "type": "conversation.update", "occurred_at": ts, "source": "bench",
             "payload": {"session_id": f"BENCH-{i % 7}", "channel": random.choice(["voice", "whatsapp"]), "bot": "VANI",
                         "product": "PVC Pipe", "captured": {"Size": random.choice(["2 inch", "4 inch"])},
                         "pending": [], "notes": [], "outcome": "in_progress", "summary": "bench", "lang": "hi"}}]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--rate", type=float, default=20.0, help="events per second (Poisson)")
    a = ap.parse_args()
    store, ref = bootstrap(reset=True)
    random.seed(7)

    # 1) event-driven path
    t0 = time.perf_counter()
    sent = 0
    for i in range(a.n):
        sent += len(ref.ingest(random_event(i), trigger="bench"))
        time.sleep(random.expovariate(a.rate))
    ref.wait_idle(10)
    wall = time.perf_counter() - t0
    st = freshness_stats(store, "bench")

    # 2) read-through guarantee: read immediately after ingest, before the async worker runs
    stale = 0
    checks = 50
    for i in range(checks):
        ev = random_event(10_000 + i)[0]
        row = ref.ingest([ev], trigger="readthrough-check")[0]
        info = ref.ensure_fresh(row["glid"], row["role"])
        c = reader.read(row["glid"], row["role"])
        if c.meta["watermark"] < row["seq"]:
            stale += 1
        _ = info
    ref.wait_idle(5)

    # 3) build cost per file
    t1 = time.perf_counter()
    n_files = ref.rebuild_all("bench-rebuild")
    rebuild_ms = (time.perf_counter() - t1) * 1000 / max(1, n_files)

    report = {"events_fired": sent, "duration_s": round(wall, 1), "rate_per_s": a.rate, "debounce_ms": DEBOUNCE_MS,
              "ingest_to_file_ms": {k: st[k] for k in ("p50_ms", "p95_ms", "p99_ms", "max_ms")},
              "activity_to_file_ms": {"p50": st["activity_p50_ms"], "p95": st["activity_p95_ms"]},
              "measured_events": st["n"], "read_through_checks": checks, "stale_reads": stale,
              "avg_full_rebuild_ms_per_file": round(rebuild_ms, 2), "generated_at": iso(now())}
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "freshness_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    md = f"""# Freshness evidence

Generated {report['generated_at']} on a laptop (Windows, SQLite WAL, files on OneDrive-synced disk).

| Metric | Value |
|---|---|
| Events fired (Poisson, {a.rate}/s, mixed types; PNS calls touch two files) | {sent} |
| **Ingest → file rewritten, p50** | **{st['p50_ms']} ms** |
| **Ingest → file rewritten, p95** | **{st['p95_ms']} ms** |
| p99 / max | {st['p99_ms']} / {st['max_ms']} ms |
| Activity timestamp → file, p50 / p95 | {st['activity_p50_ms']} / {st['activity_p95_ms']} ms |
| Debounce window (included above) | {DEBOUNCE_MS} ms |
| Full rebuild cost per file (build + render + atomic write) | {report['avg_full_rebuild_ms_per_file']} ms |
| Read-through checks (bot reads right after an event) | {checks}, **stale reads: {stale}** |

Mechanism: hybrid. Event-driven rebuild of only the affected GLID files (worker with a {DEBOUNCE_MS} ms
coalescing window), a scheduled sweep every 5 minutes that ages items out of lookback windows, and a
read-through watermark check on every bot session start, so a bot can never load a file older than the
newest stored event for that GLID.
"""
    (OUT_DIR / "freshness_report.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
