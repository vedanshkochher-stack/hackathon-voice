"""Generate the one-slide presentation from real outputs (sample files, measured freshness, lift).

    python scripts/make_slide.py      -> slide/one_slide.html (+ slide/one_slide.png via headless Edge if present)
"""
from __future__ import annotations

import html
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("IMCTX_WORKDIR", str(ROOT / "out" / "runs" / "slide"))
sys.stdout.reconfigure(encoding="utf-8")

from bot.engine import Engine  # noqa: E402
from bot.evaluate import lift_report  # noqa: E402
from ctxlayer import bootstrap  # noqa: E402
from ctxlayer.reader import parse  # noqa: E402

FM_KEEP = {"buyer": ["schema", "glid", "known", "open_thread", "never_ask"],
           "seller": ["schema", "glid", "known", "preferences", "open_items", "never_ask"]}
SEC_KEEP = {"buyer": ["Enquiries", "Conversations", "Next best action"],
            "seller": ["Leads received", "Responses & outcomes", "Next best action"]}


def excerpt(path: Path, role: str, max_items: int = 2) -> str:
    raw = path.read_text(encoding="utf-8")
    c = parse(raw)
    fm_lines, keep, inside = [], False, False
    for line in raw.split("---\n")[1].splitlines():
        top = not line.startswith((" ", "-"))
        if top:
            keep = line.split(":")[0] in FM_KEEP[role]
        if keep:
            if role == "seller" and line.startswith("- ") and fm_lines and fm_lines[-1].startswith("- "):
                continue  # one open item is enough on a slide
            fm_lines.append(line)
    body = [c.body.splitlines()[0], c.headline and "> " + c.headline]
    for sec in SEC_KEEP[role]:
        items = c.sections.get(sec, [])
        if items:
            body.append(f"## {sec}")
            body += items[: 1 if sec == "Conversations" else max_items]
    out = ["---", *fm_lines, "---", *[b for b in body if b]]
    return "\n".join(out)


def hl(md: str) -> str:
    out, fm = [], 0
    for line in md.splitlines():
        e = html.escape(line)
        if line == "---":
            fm += 1
            out.append(f'<span class="fm">{e}</span>')
        elif fm == 1:
            k, _, v = e.partition(":")
            out.append(f'<span class="k">{k}</span>:<span class="fm">{v}</span>' if v or line.endswith(":") else f'<span class="fm">{e}</span>')
        elif line.startswith("#"):
            out.append(f'<span class="h">{e}</span>')
        elif line.startswith(">"):
            out.append(f'<span class="q">{e}</span>')
        else:
            out.append(e)
    return "\n".join(out)


