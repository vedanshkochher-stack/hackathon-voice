# File schema: `imctx.buyer/v1`, `imctx.seller/v1`

Location: `out/context/<GLID>/buyer.md` and/or `seller.md` (a GLID can be both).
Read with `ctxlayer.reader.read(glid, role)` or any YAML-frontmatter parser.

## Contract rules
- Core keys are always present: `schema glid role generated_at watermark synthetic known kyc next never_ask`.
- Other keys are omitted when empty; new keys are additive within a major version.
- Timestamps are ISO 8601 with offset; the body uses absolute dates only.
- `watermark` = highest event sequence included; compare it with the store to prove freshness.
- Hard cap 2,800 bytes per file.

## buyer.md frontmatter
| Key | Type | Meaning |
|---|---|---|
| `known` | `{name, city, state, language}` | confirmed identity facts; never re-ask |
| `kyc` | `{mobile, email, gst: bool}` or `"unknown"`/`"unavailable"` | verification flags (never spoken) |
| `sources_missing` | list | sources that were down at build time |
| `open_thread` | `{product, ref, status, last_channel, last_at, captured{}, pending[], notes[]}` | the requirement to resume; `status` ∈ open, in_progress, transferred |
| `intent` | `{product, mcat, last_search_at}` | recent interest without an enquiry (suggest, never quote) |
| `signals` | `{warmth, last_active, active_days_30d, preferred_channel}` | engagement |
| `next` | list of `ask:<field>`, `offer:live_seller`, `followup:<product>`, `suggest:<product>` | next best actions in order |
| `never_ask` | list | fields any consumer must treat as known |

Body sections (fixed order): headline (`> …`), Enquiries (90d), Categories searched (30d),
Sellers contacted (60d), KYC, Conversations (30d), Engagement (30d), Data notes, Next best action.

## seller.md frontmatter
| Key | Type | Meaning |
|---|---|---|
| `known` | `{company, contact, city, state, language}` | contact is a first name |
| `kyc` | `{gst, bank: bool}` | |
| `products` | list | catalogue |
| `preferences` | `{pref_min_qty, pref_regions}` | said by the seller in a conversation |
| `callback_after` | date | do not contact before this date |
| `open_items` | list of `{kind: lead_unactioned \| missed_call \| pref_missing, …}` | what to raise, in order |
| `stats_30d` | `{leads, responded, response_rate, won, quoted, lost, not_reachable, avg_response_h}` | |
| `signals`, `next`, `never_ask` | as for buyers | |

Body sections: headline, Leads received (30d), Responses & outcomes (30d), Missed buyer calls (7d),
Products, Lead preferences, KYC, Conversations (30d), Engagement (30d), Next best action.

## Events (input contract, `POST /api/events`)
```json
{"events": [{"event_id": "optional-dedupe-key", "glid": "50112001", "role": "buyer",
  "type": "conversation.update", "occurred_at": "2026-10-09T14:33:00+05:30", "source": "whatsapp_bot",
  "counterparty": "70221001",
  "payload": {"session_id": "W-1", "channel": "whatsapp", "product": "PVC Pipe",
              "captured": {"quantity": "500 Piece"}, "pending": ["Size"], "outcome": "in_progress",
              "summary": "Gave quantity", "lang": "hi"}}]}
```
Allowed payload fields per type: `ctxlayer/privacy.py::ALLOWED_FIELDS` (anything else is dropped).
