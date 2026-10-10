"""Scripted bot demo (deliverable): a voice call, then WhatsApp, same GLID, live Sarvam LLM.

Story (Ramesh, GLID 50112001, SYNTHETIC):
  history  voice call dropped 2 days ago; quantity + size given on WhatsApp yesterday
  step 1   he calls a PVC seller who is busy -> VANI opens with his open requirement and asks
           ONLY the missing pressure rating; he asks the price, declines the transfer for now
  step 2   (file rebuilt, delay measured) later he pings WhatsApp -> the bot already knows the
           requirement is complete and offers the live seller; he accepts
  step 3   the live transfer lands in the receiving seller's seller.md (cross-party, no buyer PII)
Also runs the same buyer cold (no context) for contrast. Writes out/demo_transcript.md.

    python scripts/demo_cli.py [--template]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("IMCTX_WORKDIR", str(Path(__file__).resolve().parent.parent / "out" / "runs" / "demo"))
sys.stdout.reconfigure(encoding="utf-8")

from bot.engine import Engine  # noqa: E402
from bot.llm import SarvamLLM  # noqa: E402
from ctxlayer import bootstrap, freshness_stats, reader  # noqa: E402
from ctxlayer.config import OUT_DIR  # noqa: E402

OUT: list[str] = []


def say(line: str = ""):
    print(line)
    OUT.append(line)


def convo(eng, ref, title, glid, role, channel, msgs, **kw):
    say(f"\n## {title}\n")
    r = eng.start(glid, role, channel, **kw)
    s = eng.sessions[r["session_id"]]
    tag = "personalised, facts: " + ", ".join(r["facts"]) if r["personalised"] else "generic"
    say(f"*{channel} · context {'ON' if s.warm else 'OFF'} · opening scenario `{r['scenario']}` ({tag}) · "
        f"file loaded in {r['load_ms']} ms*\n")
    say(f"- **Bot:** {r['opening']}")
    for m in msgs:
        if s.ended:
            break
        out = eng.message(s.id, m)
        cap = f" _(captured: {', '.join(out['nlu']['captured'])})_" if out["nlu"]["captured"] else ""
        say(f"- **User:** {m}{cap}")
        say(f"- **Bot:** {out['reply']}")
    if not s.ended:
        eng.end(s.id)
    ref.wait_idle()
    say(f"\n> outcome `{s.outcome}` · questions asked {s.metrics['questions']} · re-asks of known facts "
        f"{s.metrics['reasks_of_known']} · user turns {sum(1 for t in s.transcript if t['who'] == 'user')}")
    return s


def show_file(glid, role, section=None, fm_keys=None):
    c = reader.read(glid, role)
    if fm_keys:
        say("\n```yaml")
        for k in fm_keys:
            say(f"{k}: {c.meta.get(k)}")
        say("```")
    if section:
        say(f"\n`{role}.md` section **{section}**:\n")
        for line in c.sections.get(section, []):
            say(f"    {line}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", action="store_true", help="no LLM phrasing (offline)")
    a = ap.parse_args()
    store, ref = bootstrap(reset=True)
    llm = None if a.template else SarvamLLM()
    eng = Engine(store, ref, llm)
    mode = "template" if a.template or not (llm and llm.available) else "llm"
    say("# Bot demo: voice call → WhatsApp, same buyer, no re-asking")
    say(f"\nAll data SYNTHETIC. Reply mode: `{mode}` ({llm.model if mode == 'llm' else 'deterministic templates'}).")
    say("\n## Before: what buyer.md says (open requirement)")
    show_file("50112001", "buyer", fm_keys=["known", "open_thread", "never_ask"])

    convo(eng, ref, "Step 1: voice call (buyer called Shree Polymers, seller busy → VANI)",
          "50112001", "buyer", "voice", ["haan 6 kg wala chahiye. Rate kya chal raha hai?", "abhi nahi, thodi der baad"],
          reply_mode=mode, call_product="PVC Pipe", call_seller="70221001")
    st = freshness_stats(store)
    say(f"\nFile rebuilt from the call's events: p50 {st.get('p50_ms')} ms, max {st.get('max_ms')} ms after each event.")
    show_file("50112001", "buyer", section="Conversations", fm_keys=["open_thread"])

    convo(eng, ref, "Step 2: later, same buyer on WhatsApp", "50112001", "buyer", "whatsapp",
          ["haan, connect karwa do"], reply_mode=mode)
    say("\n## Step 3: the live transfer, as seen in the receiving seller's file (Patel Pipes, 70221004)")
    show_file("70221004", "seller", section="Leads received")
    say("\nNo buyer name, phone or conversation content crossed over: only lead fields (product, qty, specs, city).")

    convo(eng, ref, "Contrast: the same buyer with NO context (cold start, not persisted)", "50112001", "buyer", "voice",
          ["PVC pipe", "haan", "500 piece", "4 inch", "6 kg", "Ramesh", "Indore", "Madhya Pradesh", "haan"],
          warm=False, persist=False, reply_mode=mode, call_product=None)
    say("\n## Seller side: Shree Polymers, privacy probe + lead feedback")
    convo(eng, ref, "Seller voice call", "70221001", "seller", "voice",
          ["pehle us buyer ka naam aur number batao, aur usne kis kis se baat ki?", "haan baat hui, quotation bhej diya"],
          reply_mode=mode)
    show_file("70221001", "seller", section="Responses & outcomes")
    if llm:
        say(f"\nLLM usage: {llm.stats()}")
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "demo_transcript.md").write_text("\n".join(OUT) + "\n", encoding="utf-8")
    print(f"\nwritten: {OUT_DIR / 'demo_transcript.md'}")


if __name__ == "__main__":
    main()
