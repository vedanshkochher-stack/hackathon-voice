"""Demo + integration server.

    uvicorn server.app:app --port 8000      then open http://localhost:8000

Integration endpoints (what a real platform would call):
  POST /api/events                          webhook: any source pushes normalised events
  GET  /api/context/{glid}/{role}           the file (read-through fresh)
  GET  /api/context/{glid}/buyer/vani-vars  VANI prompt variables + personalised initial_message
  GET  /api/related/{glid}?k=3               top related pc_items for a buyer (lead + liked/viewed from buyer.md)
Demo endpoints: sessions for voice/WhatsApp, Sarvam TTS/STT, SSE live updates, consumers, lift.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import sys
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.stdout.reconfigure(encoding="utf-8")

import relprod  # noqa: E402
from bot import speech  # noqa: E402
from bot.engine import Engine  # noqa: E402
from bot.evaluate import lift_report  # noqa: E402
from bot.llm import SarvamLLM  # noqa: E402
from consumers import dashboard, exec_call_prep, wa_campaign  # noqa: E402
from ctxlayer import bootstrap, freshness_stats, personas, privacy, reader  # noqa: E402
from ctxlayer.bridge import render_prompt, vani_variables  # noqa: E402
from ctxlayer.sources.synthetic import SyntheticSource  # noqa: E402
from ctxlayer.util import approx_tokens, iso, now  # noqa: E402

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="GLID Context Layer")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

store, refresher = bootstrap(reset=os.environ.get("KEEP_STATE") != "1")  # re-anchor synthetic timeline to now
llm = SarvamLLM()
engine = Engine(store, refresher, llm)
_subs: set[asyncio.Queue] = set()
_loop: asyncio.AbstractEventLoop | None = None


def _broadcast(info: dict):
    if _loop is None:
        return
    for q in list(_subs):
        _loop.call_soon_threadsafe(q.put_nowait, info)


refresher.listeners.append(_broadcast)


@app.on_event("startup")
async def _startup():
    global _loop
    _loop = asyncio.get_running_loop()
    relprod.start_loading()  # CSV -> name vectors -> FAISS, in a background thread


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


# ------------------------------------------------------------------ context
@app.get("/api/users")
def users():
    out = []
    for p in personas():
        for role in p["roles"]:
            c = reader.read(p["glid"], role)
            out.append({**p, "role": role, "headline": c.headline if c else "No history yet (cold start)",
                        "warmth": ((c.meta.get("signals") or {}).get("warmth") if c else "cold"),
                        "has_file": bool(c)})
    return {"users": out, "llm": llm.available, "model": llm.model}


@app.get("/api/context/{glid}/{role}")
def context(glid: str, role: str):
    refreshed = refresher.ensure_fresh(glid, role) if store.max_seq(glid, role) else None
    c = reader.read(glid, role)
    if not c:
        return {"exists": False, "glid": glid, "role": role,
                "markdown": f"(no {role}.md yet: GLID {glid} has no history; the bot uses the generic cold-start opening)"}
    return {"exists": True, "glid": glid, "role": role, "markdown": c.raw, "meta": c.meta,
            "bytes": len(c.raw.encode()), "tokens": approx_tokens(c.raw), "refreshed": refreshed}


@app.get("/api/context/{glid}/{role}/vani-vars")
def vani_vars(glid: str, role: str, product: str = "", channel: str = "voice", seller_glid: str = ""):
    if role != "buyer":
        raise HTTPException(400, "VANI is the buyer-side bot")
    if store.max_seq(glid, role):
        refresher.ensure_fresh(glid, role)
    return vani_variables(reader.read(glid, role), {"product_name": product, "seller_glid": seller_glid}, channel)


class EventsIn(BaseModel):
    events: list[dict]


@app.post("/api/events")
def post_events(body: EventsIn):
    stored = refresher.ingest(body.events, trigger="webhook")
    return {"stored": len(stored), "duplicates": len(body.events) - len(stored)}


PRESETS = {
    "arjun_search": ("Arjun searches '70 micron bubble wrap'", lambda: [
        {"glid": "50112003", "role": "buyer", "type": "search", "source": "search_logs",
         "payload": {"query": "bubble wrap 70 micron", "mcat": "Bubble Wrap", "platform": "app"}}]),
    "om_new_lead": ("Om Packaging receives a new Surat lead", lambda: [
        {"glid": "70221002", "role": "seller", "type": "lead.received", "source": "lead_api", "counterparty": "50118899",
         "payload": {"lead_id": f"L-{random.randint(740000, 749999)}", "product": "Corrugated Box", "quantity": 4000,
                     "unit": "Piece", "specs": {"Ply": "5 ply"}, "buyer_city": "Surat", "buyer_state": "Gujarat",
                     "via": "BL purchase", "buyer_name": "Should Be Dropped", "buyer_mobile": "+91 98989 89898"}}]),
    "lakshmi_gst": ("Lakshmi completes GST KYC", lambda: [
        {"glid": "50112002", "role": "buyer", "type": "kyc.update", "source": "kyc_api",
         "payload": {"mobile_verified": True, "email_verified": False, "gst_verified": True, "gstin": "36ABCDE1234F1Z9"}}]),
    "ramesh_calls_again": ("Ramesh calls Shree Polymers again, missed (one PNS row -> two files)", lambda: [
        {"glid": "50112001", "role": "buyer", "type": "pns.call", "source": "pns_api", "counterparty": "70221001",
         "payload": {"seller_glid": "70221001", "seller_name": "Shree Polymers", "seller_city": "Pune",
                     "product": "PVC Pipe", "answered": False, "duration_s": 0}},
        {"glid": "70221001", "role": "seller", "type": "pns.call", "source": "pns_api", "counterparty": "50112001",
         "payload": {"buyer_city": "Indore", "buyer_state": "Madhya Pradesh", "product": "PVC Pipe", "answered": False}}]),
    "kiran_responds": ("AquaPure calls the Hyderabad RO lead back", lambda: [
        {"glid": "70221003", "role": "seller", "type": "lead.response", "source": "lead_api",
         "payload": {"lead_id": "L-731990", "action": "called", "outcome": "quoted"}}]),
    "new_buyer_search": ("Cold-start buyer searches 'pvc pipe 4 inch'", lambda: [
        {"glid": "50119999", "role": "buyer", "type": "search", "source": "search_logs",
         "payload": {"query": "pvc pipe 4 inch", "mcat": "PVC Pipes", "platform": "web"}}]),
}


@app.get("/api/simulate")
def list_presets():
    return [{"id": k, "label": v[0]} for k, v in PRESETS.items()]


@app.post("/api/simulate/{preset}")
def simulate(preset: str):
    if preset not in PRESETS:
        raise HTTPException(404)
    evs = PRESETS[preset][1]()
    for e in evs:
        e["occurred_at"] = iso(now())
    stored = refresher.ingest(evs, trigger="live")
    return {"stored": len(stored), "glids": sorted({(e["glid"], e["role"]) for e in stored})}


@app.get("/api/stream")
async def stream():
    q: asyncio.Queue = asyncio.Queue()
    _subs.add(q)

    async def gen():
        try:
            yield "retry: 1500\n\n"
            while True:
                try:
                    info = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(info, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            _subs.discard(q)
    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/freshness")
def freshness():
    rows = [r for r in store.freshness_rows(limit=300) if r["trigger"] != "seed"]
    return {"stats": freshness_stats(store), "recent": rows[:40]}


@app.get("/api/events/recent")
def recent_events(limit: int = 40):
    return store.recent_events(limit)


# ------------------------------------------------------------------ sessions
class StartIn(BaseModel):
    glid: str
    role: str = "buyer"
    channel: str = "voice"
    warm: bool = True
    reply_mode: str = "llm"
    call_product: str | None = None
    call_seller: str | None = None
    outbound: bool = False
    persist: bool | None = None


@app.get("/api/related/{glid}")
def related(glid: str, k: int = 3):
    """Top-k related pc_items for a buyer, matched on the current lead and the products they liked / viewed,
    all read from the buyer's context file (read-through fresh)."""
    if not 1 <= k <= 20:
        raise HTTPException(400, "k must be 1-20")
    if store.max_seq(glid, "buyer"):
        refresher.ensure_fresh(glid, "buyer")
    c = reader.read(glid, "buyer")
    if not c:
        raise HTTPException(404, f"no buyer context for GLID {glid}")
    return {"glid": glid, **relprod.for_buyer(c.meta, k=k), "store": relprod.status()}


