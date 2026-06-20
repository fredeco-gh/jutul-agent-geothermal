// jutul-agent web client. One WebSocket per session; renders the wire protocol
// (docs/server-interface.md) as a chat, with interactive views (plots, reports)
// pinned to a closable side canvas. Vanilla JS, no build step.

const thread = document.getElementById("thread");
const conversation = document.getElementById("conversation");
const welcome = document.getElementById("welcome");
const promptEl = document.getElementById("prompt");
const sendEl = document.getElementById("send");
const metaEl = document.getElementById("meta");
const canvasEl = document.getElementById("canvas");
const canvasBody = document.getElementById("canvas-body");
const canvasTabs = document.getElementById("canvas-tabs");
const viewsBtn = document.getElementById("views-btn");
const viewsCount = document.getElementById("views-count");
const simSelect = document.getElementById("sim-select");

let ws = null;
let sessionId = null;
let sim = null;
let model = null;
let assistant = null; // { el, raw } for the in-progress assistant message
const toolCards = new Map(); // tool_call_id -> { details, body, chip }
let busy = false;
let pendingInterrupt = null; // { card } while an approval awaits a decision

const ICONS = {
  plot: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="M7 15l3-4 3 2 4-6"/></svg>',
  report: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2h9l5 5v15H6z"/><path d="M14 2v6h6M9 13h6M9 17h6"/></svg>',
  image: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="1.6"/><path d="M21 16l-5-5L5 20"/></svg>',
};
const KIND_LABEL = { plot: "Interactive plot", report: "Report", image: "Image" };

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
  const names = sims.simulators || [];
  sim = sims.default || names[0] || "jutuldarcy";
  model = models.default || null;
  populateSims(names);
  await startSession();
}

// Offer a simulator picker when more than one is installed. Switching starts a
// fresh session for that simulator; the first session for a simulator may pause
// while its Julia environment is prepared.
function populateSims(names) {
  if (!names || names.length < 2) return;
  simSelect.innerHTML = "";
  for (const name of names) {
    const opt = el("option", null, name);
    opt.value = name;
    simSelect.appendChild(opt);
  }
  simSelect.value = sim;
  simSelect.hidden = false;
  simSelect.onchange = () => switchSim(simSelect.value);
}

async function switchSim(name) {
  if (name === sim || busy) {
    simSelect.value = sim;
    return;
  }
  sim = name;
  await newChat();
}

async function startSession() {
  // The first session for a simulator builds its Julia environment, which can
  // take a few minutes; say so rather than looking hung.
  metaEl.textContent = `starting ${sim}… (first run builds its environment, this can take a few minutes)`;
  if (simSelect) simSelect.disabled = true;
  const resp = await fetch("/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sim }),
  }).catch(() => null);
  if (simSelect) simSelect.disabled = false;
  if (!resp || !resp.ok) {
    metaEl.textContent = "could not start a session";
    return;
  }
  sessionId = (await resp.json()).session_id;
  metaEl.innerHTML = `${model || "no model"} · ${sessionId.slice(0, 13)}`;
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
  pendingInterrupt = null;
  promptEl.placeholder = "Message jutul-agent…";
  resetCanvas();
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
    case "usage": return onUsage(msg);
    case "turn_end": return onTurnEnd();
    case "ui": return onUi(msg);
    case "error": return onError(msg.message);
  }
}

// A tool drove the application's interface. The action vocabulary belongs to the
// host app (see docs/server-interface.md); a real app applies it to its own
// controls. This reference UI has none, so it surfaces the action transparently
// — both honest and useful when building/​debugging a host app. Host apps can
// override window.jutulDebug.onUi to apply actions to their interface.
function onUi(msg) {
  if (window.onJutulUi && window.onJutulUi(msg) === true) return; // host-app hook
  finalizeAssistant();
  const note = add(el("div", "ui-note"));
  note.appendChild(el("span", "ui-gear", "⚙"));
  note.appendChild(el("span", "ui-action", msg.action || "ui"));
  const payload = msg.payload && Object.keys(msg.payload).length ? JSON.stringify(msg.payload) : "";
  if (payload) note.appendChild(el("span", "ui-payload", payload));
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
    block.open = true; // visible while streaming; collapsed at turn end
    block.setAttribute("data-live", "1");
    const sum = el("summary");
    sum.appendChild(el("span", "tool-name", "Reasoning"));
    const body = el("div", "body");
    block.append(sum, body);
    add(block);
  }
  block.querySelector(".body").textContent += text;
  if (atBottom()) scrollDown();
}

