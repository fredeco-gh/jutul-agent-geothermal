// jutul-agent web client. One WebSocket per session; renders the wire protocol
// (docs/server-interface.md) as a chat. Vanilla JS, no build step.

const thread = document.getElementById("thread");
const conversation = document.getElementById("conversation");
const welcome = document.getElementById("welcome");
const promptEl = document.getElementById("prompt");
const sendEl = document.getElementById("send");
const metaEl = document.getElementById("meta");
const hintEl = document.getElementById("hint");
const vizPanel = document.getElementById("viz-panel");
const vizFrame = document.getElementById("viz-frame");
const vizTitle = document.getElementById("viz-title");

let ws = null;
let sessionId = null;
let sim = null;
let model = null;
let assistant = null; // { el, raw } for the in-progress assistant message
const toolCards = new Map(); // tool_call_id -> { details, body, chip }
let busy = false;

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}

function add(node) {
  if (welcome) welcome.remove();
  thread.appendChild(node);
  atBottom() && scrollDown();
  return node;
}

function atBottom() {
  return conversation.scrollHeight - conversation.scrollTop - conversation.clientHeight < 120;
}
function scrollDown() {
  conversation.scrollTop = conversation.scrollHeight;
}

// --- session lifecycle ----------------------------------------------------

async function init() {
  const sims = await fetch("/simulators").then((r) => r.json()).catch(() => ({}));
  const models = await fetch("/models").then((r) => r.json()).catch(() => ({}));
  sim = sims.default || (sims.simulators && sims.simulators[0]) || "jutuldarcy";
  model = models.default || null;
  await startSession();
}

