"""Name encoder (ONNX via fastembed, no torch): NAME_MODEL, 384-d, unit-normalised (cosine = inner product)."""
from __future__ import annotations

import threading
import warnings
from functools import lru_cache

import numpy as np

from ctxlayer.config import NAME_MODEL

_lock = threading.Lock()  # first load downloads the model; never twice in parallel
warnings.filterwarnings("ignore", message=".*now uses mean pooling.*")  # mean pooling is right for MiniLM


@lru_cache(maxsize=1)
def _model():
    from fastembed import TextEmbedding
    with _lock:
        return TextEmbedding(NAME_MODEL)


def embed_names(texts: list[str], batch_size: int = 256) -> np.ndarray:
    if not texts:
        return np.zeros((0, 384), np.float32)
    v = np.array(list(_model().embed(texts, batch_size=batch_size)), dtype=np.float32)
    return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-9)