// Args worth previewing on the collapsed summary line, in priority order.
const PREVIEW_KEYS = ["code", "command", "caption", "file_path", "path", "query", "slot"];

function argPreview(args) {
  if (!args) return "";
  for (const k of PREVIEW_KEYS) {
    if (args[k]) return String(args[k]).split("\n").find((l) => l.trim()) || "";
  }
  const first = Object.values(args)[0];
  return first == null ? "" : String(first).split("\n")[0];
}

function codeArg(args) {
  if (!args) return null;
  if (args.code) return String(args.code);
  if (args.command) return String(args.command);
  return null;
}

// Render a tool card's body, specialized per tool so each reads well: a plan as
// a checklist, an edit as a diff, a written file as its content, code-bearing
// tools as a code block, and anything else as a compact key/value list.
function fillToolBody(body, msg) {
  const name = msg.name;
  const args = msg.args || {};
  if (name === "write_todos" && Array.isArray(args.todos)) {
    body.appendChild(renderTodos(args.todos));
    return;
  }
  if (name === "edit_file" && (args.old_string != null || args.new_string != null)) {
    if (args.file_path) body.appendChild(el("div", "tool-path", args.file_path));
    body.appendChild(renderDiff(String(args.old_string || ""), String(args.new_string || "")));
    return;
  }
  if (name === "write_file" && args.content != null) {
    if (args.file_path) body.appendChild(el("div", "tool-path", args.file_path));
    const pre = el("pre", "tool-code");
    pre.appendChild(el("code", null, String(args.content)));
    body.appendChild(pre);
    return;
  }
  const code = codeArg(args);
  if (code) {
    const pre = el("pre", "tool-code");
    pre.appendChild(el("code", null, code));
    body.appendChild(pre);
    return;
  }
  if (Object.keys(args).length) {
    body.appendChild(el("div", "tool-args", summarizeArgs(args)));
  }
}

const TODO_MARK = { completed: "✓", in_progress: "▸", pending: "○" };
function renderTodos(todos) {
  const ul = el("ul", "todos");
  for (const t of todos) {
    const status = t.status || "pending";
    const li = el("li", `todo ${status}`);
    li.appendChild(el("span", "todo-mark", TODO_MARK[status] || "○"));
    li.appendChild(el("span", "todo-text", t.content || t.activeForm || ""));
    ul.appendChild(li);
  }
  return ul;
}

function renderDiff(oldStr, newStr) {
  const pre = el("pre", "tool-diff");
  if (oldStr) for (const line of oldStr.split("\n")) pre.appendChild(el("div", "del", "- " + line));
  if (newStr) for (const line of newStr.split("\n")) pre.appendChild(el("div", "add", "+ " + line));
  return pre;
}

function onTool(msg) {
  let card = toolCards.get(msg.tool_call_id);
  if (!card) {
    finalizeAssistant();
    const details = el("details", "block tool");
    details.open = true; // show what ran; the user complained about all-collapsed
    const sum = el("summary");
    sum.appendChild(el("span", "tool-name", msg.label || msg.name));
    sum.appendChild(el("span", "tool-preview", argPreview(msg.args)));
    const chip = el("span", "chip-status running");
    chip.innerHTML = '<span class="spinner"></span>';
    sum.appendChild(chip);
    const body = el("div", "body");
    fillToolBody(body, msg);
    const out = el("pre", "tool-output");
    out.hidden = true;
    body.appendChild(out);
    details.append(sum, body);
    add(details);
    card = { details, body, chip, out };
    toolCards.set(msg.tool_call_id, card);
  }
  if (msg.event === "finished") {
    card.chip.textContent = "done";
    card.chip.className = "chip-status";
    if (msg.content) setOutput(card, msg.content);
  } else if (msg.event === "error") {
    card.chip.textContent = "error";
    card.chip.className = "chip-status error";
    if (msg.content) setOutput(card, msg.content);
  }
}

function summarizeArgs(args) {
  return Object.entries(args)
    .map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join("\n");
}

function setOutput(card, content) {
  card.out.hidden = false;
  card.out.textContent = content;
  if (atBottom()) scrollDown();
}

// --- the canvas: a registry of pinned views shown in the side panel -------

const views = new Map(); // id -> { id, url, title, kind, poster, frame }
let viewOrder = []; // id order for the tab strip
let activeView = null; // id
let canvasOpen = false;
const chips = []; // { id, el } inline chips, to keep their active highlight in sync

