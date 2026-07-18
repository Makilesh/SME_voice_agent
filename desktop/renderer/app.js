// Renderer: connects to the backend control WebSocket, renders transcript,
// copilot cards, notes, and drives the ask box + global-shortcut UI events.

const $ = (id) => document.getElementById(id);
let ws = null;
let running = false;
let auto = true;
let opacity = 1;

const cards = $("cards");
const transcript = $("transcript");
const notesEl = $("notes");

// Track streaming cards by id so deltas append to the right element.
const cardState = {}; // card_id -> { el, aEl, stage, text }
let partialEls = { them: null, you: null };

function setStatus(text, on) {
  $("status").textContent = text;
  $("dot").className = "dot " + (on ? "on" : "off");
}

function connect(url) {
  ws = new WebSocket(url);
  ws.onopen = () => setStatus("connected", false);
  ws.onclose = () => { setStatus("disconnected", false); setTimeout(() => connect(url), 1500); };
  ws.onmessage = (e) => handleEvent(JSON.parse(e.data));
}

function send(obj) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj)); }

function handleEvent(ev) {
  switch (ev.type) {
    case "transcript": return onTranscript(ev);
    case "copilot": return onCopilot(ev);
    case "qa": return onQA(ev);
    case "notes": return onNotes(ev);
    case "status": return setStatus(ev.text, ev.text === "listening");
  }
}

function onTranscript(ev) {
  const { speaker, text, final } = ev;
  if (!final) {
    if (!partialEls[speaker]) {
      const el = document.createElement("div");
      el.className = `line ${speaker} partial`;
      el.innerHTML = `<span class="who">${speaker === "them" ? "THEM" : "YOU"}</span><span class="t"></span>`;
      transcript.appendChild(el);
      partialEls[speaker] = el;
    }
    partialEls[speaker].querySelector(".t").textContent = text;
  } else {
    if (partialEls[speaker]) { partialEls[speaker].remove(); partialEls[speaker] = null; }
    const el = document.createElement("div");
    el.className = `line ${speaker}`;
    el.innerHTML = `<span class="who">${speaker === "them" ? "THEM" : "YOU"}</span><span class="t"></span>`;
    el.querySelector(".t").textContent = text;
    transcript.appendChild(el);
  }
  transcript.scrollTop = transcript.scrollHeight;
}

function onCopilot(ev) {
  const id = ev.card_id;
  if (ev.stage === "start") {
    const el = document.createElement("div");
    el.className = "card draft";
    el.innerHTML = `<div class="q"></div><div class="a"></div>`;
    el.querySelector(".q").textContent = "Q: " + (ev.question || "");
    cards.prepend(el);
    cardState[id] = { el, aEl: el.querySelector(".a"), stage: "draft", text: "" };
    trimCards();
  } else if (ev.stage === "draft" || ev.stage === "final") {
    const st = cardState[id];
    if (!st) return;
    if (ev.stage === "final" && st.stage !== "final") {
      // First 'final' delta → swap draft for the refined answer.
      st.stage = "final";
      st.text = "";
      st.el.className = "card final";
      st.aEl.textContent = "";
    }
    st.text += ev.delta || "";
    st.aEl.textContent = st.text;
  } else if (ev.stage === "cancelled") {
    const st = cardState[id];
    if (st && st.stage !== "final") st.el.remove();
  }
}

function onQA(ev) {
  const id = "qa-" + ev.card_id;
  if (ev.stage === "start") {
    const el = document.createElement("div");
    el.className = "card qa final";
    el.innerHTML = `<div class="q"></div><div class="a"></div>`;
    el.querySelector(".q").textContent = "You asked: " + (ev.question || "");
    cards.prepend(el);
    cardState[id] = { el, aEl: el.querySelector(".a"), text: "" };
    trimCards();
  } else if (ev.stage === "delta") {
    const st = cardState[id];
    if (st) { st.text += ev.delta || ""; st.aEl.textContent = st.text; }
  }
}

function onNotes(ev) {
  const dec = (ev.decisions || []).map((d) => `<li>${escapeHtml(d)}</li>`).join("");
  const act = (ev.action_items || []).map((a) => `<li>${escapeHtml(a)}</li>`).join("");
  notesEl.innerHTML =
    `<div class="n-summary">${escapeHtml(ev.summary || "")}</div>` +
    (dec ? `<div class="pane-title">Decisions</div><ul>${dec}</ul>` : "") +
    (act ? `<div class="pane-title">Action items</div><ul>${act}</ul>` : "");
}

function trimCards() { while (cards.children.length > 6) cards.lastChild.remove(); }
function escapeHtml(s) { return (s || "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); }

// ── Controls ───────────────────────────────────────────────────────────
$("startBtn").onclick = () => {
  running = !running;
  if (running) { send({ cmd: "start" }); $("startBtn").textContent = "Stop"; setStatus("listening", true); }
  else { send({ cmd: "stop" }); $("startBtn").textContent = "Start"; setStatus("stopped", false); }
};
$("autoBtn").onclick = () => {
  auto = !auto;
  $("autoBtn").classList.toggle("on", auto);
  send({ cmd: "set_auto_copilot", enabled: auto });
};
$("notesToggle").onclick = () => {
  const p = $("notesPane");
  p.classList.toggle("collapsed");
  $("notesToggle").textContent = p.classList.contains("collapsed") ? "Notes ▸" : "Notes ▾";
};
function submitAsk() {
  const v = $("ask").value.trim();
  if (v) { send({ cmd: "ask", text: v }); $("ask").value = ""; }
}
$("askBtn").onclick = submitAsk;
$("ask").addEventListener("keydown", (e) => { if (e.key === "Enter") submitAsk(); });

// ── Global-shortcut events from main process ───────────────────────────
window.copilot.onUi((p) => {
  if (p.type === "forceCopilot") send({ cmd: "force_copilot" });
  else if (p.type === "focusAsk") $("ask").focus();
  else if (p.type === "opacity") { opacity = Math.min(1, Math.max(0.3, opacity + p.delta)); document.getElementById("app").style.opacity = opacity; }
  else if (p.type === "clickThrough") setStatus(p.value ? "click-through" : (running ? "listening" : "idle"), running);
});

// ── Boot ───────────────────────────────────────────────────────────────
(async () => {
  const cfg = await window.copilot.getConfig();
  connect(cfg.backendUrl);
})();
