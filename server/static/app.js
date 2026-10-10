"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts, body: opts.body ? JSON.stringify(opts.body) : undefined });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

const S = { users: [], sel: null, prevLines: null, meta: null, ch: { voice: null }, activeSid: null, tab: "prompt" };

const LANG_NAMES = { hi: "Hindi", en: "English", bn: "Bengali", ta: "Tamil", te: "Telugu", kn: "Kannada", ml: "Malayalam",
                     mr: "Marathi", gu: "Gujarati", pa: "Punjabi", od: "Odia" };
const LANG_CHIPS = ["English please", "Tamil mein baat kijiye", "తెలుగులో మాట్లాడండి", "Hindi mein boliye", "Urdu mein baat karo"];
// Who the buyer "called" when their call fell through to VANI (seller-unavailable redirect)
const CALLED_SELLER = { "50112001": "70221001", "50112002": "70221003" };
const QUICK = {
  "50112001": ["haan 6 kg wala chahiye, rate kya chal raha hai?", "abhi nahi, baad mein", "haan connect kar do", "Shree Polymers ka number do",
               "nahi ji, ab kuch nahi chahiye", "haan, pipe fittings chahiye, 200 piece", "elbow"],
  "50112002": ["SS 304 please. What's the price range?", "FRP is fine", "Connect me", "We already bought it from a local vendor", "Yes, a water softener, 2 units"],
  "50112003": ["haan, 500 roll chahiye", "1 meter aur 70 micron", "haan connect karo"],
  "50119999": ["mujhe PVC pipe chahiye", "haan", "200 piece", "4 inch", "6 kg", "Vikram", "Surat", "Gujarat", "haan"],
  "70221001": ["haan baat hui, quotation bhej diya", "pehle buyer ka naam aur number batao, usne kis kis se baat ki?", "nahi abhi call nahi kiya", "haan bhej do"],
  "70221002": ["haan, order mil gaya", "100 roll", "nahi"],
  "70221003": ["nahi abhi time nahi mila", "haan bhej do"],
  "70221004": ["haan", "leads theek aa rahi hain"],
};

// ------------------------------------------------------------------ theme (light / dark)
function currentTheme() {
  const set = document.documentElement.dataset.theme;
  if (set) return set;
  return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}
$("#theme-toggle").addEventListener("click", () => {
  const next = currentTheme() === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("vani-theme", next); } catch (e) { /* storage blocked: theme still applies for this visit */ }
  $("#theme-toggle").title = `Switch to ${next === "dark" ? "light" : "dark"} theme`;
});

// ------------------------------------------------------------------ people + presets
const initials = (label) => {
  const words = String(label).replace(/\(.*\)/, "").trim().split(/\s+/).filter(Boolean);
  if (!words.length || /new buyer/i.test(label)) return "?";
  return (words[0][0] + (words.length > 1 && /[A-Z]/.test(words[1][0]) ? words[1][0] : "")).toUpperCase();
};
async function loadUsers(keepSel = true) {
  const d = await api("/api/users");
  S.users = d.users;
  const pill = $("#pill-llm");
  $(".ptxt", pill).textContent = d.llm ? d.model : "template mode";
  pill.classList.toggle("ok", d.llm);
  $("#people").innerHTML = S.users.map((u, i) => `
    <div class="person ${S.sel && S.sel.glid === u.glid && S.sel.role === u.role ? "on" : ""}" data-i="${i}" role="button" tabindex="0">
      <div class="avatar ${u.role}">${esc(initials(u.label))}</div>
      <div>
        <div class="p-top"><span class="p-name">${esc(u.label)}</span><span class="badge ${u.warmth || "cold"}">${esc(u.warmth || "cold")}</span></div>
        <div class="p-hl">${esc(u.headline)}</div>
        <div class="p-meta"><span class="badge ${u.role}">${u.role}</span><span class="mono">GLID ${u.glid}</span></div>
      </div>
    </div>`).join("");
  $$(".person").forEach((el) => {
    const go = () => select(S.users[+el.dataset.i]);
    el.addEventListener("click", go);
    el.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
  });
  if (!keepSel || !S.sel) select(S.users[0]);
}
async function loadPresets() {
  const p = await api("/api/simulate");
  $("#presets").innerHTML = p.map((x) => `<button class="preset" data-id="${x.id}"><span class="bolt">⚡</span><span>${esc(x.label)}</span></button>`).join("");
  $$(".preset").forEach((b) => b.addEventListener("click", async () => {
    b.disabled = true; await api(`/api/simulate/${b.dataset.id}`, { method: "POST" }); b.disabled = false;
  }));
}

