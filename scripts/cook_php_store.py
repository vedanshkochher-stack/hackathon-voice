"""Cook the buyer context into a self-contained PHP data store + API: php/buyer_context.php.

The generated PHP file holds the data itself (a PHP array keyed by GLID) and serves it over HTTP;
it does not read files, a database or the Python layer at request time.

    python scripts/cook_php_store.py           # re-run to refresh the cooked data
    php -S localhost:8080 php/buyer_context.php
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("IMCTX_WORKDIR", str(ROOT / "out" / "runs" / "cook"))
sys.stdout.reconfigure(encoding="utf-8")

from ctxlayer import bootstrap, reader  # noqa: E402
from ctxlayer.util import iso, now  # noqa: E402

OUT = ROOT / "php" / "buyer_context.php"
KEYS = ["known", "kyc", "open_thread", "interests", "purchases", "intent", "signals", "next", "never_ask",
        "sources_missing", "synthetic", "schema", "generated_at", "watermark"]


def php(v, ind: int = 1) -> str:
    """Python value -> PHP literal (arrays use short syntax, strings are single-quoted)."""
    pad, pad_in = "    " * (ind - 1), "    " * ind
    if v is None:
        return "null"
    if v is True or v is False:
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return "'" + v.replace("\\", "\\\\").replace("'", "\\'") + "'"
    if isinstance(v, dict):
        if not v:
            return "[]"
        rows = [f"{pad_in}{php(str(k))} => {php(x, ind + 1)}," for k, x in v.items()]
        return "[\n" + "\n".join(rows) + f"\n{pad}]"
    if isinstance(v, (list, tuple)):
        if not v:
            return "[]"
        if all(not isinstance(x, (dict, list)) for x in v) and len(", ".join(map(php, v))) < 90:
            return "[" + ", ".join(php(x) for x in v) + "]"
        return "[\n" + "\n".join(f"{pad_in}{php(x, ind + 1)}," for x in v) + f"\n{pad}]"
    return php(str(v), ind)


def cook() -> dict:
    bootstrap(reset=True, start_threads=False)
    data = {}
    for c in reader.read_all("buyer"):
        m = c.meta
        rec = {"glid": str(m["glid"]), "summary": c.headline}
        rec.update({k: m[k] for k in KEYS if k in m})
        rec["sections"] = c.sections
        rec["context_md"] = c.raw
        data[str(m["glid"])] = rec
    return data


API = r'''
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
'''


def main():
    data = cook()
    body = (
        "<?php\ndeclare(strict_types=1);\n\n"
        "/**\n * Buyer context data store + API (self-contained).\n *\n"
        " * The data below is cooked from the GLID context layer by scripts/cook_php_store.py.\n"
        " * Nothing is read at request time: this file is the store. Re-run the script to refresh it.\n"
        " *\n *   php -S localhost:8080 php/buyer_context.php      then  GET /api/buyer/50112001\n"
        f" *\n * SYNTHETIC demo data ({len(data)} buyers).\n */\n\n"
        f"const COOKED_AT = {php(iso(now()))};\n\n"
        "// ======================================================================= cooked data store\n"
        f"$BUYER_CONTEXT = {php(data)};\n"
        + API
    )
    OUT.write_text(body, encoding="utf-8", newline="\n")
    print(f"cooked {len(data)} buyers into {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
