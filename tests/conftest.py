import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["IMCTX_WORKDIR"] = tempfile.mkdtemp(prefix="imctx_test_")
os.environ["SARVAM_API_KEY"] = ""  # tests are deterministic: template mode, no network

import pytest  # noqa: E402


@pytest.fixture()
def env():
    from bot.engine import Engine
    from ctxlayer import bootstrap
    store, ref = bootstrap(reset=True)
    yield store, ref, Engine(store, ref, llm=None)
    ref.stop()
