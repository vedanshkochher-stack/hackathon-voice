"""Build every context file from the sources and copy them to samples/ for the submission.

    python scripts/build_all.py
"""
from __future__ import annotations

import shutil
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("IMCTX_WORKDIR", str(Path(__file__).resolve().parent.parent / "out" / "runs" / "build"))
sys.stdout.reconfigure(encoding="utf-8")

from ctxlayer import bootstrap, reader  # noqa: E402
from ctxlayer.config import ROOT  # noqa: E402
from ctxlayer.util import approx_tokens  # noqa: E402


def main():
    bootstrap(reset=True, start_threads=False)
    dst = ROOT / "samples"
    dst.mkdir(exist_ok=True)
    print(f"{'file':40} {'bytes':>6} {'~tokens':>8}")
    for c in reader.read_all():
        name = f"{c.meta['glid']}_{c.meta['role']}.md"
        shutil.copy(c.path, dst / name)
        print(f"{str(c.path.relative_to(ROOT)):40} {len(c.raw.encode()):>6} {approx_tokens(c.raw):>8}")
    print(f"copied to {dst}")


if __name__ == "__main__":
    main()
