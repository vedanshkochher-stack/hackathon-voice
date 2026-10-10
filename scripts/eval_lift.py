"""Lift from the context layer: cold start vs context file, same simulated users.

    python scripts/eval_lift.py        -> out/lift_report.md
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("IMCTX_WORKDIR", str(Path(__file__).resolve().parent.parent / "out" / "runs" / "lift"))
sys.stdout.reconfigure(encoding="utf-8")

from bot.engine import Engine  # noqa: E402
from bot.evaluate import SECONDS_PER_TURN, lift_report  # noqa: E402
from ctxlayer import bootstrap  # noqa: E402
from ctxlayer.config import OUT_DIR  # noqa: E402


def main():
    store, ref = bootstrap(reset=True)
    r = lift_report(Engine(store, ref))
    s = r["summary"]
    pct = lambda a, b: f"-{round((1 - b / a) * 100)}%" if a else "-"  # noqa: E731
    lines = ["# Lift: cold start vs context file", "",
             "Same 6 synthetic users (3 buyers, 3 sellers), same scripted answers. Deterministic policy, template replies.", "",
             "| Metric | Cold start | With context | Change |", "|---|---|---|---|",
             f"| Re-asks of facts already known | {s['cold_reasks']} | **{s['warm_reasks']}** | {pct(s['cold_reasks'], s['warm_reasks'])} |",
             f"| Questions asked | {s['cold_questions']} | **{s['warm_questions']}** | {pct(s['cold_questions'], s['warm_questions'])} |",
             f"| User turns to goal | {s['cold_turns']} | **{s['warm_turns']}** | {pct(s['cold_turns'], s['warm_turns'])} |",
             f"| Est. voice time (~{SECONDS_PER_TURN} s/turn) | {s['cold_seconds']} s | **{s['warm_seconds']} s** | {pct(s['cold_seconds'], s['warm_seconds'])} |",
             f"| Goal reached (buyer transfer / seller lead follow-up) | {s['cold_goals']}/6 | **{s['warm_goals']}/6** | |",
             f"| Personalised openings | 0/6 | **{s['personalised_openings']}/6** | |", "",
             "## Openings", "", "| GLID | Cold start | From context file | Facts used |", "|---|---|---|---|"]
    for row in r["rows"]:
        lines.append(f"| {row['glid']} ({row['role']}) | {row['cold']['opening']} | {row['warm']['opening']} | {row['warm']['facts_in_opening']} |")
    md = "\n".join(lines) + "\n"
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "lift_report.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
