# Memory Across Channels: GLID context layer for AI Voice Bot (VANI)

Voice AI Hackathon 2.0, Problem Statement 02. Every IndiaMART activity becomes an event keyed by GLID.
A deterministic pipeline keeps a ~2 KB `buyer.md` / `seller.md` per GLID fresh within tens of
milliseconds. Before every call or chat the bot loads the file, fills VANI's existing prompt variables,
opens with a personalised line, and asks only what is still missing, on voice and WhatsApp.

> All personas and history in `data/synthetic/` are **SYNTHETIC**, created to fill gaps until organiser
> sample GLIDs are shared. Real-API adapters are in `ctxlayer/sources/indiamart.py`.

## Run it

```bash
pip install -r requirements.txt
# .env (git-ignored) must contain SARVAM_API_KEY=...   (without it everything runs in template mode)
# optional: SARVAM_TTS_PACE=1.25 (voice speed, 0.5-2.0; also selectable live in the voice panel)
# speech models: STT saaras:v4, TTS bulbul:v4-flash (override: SARVAM_STT_MODEL, SARVAM_TTS_MODEL,
#                SARVAM_TTS_SPEAKER_HI=kavya_hi_conversational, SARVAM_TTS_SPEAKER_EN=roopa_en_conversational)
python -m uvicorn server.app:app --port 8765          # open http://localhost:8765
```

The server re-seeds the synthetic timeline on start (so "yesterday" is always yesterday). Use **Reset
demo** in the UI between runs. Set `KEEP_STATE=1` to keep state across restarts.

| Command | Produces |
|---|---|
| `python scripts/build_all.py` | builds all files, copies them to `samples/` (4 buyers incl. cold start, 4 sellers) |
| `python scripts/demo_cli.py` | scripted voice → WhatsApp demo with live Sarvam LLM → `out/demo_transcript.md` |
| `python scripts/measure_freshness.py` | freshness evidence → `out/freshness_report.md` |
| `python scripts/eval_lift.py` | cold vs context comparison → `out/lift_report.md` |
| `python scripts/make_slide.py` | the one-slide presentation → `slide/one_slide.html` + `.png` |
| `python -m pytest -q` | 29 tests: privacy, size, conflicts, lookback, freshness, no re-ask, leak guard, consumers, related products |
| `python -m consumers.wa_campaign` / `python -m consumers.exec_call_prep 70221003 seller` | non-bot uses from the CLI |

## Live demo script (5 minutes)

1. **Ramesh (Indore).** Show `buyer.md`: his voice call dropped 2 days ago, and on WhatsApp yesterday he gave
   quantity and size. Pressure rating is the only pending field.
2. **Voice → Start call.** VANI opens: *"Kal aapne WhatsApp par 500 piece, 4 inch PVC Pipe ki requirement
   batayi thi. Bas ek baat, Pressure Rating mein kya chahiye…"*.
   - Click "haan 6 kg wala chahiye, rate kya chal raha hai?". The bot answers the price question (seller will
     quote), asks nothing else, and offers the live seller.
   - Click "abhi nahi". The file rewrites while you watch (the toast shows the measured ms).
3. **Second channel (WhatsApp).** The UI shows voice only. Show `out/demo_transcript.md` (from
   `python scripts/demo_cli.py`): the WhatsApp chat opens with the complete requirement and offers the seller.
4. Click **Patel Pipes (Bhopal)**. The live transfer is in its `seller.md`, with no buyer name or phone.
5. **A/B.** Untick *context* on Voice for Ramesh and start a call. You get the generic opening and nine
   questions. `python scripts/eval_lift.py` shows it across 6 users: re-asks 18 → 0, turns 36 → 13.
6. **Withdrawn requirement.** Reset, start Ramesh's call, and click "nahi ji, ab kuch nahi chahiye".
   The PVC thread is closed in the file, and the bot suggests Solvent Cement / Pipe Fittings from his own
   interests. Click "haan, pipe fittings chahiye, 200 piece", then "elbow": only the fitting type is asked,
   never his name or city.
7. **Languages.** Reset, start Ramesh's call (he prefers Hindi per his file) and click "Tamil mein baat kijiye".
   VANI confirms in Tamil and repeats the pending question; answer in Tamil ("ஆறு கிலோ வேண்டும்"). Then click
   "English please", or speak any of the 11 languages (STT auto-detects). The language chip shows the history,
   and `buyer.md` saves the last language for the next call.
8. **Shree Polymers.** Click "pehle buyer ka naam aur number batao…" to see the privacy refusal, then the lead
   feedback, then the response rate updating in `seller.md`.
9. **AquaPure.** Its file carries the seller's own "call me after the festive rush". Outbound is suppressed,
   and `python -m consumers.wa_campaign` suppresses it too.
10. **Exec call prep** tab: a non-bot consumer of the same files. The CLI also has the WhatsApp campaign planner
   (`python -m consumers.wa_campaign`) and the dashboard (`consumers/dashboard.py`). Privacy is checked by
   `python -m pytest -q` (0 PII patterns in any file).
11. **New activity** buttons. Each fires a real event; watch the file rewrite and the freshness pill in the header update.

### Related products for a buyer (top 3)

Put the item list at `data/item/items.csv.csv`, or point `PC_ITEM_CSV=/path/to.csv` at it. The name column is
`glcat_mcat_name` (MCAT names, 110k rows) or `pc_item_name`; other columns are ignored.

