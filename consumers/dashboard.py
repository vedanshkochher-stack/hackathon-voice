"""Non-bot use #3: one-row-per-GLID sales dashboard table, read from the same files."""
from __future__ import annotations

from ctxlayer.reader import read_all
from ctxlayer.util import approx_tokens


def rows() -> list[dict]:
    out = []
    for c in read_all():
        m = c.meta
        k, sig = m.get("known") or {}, m.get("signals") or {}
        if m["role"] == "buyer":
            th = m.get("open_thread")
            who = k.get("name", "-")
            focus = (f"{th['product']} ({th['status']}" + (f", needs {', '.join(th['pending'])})" if th.get("pending") else ")")) if th \
                else (f"interest: {m['intent']['product']}" if m.get("intent") else "-")
        else:
            who = k.get("company", "-")
            st = m.get("stats_30d") or {}
            focus = f"{st.get('leads', 0)} leads, {round((st.get('response_rate') or 0) * 100)}% responded"
        out.append({"glid": str(m["glid"]), "role": m["role"], "who": who, "city": k.get("city", "-"),
                    "warmth": sig.get("warmth", "-"), "focus": focus, "next": (m.get("next") or ["-"])[0],
                    "bytes": len(c.raw.encode()), "tokens": approx_tokens(c.raw), "generated_at": m.get("generated_at")})
    return out