function viewId(msg) {
  return msg.slot ? `slot:${msg.slot}` : `url:${msg.url}`;
}

function onViz(msg) {
  finalizeAssistant();
  const id = viewId(msg);
  const kind = msg.kind === "report" ? "report" : "plot";
  const title = msg.title || (kind === "report" ? "Report" : "Interactive plot");
  const existing = views.get(id);
  const view = existing || { id };
  Object.assign(view, { url: msg.url, title, kind, poster: msg.poster || null });
  if (!existing) {
    views.set(id, view);
    viewOrder.push(id);
  } else if (view.frame) {
    // A refreshed view (same slot): reload its frame so the new content shows.
    view.loaded = false;
    view.frame.src = bust(view.url);
  }
  addChip(view); // a fresh inline reference in the conversation each time
  openView(id); // reveal the panel and focus this view
}

function onArtifact(msg) {
  finalizeAssistant();
  if (msg.mime && msg.mime.startsWith("image/")) {
    const id = viewId(msg);
    const title = msg.caption || "Image";
    const existing = views.get(id);
    const view = existing || { id };
    Object.assign(view, { url: msg.url, title, kind: "image", poster: msg.url });
    if (!existing) { views.set(id, view); viewOrder.push(id); }
    // Static images stay visible inline (a direct record), and also open larger
    // in the canvas on click.
    const card = el("div", "art-card");
    const head = el("div", "head");
    head.appendChild(el("span", "grow", title));
    const openBtn = el("button", "ghost", "Open");
    openBtn.onclick = () => openView(id);
    head.appendChild(openBtn);
    const img = el("img");
    const wasBottom = atBottom();
    img.src = msg.url;
    img.onclick = () => openView(id);
    // The image's height isn't known until it loads; keep the view pinned to the
    // bottom once it does, so a late-loading figure doesn't strand the latest
    // messages (e.g. an approval) below the fold.
    img.onload = () => { if (wasBottom) scrollDown(); };
    card.append(head, img);
    add(card);
  } else {
    const card = el("div", "art-card");
    card.appendChild(el("div", "head", msg.caption || "Artifact"));
    const a = el("a", "file", msg.url);
    a.href = msg.url;
    a.target = "_blank";
    card.appendChild(a);
    add(card);
  }
}

function addChip(view) {
  const chip = el("button", "viz-chip");
  const ico = el("span", `ico ${view.kind}`);
  ico.innerHTML = ICONS[view.kind] || ICONS.plot;
  const info = el("div", "info");
  info.appendChild(el("div", "t", view.title));
  info.appendChild(el("div", "s", KIND_LABEL[view.kind] || "View"));
  const go = el("span", "go");
  go.innerHTML = "Open <svg viewBox='0 0 24 24' width='14' height='14' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M9 6l6 6-6 6'/></svg>";
  chip.append(ico, info, go);
  chip.onclick = () => openView(view.id);
  add(chip);
  chips.push({ id: view.id, el: chip });
  syncChips();
}

function bust(url) {
  return url + (url.includes("?") ? "&" : "?") + "_=" + Date.now();
}

// A spinner shown over the canvas until the active view finishes loading (a
// WebGL figure can take a moment to spin up).
let canvasLoader = null;
function showLoading(on) {
  if (!canvasLoader) {
    canvasLoader = el("div", "canvas-loading");
    canvasLoader.innerHTML = '<span class="spinner"></span><span>Loading view…</span>';
    canvasBody.appendChild(canvasLoader);
  }
  canvasLoader.classList.toggle("on", on);
}

// Lazily build the canvas element for a view (iframe for html, img for image),
// kept in the DOM so switching tabs preserves each view's state.
function ensureFrame(view) {
  if (view.frame) return view.frame;
  const node = view.kind === "image" ? el("img") : el("iframe");
  if (view.kind !== "image") {
    node.setAttribute("title", view.title);
    node.setAttribute("loading", "lazy");
  }
  node.addEventListener("load", () => {
    view.loaded = true;
    if (activeView === view.id) showLoading(false);
  });
  node.src = view.url;
  canvasBody.appendChild(node);
  view.frame = node;
  return node;
}

function openView(id) {
  const view = views.get(id);
  if (!view) return;
  activeView = id;
  ensureFrame(view);
  showLoading(!view.loaded);
  for (const v of views.values()) {
    if (v.frame) v.frame.classList.toggle("active", v.id === id);
  }
  if (canvasLoader) canvasBody.appendChild(canvasLoader); // keep the loader on top
  revealCanvas();
  renderTabs();
  syncChips();
}