async function select(u) {
  if (S.ch.voice && !S.ch.voice.ended) await endSession("switch");
  S.sel = u; S.prevLines = null;
  $$(".person").forEach((el) => el.classList.toggle("on", S.users[+el.dataset.i] === u));
  resetPanel("voice");
  await loadFile(false);
  if (S.tab === "prep") renderPrep();
}

// ------------------------------------------------------------------ context file view
async function loadFile(highlight, info) {
  const u = S.sel; if (!u) return;
  const d = await api(`/api/context/${u.glid}/${u.role}`);
  S.meta = d.meta || null;
  $("#file-path").textContent = `out/context/${u.glid}/${u.role}.md`;
  $("#file-meta").innerHTML = d.exists
    ? [`${d.bytes} bytes`, `~${d.tokens} tokens`, `watermark #${d.meta.watermark}`, `generated ${esc(String(d.meta.generated_at).slice(11, 19))}`]
        .map((x) => `<span class="mchip">${x}</span>`).join("") + (d.meta.synthetic ? '<span class="mchip syn">synthetic data</span>' : "")
    : '<span class="mchip">no file yet: cold start</span>';
  const lines = d.markdown.split("\n");
  const prev = highlight && S.prevLines ? new Set(S.prevLines) : null;
  let inFm = false, fmCount = 0;
  $("#md").innerHTML = lines.map((ln) => {
    const isNew = prev && !prev.has(ln) && !/^(generated_at|watermark):/.test(ln) ? " new" : "";
    if (ln === "---" && fmCount < 2) { fmCount++; inFm = fmCount === 1; return `<span class="fm">${esc(ln)}</span>`; }
    if (inFm) {
      const m = ln.match(/^(\s*-?\s*)([\w.]+)(:)(.*)$/);
      return m ? `<span class="${isNew.trim()}">${esc(m[1])}<span class="fk">${esc(m[2])}</span>${m[3]}<span class="fm">${esc(m[4])}</span></span>`
               : `<span class="fm${isNew}">${esc(ln)}</span>`;
    }
    const cls = ln.startsWith("#") ? "h" : ln.startsWith(">") ? "q" : "";
    return `<span class="${cls}${isNew}">${esc(ln)}</span>`;
  }).join("\n");
  S.prevLines = lines;
  if (highlight) setTimeout(() => $$("#md .new").forEach((e) => e.classList.remove("new")), 4000);
  if (info) {
    const t = $("#toast");
    t.textContent = `✓ rewritten ${info.max_lag_ms ?? "–"} ms after ${info.events} new event${info.events === 1 ? "" : "s"}`;
    t.classList.add("show"); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("show"), 5000);
  }
}

// ------------------------------------------------------------------ call panel
const panel = () => $("#ch-voice");
const call = { timer: null, t0: 0 };
function setStatus(text, live) {
  panel().classList.toggle("live", !!live);
  $("#call-status .stxt").textContent = text;
}
function startTimer() {
  call.t0 = Date.now();
  clearInterval(call.timer);
  const tick = () => {
    const s = Math.floor((Date.now() - call.t0) / 1000);
    setStatus(`On call · ${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`, true);
  };
  tick(); call.timer = setInterval(tick, 1000);
}
function stopTimer(text) { clearInterval(call.timer); call.timer = null; setStatus(text, false); }

function resetPanel() {
  const p = panel();
  stopVoice(); stopTimer(S.sel ? `Ready · ${S.sel.label}` : "Ready");
  $(".msgs", p).innerHTML = "";
  $(".ch-info", p).innerHTML = "";
  $(".start", p).disabled = false; $(".end", p).disabled = true; setComposer(false);
  const q = [...(QUICK[S.sel?.glid] || []), ...LANG_CHIPS];
  $(".chips", p).innerHTML = q.map((x) => `<button type="button" class="qr">${esc(x)}</button>`).join("");
  $$(".qr", p).forEach((b) => b.addEventListener("click", () => send(b.textContent)));
  S.ch.voice = null;
}
function setComposer(on) { $$(".composer input, .composer button", panel()).forEach((e) => (e.disabled = !on)); }
function addMsg(who, text, meta) {
  const box = $(".msgs", panel());
  const el = document.createElement("div");
  el.className = `msg ${who}`;
  el.innerHTML = esc(text) + (meta ? `<div class="meta">${meta}</div>` : "");
  box.appendChild(el); box.scrollTop = box.scrollHeight;
  return el;
}
function infoChips(r, st) {
  const chips = [];
  if (r) chips.push(`<span class="chip ${r.personalised ? "known" : "warnc"}">${r.warm ? "context loaded" : "cold start · no context"} · ${esc(r.scenario || "")}${r.warm && r.context ? ` · ${r.context.bytes} B in ${r.load_ms} ms` : ""}</span>`);
  if (st) {
    const known = (st.prefilled || []).filter((x) => x !== "product");
    if (known.length) chips.push(`<span class="chip known">won't ask: ${esc(known.join(", "))}</span>`);
    if (st.languages) chips.push(`<span class="chip lang">${esc(st.languages.map((l) => LANG_NAMES[l] || l).join(" → "))}</span>`);
    if (st.expect && !st.ended) chips.push(`<span class="chip">next: ${esc(st.expect)}</span>`);
    const m = st.metrics || {};
    chips.push(`<span class="chip">questions ${m.questions || 0} · re-asks ${m.reasks_of_known || 0}</span>`);
    if (m.leak_blocked || m.privacy_refusals) chips.push(`<span class="chip warnc">privacy: ${m.leak_blocked || 0} blocked, ${m.privacy_refusals || 0} refused</span>`);
  }
  $(".ch-info", panel()).innerHTML = chips.join("");
}