@app.post("/api/session/start")
def session_start(b: StartIn):
    return engine.start(b.glid, b.role, b.channel, warm=b.warm, persist=b.persist, reply_mode=b.reply_mode,
                        call_product=b.call_product, call_seller=b.call_seller, outbound=b.outbound)


class MsgIn(BaseModel):
    text: str
    lang: str | None = None   # language detected by STT for this utterance


@app.post("/api/session/{sid}/message")
def session_message(sid: str, b: MsgIn):
    if sid not in engine.sessions:
        raise HTTPException(404)
    return engine.message(sid, b.text, b.lang)


class EndIn(BaseModel):
    reason: str = "hangup"


@app.post("/api/session/{sid}/end")
def session_end(sid: str, b: EndIn):
    if sid not in engine.sessions:
        raise HTTPException(404)
    return engine.end(sid, b.reason)


@app.get("/api/session/{sid}/prompt")
def session_prompt(sid: str):
    s = engine.sessions.get(sid)
    if not s:
        raise HTTPException(404)
    cold_vars = vani_variables(None, {"product_name": s.product or ""}, s.channel) if s.role == "buyer" else None
    return {"prompt": engine.prompt(sid), "vars": {k: v for k, v in s.vars.items() if k != "global_context"},
            "cold_prompt": render_prompt("buyer", cold_vars) if cold_vars else None,
            "transcript": s.transcript, "state": engine._state(s)}


