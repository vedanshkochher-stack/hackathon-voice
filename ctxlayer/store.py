"""Append-only event store keyed by GLID.

Every source (APIs, bots, webhooks) writes normalised events here. The file builder is a pure
function of (events for a GLID+role, now). `seq` is a monotonic ingest counter: a file's
watermark is the highest seq it includes, so "is this file stale?" is one indexed lookup.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from typing import Iterable

from .config import DB_PATH
from .util import iso, now

SCHEMA = """
CREATE TABLE IF NOT EXISTS events(
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT UNIQUE NOT NULL,
  glid TEXT NOT NULL,
  role TEXT NOT NULL,              -- which file the fact belongs to: buyer | seller
  type TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  ingested_at TEXT NOT NULL,
  source TEXT NOT NULL,
  counterparty TEXT,
  synthetic INTEGER NOT NULL DEFAULT 0,
  payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_key ON events(glid, role, seq);
CREATE TABLE IF NOT EXISTS files(
  glid TEXT NOT NULL, role TEXT NOT NULL,
  watermark INTEGER NOT NULL, generated_at TEXT NOT NULL, bytes INTEGER NOT NULL,
  PRIMARY KEY(glid, role)
);
CREATE TABLE IF NOT EXISTS freshness(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT, glid TEXT, role TEXT, type TEXT, trigger TEXT,
  occurred_at TEXT, ingested_at TEXT, written_at TEXT,
  activity_to_file_ms REAL, ingest_to_file_ms REAL
);
"""


class EventStore:
    def __init__(self, path=DB_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript(SCHEMA)
        self._lock = threading.Lock()

    # ---------- writes ----------
    def append(self, ev: dict) -> dict | None:
        """Insert one normalised event. Returns the stored row (with seq) or None if duplicate."""
        ev = dict(ev)
        ev.setdefault("event_id", uuid.uuid4().hex)
        ev.setdefault("occurred_at", iso(now()))
        ev["ingested_at"] = iso(now())
        with self._lock:
            cur = self._db.execute(
                "INSERT OR IGNORE INTO events(event_id,glid,role,type,occurred_at,ingested_at,source,"
                "counterparty,synthetic,payload) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (ev["event_id"], str(ev["glid"]), ev["role"], ev["type"], ev["occurred_at"],
                 ev["ingested_at"], ev.get("source", "unknown"), ev.get("counterparty"),
                 1 if ev.get("synthetic") else 0, json.dumps(ev.get("payload", {}), ensure_ascii=False)),
            )
            if cur.rowcount == 0:
                return None
            ev["seq"] = cur.lastrowid
        return ev

    def record_file(self, glid: str, role: str, watermark: int, generated_at: str, nbytes: int) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO files(glid,role,watermark,generated_at,bytes) VALUES(?,?,?,?,?) "
                "ON CONFLICT(glid,role) DO UPDATE SET watermark=excluded.watermark, "
                "generated_at=excluded.generated_at, bytes=excluded.bytes",
                (glid, role, watermark, generated_at, nbytes))

    def record_freshness(self, rows: Iterable[tuple]) -> None:
        with self._lock:
            self._db.executemany(
                "INSERT INTO freshness(event_id,glid,role,type,trigger,occurred_at,ingested_at,written_at,"
                "activity_to_file_ms,ingest_to_file_ms) VALUES(?,?,?,?,?,?,?,?,?,?)", list(rows))

    def reset(self) -> None:
        with self._lock:
            self._db.executescript("DELETE FROM events; DELETE FROM files; DELETE FROM freshness;"
                                   "DELETE FROM sqlite_sequence;")

    # ---------- reads ----------
    def events_for(self, glid: str, role: str) -> list[dict]:
        rows = self._db.execute("SELECT * FROM events WHERE glid=? AND role=? ORDER BY occurred_at, seq",
                                (glid, role)).fetchall()
        return [self._row(r) for r in rows]

    def max_seq(self, glid: str, role: str) -> int:
        r = self._db.execute("SELECT MAX(seq) FROM events WHERE glid=? AND role=?", (glid, role)).fetchone()
        return r[0] or 0

    def file_watermark(self, glid: str, role: str) -> int | None:
        r = self._db.execute("SELECT watermark FROM files WHERE glid=? AND role=?", (glid, role)).fetchone()
        return r[0] if r else None

    def keys(self) -> list[tuple[str, str]]:
        return [(r[0], r[1]) for r in self._db.execute("SELECT DISTINCT glid, role FROM events")]

    def recent_events(self, limit: int = 50) -> list[dict]:
        rows = self._db.execute("SELECT * FROM events ORDER BY seq DESC LIMIT ?", (limit,)).fetchall()
        return [self._row(r) for r in rows]

    def freshness_rows(self, trigger: str | None = None, limit: int = 1000) -> list[dict]:
        q, args = "SELECT * FROM freshness", []
        if trigger:
            q += " WHERE trigger=?"
            args.append(trigger)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        return [dict(r) for r in self._db.execute(q, args).fetchall()]

    @staticmethod
    def _row(r: sqlite3.Row) -> dict:
        d = dict(r)
        d["payload"] = json.loads(d["payload"])
        d["synthetic"] = bool(d["synthetic"])
        return d
