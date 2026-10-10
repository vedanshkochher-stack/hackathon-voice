# Design: GLID context layer (Problem Statement 02)

One sentence: every IndiaMART activity becomes an event keyed by GLID; a deterministic builder turns
a GLID's events into a ~2 KB `buyer.md` / `seller.md` within tens of milliseconds; every bot session
loads that file, fills VANI's *existing* prompt variables from it, opens with a line built from it,
and asks only what is still missing.

```
 sources (APIs, PNS, search logs, KYC, VANI, WhatsApp bot, app events)
        │  normalise + privacy whitelist (PII dropped here, never stored)
        ▼
 event store (append-only, keyed by GLID+role, monotonic seq)          webhook POST /api/events
        │  queue(glid, role)  ── 15 ms debounce ──►  worker
        ▼
 builder (pure: events → profile)  →  renderer (budgeted Markdown + YAML frontmatter)  →  atomic write
        │                                                     out/context/<glid>/buyer.md | seller.md
        ├── bots: read-through watermark check → vani-vars → personalised opening → no re-asks
        ├── exec call-prep card, sales dashboard, WhatsApp campaign planner (read files only)
        └── scheduled sweep (5 min): lookback expiry + reconciliation
```

## 1. Data sources and how they map

| Source (starter API / system) | Event type | Lands in | Why it is needed |
|---|---|---|---|
| Enquiry / BuyLead API | `enquiry.created/.update/.status` | buyer: Enquiries, open thread | what they asked for and whether it closed |
| BL purchase / Lead API | `lead.received`, `lead.response` | seller: Leads, Responses | what the seller got and did with it |
| PNS call logs (also Call Insights `run_pns_query`) | `pns.call` (one row → two events) | buyer: Sellers contacted; seller: Missed calls | the most common reason the bot is called at all |
| Search logs | `search` | buyer: Categories searched, intent | guess the need for a buyer with no enquiry yet |
| KYC API | `kyc.update` | both: KYC | trust signal for dashboards; never spoken by the bot |
| User / seller profile | `profile.update` | frontmatter `known` | name, city, state, language |
| VANI, WhatsApp bot, Seller Assist | `conversation.update/.ended` | Conversations, open thread, preferences | the cross-channel memory itself |
| App / WhatsApp / email engagement | `engagement` | Engagement, warmth | channel preference and recency |

`ctxlayer/sources/indiamart.py` holds the adapters; each is one `normalize(row)` function. Until the
organisers' API list is wired in, `data/synthetic/events.json` (clearly labelled SYNTHETIC) fills the gap.

**Missing, partial, conflicting data.**
- A source that is down emits `source.status: unavailable`, and the file says `kyc: unavailable` (not "no").
- Field conflicts are resolved by trust, then recency. What the user confirmed in a conversation beats the
  system of record (Lakshmi said "Hyderabad" on a call; her profile says "Secunderabad"). The losing value is
  kept in a "Data notes" line so nothing is silently overwritten.
- State must agree with the confirmed city, or it is treated as unknown (VANI: never assume the state).
- Duplicates are dropped by `event_id`.

**Cold start.** No events means no file, so the bot uses today's generic opening and the VANI prompt is
byte-identical to production. After the first conversation the GLID has a file within ~50 ms.

## 2. Lookback windows (per source)

| Section | Window | Justification |
|---|---|---|
| Enquiries | 90 d | B2B cycle (quote → negotiate → PO) usually closes inside a quarter; shows repeat-buy context |
| Searches | 30 d (intent: 72 h) | search intent decays within days; older searches are noise |
| Sellers contacted | 60 d | covers re-orders and "the seller I spoke to last month" |
| Conversations | 30 d (resume window 14 d) | an unfinished requirement older than 2 weeks is restarted, not resumed |
| Engagement | 30 d | same rolling window IndiaMART engagement scores use |
| Seller leads / responses | 30 d | a lead's value is mostly gone after a month; response rate uses the same base |
| Missed buyer calls | 7 d | older missed calls are not actionable |
| KYC, profile, catalog, preferences | current state | not time-series facts |

Proof in the demo data: Om Packaging's 40-day-old lead is in the store but not in `seller.md`.

## 3. Freshness: mechanism and measurement

Hybrid, three layers:
1. **Event-driven.** Each event re-renders only its GLID's file(s), after a 15 ms coalescing window. A PNS
   call or a live transfer updates both parties' files from one ingest.