// The bot's text appears only when its audio starts playing. Audio is fetched immediately (in parallel
// with anything still playing) and played strictly in order. Resolves once the text is shown.
let audioQ = Promise.resolve();
const voice = { gen: 0, audio: null };
function botSay(text, meta, lang) {
  if (!$(".tts", panel()).checked || !text) { addMsg("bot", text, meta); return Promise.resolve(); }
  const gen = voice.gen;
  const el = addMsg("bot", "", null);
  el.classList.add("pending");
  el.innerHTML = '<span class="dots" aria-label="Vani is about to speak"><i></i><i></i><i></i></span>';
  const pace = parseFloat($(".pace", panel()).value) || 1.25;
  const audioP = api("/api/tts", { method: "POST", body: { text, lang, pace } }).then((d) => d.audio).catch(() => null);
  let shown;
  const shownP = new Promise((r) => (shown = r));
  const reveal = () => {
    if (el.classList.contains("pending")) {
      el.classList.remove("pending");
      el.innerHTML = esc(text) + (meta ? `<div class="meta">${meta}</div>` : "");
      const box = $(".msgs", panel()); box.scrollTop = box.scrollHeight;
    }
    shown();
  };
  audioQ = audioQ.then(async () => {
    const b64 = await audioP;
    if (gen !== voice.gen || !b64) return reveal();   // reset panel or TTS failure: show text, play nothing
    const a = new Audio(`data:audio/wav;base64,${b64}`);
    voice.audio = a;
    a.onplaying = reveal;                               // text appears the moment speech starts
    await new Promise((res) => {
      a.onended = res;
      a.onerror = () => { reveal(); res(); };
      a.play().catch(() => { reveal(); res(); });
    });
    reveal();
  });
  return shownP;
}
function stopVoice() {
  voice.gen++;
  if (voice.audio) { voice.audio.pause(); voice.audio = null; }
}

async function startSession() {
  const u = S.sel; if (!u) return;
  const p = panel();
  resetPanel();
  $(".start", p).disabled = true;
  setStatus("Connecting…", true);
  const warm = $(".warm", p).checked;
  const body = { glid: u.glid, role: u.role, channel: "voice", warm, reply_mode: "llm" };
  if (u.role === "buyer" && S.meta) {
    body.call_product = (S.meta.open_thread || {}).product || null;
    body.call_seller = CALLED_SELLER[u.glid] || null;
  }
  const r = await api("/api/session/start", { method: "POST", body });
  S.ch.voice = { sid: r.session_id, lang: r.lang, ended: false, r };
  S.activeSid = r.session_id;
  if (r.suppressed) {
    addMsg("sys", `Outbound call suppressed: ${r.reason}`);
    S.ch.voice.ended = true; $(".start", p).disabled = false; infoChips(r, r.state); stopTimer("Not called (do-not-disturb)"); return;
  }
  if (!warm) addMsg("sys", "A/B mode: context file ignored, nothing from this call is saved");
  infoChips(r, r.state);
  $(".end", p).disabled = false;
  startTimer();
  botSay(r.opening, r.personalised ? `personalised · ${r.facts.length} facts` : "generic opening", r.lang)
    .then(() => { if (!S.ch.voice?.ended) { setComposer(true); $(".composer input", p).focus(); } });
  if (S.tab === "prompt") renderPrompt();
}

