<?php
declare(strict_types=1);

/**
 * Buyer context data store + API (self-contained).
 *
 * The data below is cooked from the GLID context layer by scripts/cook_php_store.py.
 * Nothing is read at request time: this file is the store. Re-run the script to refresh it.
 *
 *   php -S localhost:8080 php/buyer_context.php      then  GET /api/buyer/50112001
 *
 * SYNTHETIC demo data (3 buyers).
 */

const COOKED_AT = '2026-10-10T12:09:56.748+05:30';

// ======================================================================= cooked data store
$BUYER_CONTEXT = [
    '50112001' => [
        'glid' => '50112001',
        'summary' => 'Hot buyer, mid-way on PVC Pipe (WhatsApp, 09 Oct): qty, Size given; Pressure Rating pending. Speaks Hindi.',
        'known' => [
            'name' => 'Ramesh',
            'city' => 'Indore',
            'state' => 'Madhya Pradesh',
            'language' => 'hi',
        ],
        'kyc' => [
            'mobile' => true,
            'email' => false,
            'gst' => true,
        ],
        'open_thread' => [
            'product' => 'PVC Pipe',
            'ref' => 'ENQ-731204',
            'status' => 'in_progress',
            'last_channel' => 'whatsapp',
            'last_at' => '2026-10-09T10:09+05:30',
            'captured' => [
                'quantity' => '500 Piece',
                'Size' => '4 inch',
            ],
            'pending' => ['Pressure Rating'],
            'notes' => ['Price asked'],
        ],
        'interests' => [
            [
                'product' => 'PVC Pipe',
                'last' => '2026-10-10',
                'n' => 4,
                'via' => 'app search',
            ],
            [
                'product' => 'Solvent Cement',
                'last' => '2026-10-09',
                'n' => 1,
                'via' => 'web search',
            ],
            [
                'product' => 'Pipe Fittings',
                'last' => '2026-10-08',
                'n' => 2,
                'via' => 'app search',
            ],
        ],
        'purchases' => [
            [
                'product' => 'Water Storage Tank',
                'last' => '2026-09-20',
                'note' => 'purchased',
            ],
        ],
        'intent' => [
            'product' => 'Solvent Cement',
            'mcat' => 'Solvent Cement',
            'last_search_at' => '2026-10-09T09:09+05:30',
        ],
        'signals' => [
            'warmth' => 'hot',
            'last_active' => '2026-10-10T07:09+05:30',
            'active_days_30d' => 8,
            'preferred_channel' => 'app',
        ],
        'next' => ['ask:Pressure Rating', 'offer:live_seller'],
        'never_ask' => ['name', 'city', 'state', 'product', 'quantity', 'Size'],
        'synthetic' => true,
        'schema' => 'imctx.buyer/v1',
        'generated_at' => '2026-10-10T12:09:56.661+05:30',
        'watermark' => 20,
        'sections' => [
            '_head' => [
                '# Buyer 50112001 · Ramesh · Indore, Madhya Pradesh',
                '> Hot buyer, mid-way on PVC Pipe (WhatsApp, 09 Oct): qty, Size given; Pressure Rating pending. Speaks Hindi.',
            ],
            'Enquiries' => [
                '- 08 Oct · PVC Pipe · 500 Piece · 4 inch · in progress (ENQ-731204)',
                '- 13 Sep · Water Storage Tank · 2 Piece · 1000 L · closed: purchased (ENQ-701877)',
            ],
            'Categories searched' => [
                'PVC Pipes ×3 (last 10 Oct) · Solvent Cement ×1 (last 09 Oct) · Pipe Fittings ×1 (last 08 Oct)',
            ],
            'Sellers contacted' => [
                '- Shree Polymers, Pune · PVC Pipe · 08 Oct · missed, sent to VANI',
                '- Jain Pipe House, Indore · Pipe Fittings · 04 Oct · talked 3 min',
            ],
            'KYC' => ['mobile verified · email not verified · GST verified'],
            'Conversations' => [
                '- 09 Oct WhatsApp (IM WhatsApp) · PVC Pipe · Gave quantity and size; asked price (told the seller will quote); went quiet before pressure rating. Pending: Pressure Rating.',
                '- 08 Oct Voice (VANI) · PVC Pipe · Seller missed the call; buyer confirmed the PVC Pipe requirement; call dropped before quantity. Pending: quantity, Size, Pressure Rating.',
            ],
            'Engagement' => ['Active 8 of 30 days · last active 10 Oct 07:09 · prefers App · hot'],
            'Next best action' => [
                '- Resume PVC Pipe: ask only Pressure Rating; then offer a live seller.',
                '- Never ask again: name, city, state, product, qty, Size.',
                '- Asked price before: the seller quotes; never state a price.',
                '- Never reveal other parties\' data; never read out KYC.',
            ],
        ],
        'context_md' => '---
schema: imctx.buyer/v1
glid: \'50112001\'
role: buyer
generated_at: \'2026-10-10T12:09:56.661+05:30\'
watermark: 20
synthetic: true
known: {name: Ramesh, city: Indore, state: Madhya Pradesh, language: hi}
kyc: {mobile: true, email: false, gst: true}
open_thread:
  product: PVC Pipe
  ref: ENQ-731204
  status: in_progress
  last_channel: whatsapp
  last_at: 2026-10-09T10:09+05:30
  captured: {quantity: 500 Piece, Size: 4 inch}
  pending: [Pressure Rating]
  notes: [Price asked]
interests:
- {product: PVC Pipe, last: \'2026-10-10\', n: 4, via: app search}
- {product: Solvent Cement, last: \'2026-10-09\', n: 1, via: web search}
- {product: Pipe Fittings, last: \'2026-10-08\', n: 2, via: app search}
purchases:
- {product: Water Storage Tank, last: \'2026-09-20\', note: purchased}
intent: {product: Solvent Cement, mcat: Solvent Cement, last_search_at: \'2026-10-09T09:09+05:30\'}
signals: {warmth: hot, last_active: \'2026-10-10T07:09+05:30\', active_days_30d: 8, preferred_channel: app}
next: [\'ask:Pressure Rating\', \'offer:live_seller\']
never_ask: [name, city, state, product, quantity, Size]
---
# Buyer 50112001 · Ramesh · Indore, Madhya Pradesh
> Hot buyer, mid-way on PVC Pipe (WhatsApp, 09 Oct): qty, Size given; Pressure Rating pending. Speaks Hindi.

## Enquiries (90d)
- 08 Oct · PVC Pipe · 500 Piece · 4 inch · in progress (ENQ-731204)
- 13 Sep · Water Storage Tank · 2 Piece · 1000 L · closed: purchased (ENQ-701877)

## Categories searched (30d)
PVC Pipes ×3 (last 10 Oct) · Solvent Cement ×1 (last 09 Oct) · Pipe Fittings ×1 (last 08 Oct)

## Sellers contacted (60d)
- Shree Polymers, Pune · PVC Pipe · 08 Oct · missed, sent to VANI
- Jain Pipe House, Indore · Pipe Fittings · 04 Oct · talked 3 min

## KYC
mobile verified · email not verified · GST verified

## Conversations (30d, newest first)
- 09 Oct WhatsApp (IM WhatsApp) · PVC Pipe · Gave quantity and size; asked price (told the seller will quote); went quiet before pressure rating. Pending: Pressure Rating.
- 08 Oct Voice (VANI) · PVC Pipe · Seller missed the call; buyer confirmed the PVC Pipe requirement; call dropped before quantity. Pending: quantity, Size, Pressure Rating.

## Engagement (30d)
Active 8 of 30 days · last active 10 Oct 07:09 · prefers App · hot

## Next best action
- Resume PVC Pipe: ask only Pressure Rating; then offer a live seller.
- Never ask again: name, city, state, product, qty, Size.
- Asked price before: the seller quotes; never state a price.
- Never reveal other parties\' data; never read out KYC.
',
    ],
    '50112002' => [
        'glid' => '50112002',
        'summary' => 'Warm buyer, mid-way on Industrial RO Plant (Voice, 07 Oct): qty, Capacity given; Body Material pending. Speaks English.',
        'known' => [
            'name' => 'Lakshmi',
            'city' => 'Hyderabad',
            'state' => 'Telangana',
            'language' => 'en',
        ],
        'kyc' => [
            'mobile' => true,
            'email' => false,
            'gst' => false,
        ],
        'open_thread' => [
            'product' => 'Industrial RO Plant',
            'ref' => 'ENQ-731990',
            'status' => 'in_progress',
            'last_channel' => 'voice',
            'last_at' => '2026-10-07T10:09+05:30',
            'captured' => [
                'quantity' => '1 Unit',
                'Capacity' => '2000 LPH',
            ],
            'pending' => ['Body Material'],
            'notes' => ['Use-case: packaged drinking water unit'],
        ],
        'interests' => [
            [
                'product' => 'Industrial RO Plant',
                'last' => '2026-10-07',
                'n' => 3,
                'via' => 'seller call',
            ],
            [
                'product' => 'Water Softener',
                'last' => '2026-10-01',
                'n' => 1,
                'via' => 'web search',
            ],
        ],
        'signals' => [
            'warmth' => 'warm',
            'last_active' => '2026-10-07T10:09+05:30',
            'active_days_30d' => 5,
            'preferred_channel' => 'app',
        ],
        'next' => ['ask:Body Material', 'offer:live_seller'],
        'never_ask' => ['name', 'city', 'state', 'product', 'quantity', 'Capacity'],
        'synthetic' => true,
        'schema' => 'imctx.buyer/v1',
        'generated_at' => '2026-10-10T12:09:56.671+05:30',
        'watermark' => 31,
        'sections' => [
            '_head' => [
                '# Buyer 50112002 · Lakshmi · Hyderabad, Telangana',
                '> Warm buyer, mid-way on Industrial RO Plant (Voice, 07 Oct): qty, Capacity given; Body Material pending. Speaks English.',
            ],
            'Enquiries' => ['- 07 Oct · Industrial RO Plant · 1 Unit · 2000 LPH · in progress (ENQ-731990)'],
            'Categories searched' => ['Industrial RO Plants ×2 (last 06 Oct) · Water Softeners ×1 (last 01 Oct)'],
            'Sellers contacted' => ['- AquaPure Systems, Hyderabad · Industrial RO Plant · 07 Oct · missed, sent to VANI'],
            'KYC' => ['mobile verified · email not verified · GST not verified'],
            'Conversations' => [
                '- 07 Oct Voice (VANI) · Industrial RO Plant · Confirmed one 2000 LPH RO plant for a packaged drinking water unit; call dropped while choosing body material. Pending: Body Material.',
            ],
            'Engagement' => ['Active 5 of 30 days · last active 07 Oct 10:09 · prefers App · warm'],
            'Data notes' => [
                '- city: kept \'Hyderabad\' over \'Secunderabad\' (voice conversation newer/more trusted)',
            ],
            'Next best action' => [
                '- Resume Industrial RO Plant: ask only Body Material; then offer a live seller.',
                '- Never ask again: name, city, state, product, qty, Capacity.',
                '- Never reveal other parties\' data; never read out KYC.',
            ],
        ],
        'context_md' => '---
schema: imctx.buyer/v1
glid: \'50112002\'
role: buyer
generated_at: \'2026-10-10T12:09:56.671+05:30\'
watermark: 31
synthetic: true
known: {name: Lakshmi, city: Hyderabad, state: Telangana, language: en}
kyc: {mobile: true, email: false, gst: false}
open_thread:
  product: Industrial RO Plant
  ref: ENQ-731990
  status: in_progress
  last_channel: voice
  last_at: 2026-10-07T10:09+05:30
  captured: {quantity: 1 Unit, Capacity: 2000 LPH}
  pending: [Body Material]
  notes: [\'Use-case: packaged drinking water unit\']
interests:
- {product: Industrial RO Plant, last: \'2026-10-07\', n: 3, via: seller call}
- {product: Water Softener, last: \'2026-10-01\', n: 1, via: web search}
signals: {warmth: warm, last_active: \'2026-10-07T10:09+05:30\', active_days_30d: 5, preferred_channel: app}
next: [\'ask:Body Material\', \'offer:live_seller\']
never_ask: [name, city, state, product, quantity, Capacity]
---
# Buyer 50112002 · Lakshmi · Hyderabad, Telangana
> Warm buyer, mid-way on Industrial RO Plant (Voice, 07 Oct): qty, Capacity given; Body Material pending. Speaks English.

## Enquiries (90d)
- 07 Oct · Industrial RO Plant · 1 Unit · 2000 LPH · in progress (ENQ-731990)

## Categories searched (30d)
Industrial RO Plants ×2 (last 06 Oct) · Water Softeners ×1 (last 01 Oct)

## Sellers contacted (60d)
- AquaPure Systems, Hyderabad · Industrial RO Plant · 07 Oct · missed, sent to VANI

## KYC
mobile verified · email not verified · GST not verified

## Conversations (30d, newest first)
- 07 Oct Voice (VANI) · Industrial RO Plant · Confirmed one 2000 LPH RO plant for a packaged drinking water unit; call dropped while choosing body material. Pending: Body Material.

## Engagement (30d)
Active 5 of 30 days · last active 07 Oct 10:09 · prefers App · warm

## Data notes
- city: kept \'Hyderabad\' over \'Secunderabad\' (voice conversation newer/more trusted)

## Next best action
- Resume Industrial RO Plant: ask only Body Material; then offer a live seller.
- Never ask again: name, city, state, product, qty, Capacity.
- Never reveal other parties\' data; never read out KYC.
',
    ],
    '50112003' => [
        'glid' => '50112003',
        'summary' => 'Hot buyer, browsing Bubble Wrap since 10 Oct with no enquiry yet. Speaks Hindi.',
        'known' => [
            'name' => 'Arjun',
            'city' => 'Ahmedabad',
            'state' => 'Gujarat',
            'language' => 'hi',
        ],
        'kyc' => 'unavailable',
        'interests' => [
            [
                'product' => 'Bubble Wrap Roll',
                'last' => '2026-10-10',
                'n' => 3,
                'via' => 'app search',
            ],
        ],
        'purchases' => [
            [
                'product' => 'Corrugated Box',
                'last' => '2026-09-16',
                'note' => 'purchased from Om Packaging',
            ],
        ],
        'intent' => [
            'product' => 'Bubble Wrap Roll',
            'mcat' => 'Bubble Wrap',
            'last_search_at' => '2026-10-10T10:59+05:30',
        ],
        'signals' => [
            'warmth' => 'hot',
            'last_active' => '2026-10-10T10:59+05:30',
            'active_days_30d' => 4,
            'preferred_channel' => 'app',
        ],
        'next' => ['suggest:Bubble Wrap Roll'],
        'never_ask' => ['name', 'city', 'state'],
        'sources_missing' => ['kyc'],
        'synthetic' => true,
        'schema' => 'imctx.buyer/v1',
        'generated_at' => '2026-10-10T12:09:56.678+05:30',
        'watermark' => 43,
        'sections' => [
            '_head' => [
                '# Buyer 50112003 · Arjun · Ahmedabad, Gujarat',
                '> Hot buyer, browsing Bubble Wrap since 10 Oct with no enquiry yet. Speaks Hindi.',
            ],
            'Enquiries' => [
                '- 31 Aug · Corrugated Box · 5000 Piece · 5 ply · closed: purchased from Om Packaging (ENQ-690112)',
            ],
            'Categories searched' => ['Bubble Wrap ×3 (last 10 Oct)'],
            'Sellers contacted' => ['- Om Packaging, Ahmedabad · Corrugated Box · 31 Aug · talked 7 min'],
            'KYC' => ['unavailable (source down at build time); treat as unknown'],
            'Conversations' => [
                '- 18 Sep WhatsApp (IM WhatsApp) · Corrugated Box · Reported a 4-day delivery delay on boxes; seller resolved it; buyer satisfied.',
            ],
            'Engagement' => ['Active 4 of 30 days · last active 10 Oct 10:59 · prefers App · hot'],
            'Data notes' => ['- sources unavailable at build: kyc'],
            'Next best action' => [
                '- Ask if they need Bubble Wrap Roll.',
                '- Never ask again: name, city, state.',
                '- Past complaint (18 Sep, resolved): be empathetic if raised.',
                '- Never reveal other parties\' data; never read out KYC.',
            ],
        ],
        'context_md' => '---
schema: imctx.buyer/v1
glid: \'50112003\'
role: buyer
generated_at: \'2026-10-10T12:09:56.678+05:30\'
watermark: 43
synthetic: true
sources_missing: [kyc]
known: {name: Arjun, city: Ahmedabad, state: Gujarat, language: hi}
kyc: unavailable
interests:
- {product: Bubble Wrap Roll, last: \'2026-10-10\', n: 3, via: app search}
purchases:
- {product: Corrugated Box, last: \'2026-09-16\', note: purchased from Om Packaging}
intent: {product: Bubble Wrap Roll, mcat: Bubble Wrap, last_search_at: \'2026-10-10T10:59+05:30\'}
signals: {warmth: hot, last_active: \'2026-10-10T10:59+05:30\', active_days_30d: 4, preferred_channel: app}
next: [\'suggest:Bubble Wrap Roll\']
never_ask: [name, city, state]
---
# Buyer 50112003 · Arjun · Ahmedabad, Gujarat
> Hot buyer, browsing Bubble Wrap since 10 Oct with no enquiry yet. Speaks Hindi.

## Enquiries (90d)
- 31 Aug · Corrugated Box · 5000 Piece · 5 ply · closed: purchased from Om Packaging (ENQ-690112)

## Categories searched (30d)
Bubble Wrap ×3 (last 10 Oct)

## Sellers contacted (60d)
- Om Packaging, Ahmedabad · Corrugated Box · 31 Aug · talked 7 min

## KYC
unavailable (source down at build time); treat as unknown

## Conversations (30d, newest first)
- 18 Sep WhatsApp (IM WhatsApp) · Corrugated Box · Reported a 4-day delivery delay on boxes; seller resolved it; buyer satisfied.

## Engagement (30d)
Active 4 of 30 days · last active 10 Oct 10:59 · prefers App · hot

## Data notes
- sources unavailable at build: kyc

## Next best action
- Ask if they need Bubble Wrap Roll.
- Never ask again: name, city, state.
- Past complaint (18 Sep, resolved): be empathetic if raised.
- Never reveal other parties\' data; never read out KYC.
',
    ],
];

// ======================================================================= API
// GET /api/buyer/{glid}                     buyer context (JSON)
// GET /api/buyer/{glid}?fields=known,open_thread,next     only these keys
// GET /api/buyer/{glid}?markdown=0          without the context_md body
// GET /api/buyer/{glid}.md                  the context as Markdown (what the bot prompt receives)
// GET /api/buyers                           all GLIDs in this store
// GET /health
// Query-string form for any PHP host: buyer_context.php?glid=50112001 (&fields=, &markdown=0, &format=md),
// buyer_context.php?list=1, buyer_context.php?health=1
// Optional auth: set CTX_STORE_API_KEY and send it as the X-API-Key header.

function respond(int $status, $body, string $type = 'application/json'): never
{
    http_response_code($status);
    header("Content-Type: {$type}; charset=utf-8");
    header('Cache-Control: no-store');
    header('Access-Control-Allow-Origin: *');
    header('Access-Control-Allow-Headers: X-API-Key, Content-Type');
    echo $type === 'application/json'
        ? json_encode($body, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT)
        : $body;
    exit;
}

function buyer_context(string $glid): array
{
    global $BUYER_CONTEXT;
    if (isset($BUYER_CONTEXT[$glid])) {
        return ['glid' => $glid, 'exists' => true, 'cold_start' => false] + $BUYER_CONTEXT[$glid];
    }
    return [                                   // unknown GLID: a well-formed cold start, not an error
        'glid' => $glid, 'exists' => false, 'cold_start' => true,
        'summary' => 'No IndiaMART history for this GLID: use the generic opening and collect everything.',
        'known' => new stdClass(), 'next' => ['ask:product', 'ask:name', 'ask:city', 'ask:state'], 'never_ask' => [],
    ];
}

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
if ($method === 'OPTIONS') {
    respond(204, '', 'text/plain');
}
if ($method !== 'GET') {
    respond(405, ['error' => 'only GET is supported']);
}
$key = getenv('CTX_STORE_API_KEY');
if ($key && !hash_equals($key, (string) ($_SERVER['HTTP_X_API_KEY'] ?? ''))) {
    respond(401, ['error' => 'missing or invalid X-API-Key']);
}

$q = $_GET;
$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';
if ($path === '/health') {
    $q['health'] = 1;
} elseif ($path === '/api/buyers') {
    $q['list'] = 1;
} elseif (preg_match('#^/api/buyer/([^/]+?)(\.md)?$#', $path, $m)) {
    $q['glid'] = $m[1];
    if (!empty($m[2])) {
        $q['format'] = 'md';
    }
} elseif ($path !== '/' && !str_ends_with($path, '.php')) {
    respond(404, ['error' => 'not found', 'try' => ['/api/buyer/{glid}', '/api/buyers', '/health']]);
}

if (!empty($q['health'])) {
    respond(200, ['ok' => true, 'buyers' => count($BUYER_CONTEXT), 'cooked_at' => COOKED_AT]);
}
if (!empty($q['list'])) {
    respond(200, ['cooked_at' => COOKED_AT, 'buyers' => array_map(
        fn ($r) => ['glid' => $r['glid'], 'name' => $r['known']['name'] ?? null, 'summary' => $r['summary']],
        array_values($BUYER_CONTEXT))]);
}
$glid = trim((string) ($q['glid'] ?? ''));
if ($glid === '') {
    respond(400, ['error' => 'glid is required, e.g. /api/buyer/50112001 or ?glid=50112001']);
}
if (!preg_match('/^\d{1,15}$/', $glid)) {
    respond(400, ['error' => 'glid must be 1-15 digits']);
}
$ctx = buyer_context($glid);
if (($q['format'] ?? 'json') === 'md') {
    $ctx['exists'] ? respond(200, $ctx['context_md'], 'text/markdown')
                   : respond(404, "no buyer context for GLID {$glid}\n", 'text/plain');
}
if (($q['markdown'] ?? '1') === '0') {
    unset($ctx['context_md']);
}
if (!empty($q['fields'])) {
    $want = array_map('trim', explode(',', (string) $q['fields']));
    $ctx = array_intersect_key($ctx, array_flip(array_merge(['glid', 'exists'], $want)));
}
respond(200, $ctx);