function renderTabs() {
  canvasTabs.innerHTML = "";
  for (const id of viewOrder) {
    const view = views.get(id);
    if (!view) continue;
    const tab = el("button", "tab" + (id === activeView ? " active" : ""));
    const ico = el("span", "tab-ico");
    ico.innerHTML = ICONS[view.kind] || ICONS.plot;
    const label = el("span", "tab-label", view.title);
    tab.append(ico, label);
    const close = el("button", "tab-close");
    close.innerHTML = "<svg viewBox='0 0 24 24' width='12' height='12' fill='none' stroke='currentColor' stroke-width='2.4' stroke-linecap='round'><path d='M6 6l12 12M18 6L6 18'/></svg>";
    close.title = "Remove view";
    close.onclick = (e) => { e.stopPropagation(); removeView(id); };
    tab.appendChild(close);
    tab.onclick = () => openView(id);
    canvasTabs.appendChild(tab);
  }
}

function removeView(id) {
  const view = views.get(id);
  if (view && view.frame) view.frame.remove();
  views.delete(id);
  viewOrder = viewOrder.filter((x) => x !== id);
  if (activeView === id) {
    activeView = viewOrder[viewOrder.length - 1] || null;
    if (activeView) openView(activeView);
    else closeCanvas();
  }
  renderTabs();
  syncChips();
  updateViewsButton();
}

function revealCanvas() {
  canvasOpen = true;
  canvasEl.hidden = false;
  updateViewsButton();
}

function closeCanvas() {
  canvasOpen = false;
  canvasEl.hidden = true;
  syncChips();
  updateViewsButton();
}

function resetCanvas() {
  for (const v of views.values()) if (v.frame) v.frame.remove();
  views.clear();
  viewOrder = [];
  chips.length = 0;
  activeView = null;
  closeCanvas();
}

function syncChips() {
  for (const c of chips) {
    c.el.classList.toggle("active", canvasOpen && c.id === activeView);
  }
}

function updateViewsButton() {
  const n = views.size;
  if (n && !canvasOpen) {
    viewsBtn.hidden = false;
    viewsCount.innerHTML = `Views <span class="count">${n}</span>`;
  } else {
    viewsBtn.hidden = true;
  }
}

function onInterrupt(msg) {
  finalizeAssistant();
  clearWorking();
  const card = add(el("div", "approval"));
  pendingInterrupt = { card };
  const names = msg.actions.map((a) => a.label || a.name).join(", ");
  card.appendChild(el("div", "title", `Approve ${names}?`));
  // Show what each action will actually do (the command, file, etc.).
  for (const a of msg.actions) {
    const detail = argPreview(a.args) || a.description;
    if (detail) card.appendChild(el("pre", "approval-detail", detail));
  }
  const buttons = el("div", "buttons");
  // approve/reject resolve immediately; "respond" is sent by typing a reply.
  for (const decision of msg.allowed_decisions.filter((d) => d !== "respond")) {
    const btn = el("button", decision === "approve" ? "btn primary" : "btn", decision);
    btn.onclick = () => sendDecision(decision);
    buttons.appendChild(btn);
  }
  card.appendChild(buttons);
  if (msg.allowed_decisions.includes("respond")) {
    card.appendChild(el("div", "approval-hint", "…or type a reply below to send feedback."));
    promptEl.placeholder = "Reply to the agent…";
  }
  // The turn is paused on the user, so free the composer (it is not "working").
  setBusy(false);
}

function sendDecision(decision, message) {
  if (!ws || !pendingInterrupt) return;
  const payload = { type: "decision", decision };
  if (message) payload.message = message;
  ws.send(JSON.stringify(payload));
  clearInterrupt();
  setBusy(true);
  showWorking();
}

function clearInterrupt() {
  if (pendingInterrupt) {
    pendingInterrupt.card.remove();
    pendingInterrupt = null;
  }
  promptEl.placeholder = "Message jutul-agent…";
}

function onTurnEnd() {
  finalizeAssistant();
  toolCards.clear();
  // Collapse the (verbose) reasoning once the turn is done; tool cards stay open
  // so the conversation keeps a visible record of what the agent ran.
  const live = thread.querySelector(".reasoning[data-live]");
  if (live) {
    live.removeAttribute("data-live");
    live.open = false;
    const label = live.querySelector(".tool-name");
    if (label) label.textContent = "Reasoning";
  }
  setBusy(false);
}

