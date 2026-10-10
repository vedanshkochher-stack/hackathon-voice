"""Thin Sarvam client (OpenAI-compatible chat endpoint). Model: sarvam-105b-conversations
(non-reasoning variant: ~0.6 s per short turn, native Hindi/Hinglish/Telugu, same vendor as VANI)."""
from __future__ import annotations

import json
import re
import time

import httpx

from ctxlayer.config import SARVAM_API_KEY, SARVAM_BASE, SARVAM_CHAT_MODEL


class SarvamLLM:
    def __init__(self, key: str = SARVAM_API_KEY, model: str = SARVAM_CHAT_MODEL):
        self.key, self.model = key, model
        self._http = httpx.Client(timeout=25)
        self.calls, self.total_ms, self.errors = 0, 0.0, 0

    @property
    def available(self) -> bool:
        return bool(self.key)

    def chat(self, messages: list[dict], max_tokens: int = 220, temperature: float = 0.3) -> str | None:
        if not self.available:
            return None
        t0 = time.perf_counter()
        try:
            r = self._http.post(f"{SARVAM_BASE}/v1/chat/completions",
                                headers={"api-subscription-key": self.key},
                                json={"model": self.model, "messages": messages,
                                      "max_tokens": max_tokens, "temperature": temperature})
            r.raise_for_status()
            out = r.json()["choices"][0]["message"].get("content")
            return out.strip() if out else None
        except (httpx.HTTPError, KeyError, ValueError):
            self.errors += 1
            return None
        finally:
            self.calls += 1
            self.total_ms += (time.perf_counter() - t0) * 1000

    def extract_json(self, system: str, user: str) -> dict | None:
        out = self.chat([{"role": "system", "content": system}, {"role": "user", "content": user}],
                        max_tokens=250, temperature=0)
        if not out:
            return None
        m = re.search(r"\{.*\}", out, re.S)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None

    def stats(self) -> dict:
        return {"model": self.model, "calls": self.calls, "errors": self.errors,
                "avg_ms": round(self.total_ms / self.calls) if self.calls else None}