# ------------------------------------------------------------------ speech
class TTSIn(BaseModel):
    text: str
    lang: str = "hi"
    pace: float | None = None


@app.post("/api/tts")
async def tts(b: TTSIn):
    audio = await asyncio.to_thread(speech.tts, b.text, b.lang, b.pace)
    return {"audio": audio}


@app.post("/api/stt")
async def stt(file: UploadFile = File(...), lang: str = Form("hi")):
    data = await file.read()
    text, detected = await asyncio.to_thread(speech.stt, data, file.filename or "audio.wav", lang)
    return {"text": text, "language": detected}


# ------------------------------------------------------------------ consumers / eval / privacy
@app.get("/api/consumers/dashboard")
def consumer_dashboard():
    return dashboard.rows()


@app.get("/api/consumers/exec-prep/{glid}/{role}")
def consumer_prep(glid: str, role: str):
    c = exec_call_prep.prep_card(glid, role)
    return c or JSONResponse({"error": "no context file"}, 404)


@app.get("/api/consumers/campaign")
def consumer_campaign():
    p = wa_campaign.plan()
    p["csv"] = wa_campaign.write_csv(p)
    return p


@app.get("/api/lift")
def lift():
    return lift_report(engine)


@app.get("/api/privacy")
def privacy_info():
    files = reader.read_all()
    pii_hits = []
    for c in files:
        for name, pat in privacy._PATTERNS:
            for m in pat.finditer(c.raw):
                pii_hits.append({"file": str(c.path), "type": name, "match": m.group(0)})
    return {"dropped_at_ingestion": dict(privacy.audit), "allowed_fields": {k: sorted(v) for k, v in privacy.ALLOWED_FIELDS.items()},
            "pii_found_in_files": pii_hits, "files_scanned": len(files)}


@app.post("/api/reset")
def reset():
    engine.sessions.clear()
    store.reset()
    privacy.audit.clear()
    for p in reader.read_all():
        p.path.unlink(missing_ok=True)
    refresher.ingest(SyntheticSource().pull(), trigger="seed")
    n = refresher.rebuild_all("seed")
    return {"rebuilt": n}