2. **Read-through guarantee.** Every bot session start compares the file's `watermark` (highest event seq
   inside it) with the store. If anything is newer, it rebuilds synchronously (~10 ms) before reading.
   Result: **0 stale reads** in 50 adversarial checks.
3. **Scheduled sweep** every 5 min. It ages items out of lookback windows on quiet GLIDs and reconciles
   events a webhook missed.

Measured (`scripts/measure_freshness.py`, 300+ Poisson events at 25/s, laptop, OneDrive disk): ingest →
file **p50 ≈ 30–40 ms, p95 ≈ 45–80 ms**. Per-file build + render + write is about 10–35 ms. The UI shows the
measured delay on every rewrite. Production note: the same contract scales by sharding the worker on GLID
(Kafka partition key = GLID) and storing per-GLID state instead of re-reading events.

## 4. Size and structure

- **Budget:** 2,800 bytes hard cap (~700 tokens). Samples are 1.5–2.8 KB (380–680 tokens).
- **Why that size:**
  - VANI's prompt is already ~20k tokens, so the context adds ≤ 3.5%.
  - Voice time-to-first-token grows with prompt length.
  - One fact per line, newest first, keeps the important facts away from the "lost in the middle" zone.
- **Two layers in one file:**
  - **YAML frontmatter** is the machine contract: `known`, `open_thread` with `captured`/`pending`, `next`,
    `never_ask`, `signals`, `kyc`, `watermark`.
  - **The Markdown body** says the same facts for an LLM or a human. Section order is fixed. Dates are
    absolute, and relative phrases ("kal") are computed at read time, so a file never ages wrongly.
- **Trimming:** when over budget, lists are cut in a fixed priority order (searches first, conversations
  last), never below per-section minimums and never mid-line.
- **Determinism:** no LLM in file generation. That gives millisecond rebuilds, identical structure every time
  (diffable, testable) and zero hallucinated facts in a file other teams will trust.

## 5. Bot integration (VANI, no prompt rewrite)

VANI already branches on `buyer_name`, `buyer_city`, `quantity`, `specifications`, `identity_revealed`,
`initial_message`. `GET /api/context/{glid}/buyer/vani-vars` fills them from `buyer.md`, plus:
- `global_context`, the Markdown body, injected by one include: `bot/prompts/context_block.j2`.
- `ctx_never_ask` and `ctx_pending`, which become Collection Control closures.

With the variables filled, the collection sections for known fields disappear from the prompt itself
(test: `test_vani_prompt_drops_known_collection_sections`).

**Opening line.** Deterministic, built only from file facts, instant (no LLM on the critical path). It uses
these scenarios:
1. Resume a pending requirement, asking only the missing field.
2. Requirement complete: offer the live seller.
3. Connected earlier: ask for feedback.
4. Recent interest: suggest the product without saying "you searched".
5. Known name only.
6. Cold.

**Turns.** A deterministic policy mirrors VANI's Collection Control and decides *what* to ask. Sarvam
`sarvam-105b-conversations` phrases it, and handles NLU when the rules miss. Three guards keep the LLM honest:
- **Re-ask guard:** never ask a known field.
- **On-target guard:** must ask the policy's field, nothing VANI forbids (pincode, "anything else").
- **No-echo guard.**

Average LLM call is ~230 ms.

**Requirement withdrawn ("ab kuch nahi chahiye", "le liya").** A separate intent from declining a transfer
("abhi nahi") and from correcting a value ("10 kg nahi, 6 kg").
1. The old thread is closed in the file (`dropped: no longer needed` / `already bought`), so no channel resumes it.
2. Following VANI's "probe once for any other current or upcoming requirement", the bot suggests at most two
   products from the buyer's own `interests` (frontmatter: product, last date, count, and source: app search,
   website search or seller call), newest first. It cites source and timeline transparently: *"Theek hai, main
   samajh gayi ki ab aapko PVC Pipe ki requirement nahi hai. Maine dekha ki aap kal IndiaMART website par
   Solvent Cement dekh rahe the, aur parson IndiaMART app par Pipe Fittings dekh rahe the. Kya aap inme se
   kisi ke liye requirement post karna chahenge?"* This only ever cites the caller's own activity, from their
   own file. With no recent interests left, it asks about what the buyer actually bought (`purchases` in
   frontmatter), as a repeat order: *"Maine dekha ki aapne 3 hafte pehle Om Packaging se Corrugated Box liya tha.
   Kya aapko dobara Corrugated Box chahiye?"* With nothing in the file, it asks a plain "any other requirement?".
   It never suggests generic "people also buy" products. Campaigns still never quote searches.
