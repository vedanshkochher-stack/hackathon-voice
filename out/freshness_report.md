# Freshness evidence

Generated 2026-10-09T14:47:50.142+05:30 on a laptop (Windows, SQLite WAL, files on OneDrive-synced disk).

| Metric | Value |
|---|---|
| Events fired (Poisson, 25.0/s, mixed types; PNS calls touch two files) | 341 |
| **Ingest → file rewritten, p50** | **41.2 ms** |
| **Ingest → file rewritten, p95** | **77.1 ms** |
| p99 / max | 99.8 / 116.0 ms |
| Activity timestamp → file, p50 / p95 | 42.0 / 78.1 ms |
| Debounce window (included above) | 15 ms |
| Full rebuild cost per file (build + render + atomic write) | 34.99 ms |
| Read-through checks (bot reads right after an event) | 50, **stale reads: 0** |

Mechanism: hybrid. Event-driven rebuild of only the affected GLID files (worker with a 15 ms
coalescing window), a scheduled sweep every 5 minutes that ages items out of lookback windows, and a
read-through watermark check on every bot session start, so a bot can never load a file older than the
newest stored event for that GLID.
