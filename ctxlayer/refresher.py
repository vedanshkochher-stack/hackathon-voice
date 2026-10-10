"""Hybrid freshness: event-driven rebuilds + scheduled sweep + read-through guarantee.

  ingest(events) --> event store (dedupe) --> queue(glid, role) --> worker (15 ms debounce)
       --> build (pure) --> render (budgeted) --> atomic write --> freshness metric + listeners

  * Event-driven: every new activity rebuilds only the affected files (both parties when an event
    involves two GLIDs, e.g. a PNS call or a live transfer).
  * Scheduled sweep: every SWEEP_INTERVAL_S rebuilds everything so items age out of their
    lookback windows even when a GLID is quiet, and reconciles events a webhook may have missed.
  * Read-through: `ensure_fresh()` compares the file's watermark (highest event seq inside it) with
    the store; if anything newer exists it rebuilds synchronously before the bot reads. A bot can
    therefore never load a stale file, even if the async worker is behind.
"""
from __future__ import annotations

import queue
import threading
import time
from collections import defaultdict
from datetime import datetime
from typing import Callable

from . import privacy
from .builder import build
from .config import CONTEXT_DIR, DEBOUNCE_MS, SWEEP_INTERVAL_S
from .reader import path_for
from .render import render
from .store import EventStore
from .util import approx_tokens, atomic_write, iso, now, parse_ts


class Refresher:
    def __init__(self, store: EventStore, out_dir=CONTEXT_DIR):
        self.store, self.out_dir = store, out_dir
        self._q: queue.Queue = queue.Queue()
        self._pending: dict[tuple, list[dict]] = defaultdict(list)
        self._plock = threading.Lock()
        self._wlock = threading.Lock()
        self.listeners: list[Callable[[dict], None]] = []
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    # ------------------------------------------------------------ ingest
    def ingest(self, raw_events: list[dict], trigger: str = "event") -> list[dict]:
        stored = []
        for ev in raw_events:
            row = self.store.append(privacy.sanitize(ev))
            if row is None:
                continue  # duplicate event_id from a retry or a second source
            stored.append(row)
            with self._plock:
                self._pending[(row["glid"], row["role"])].append({**row, "trigger": trigger})
        for key in {(r["glid"], r["role"]) for r in stored}:
            self._q.put(key)
        for r in stored:
            self._emit({"kind": "event", "event": {k: r[k] for k in ("seq", "glid", "role", "type", "source",
                                                                      "occurred_at", "ingested_at")} | {"payload": r["payload"]}})
        return stored

    # ------------------------------------------------------------ build + write
    def regenerate(self, glid: str, role: str, trigger: str = "event") -> dict:
        with self._wlock:
            t0 = time.perf_counter()
            events = self.store.events_for(glid, role)
            ref = now()
            profile = build(glid, role, events, ref)
            text = render(profile, ref)
            path = path_for(glid, role, self.out_dir)
            atomic_write(path, text)
            written = now()
            build_ms = (time.perf_counter() - t0) * 1000
            nbytes = len(text.encode("utf-8"))
            self.store.record_file(glid, role, profile["watermark"], iso(written), nbytes)
            with self._plock:
                done = self._pending.pop((glid, role), [])
        rows, lags = [], []
        for e in done:
            a2f = (written - parse_ts(e["occurred_at"])).total_seconds() * 1000
            i2f = (written - parse_ts(e["ingested_at"])).total_seconds() * 1000
            lags.append(i2f)
            rows.append((e["event_id"], glid, role, e["type"], e["trigger"], e["occurred_at"], e["ingested_at"],
                         iso(written), round(a2f, 2), round(i2f, 2)))
        if rows:
            self.store.record_freshness(rows)
        info = {"kind": "file", "glid": glid, "role": role, "trigger": trigger if not done else done[-1]["trigger"],
                "bytes": nbytes, "tokens": approx_tokens(text), "build_ms": round(build_ms, 2),
                "events": len(done), "max_lag_ms": round(max(lags), 2) if lags else None,
                "written_at": iso(written), "watermark": profile["watermark"], "path": str(path)}
        self._emit(info)
        return info

    def ensure_fresh(self, glid: str, role: str) -> dict | None:
        """Read-through check used by every bot session start. O(1) indexed lookups."""
        wm = self.store.file_watermark(glid, role)
        if wm is None or self.store.max_seq(glid, role) > wm or not path_for(glid, role, self.out_dir).exists():
            return self.regenerate(glid, role, trigger="read-through")
        return None

    def rebuild_all(self, trigger: str = "sweep") -> int:
        keys = self.store.keys()
        for glid, role in keys:
            self.regenerate(glid, role, trigger)
        return len(keys)

    # ------------------------------------------------------------ threads
    def start(self, sweep: bool = True) -> "Refresher":
        t = threading.Thread(target=self._worker, name="ctx-worker", daemon=True)
        t.start()
        self._threads.append(t)
        if sweep:
            s = threading.Thread(target=self._sweeper, name="ctx-sweeper", daemon=True)
            s.start()
            self._threads.append(s)
        return self

    def stop(self):
        self._stop.set()
        self._q.put(None)

    def _worker(self):
        while not self._stop.is_set():
            key = self._q.get()
            if key is None:
                break
            keys = {key}
            deadline = time.perf_counter() + DEBOUNCE_MS / 1000
            while (left := deadline - time.perf_counter()) > 0:  # coalesce a burst into one rebuild
                try:
                    k = self._q.get(timeout=left)
                    if k is None:
                        return
                    keys.add(k)
                except queue.Empty:
                    break
            for glid, role in keys:
                with self._plock:
                    has = bool(self._pending.get((glid, role)))
                if has:
                    try:
                        self.regenerate(glid, role, "event")
                    except Exception as exc:  # never kill the worker
                        self._emit({"kind": "error", "glid": glid, "role": role, "error": repr(exc)})

    def _sweeper(self):
        while not self._stop.wait(SWEEP_INTERVAL_S):
            self.rebuild_all("sweep")

    def _emit(self, info: dict):
        for fn in list(self.listeners):
            try:
                fn(info)
            except Exception:
                pass

    def wait_idle(self, timeout: float = 5.0) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            with self._plock:
                if not any(self._pending.values()) and self._q.empty():
                    return True
            time.sleep(0.002)
        return False


def freshness_stats(store: EventStore, trigger: str | None = None) -> dict:
    rows = store.freshness_rows(trigger, limit=5000)
    rows = [r for r in rows if r["trigger"] not in ("seed",)] if trigger is None else rows
    if not rows:
        return {"n": 0}
    lag = sorted(r["ingest_to_file_ms"] for r in rows)
    act = sorted(r["activity_to_file_ms"] for r in rows)

    def pct(xs, q):
        return round(xs[min(len(xs) - 1, int(q * (len(xs) - 1) + 0.5))], 1)
    return {"n": len(rows), "p50_ms": pct(lag, .5), "p95_ms": pct(lag, .95), "p99_ms": pct(lag, .99),
            "max_ms": round(lag[-1], 1), "activity_p50_ms": pct(act, .5), "activity_p95_ms": pct(act, .95)}