async function startSession() {
  const resp = await fetch("/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sim }),
  });
  if (!resp.ok) {
    metaEl.textContent = "could not start a session";
    return;
  }
  sessionId = (await resp.json()).session_id;
  metaEl.innerHTML = `<span class="chip">${sim}</span> · ${model || "no model"} · ${sessionId.slice(0, 13)}`;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/sessions/${sessionId}/stream`);
  ws.onmessage = (e) => handle(JSON.parse(e.data));
  ws.onclose = () => setBusy(false);
}

async function newChat() {
  if (ws) ws.close();
  if (sessionId) fetch(`/sessions/${sessionId}`, { method: "DELETE" }).catch(() => {});
  thread.innerHTML = "";
  toolCards.clear();
  assistant = null;
  const w = el("div", "welcome");
  w.innerHTML = "<h1>What would you like to explore?</h1>";
  thread.appendChild(w);
  await startSession();
}

// --- rendering ------------------------------------------------------------

let working = null;
function showWorking() {
  clearWorking();
  working = add(el("div", "working"));
  working.innerHTML = "<span></span><span></span><span></span>";
}
function clearWorking() {
  if (working) {
    working.remove();
    working = null;
  }
}

function handle(msg) {
  if (msg.type !== "usage") clearWorking();
  switch (msg.type) {
    case "text": return onText(msg.text);
    case "reasoning": return onReasoning(msg.text);
    case "tool": return onTool(msg);
    case "viz": return onViz(msg);
    case "artifact": return onArtifact(msg);
    case "interrupt": return onInterrupt(msg);
    case "usage": return; // could surface context use in meta later
    case "turn_end": return onTurnEnd();
    case "error": return onError(msg.message);
  }
}

function ensureAssistant() {
  if (!assistant) {
    const wrap = add(el("div", "msg assistant"));
    const md = el("div", "markdown");
    wrap.appendChild(md);
    assistant = { el: md, raw: "" };
  }
  return assistant;
}

function onText(text) {
  const a = ensureAssistant();
  a.raw += text;
  a.el.innerHTML = window.renderMarkdown(a.raw);
  if (atBottom()) scrollDown();
}

function onReasoning(text) {
  let block = thread.querySelector(".reasoning[data-live]");
  if (!block) {
    block = el("details", "block reasoning");
    block.setAttribute("data-live", "1");
    const sum = el("summary");
    sum.appendChild(el("span", null, "Thinking"));
    const body = el("div", "body");
    block.append(sum, body);
    add(block);
  }
  block.querySelector(".body").textContent += text;
}

function onTool(msg) {
  let card = toolCards.get(msg.tool_call_id);
  if (!card) {
    finalizeAssistant();
    const details = el("details", "block tool");
    const sum = el("summary");
    sum.appendChild(el("span", "tool-name", msg.label || msg.name));
    const chip = el("span", "chip-status running");
    chip.innerHTML = '<span class="spinner"></span>';
    sum.appendChild(chip);
    const body = el("div", "body");
    details.append(sum, body);
    add(details);
    card = { details, body, chip };
    toolCards.set(msg.tool_call_id, card);
    if (msg.args && Object.keys(msg.args).length) {
      card.body.textContent = summarizeArgs(msg.args);
    }
  }
  if (msg.event === "finished") {
    card.chip.textContent = "done";
    card.chip.className = "chip-status";
    if (msg.content) appendOutput(card, msg.content);
  } else if (msg.event === "error") {
    card.chip.textContent = "error";
    card.chip.className = "chip-status error";
    if (msg.content) appendOutput(card, msg.content);
  }
}

function summarizeArgs(args) {
  return Object.entries(args)
    .map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join("\n");
}
function appendOutput(card, content) {
  const text = card.body.textContent ? card.body.textContent + "\n\n" : "";
  card.body.textContent = text + content;
}

function onViz(msg) {
  finalizeAssistant();
  const card = el("div", "viz-card");
  const head = el("div", "head");
  head.appendChild(el("span", null, msg.title || "Interactive plot"));
  const open = el("button", "ghost open", "Expand");
  open.onclick = () => openViz(msg.url, msg.title);
  head.appendChild(open);
  const frame = el("iframe");
  frame.src = msg.url;
  frame.loading = "lazy";
  card.append(head, frame);
  add(card);
}

function openViz(url, title) {
  vizTitle.textContent = title || "Plot";
  vizFrame.src = url;
  vizPanel.hidden = false;
}

function onArtifact(msg) {
  finalizeAssistant();
  const card = el("div", "viz-card");
  const head = el("div", "head");
  head.appendChild(el("span", null, msg.caption || "Artifact"));
  card.appendChild(head);
  if (msg.mime && msg.mime.startsWith("image/")) {
    const img = el("img");
    img.src = msg.url;
    img.style.cssText = "width:100%;display:block";
    card.appendChild(img);
  } else {
    const a = el("a", null, msg.url);
    a.href = msg.url;
    a.target = "_blank";
    a.style.cssText = "display:block;padding:0.6rem 0.8rem";
    card.appendChild(a);
  }
  add(card);
}

function onInterrupt(msg) {
  finalizeAssistant();
  const card = add(el("div", "approval"));
  const names = msg.actions.map((a) => a.label || a.name).join(", ");
  card.appendChild(el("div", "title", `Approve: ${names}?`));
  const buttons = el("div", "buttons");
  for (const decision of msg.allowed_decisions) {
    const btn = el("button", decision === "approve" ? "btn primary" : "btn", decision);
    btn.onclick = () => {
      ws.send(JSON.stringify({ type: "decision", decision }));
      card.remove();
      setBusy(true);
      showWorking();
    };
    buttons.appendChild(btn);
  }
  card.appendChild(buttons);
}

function onTurnEnd() {
  finalizeAssistant();
  for (const card of toolCards.values()) card.details.removeAttribute("data-live");
  const live = thread.querySelector(".reasoning[data-live]");
  if (live) live.removeAttribute("data-live");
  toolCards.clear();
  setBusy(false);
}

function onError(message) {
  add(el("div", "approval", message)).classList.add("title");
  setBusy(false);
}

function finalizeAssistant() {
  assistant = null;
}

// --- composer -------------------------------------------------------------

function setBusy(b) {
  busy = b;
  sendEl.disabled = b;
  if (!b) promptEl.focus();
}

function addUserBubble(text) {
  const wrap = add(el("div", "msg user"));
  wrap.appendChild(el("div", "bubble", text));
  scrollDown();
}

function send() {
  const text = promptEl.value.trim();
  if (!text || busy || !ws) return;
  addUserBubble(text);
  ws.send(JSON.stringify({ type: "prompt", text }));
  promptEl.value = "";
  resize();
  setBusy(true);
  showWorking();
}

function resize() {
  promptEl.style.height = "auto";
  promptEl.style.height = Math.min(promptEl.scrollHeight, 200) + "px";
}

promptEl.addEventListener("input", resize);
promptEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
});
sendEl.onclick = send;
document.getElementById("new-chat").onclick = newChat;
document.getElementById("viz-close").onclick = () => {
  vizPanel.hidden = true;
  vizFrame.src = "about:blank";
};

// Preview/test hook: lets a headless browser drive the renderer with scripted
// events (and set the meta line) so the UI can be screenshotted deterministically.
window.jutulDebug = { handle, addUserBubble, setMeta: (html) => (metaEl.innerHTML = html) };

init();

