# Bot demo: voice call → WhatsApp, same buyer, no re-asking

All data SYNTHETIC. Reply mode: `llm` (sarvam-105b-conversations).

## Before: what buyer.md says (open requirement)

```yaml
known: {'name': 'Ramesh', 'city': 'Indore', 'state': 'Madhya Pradesh', 'language': 'hi'}
open_thread: {'product': 'PVC Pipe', 'ref': 'ENQ-731204', 'status': 'in_progress', 'last_channel': 'whatsapp', 'last_at': '2026-10-08T12:47+05:30', 'captured': {'quantity': '500 Piece', 'Size': '4 inch'}, 'pending': ['Pressure Rating'], 'notes': ['Price asked']}
never_ask: ['name', 'city', 'state', 'product', 'quantity', 'Size']
```

## Step 1: voice call (buyer called Shree Polymers, seller busy → VANI)

*voice · context ON · opening scenario `resume_pending` (personalised, facts: name, product, last_channel, when, quantity, Size, pending:Pressure Rating) · file loaded in 10.07 ms*

- **Bot:** Namaste Ramesh ji, IndiaMART se Vani bol rahi hoon. Kal aapne WhatsApp par 500 piece, 4 inch PVC Pipe ki requirement batayi thi. Bas ek baat, Pressure Rating mein kya chahiye, 4 kg ya 6 kg, ya kuch aur?
- **User:** haan 6 kg wala chahiye. Rate kya chal raha hai? _(captured: Pressure Rating)_
- **Bot:** Ji, rate ke liye main aapki call best seller se connect karwaungi, wo aapko sabse achha rate denge. Ramesh ji, abhi ek seller line par available hai, price aur baaki details aap unse directly discuss kar sakte hain. Kya main aapki call connect kar doon?
- **User:** abhi nahi, thodi der baad
- **Bot:** Theek hai. Aapki requirement note ho gayi hai. Suitable seller details aapko WhatsApp par share kar diye jayenge. IndiaMART ko call karne ke liye dhanyavaad.

> outcome `transfer_refused` · questions asked 2 · re-asks of known facts 0 · user turns 2

File rebuilt from the call's events: p50 35.3 ms, max 35.3 ms after each event.

```yaml
open_thread: {'product': 'PVC Pipe', 'ref': 'ENQ-731204', 'status': 'in_progress', 'last_channel': 'voice', 'last_at': '2026-10-09T14:47+05:30', 'captured': {'quantity': '500 Piece', 'Size': '4 inch', 'Pressure Rating': '6 kg/cm2'}, 'notes': ['Price asked']}
```

`buyer.md` section **Conversations**:

    - 09 Oct Voice (VANI) · PVC Pipe · Gave Pressure Rating 6 kg/cm2; asked price (seller will quote); declined live transfer; seller details to go on WhatsApp.
    - 08 Oct WhatsApp (IM WhatsApp) · PVC Pipe · Gave quantity and size; asked price (told the seller will quote); went quiet before pressure rating. Pending: Pressure Rating.
    - 07 Oct Voice (VANI) · PVC Pipe · Seller missed the call; buyer confirmed the PVC Pipe requirement; call dropped before quantity. Pending: quantity, Size, Pressure Rating.

## Step 2: later, same buyer on WhatsApp

*whatsapp · context ON · opening scenario `resume_complete` (personalised, facts: name, product, last_channel, when, quantity, Size, Pressure Rating) · file loaded in 15.89 ms*

- **Bot:** Namaste Ramesh ji, IndiaMART se Vani 🙏 Abhi thodi der pehle aapne call par 500 piece, 4 inch, 6 kg PVC Pipe ki requirement batayi thi. Aapki poori requirement note hai. Kya main abhi ek available seller se aapki baat karwa doon?
- **User:** haan, connect karwa do
- **Bot:** Ji, Patel Pipes & Fittings aapko 2 minute mein call karenge. Dhanyavaad! 🙏

> outcome `transferred` · questions asked 1 · re-asks of known facts 0 · user turns 1