async function send(text, lang = null) {
  const s = S.ch.voice;
  if (!s || s.ended || !text.trim()) return;
  addMsg("user", text);
  setComposer(false);
  const r = await api(`/api/session/${s.sid}/message`, { method: "POST", body: { text, lang } });
  if (r.state && r.state.lang) s.lang = r.state.lang;  // language may have switched this turn
  const cap = (r.nlu && r.nlu.captured) || [];
  const meta = [cap.length ? `captured: ${cap.join(", ")}` : "", r.nlu?.llm_used ? "LLM NLU" : "", `${r.ms.total} ms`].filter(Boolean).join(" · ");
  infoChips(s.r, r.state);
  if (r.ended) s.ended = true;
  botSay(r.reply, meta, s.lang).then(() => { if (!r.ended) setComposer(true); });
  if (r.ended) audioQ.then(() => finishPanel(r.outcome));  // "ended" note after the last line is spoken
  if (S.tab === "prompt") renderPrompt();
}

function finishPanel(outcome) {
  const p = panel();
  if (S.ch.voice) S.ch.voice.ended = true;
  addMsg("sys", `call ended · ${String(outcome).replace(/_/g, " ")} · the context file updated`);
  stopTimer(`Call ended · ${String(outcome).replace(/_/g, " ")}`);
  $(".end", p).disabled = true; $(".start", p).disabled = false; setComposer(false);
}
async function endSession(reason = "hangup") {
  const s = S.ch.voice; if (!s || s.ended) return;
  stopVoice();
  const r = await api(`/api/session/${s.sid}/end`, { method: "POST", body: { reason } });
  if (reason !== "switch") finishPanel(r.outcome); else s.ended = true;
}

$(".start", panel()).addEventListener("click", startSession);
$(".end", panel()).addEventListener("click", () => endSession("drop"));
$(".composer", panel()).addEventListener("submit", (e) => {
  e.preventDefault(); const i = $("input", e.target); const v = i.value; i.value = ""; send(v);
});

// ------------------------------------------------------------------ microphone -> WAV -> Sarvam STT
const mic = { ctx: null, proc: null, src: null, stream: null, chunks: [], rate: 16000 };
async function micStart() {
  if (!S.ch.voice || S.ch.voice.ended) return;
  mic.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  mic.ctx = new (window.AudioContext || window.webkitAudioContext)();
  mic.rate = mic.ctx.sampleRate; mic.chunks = [];
  mic.src = mic.ctx.createMediaStreamSource(mic.stream);
  mic.proc = mic.ctx.createScriptProcessor(4096, 1, 1);
  mic.proc.onaudioprocess = (e) => mic.chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
  mic.src.connect(mic.proc); mic.proc.connect(mic.ctx.destination);
  $(".mic").classList.add("rec");
}
async function micStop() {
  if (!mic.ctx) return;
  mic.proc.disconnect(); mic.src.disconnect(); mic.stream.getTracks().forEach((t) => t.stop());
  await mic.ctx.close(); mic.ctx = null;
  $(".mic").classList.remove("rec");
  const len = mic.chunks.reduce((a, c) => a + c.length, 0);
  if (len < mic.rate * 0.3) return;
  const pcm = new Float32Array(len); let o = 0; for (const c of mic.chunks) { pcm.set(c, o); o += c.length; }
  const ratio = mic.rate / 16000, n = Math.floor(pcm.length / ratio), out = new Int16Array(n);
  for (let i = 0; i < n; i++) { const v = Math.max(-1, Math.min(1, pcm[Math.floor(i * ratio)])); out[i] = v < 0 ? v * 0x8000 : v * 0x7fff; }
  const buf = new ArrayBuffer(44 + out.length * 2), dv = new DataView(buf);
  const w = (off, s) => [...s].forEach((ch, i) => dv.setUint8(off + i, ch.charCodeAt(0)));
  w(0, "RIFF"); dv.setUint32(4, 36 + out.length * 2, true); w(8, "WAVE"); w(12, "fmt ");
  dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, 1, true); dv.setUint32(24, 16000, true);
  dv.setUint32(28, 32000, true); dv.setUint16(32, 2, true); dv.setUint16(34, 16, true); w(36, "data"); dv.setUint32(40, out.length * 2, true);
  new Int16Array(buf, 44).set(out);
  const fd = new FormData(); fd.append("file", new Blob([buf], { type: "audio/wav" }), "speech.wav"); fd.append("lang", S.ch.voice?.lang || "hi");
  const r = await (await fetch("/api/stt", { method: "POST", body: fd })).json();
  if (r.text) send(r.text, r.language); else addMsg("sys", "Could not transcribe, please type instead");
}
const micBtn = $(".mic");
micBtn.addEventListener("mousedown", micStart); micBtn.addEventListener("mouseup", micStop); micBtn.addEventListener("mouseleave", micStop);
micBtn.addEventListener("touchstart", (e) => { e.preventDefault(); micStart(); }); micBtn.addEventListener("touchend", micStop);

