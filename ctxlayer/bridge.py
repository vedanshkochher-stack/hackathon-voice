"""Bridge: context file -> the VANI prompt's *existing* variables.

Production integration is two steps, no prompt rewrite:
  1. At call/chat setup the platform resolves caller -> GLID and calls
     GET /api/context/{glid}/buyer/vani-vars?product=<seller product>&channel=voice
  2. It passes the returned dict as agent variables, and the prompt gains one include
     (bot/prompts/context_block.j2).
Because VANI already branches on buyer_name / buyer_city / quantity / specifications /
identity_revealed, filling them from buyer.md removes those questions from the prompt itself.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from jinja2 import Environment, FileSystemLoader

from . import catalog
from .config import DATA_DIR, ROOT
from .opening import buyer_opening, seller_opening
from .reader import Context

PROMPTS = ROOT / "bot" / "prompts"
_env = Environment(loader=FileSystemLoader(str(PROMPTS)), trim_blocks=True, lstrip_blocks=True)
LANG_NAME = {k: v.lower() for k, v in __import__("ctxlayer.config", fromlist=["LANGS"]).LANGS.items()}


def live_seller(product: str | None, exclude: str | None = None) -> dict | None:
    pool = json.loads((DATA_DIR / "synthetic" / "live_sellers.json").read_text(encoding="utf-8"))["pool"]
    for s in pool.get(catalog.canonical_product(product) or "", []):
        if s["glid"] != exclude:
            return s
    return None


def _body_for_prompt(ctx: Context) -> str:
    """The Markdown body only (frontmatter is for machines); drop the H1 GLID line."""
    lines = [ln for ln in ctx.body.splitlines() if not ln.startswith("# ")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def vani_variables(ctx: Context | None, base: dict | None = None, channel: str = "voice",
                   ref: datetime | None = None) -> dict:
    base = dict(base or {})
    m = ctx.meta if ctx else {}
    known = m.get("known") or {}
    th = m.get("open_thread")
    call_product = base.get("product_name") or None
    op = buyer_opening(ctx, channel, call_product=call_product, ref=ref)
    product = op.get("product") or call_product or ""
    use_thread = bool(th and catalog.canonical_product(th["product"]) == catalog.canonical_product(product))
    cap = (th or {}).get("captured", {}) if use_thread else {}
    qty = cap.get("quantity", "")
    specs = {k: v for k, v in cap.items() if k != "quantity"}
    pending = (th or {}).get("pending", []) if use_thread else []
    ls = live_seller(product, exclude=base.get("seller_glid"))
    v = {
        "bot_name": "Vani", "channel": channel,
        "product_name": product,
        "seller_name": base.get("seller_name", ""),
        "initial_message": op["text"],
        "buyer_name": known.get("name", ""), "updated_buyer_name": "",
        "buyer_city": known.get("city", ""), "updated_city_name": known.get("city", ""),
        "updated_state_name": known.get("state", ""),
        "triangulation_response_value": "0", "triangulation_response_city": "",
        "language_name": LANG_NAME.get(op["lang"], "hindi"),
        "quantity_unit_options": catalog.units(product) if product else [],
        "specification_options": catalog.specs(product) if product else {},
        "quantity": qty.split(" ")[0] if qty else "", "quantity_unit": " ".join(qty.split(" ")[1:]) if qty else "",
        "specifications": specs,
        "identity_revealed": "1" if ctx else "0",
        "bl_converted": "1" if use_thread else "0",
        "current_phase": ("REQUIREMENT COLLECTION" if use_thread and pending else
                          "FINALISATION" if use_thread else "REQUIREMENT CONFIRMATION"),
        "additional_details": "; ".join((th or {}).get("notes", []) if use_thread else []),
        "is_enrich": "0", "pcd_pitch": "", "identity_challenge_count": "0", "seller_ask_count": "0",
        "off_topic_counter": "0",
        "ast_seller_pns": ls["glid"] if ls else "", "ast_seller_company": ls["company"] if ls else "",
        "ast_seller_city": ls["city"] if ls else "", "ast_flow_live": "true" if ls else "false",
        # new, context-layer variables
        "global_context": _body_for_prompt(ctx) if ctx and not m.get("empty") and known else "",
        "ctx_generated_at": m.get("generated_at", ""),
        "ctx_never_ask": m.get("never_ask", []), "ctx_pending": pending,
        "ctx_opening_scenario": op["scenario"], "ctx_opening_facts": op["facts"],
    }
    if ctx and not known and not th and not m.get("intent"):
        v["global_context"] = ""  # cold start: no block at all, the prompt is byte-identical to today's
    return v


def seller_variables(ctx: Context | None, channel: str = "voice", ref: datetime | None = None) -> dict:
    m = ctx.meta if ctx else {}
    known = m.get("known") or {}
    op = seller_opening(ctx, channel, ref=ref)
    return {"bot_name": "Vani", "channel": channel, "initial_message": op["text"],
            "language_name": LANG_NAME.get(op["lang"], "hindi"),
            "global_context": _body_for_prompt(ctx) if ctx and known else "",
            "ctx_generated_at": m.get("generated_at", ""), "ctx_never_ask": m.get("never_ask", []),
            "callback_after": m.get("callback_after"), "contact": known.get("contact", "")}


def render_prompt(role: str, variables: dict) -> str:
    tpl = "buyer_vani.j2" if role == "buyer" else "seller_assist.j2"
    return _env.get_template(tpl).render(**variables).strip()