3. If the buyer names one, the bot switches to it and asks only that product's quantity and specs. Name, city
   and state stay known.
4. A second "no" ends with a clean thank-you, not "requirement noted".

**Languages (11) and switching.** Hindi, English, Bengali, Tamil, Telugu, Kannada, Malayalam, Marathi,
Gujarati, Punjabi and Odia.
- **Start:** the session starts in the language from the context file (`known.language`).
- **Explicit switch:** a request such as "English please", "Tamil mein baat kijiye" or "తెలుగులో మాట్లాడండి"
  switches language. The bot confirms and repeats its pending question in the new language without using up an
  ask. Negations ("Tamil nahi aati") and "Tamil Nadu" are not requests.
- **Implicit switch:** typing in another script, or `saaras:v4` auto-detecting another spoken language, also
  switches. Hindi, English and Marathi confusions need an explicit request.
- **Repeats and persistence:** switches can happen any number of times. Each one is written to the file
  immediately, so the next call opens in the last language used.
- **Unsupported languages** get the list of supported ones, and the conversation stays in the current language.
- **Replies:** the policy still drafts in Hinglish or English; other languages get a faithful translation of that
  fixed draft (Sarvam LLM, with the Sarvam Translate API as fallback), so translation never changes *what* is
  asked.
- **Speech:**
  - Text-to-speech uses `bulbul:v4-flash` conversational voices (hi, en, bn, gu, mr) and `bulbul:v3` for ta, te,
    kn, ml, pa and od, since v4-flash has no voices for those yet.
  - Speech-to-text is `saaras:v4` with auto-detection.

**Cross-channel resumption** works because every channel writes the same `conversation.update` event on each
captured slot, not only at the end. A call that drops mid-sentence still leaves an up-to-date file. Voice
and WhatsApp are implemented end to end. App and web chat plug in as one more `channel` value: same session
API, same events, a channel-specific opening renderer.

**Chosen LLM.**
- **Conversation:** Sarvam `sarvam-105b-conversations`, the non-reasoning variant with ~0.2–0.6 s turns.
  It handles Hindi, Hinglish and Telugu natively, and VANI already runs on Sarvam.
- **Speech:** `saaras:v4` STT in translit mode (Roman Hinglish) and `bulbul:v4-flash` TTS (female conversational
  voices: `kavya_hi_conversational` for Hindi/Hinglish, `roopa_en_conversational` for English; pace 1.25).
- **File generation:** no LLM.

## 6. Reuse beyond the bot

All consumers import only `ctxlayer/reader.py`. None of them touch the event store, the source APIs or the
bot code:
- `consumers/exec_call_prep.py`: a 30-second card for a sales or buyer-care executive (agenda, risks,
  "already known, don't ask").
- `consumers/dashboard.py`: one row per GLID for a sales dashboard.
- `consumers/wa_campaign.py`: picks WhatsApp audiences from frontmatter only. It respects do-not-disturb,
  suppresses cold users, and never quotes searches back. Writes a CSV.

## 7. Privacy and safety

- **Ingestion whitelist per event type.** Phone, email, address, GSTIN, PAN and buyer names inside seller
  leads are dropped before storage (audit counter in the UI). Names are reduced to first names, and free
  text is regex-scrubbed.
- **Party separation by construction.**
  - `seller.md` only ever receives lead fields: product, quantity, specs, buyer city.
  - A buyer's searches, other sellers, conversations and use-case never reach a seller's file.
  - Om Packaging sells bubble wrap and once served Arjun, yet Arjun's bubble-wrap searches are not in
    Om's file.
- **Runtime leak guard.** Every reply is checked against entities that exist only in *other* GLIDs' files,
  and against contact patterns. Offenders are replaced with a refusal. Seller requests for a buyer's
  number or "who else did they talk to" get a fixed policy answer.
- **The bot never reads KYC aloud.** KYC is for dashboards. Do-not-disturb requests in a file suppress
  outbound bot calls and campaigns.