function onError(message) {
  add(el("div", "approval", message)).classList.add("title");
  setBusy(false);
}

let lastInputTokens = 0;
function onUsage(msg) {
  // Show the latest turn's input size as a rough "context used" figure.
  lastInputTokens = msg.input_tokens || lastInputTokens;
  const usage = document.getElementById("usage");
  if (usage && lastInputTokens) {
    usage.textContent = `${formatTokens(lastInputTokens)} ctx`;
  }
}

function formatTokens(n) {
  return n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : String(n);
}

function finalizeAssistant() {
  assistant = null;
}

// --- composer -------------------------------------------------------------

function setBusy(b) {
  busy = b;
  // While a turn runs the send button becomes a stop button (it stays enabled so
  // the user can interrupt); idle, it sends.
  sendEl.classList.toggle("stop", b);
  sendEl.title = b ? "Stop" : "Send";
  if (!b) promptEl.focus();
}

function stop() {
  if (ws) ws.send(JSON.stringify({ type: "cancel" }));
}

function addUserBubble(text) {
  const wrap = add(el("div", "msg user"));
  wrap.appendChild(el("div", "bubble", text));
  scrollDown();
}

function send() {
  const text = promptEl.value.trim();
  if (!text || !ws) return;
  slashMenu.hidden = true;
  // A slash command is an instruction to the interface, not a turn.
  if (text.startsWith("/")) {
    dispatchSlash(text);
    promptEl.value = "";
    resize();
    return;
  }
  if (busy) return;
  addUserBubble(text);
  // A reply while an approval is pending is feedback to the agent (respond),
  // not a new turn.
  if (pendingInterrupt) {
    sendDecision("respond", text);
  } else {
    ws.send(JSON.stringify({ type: "prompt", text }));
    setBusy(true);
    showWorking();
  }
  promptEl.value = "";
  resize();
}

function resize() {
  promptEl.style.height = "auto";
  promptEl.style.height = Math.min(promptEl.scrollHeight, 200) + "px";
}

// --- slash commands -------------------------------------------------------

const SLASH = [
  { name: "/help", desc: "show available commands", run: showHelp },
  { name: "/clear", desc: "clear the visible conversation", run: clearThread },
  { name: "/new", desc: "start a new chat", run: newChat },
  { name: "/copy", desc: "copy the last assistant message", run: copyLast },
  { name: "/context", desc: "show how much context the last turn used", run: showContext },
  { name: "/model", hint: "[provider:model]", desc: "switch the model (keeps the session)", run: cmdModel },
  { name: "/approval-mode", hint: "[ask|workspace|auto]", desc: "set the approval policy", run: cmdApproval },
];

function addSystemNote(text, kind) {
  finalizeAssistant();
  const n = add(el("div", "sys-note" + (kind ? " " + kind : "")));
  n.textContent = text;
  return n;
}

function dispatchSlash(text) {
  const name = text.split(/\s+/)[0];
  const arg = text.slice(name.length).trim();
  const cmd = SLASH.find((c) => c.name === name);
  if (!cmd) return addSystemNote(`Unknown command ${name}. Type /help for the list.`, "warn");
  cmd.run(arg);
}

function showHelp() {
  finalizeAssistant();
  const card = add(el("div", "help-card"));
  card.appendChild(el("div", "help-title", "Commands"));
  for (const c of SLASH) {
    const row = el("div", "help-row");
    row.appendChild(el("span", "help-name", c.name + (c.hint ? " " + c.hint : "")));
    row.appendChild(el("span", "help-desc", c.desc));
    card.appendChild(row);
  }
}

function clearThread() {
  thread.innerHTML = "";
  const w = el("div", "welcome");
  w.innerHTML = "<h1>What would you like to explore?</h1>";
  thread.appendChild(w);
}

function copyLast() {
  const blocks = thread.querySelectorAll(".msg.assistant .markdown");
  const last = blocks[blocks.length - 1];
  if (!last) return addSystemNote("No assistant message to copy yet.");
  navigator.clipboard.writeText(last.textContent || "").then(
    () => addSystemNote("Copied the last reply to the clipboard."),
    () => addSystemNote("Could not access the clipboard.", "warn"),
  );
}