## Step 3: the live transfer, as seen in the receiving seller's file (Patel Pipes, 70221004)

`seller.md` section **Leads received**:

    - 09 Oct · PVC Pipe · 500 Piece · 4 inch · Indore, MP · Live transfer · live call → connected (L-731204)
    - 04 Oct · Water Storage Tank · 10 Piece · 1000 L · Bhopal, MP · Enquiry · called → quoted · outside prefs (L-728950)
    - 23 Sep · PVC Pipe · 300 Piece · 2 inch · Jabalpur, MP · BL purchase · called → won (L-724900)

No buyer name, phone or conversation content crossed over: only lead fields (product, qty, specs, city).

## Contrast: the same buyer with NO context (cold start, not persisted)

*voice · context OFF · opening scenario `cold_start` (generic) · file loaded in 44.04 ms*

- **Bot:** Namaste, IndiaMART se Vani bol rahi hoon. Bataiye, aaj aapko kis product ki requirement hai?
- **User:** PVC pipe
- **Bot:** Achha, toh aap PVC Pipe ke liye dekh rahe hain, jo plumbing aur paani ki supply line ke kaam aata hai, sahi hai na?
- **User:** haan
- **Bot:** Ji, aapko kitne Piece chahiye?
- **User:** 500 piece _(captured: quantity)_
- **Bot:** Theek hai. Size mein kya chahiye, 2 inch ya 4 inch, ya kuch aur?
- **User:** 4 inch _(captured: Size)_
- **Bot:** Ji. Pressure Rating mein kya chahiye, 4 kg ya 6 kg, ya kuch aur?
- **User:** 6 kg _(captured: Pressure Rating)_
- **Bot:** Theek hai. Best seller se connect karne se pehle, aapka naam jaan sakti hoon?
- **User:** Ramesh _(captured: name)_
- **Bot:** Theek hai. Aap kis city se call kar rahe hain?
- **User:** Indore _(captured: city)_
- **Bot:** Ji. Aur aapka state kaunsa hai?
- **User:** Madhya Pradesh _(captured: state)_
- **Bot:** Theek hai. Ramesh ji, abhi ek seller line par available hai, price aur baaki details aap unse directly discuss kar sakte hain. Kya main aapki call connect kar doon?
- **User:** haan
- **Bot:** Ji, main abhi aapki call Patel Pipes & Fittings se connect kar rahi hoon. IndiaMART ko call karne ke liye dhanyavaad.

> outcome `transferred` · questions asked 9 · re-asks of known facts 8 · user turns 9

## Seller side: Shree Polymers, privacy probe + lead feedback

## Seller voice call

*voice · context ON · opening scenario `lead_followup` (personalised, facts: contact, lead, buyer_city, product, when, missed_call) · file loaded in 13.22 ms*

- **Bot:** Namaste Sunil ji, IndiaMART se Vani bol rahi hoon. Kal aapko Indore se 500 Piece 4 inch PVC Pipe ki lead mili thi aur us buyer ki call bhi aapse miss ho gayi thi. Kya aapki unse baat ho payi?
- **User:** pehle us buyer ka naam aur number batao, aur usne kis kis se baat ki?
- **Bot:** Buyer ka naam aur number aapke Lead Manager mein us lead ke andar hai. Buyer ne aur kis se baat ki, ye main share nahi kar sakti. Kya aapki us buyer se baat ho payi?
- **User:** haan baat hui, quotation bhej diya _(captured: lead_feedback)_
- **Bot:** Bahut badhiya, note kar liya. Dhanyavaad Sunil ji. Aapko sahi leads milti rahengi. IndiaMART ke saath bane rahne ke liye shukriya.

> outcome `feedback_given` · questions asked 1 · re-asks of known facts 0 · user turns 2

`seller.md` section **Responses & outcomes**:

    Responded 4/7 (57%) · avg first response 18.3h · won 1 · quoted 2 · lost 0 · not reachable 1

LLM usage: {'model': 'sarvam-105b-conversations', 'calls': 11, 'errors': 0, 'avg_ms': 323}