// ------------------------------------------------------------------ live updates (SSE) + header freshness
async function loadFresh() {
  const f = await api("/api/freshness");
  const st = f.stats || {};
  $("#pill-fresh .ptxt").textContent = st.n ? `freshness p50 ${st.p50_ms} ms · p95 ${st.p95_ms} ms` : "freshness: waiting for live events";
}
let refreshT = null;
function scheduleRefresh() { clearTimeout(refreshT); refreshT = setTimeout(() => { loadFresh(); loadUsers(true); }, 250); }
const es = location.search.includes("shot") ? {} : new EventSource("/api/stream");  // ?shot: static screenshots
es.onmessage = (m) => {
  const d = JSON.parse(m.data);
  if (d.kind === "file") {
    if (S.sel && d.glid === S.sel.glid && d.role === S.sel.role) loadFile(true, d);
    scheduleRefresh();
  }
};

// ------------------------------------------------------------------ drawer tabs
$$("#tabs button").forEach((b) => b.addEventListener("click", () => {
  S.tab = b.dataset.tab;
  $$("#tabs button").forEach((x) => x.classList.toggle("on", x === b));
  $$(".tab").forEach((t) => t.classList.toggle("hidden", t.id !== `tab-${S.tab}`));
  (S.tab === "prompt" ? renderPrompt : renderPrep)();
}));

async function renderPrompt() {
  const el = $("#tab-prompt");
  if (!S.activeSid) { el.innerHTML = '<p class="empty">Start a call to see the VANI variables the context layer filled and the rendered prompt.</p>'; return; }
  const d = await api(`/api/session/${S.activeSid}/prompt`);
  const hl = esc(d.prompt).replace(/(GLOBAL CONTEXT[\s\S]*?(?:&lt;\/buyer_context&gt;|&lt;\/seller_context&gt;))/, "<mark>$1</mark>");
  const vars = Object.fromEntries(Object.entries(d.vars).filter(([k]) => !["specification_options", "quantity_unit_options"].includes(k)));
  el.innerHTML = `<div class="two">
    <div><div class="box-title">Prompt variables filled from the context file</div><div class="prompt-box">${esc(JSON.stringify(vars, null, 2))}</div></div>
    <div><div class="box-title">Rendered prompt · ${d.prompt.length} chars · highlighted = context block</div><div class="prompt-box">${hl}</div></div></div>
    ${d.cold_prompt ? `<details><summary>Same prompt with no context (cold start, ${d.cold_prompt.length} chars): every collection section is back</summary><div class="prompt-box">${esc(d.cold_prompt)}</div></details>` : ""}`;
}

async function renderPrep() {
  const el = $("#tab-prep");
  if (!S.sel) return;
  const r = await fetch(`/api/consumers/exec-prep/${S.sel.glid}/${S.sel.role}`);
  if (!r.ok) { el.innerHTML = '<p class="empty">No context file for this GLID yet.</p>'; return; }
  const c = await r.json();
  el.innerHTML = `<div class="prep-head"><div class="avatar ${c.role}">${esc(initials(S.sel.label))}</div>
      <div><div class="prep-title">${esc(c.title)}</div><p class="prep-line">${esc(c.one_liner)}</p></div></div>
    <div class="tiles">${Object.entries(c.kpis).map(([k, v]) => `<div class="tile"><div class="v">${esc(v ?? "–")}</div><div class="l">${esc(k)}</div></div>`).join("")}</div>
    <div class="prep"><div><b>Agenda</b><ul>${c.agenda.map((a) => `<li>${esc(a)}</li>`).join("")}</ul></div>
    <div><b>Watch out</b><ul>${(c.risks.length ? c.risks : ["Nothing flagged"]).map((a) => `<li>${esc(a)}</li>`).join("")}</ul>
    <b>Already known, don't ask</b><p class="mono">${esc(c.do_not_ask.join(", ") || "-")}</p></div></div>
    <div class="src">Built by consumers/exec_call_prep.py from ${esc(c.source_file)}</div>`;
}

$("#btn-reset").addEventListener("click", async () => {
  $("#btn-reset").disabled = true;
  await api("/api/reset", { method: "POST" });
  $("#btn-reset").disabled = false;
  S.sel = null; S.activeSid = null; await loadUsers(false); loadFresh(); renderPrompt();
});

loadUsers(false); loadPresets(); loadFresh();