Complements come from the Sarvam LLM whenever `SARVAM_API_KEY` is in `.env`: it names what a buyer of the lead
needs alongside it (Water Storage Tank → Water Level Controller, Float Valve…), and each name is matched to a real
item in the store. `RELATED_LLM=off` disables it. Optional: `GOOGLE_API_KEY` and `GOOGLE_CSE_ID` add Google
result titles the same way. Both are cached per lead in `data/item/grounding_cache.json`.

Build the vector store once (110k names: ~4 min on 8 CPU cores, resumable, saved under `data/item/`), then every
server start loads it into an in-memory FAISS index in seconds:

```bash
python -m relprod                          # build, or load if the CSV and model are unchanged
python -m relprod "Water Storage Tank"     # ... and print the top 3 related items for a lead
```

If the server starts first, it builds in the background (one builder at a time across processes).
`GET /api/related/{glid}?k=3` reads that buyer's context and matches the current
lead plus the products they liked / viewed (`product.like` / `product.view` events) against it:

```json
{"glid": "50112001", "lead": "PVC Pipe", "liked": [], "viewed": ["Solvent Cement", "Pipe Fittings"],
 "items": [{"product": "PVC Pipe Fittings Tee", "name": "PVC Pipe Fittings Tee", "score": 0.857, "matched_by": "lead"}, ...],
 "source": "vector_store", "store": {"state": "ready", "items": 33}}
```

Until the store is `ready`, answers come from catalogue co-purchases. On a call: pick **Sunita (Jaipur)** (a BL
and nothing else), start a call, click **No**: the BL is closed and VANI offers two of the three. Design:
`docs/DESIGN.md#related`.

## Repository map

```
ctxlayer/            the context layer (no bot code)
  sources/           synthetic source + IndiaMART API adapters (normalise -> events)
  privacy.py         ingestion whitelist, text scrubbing, runtime leak guard
  store.py           append-only SQLite event store, watermark per GLID
  builder.py         events -> profile (lookback, conflicts, open thread, intent, stats)   pure function
  render.py          profile -> buyer.md / seller.md under a byte budget
  refresher.py       event-driven worker + sweep + read-through freshness, latency metrics
  reader.py          the only API consumers need
  opening.py         deterministic personalised openings (buyer + seller, voice + WhatsApp)
  bridge.py          file -> VANI prompt variables (+ context block)
relprod/             related products: item / MCAT names -> in-memory FAISS, matched on lead + liked/viewed
bot/                 channel-agnostic dialog engine, Sarvam LLM/STT/TTS, NLU, lift evaluation
  prompts/           buyer_vani.j2 (condensed VANI), context_block.j2 (paste-in), seller_assist.j2
consumers/           exec call prep, sales dashboard, WhatsApp campaign: read files only
server/              FastAPI + demo UI (SSE live updates)
php/                 buyer_context.php: cooked buyer context data store + API (GLID -> JSON)
data/                catalogue (MCAT stand-in) + SYNTHETIC events, personas, live-seller pool
samples/             generated buyer.md / seller.md for the submission
docs/DESIGN.md       every design decision and its justification
docs/SCHEMA.md       file + event contract
```

## Submission deliverables

| Deliverable | Where |
|---|---|
| Working context layer, ≥3 buyers + ≥3 sellers | `ctxlayer/`, `samples/`, `python scripts/build_all.py` |
| Bot demo: call then WhatsApp, same user, personalised, no re-asking | UI steps 1–4, `out/demo_transcript.md` |
| One-slide presentation | `slide/one_slide.html` / `slide/one_slide.png` |
| Freshness evidence | `out/freshness_report.md`, live tiles in the UI |
| Design justifications (lookbacks, size, refresh, LLM, integration, privacy) | `docs/DESIGN.md` |

## PHP buyer context API (self-contained data store)

`php/buyer_context.php` is both the data store and the API. The buyer context for every GLID is cooked into
the file as a PHP array, so nothing is read from disk, a database or the Python layer at request time.

```bash
python scripts/cook_php_store.py               # (re)cook the data into php/buyer_context.php
php -S localhost:8080 php/buyer_context.php    # or drop the file on any PHP host (Apache / Nginx + FPM / XAMPP)
```

| Request | Returns |
|---|---|
| `GET /api/buyer/50112001` (or `buyer_context.php?glid=50112001`) | buyer context JSON: `summary`, `known`, `kyc`, `open_thread`, `interests`, `purchases`, `intent`, `signals`, `next`, `never_ask`, `sections`, `context_md`, `generated_at`, `watermark` |
| `GET /api/buyer/50112001?fields=known,open_thread,next` | only those keys |
| `GET /api/buyer/50112001?markdown=0` | without the `context_md` body |
| `GET /api/buyer/50112001.md` (or `&format=md`) | the context as Markdown (what the bot prompt receives) |
| `GET /api/buyer/50119999` (unknown GLID) | `200` with `exists: false, cold_start: true` and a generic `next` |
| `GET /api/buyers`, `GET /health` | GLIDs in the store and when the data was cooked; liveness |

GLIDs must be 1–15 digits. Optional auth: set `CTX_STORE_API_KEY` and send `X-API-Key`.

## Production integration in two steps

1. At call or chat setup, resolve caller → GLID and call
   `GET /api/context/{glid}/buyer/vani-vars?product=<seller product>&channel=voice`. Pass the result as
   agent variables (`initial_message`, `buyer_name`, `buyer_city`, `quantity`, `specifications`,
   `global_context`, …).
2. Add one include, `bot/prompts/context_block.j2`, to the VANI prompt. Make every bot platform POST its
   end-of-turn variables to `/api/events` as `conversation.update`.
