import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["IMCTX_WORKDIR"] = tempfile.mkdtemp(prefix="imctx_test_")
os.environ["SARVAM_API_KEY"] = ""  # tests are deterministic: template mode, no network
os.environ["PC_ITEM_DIR"] = tempfile.mkdtemp(prefix="pc_item_test_")  # never the real vector store
os.environ["GOOGLE_API_KEY"] = ""  # no grounding calls

import pytest  # noqa: E402


@pytest.fixture()
def env():
    from bot.engine import Engine
    from ctxlayer import bootstrap
    store, ref = bootstrap(reset=True)
    yield store, ref, Engine(store, ref, llm=None)
    ref.stop()
    import relprod
    relprod.set_store(None)