function showContext() {
  const tok = lastInputTokens ? formatTokens(lastInputTokens) : "—";
  addSystemNote(`Context: ~${tok} input tokens on the last turn · model ${model || "default"}.`);
}

function cmdModel(arg) {
  if (!arg) return addSystemNote(`Current model: ${model || "default"}. Usage: /model <provider:model>.`);
  model = arg;
  metaEl.innerHTML = `${model} · ${(sessionId || "").slice(0, 13)}`;
  sendCommand("set_model", arg, `Switched the model to ${arg}.`);
}

function cmdApproval(arg) {
  const modes = ["ask", "workspace", "auto"];
  if (!modes.includes(arg)) return addSystemNote(`Usage: /approval-mode ${modes.join(" | ")}.`);
  sendCommand("set_approval", arg, `Approval policy set to ${arg}.`);
}

function sendCommand(command, arg, note) {
  if (!ws) return;
  ws.send(JSON.stringify({ type: "command", command, arg }));
  if (note) addSystemNote(note);
}

// Autocomplete menu above the composer.
const slashMenu = el("div", "slash-menu");
slashMenu.hidden = true;
document.querySelector(".composer-wrap").prepend(slashMenu);
let slashItems = [];
let slashIndex = 0;

function updateSlashMenu() {
  const v = promptEl.value;
  slashItems = v.startsWith("/") && !/\s/.test(v) ? SLASH.filter((c) => c.name.startsWith(v)) : [];
  if (!slashItems.length) {
    slashMenu.hidden = true;
    return;
  }
  slashIndex = Math.min(slashIndex, slashItems.length - 1);
  slashMenu.innerHTML = "";
  slashItems.forEach((c, i) => {
    const item = el("div", "slash-item" + (i === slashIndex ? " active" : ""));
    item.appendChild(el("span", "slash-name", c.name + (c.hint ? " " + c.hint : "")));
    item.appendChild(el("span", "slash-desc", c.desc));
    item.onclick = () => completeSlash(c);
    slashMenu.appendChild(item);
  });
  slashMenu.hidden = false;
}

function completeSlash(cmd) {
  promptEl.value = cmd.name + (cmd.hint ? " " : "");
  slashMenu.hidden = true;
  promptEl.focus();
  resize();
}

promptEl.addEventListener("input", () => {
  resize();
  slashIndex = 0;
  updateSlashMenu();
});
promptEl.addEventListener("keydown", (e) => {
  if (!slashMenu.hidden && slashItems.length) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      slashIndex = (slashIndex + 1) % slashItems.length;
      return updateSlashMenu();
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      slashIndex = (slashIndex - 1 + slashItems.length) % slashItems.length;
      return updateSlashMenu();
    }
    if (e.key === "Tab") {
      e.preventDefault();
      return completeSlash(slashItems[slashIndex]);
    }
    if (e.key === "Escape") {
      slashMenu.hidden = true;
      return;
    }
  }
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
});
sendEl.onclick = () => {
  if (busy && !promptEl.value.trim().startsWith("/")) return stop();
  send();
};
document.getElementById("new-chat").onclick = newChat;
document.getElementById("canvas-close").onclick = closeCanvas;
viewsBtn.onclick = () => { if (activeView) openView(activeView); };
document.getElementById("canvas-popout").onclick = () => {
  const v = views.get(activeView);
  if (v) window.open(v.url, "_blank", "noopener");
};

// Drag the grip to resize the canvas (and so the conversation) live.
(function () {
  const grip = document.getElementById("canvas-grip");
  let dragging = false;
  grip.addEventListener("mousedown", (e) => {
    dragging = true;
    grip.classList.add("dragging");
    document.body.style.userSelect = "none";
    e.preventDefault();
  });
  window.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    const w = Math.min(Math.max(window.innerWidth - e.clientX, 320), window.innerWidth * 0.72);
    document.documentElement.style.setProperty("--canvas-w", w + "px");
  });
  window.addEventListener("mouseup", () => {
    dragging = false;
    grip.classList.remove("dragging");
    document.body.style.userSelect = "";
  });
})();

// Preview/test hook: lets a headless browser drive the renderer with scripted
// events (and set the meta line) so the UI can be screenshotted deterministically.
window.jutulDebug = {
  handle,
  addUserBubble,
  setBusy,
  showWorking,
  setMeta: (html) => (metaEl.innerHTML = html),
  openView,
  closeCanvas,
  views,
  dispatchSlash,
  setPrompt: (v) => { promptEl.value = v; updateSlashMenu(); },
};

init();