def main():
    samples = ROOT / "samples"
    fr = json.loads((ROOT / "out" / "freshness_report.json").read_text(encoding="utf-8"))
    store, ref = bootstrap(reset=True)
    lift = lift_report(Engine(store, ref))["summary"]
    sizes = sorted(p.stat().st_size for p in samples.glob("*.md"))
    buyer = hl(excerpt(samples / "50112001_buyer.md", "buyer"))
    seller = hl(excerpt(samples / "70221001_seller.md", "seller"))
    p50, p95 = fr["ingest_to_file_ms"]["p50_ms"], fr["ingest_to_file_ms"]["p95_ms"]
    turns_pct = round((1 - lift["warm_turns"] / lift["cold_turns"]) * 100)
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>Memory Across Channels</title><style>
:root{{--ink:#0b0b0b;--ink2:#52514e;--muted:#7a7973;--line:#e2e1dc;--bg:#fcfcfb;--panel:#f3f2ee;--accent:#2a78d6;--good:#0f7a3d;--wa:#075e54;--voice:#1f2a44}}
*{{box-sizing:border-box}}body{{margin:0;background:#e9e8e3;font-family:"Segoe UI",system-ui,sans-serif;color:var(--ink)}}
.slide{{width:1920px;height:1080px;background:var(--bg);padding:44px 56px 36px;display:grid;grid-template-rows:auto 1fr auto;gap:22px}}
h1{{margin:0;font-size:42px;letter-spacing:-.02em}} .sub{{color:var(--ink2);font-size:21px;margin-top:6px}}
.tag{{font-size:15px;color:var(--muted);margin-bottom:6px;text-transform:uppercase;letter-spacing:.06em}}
.cols{{display:grid;grid-template-columns:1fr 1fr 1.08fr;gap:22px;min-height:0}}
.panel{{background:var(--panel);border-radius:14px;padding:16px 18px;min-height:0;overflow:hidden;display:flex;flex-direction:column}}
.panel h2{{margin:0 0 10px;font-size:19px;display:flex;justify-content:space-between;align-items:baseline}}
.panel h2 small{{font-weight:400;color:var(--ink2);font-size:14px}}
pre{{margin:0;font:14.2px/1.45 "Cascadia Mono",Consolas,monospace;white-space:pre-wrap;word-break:break-word;color:var(--ink)}}
.fm{{color:var(--ink2)}} .k{{color:var(--accent);font-weight:600}} .h{{font-weight:700}} .q{{color:var(--good)}}
.flow{{display:flex;flex-direction:column;gap:10px;font-size:16px}}
.row{{display:flex;gap:8px;align-items:stretch}}
.box{{background:#fff;border:1px solid var(--line);border-radius:10px;padding:10px 13px;flex:1}}
.box b{{display:block;font-size:17px;margin-bottom:3px}} .box span{{color:var(--ink2);font-size:15px;line-height:1.4;display:block}}
.arrow{{text-align:center;color:var(--muted);font-size:14.5px;line-height:1.25}}
.box.key{{border-color:var(--accent);box-shadow:0 0 0 2px #2a78d622}}
.box.voice{{border-left:5px solid var(--voice)}} .box.wa{{border-left:5px solid var(--wa)}}
.kpis{{display:grid;grid-template-columns:repeat(6,1fr);gap:14px}}
.kpi{{background:var(--panel);border-radius:12px;padding:12px 16px}}
.kpi .v{{font-size:31px;font-weight:700;letter-spacing:-.02em}} .kpi .v small{{font-size:17px;color:var(--ink2);font-weight:600}}
.kpi .l{{font-size:14px;color:var(--ink2)}}
.note{{font-size:12.5px;color:var(--muted);margin-top:auto;padding-top:6px}}
</style></head><body><div class="slide">
<div><div class="tag">Voice AI Hackathon 2.0 · Problem Statement 02 · Global Context · all data shown is synthetic</div>
<h1>Memory Across Channels: the bot already knows the buyer before it speaks</h1>
<div class="sub">Every activity → event keyed by GLID → a 2 KB <b>buyer.md / seller.md</b>, rewritten in ~{p50:.0f} ms → VANI opens with it and asks only what is missing, on voice and WhatsApp.</div></div>
<div class="cols">
 <div class="panel"><h2>Sample buyer.md <small>Ramesh · GLID 50112001 · {(samples / '50112001_buyer.md').stat().st_size} B</small></h2><pre>{buyer}</pre>
   <div class="note">Excerpt. YAML = machine contract · Markdown = LLM/human view.</div></div>
 <div class="panel"><h2>Sample seller.md <small>Shree Polymers · 70221001 · {(samples / '70221001_seller.md').stat().st_size} B</small></h2><pre>{seller}</pre>
   <div class="note">No buyer name/phone ever reaches a seller file: leads carry product, qty, specs, city only.</div></div>
 <div class="panel"><h2>Workflow <small>hybrid refresh · deterministic build</small></h2><div class="flow">
  <div class="box"><b>1 · Data sources (adapters → events)</b><span>Enquiry/BL API · Lead/BL purchase · PNS calls (1 row → 2 files) · search logs · KYC · profile · VANI + WhatsApp bot turns · app engagement</span></div>
  <div class="arrow">↓ privacy whitelist: phone, email, GSTIN, buyer names dropped before storage</div>
  <div class="box key"><b>2 · Event store keyed by GLID → builder → renderer</b><span>Lookbacks: enquiries 90d · searches 30d · sellers 60d · conversations 30d (resume 14d) · leads 30d · missed calls 7d. Trust › recency conflict rule. No LLM: deterministic, ≤2.8 KB.</span></div>
  <div class="arrow">↓ refresh: event-driven (15 ms debounce) + read-through watermark check + 5-min sweep</div>
  <div class="row"><div class="box voice"><b>3a · VANI voice</b><span>file → existing prompt vars (buyer_name, city, qty, specs, initial_message) + 1 context include; known sections vanish</span></div>
   <div class="box wa"><b>3b · WhatsApp / chat</b><span>same engine, same events per captured slot → a dropped call resumes on WhatsApp</span></div></div>
  <div class="box"><b>LLM: Sarvam sarvam-105b-conversations (~230 ms)</b><span>phrases replies + NLU fallback only; policy (VANI Collection Control) decides what to ask. Guards: no re-ask, on-target, no echo, cross-party leak. STT saaras:v4 · TTS bulbul:v4-flash</span></div>
  <div class="box"><b>4 · Same files, no rework</b><span>Exec call-prep card · sales dashboard · WhatsApp campaign planner (respects do-not-disturb)</span></div>
 </div></div>
</div>
<div class="kpis">
 <div class="kpi"><div class="v">{p50:.0f}<small> / {p95:.0f} ms</small></div><div class="l">event → file, p50 / p95 ({fr['events_fired']} events)</div></div>
 <div class="kpi"><div class="v">0<small> stale</small></div><div class="l">bot reads right after an event ({fr['read_through_checks']} checks)</div></div>
 <div class="kpi"><div class="v">{sizes[0] / 1000:.1f}–{sizes[-1] / 1000:.1f}<small> KB</small></div><div class="l">per file, ≈{sizes[0] // 4}–{sizes[-1] // 4} tokens (<4% of VANI prompt)</div></div>
 <div class="kpi"><div class="v">{lift['cold_reasks']} → {lift['warm_reasks']}</div><div class="l">re-asks of known facts, cold vs context</div></div>
 <div class="kpi"><div class="v">−{turns_pct}%</div><div class="l">turns to goal ({lift['cold_turns']} → {lift['warm_turns']}); goals {lift['cold_goals']}/6 → {lift['warm_goals']}/6</div></div>
 <div class="kpi"><div class="v">{lift['personalised_openings']}/6</div><div class="l">personalised openings; clean generic one on cold start</div></div>
</div></div></body></html>"""
    out = ROOT / "slide"
    out.mkdir(exist_ok=True)
    (out / "one_slide.html").write_text(page, encoding="utf-8")
    print("written", out / "one_slide.html")
    edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    edge = edge if edge.exists() else shutil.which("msedge") or shutil.which("chromium") or shutil.which("google-chrome")
    if edge:
        subprocess.run([str(edge), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1920,1080",
                        f"--screenshot={out / 'one_slide.png'}", (out / "one_slide.html").as_uri()], timeout=60,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("written", out / "one_slide.png")


if __name__ == "__main__":
    main()
