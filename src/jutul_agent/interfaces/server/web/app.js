// jutul-agent web client. One WebSocket per session; renders the wire protocol
// (docs/server-interface.md) as a chat, with interactive views (plots, reports)
// pinned to a closable side canvas. Vanilla JS, no build step.

const thread = document.getElementById("thread");
const conversation = document.getElementById("conversation");
const promptEl = document.getElementById("prompt");
const sendEl = document.getElementById("send");
const metaEl = document.getElementById("meta");
const canvasEl = document.getElementById("canvas");
const canvasBody = document.getElementById("canvas-body");
const canvasTabs = document.getElementById("canvas-tabs");
const viewsBtn = document.getElementById("views-btn");
const viewsCount = document.getElementById("views-count");
const simLabel = document.getElementById("sim-label");

let ws = null;
let sessionId = null;
let sim = null;
let simDetails = {}; // name -> { display_name, examples } from /simulators
let model = null;
let allModels = []; // [{id, label, provider}] for the model picker
let contextWindow = null; // active model's token window, for the % indicator
let assistant = null; // { el, raw } for the in-progress assistant message
const toolCards = new Map(); // tool_call_id -> { details, body, chip }
let busy = false;
let pendingInterrupt = null; // { card } while an approval awaits a decision
let lastPrompt = ""; // last submitted prompt, for ↑-recall and retry-on-error

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
  const w = thread.querySelector(".welcome");
  if (w) w.remove();
  const stay = atBottom(); // capture BEFORE appending — afterwards we're never "at bottom"
  thread.appendChild(node);
  if (stay) scrollDown();
  return node;
}

// Run a DOM mutation and keep the view pinned to the bottom if it was already
// there. The check must happen before the mutation, since adding content makes
// the old scroll position no longer "at the bottom".
function keepingBottom(mutate) {
  const stay = atBottom();
  mutate();
  if (stay) scrollDown();
}

// Fallback suggestions when the active simulator declares no examples of its own.
const EXAMPLES = [
  "Set up a small simulation and show me the interactive result.",
  "Plot the results from the run.",
  "Give me a quick tour of what this simulator can do.",
];

function showWelcome() {
  thread.innerHTML = "";
  const w = el("div", "welcome");
  const display = (simDetails[sim] && simDetails[sim].display_name) || sim;
  const h = el("h1", null, display ? `What would you like to explore with ${display}?`
    : "What would you like to explore?");
  const p = el("p", null,
    "Ask a question or describe a task. The agent runs the simulator, writes and runs Julia, and shows results here.");
  const ex = el("div", "examples");
  const prompts = (simDetails[sim] && simDetails[sim].examples && simDetails[sim].examples.length)
    ? simDetails[sim].examples : EXAMPLES;
  for (const t of prompts) {
    const btn = el("button", "example", t);
    btn.onclick = () => {
      if (busy || !ws) return;
      promptEl.value = t;
      resize();
      send();
    };
    ex.appendChild(btn);
  }
  w.append(h, p, ex);
  thread.appendChild(w);
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
  simDetails = sims.details || {};
  // The server is bound to one simulator (this folder's); the UI does not switch.
  sim = sims.default || names[0] || "jutuldarcy";
  model = models.default || null;
  allModels = models.models || [];
  setSimLabel();
  showWelcome();
  refreshHistory();
  refreshContextWindow();
  await startSession();
}

// The active model's token window (for the % context indicator). Fetched lazily
// because the server instantiates the model to read it.
async function refreshContextWindow() {
  const data = await fetch(`/models/window?model=${encodeURIComponent(model || "")}`)
    .then((r) => r.json())
    .catch(() => ({}));
  contextWindow = data.window || null;
  if (lastInputTokens) onUsage(lastUsage || { input_tokens: lastInputTokens });
}

// Show the bound simulator as a static chip (a folder is bound to one simulator).
function setSimLabel() {
  const d = simDetails[sim];
  const name = (d && d.display_name) || sim;
  if (!name) return;
  simLabel.textContent = name;
  simLabel.hidden = false;
}

async function startSession() {
  // The first session in a folder builds its Julia environment, which can take a
  // few minutes; say so rather than looking hung.
  metaEl.textContent = `starting ${sim}… (first run builds its environment, this can take a few minutes)`;
  const resp = await fetch("/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sim }),
  }).catch(() => null);
  if (!resp || !resp.ok) {
    metaEl.textContent = "could not start a session";
    return;
  }
  sessionId = (await resp.json()).session_id;
  metaEl.textContent = `${model || "no model"} · ${sessionId.slice(0, 13)}`;
  openSocket();
}

function openSocket() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/sessions/${sessionId}/stream`);
  ws.onmessage = (e) => handle(JSON.parse(e.data));
  ws.onclose = () => setBusy(false);
  setWarming(true); // the kernel warms in the background until the first turn lands
}

// The "warming up Julia" hint: the kernel loads the simulator + plotting stack on
// a fresh/resumed session, so the first run can be slow; clear it once a turn lands.
function setWarming(on) {
  const w = document.getElementById("warming");
  if (w) w.hidden = !on;
}

// Reopen an earlier session: resume it server-side (history is restored, the
// Julia REPL restarts) and replay the prior conversation into the thread.
async function resumeSession(id, sessSim) {
  if (ws) ws.close();
  thread.innerHTML = "";
  toolCards.clear();
  assistant = null;
  pendingInterrupt = null;
  promptEl.placeholder = "Message jutul-agent…";
  resetCanvas();
  if (sessSim) {
    sim = sessSim;
    setSimLabel();
  }
  metaEl.textContent = `resuming ${sim}…`;
  const resp = await fetch(`/sessions/${id}/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sim, model }),
  }).catch(() => null);
  if (!resp || !resp.ok) {
    metaEl.textContent = "could not resume";
    addSystemNote("Could not resume that session.", "warn");
    return;
  }
  sessionId = (await resp.json()).session_id;
  metaEl.textContent = `${model || "no model"} · ${sessionId.slice(0, 13)}`;
  openSocket();
  const data = await fetch(`/sessions/${id}/messages`).then((r) => r.json()).catch(() => ({}));
  replaySession(data.messages || []);
  addSystemNote(
    "Resumed this session. The chat is restored, but the Julia REPL restarted — " +
      "earlier files and artifacts are intact; re-run setup to rebuild in-memory state.",
  );
  refreshHistory(); // move the current highlight to the reopened session
}

// Reconstruct a resumed session inline from the recorded wire stream so it looks
// like it did when the user left: user/assistant text, collapsed reasoning, tool
// cards (with their output), and views. The same renderers as the live socket are
// reused, so a replayed turn is indistinguishable from a live one.
function replaySession(msgs) {
  for (const m of msgs) {
    if (m.type === "user") addUserBubble(m.text);
    else if (m.type === "assistant") addAssistantText(m.text);
    else if (m.type === "reasoning") addReasoningBlock(m.text);
    else if (m.type === "tool") onTool(m);
    else if (m.type === "viz") onViz(m);
    else if (m.type === "artifact") onArtifact(m);
  }
  finalizeAssistant();
  toolCards.clear(); // replayed cards are complete; a new turn starts its own
  addCopyButtons(thread);
  scrollDown();
}

// A finished reasoning block, collapsed like one the live stream leaves at turn end.
function addReasoningBlock(text) {
  finalizeAssistant();
  const block = el("details", "block reasoning");
  block.open = false;
  const sum = el("summary");
  sum.appendChild(el("span", "tool-name", "Reasoning"));
  const body = el("div", "body");
  body.textContent = text;
  block.append(sum, body);
  add(block);
}

function addAssistantText(text) {
  finalizeAssistant();
  const wrap = add(el("div", "msg assistant"));
  const md = el("div", "markdown");
  md.innerHTML = window.renderMarkdown(text);
  wrap.appendChild(md);
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
  showWelcome();
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
  setWarming(false); // any message means the kernel responded, so it's warm
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
    case "notice": return onNotice(msg);
    case "error": return onError(msg.message);
  }
}

// A server-originated system note: the result of a command (/compact, /add-dir).
function onNotice(msg) {
  setBusy(false); // a command that set the working state (e.g. /compact) finished
  addSystemNote(msg.text || "");
}

// A tool drove the application's interface. The action vocabulary belongs to the
// host app (see docs/server-interface.md); a real app applies it to its own
// controls. This reference UI has none, so it surfaces the action transparently
// — both honest and useful when building/​debugging a host app. Host apps can
// override window.jutulDebug.onUi to apply actions to their interface.
function onUi(msg) {
  if (window.onJutulUi && window.onJutulUi(msg) === true) return; // host-app hook
  // Internal signal: the session was renamed (e.g. an LLM title landed after the
  // first turn). Refresh the sidebar quietly rather than surfacing it as an action.
  if (msg.action === "history_changed") { refreshHistory(); return; }
  finalizeAssistant();
  const note = add(el("div", "ui-note"));
  note.appendChild(el("span", "ui-gear", "⚙"));
  note.appendChild(el("span", "ui-action", msg.action || "ui"));
  const payload = msg.payload && Object.keys(msg.payload).length ? JSON.stringify(msg.payload) : "";
  if (payload) note.appendChild(el("span", "ui-payload", payload));
}

function ensureAssistant() {
  if (!assistant) {
    finalizeReasoning(); // assistant prose starts a new segment after any reasoning
    const wrap = add(el("div", "msg assistant"));
    const md = el("div", "markdown");
    wrap.appendChild(md);
    assistant = { el: md, raw: "" };
  }
  return assistant;
}

function onText(text) {
  const a = ensureAssistant();
  keepingBottom(() => {
    a.raw += text;
    a.el.innerHTML = window.renderMarkdown(a.raw);
  });
}

function onReasoning(text) {
  let block = thread.querySelector(".reasoning[data-live]");
  if (!block) {
    block = el("details", "block reasoning");
    block.open = true; // visible while streaming; collapsed when the segment ends
    block.setAttribute("data-live", "1");
    const sum = el("summary");
    sum.appendChild(el("span", "tool-name", "Reasoning"));
    sum.appendChild(el("span", "tool-preview")); // a snippet, so the collapsed block still hints its content
    const body = el("div", "body");
    block.append(sum, body);
    add(block);
  }
  const body = block.querySelector(".body");
  keepingBottom(() => {
    body.textContent += text;
    block.querySelector(".tool-preview").textContent = reasoningSnippet(body.textContent);
  });
}

// The first non-empty reasoning line, markdown-stripped and truncated — shown on
// the summary so a collapsed reasoning block still says what it was about.
function reasoningSnippet(text) {
  const first = text.split("\n").map((l) => l.trim()).find((l) => l) || "";
  const clean = first.replace(/[*#`>_]/g, "").trim();
  return clean.length > 90 ? clean.slice(0, 90).replace(/\s+\S*$/, "") + "…" : clean;
}

// End the current (live) reasoning block so the next thought starts a fresh one —
// the terminal UI shows separate reasoning between tool calls, not one long block.
function finalizeReasoning() {
  const live = thread.querySelector(".reasoning[data-live]");
  if (live) {
    live.removeAttribute("data-live");
    live.open = false;
  }
}

// Args worth previewing on the collapsed summary line, in priority order.
const PREVIEW_KEYS = ["title", "caption", "code", "command", "file_path", "path", "pattern", "query", "slot"];

function argPreview(args, name) {
  if (!args) return "";
  if (name === "write_todos" && Array.isArray(args.todos)) {
    const active = args.todos.find((t) => t.status === "in_progress");
    return active ? active.content : `${args.todos.length} item${args.todos.length === 1 ? "" : "s"}`;
  }
  for (const k of PREVIEW_KEYS) {
    if (args[k]) return String(args[k]).split("\n").find((l) => l.trim()) || "";
  }
  const first = Object.values(args)[0];
  if (first == null || typeof first === "object") return "";
  return String(first).split("\n")[0];
}

const JULIA_KEYWORDS = new Set([
  "function", "end", "if", "else", "elseif", "for", "while", "do", "return", "break",
  "continue", "using", "import", "export", "struct", "mutable", "abstract", "primitive",
  "const", "global", "local", "let", "begin", "module", "macro", "quote", "try", "catch",
  "finally", "where", "in", "isa", "true", "false", "nothing", "missing",
]);

function escapeHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// A small, dependency-free Julia highlighter for code shown in tool cards. It
// tokenizes comments/strings/macros/numbers/words so nothing is highlighted
// inside a string or comment; good enough for display (not a real parser).
function highlightJulia(code) {
  const re =
    /(#=[\s\S]*?=#|#[^\n]*)|("""[\s\S]*?"""|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])')|(@[A-Za-z_]\w*)|(\b\d+\.?\d*(?:[eE][+-]?\d+)?\b)|([A-Za-z_]\w*!?)/g;
  let out = "";
  let last = 0;
  let m;
  while ((m = re.exec(code))) {
    out += escapeHtml(code.slice(last, m.index));
    last = re.lastIndex;
    if (m[1]) out += `<span class="jl-com">${escapeHtml(m[1])}</span>`;
    else if (m[2]) out += `<span class="jl-str">${escapeHtml(m[2])}</span>`;
    else if (m[3]) out += `<span class="jl-mac">${escapeHtml(m[3])}</span>`;
    else if (m[4]) out += `<span class="jl-num">${escapeHtml(m[4])}</span>`;
    else if (JULIA_KEYWORDS.has(m[5])) out += `<span class="jl-kw">${m[5]}</span>`;
    else if (/^[A-Z]/.test(m[5])) out += `<span class="jl-type">${escapeHtml(m[5])}</span>`;
    else out += escapeHtml(m[5]);
  }
  return out + escapeHtml(code.slice(last));
}

// A <pre><code> block; Julia code is syntax-highlighted, anything else is plain.
function codeBlock(text, { julia = false } = {}) {
  const pre = el("pre", "tool-code");
  const code = el("code");
  if (julia) code.innerHTML = highlightJulia(text);
  else code.textContent = text;
  pre.appendChild(code);
  return pre;
}

// Per-tool card policy. Unlisted tools default to: open, with the args/code body
// and the raw text output shown. Listed tools get a compact, web-native rendering.
//   collapsed  – start collapsed (a quiet, read-only step)
//   body       – "none" (summary only) or "path" (just the file path)
//   rawOutput  – false: don't dump the text result (it's noise, or lives in the canvas)
//   note(text) – a short result summary appended to the summary line ("42 lines")
const TOOL_POLICY = {
  write_todos: { rawOutput: false }, // the checklist is the body
  read_file: { collapsed: true, body: "path", rawOutput: false, note: (c) => unitNote(c, "line") },
  // Search: collapsed with a match count, but the matches themselves show on expand.
  grep: { collapsed: true, body: "none", note: (c) => unitNote(c, "match", "matches") },
  glob: { collapsed: true, body: "none", note: (c) => unitNote(c, "file") },
  ls: { collapsed: true, body: "none", rawOutput: false, note: listingNote }, // directory listing
  plot_julia: { collapsed: true, rawOutput: false }, // the figure is pinned in the canvas
  write_report: { collapsed: true, body: "none", rawOutput: false }, // the report is in the canvas
  record_attempt: { rawOutput: false }, // a structured body (rationale + metrics) below
};

// Parse a value that may be a dict or a JSON string into an object, else null.
function asObject(v) {
  if (v && typeof v === "object" && !Array.isArray(v)) return v;
  if (typeof v === "string") {
    try {
      const o = JSON.parse(v);
      return o && typeof o === "object" && !Array.isArray(o) ? o : null;
    } catch {
      return null;
    }
  }
  return null;
}

// Round long floats to a few significant digits so a metrics grid stays readable.
function fmtNum(v) {
  return typeof v === "number" && Number.isFinite(v) ? String(Number(v.toPrecision(4))) : String(v);
}

// A compact two-column key/value grid (metrics, changed parameters).
function renderKV(obj, label) {
  const wrap = el("div", "tool-kv");
  if (label) wrap.appendChild(el("div", "kv-label", label));
  const grid = el("div", "kv-grid");
  for (const [k, v] of Object.entries(obj)) {
    grid.appendChild(el("span", "kv-key", k));
    grid.appendChild(el("span", "kv-val", Array.isArray(v) ? v.map(fmtNum).join(", ") : fmtNum(v)));
  }
  wrap.appendChild(grid);
  return wrap;
}

// ls returns a single-line Python list repr (['a/', 'b/', …]); count the quoted
// entries rather than the (one) line.
function listingNote(content) {
  const n = (String(content || "").match(/'/g) || []).length >> 1;
  return `${n} ${n === 1 ? "entry" : "entries"}`;
}

function unitNote(content, singular, plural) {
  const n = String(content || "").split("\n").filter((l) => l.trim()).length;
  return `${n} ${n === 1 ? singular : plural || singular + "s"}`;
}

// Render a tool card's body per tool so each reads well: a plan as a checklist,
// an edit as a diff, code highlighted, and a read/search as just what it queried.
function fillToolBody(body, msg, policy) {
  const name = msg.name;
  const args = msg.args || {};
  if (policy.body === "none") return;
  if (policy.body === "path") {
    const p = args.file_path || args.path;
    if (p) body.appendChild(el("div", "tool-path", String(p)));
    return;
  }
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
    body.appendChild(codeBlock(String(args.content), { julia: /\.jl$/.test(args.file_path || "") }));
    return;
  }
  if (name === "record_attempt") {
    if (args.rationale) body.appendChild(el("div", "attempt-rationale", String(args.rationale)));
    const metrics = asObject(args.metrics);
    const params = asObject(args.parameters_changed);
    if (params) body.appendChild(renderKV(params, "changed"));
    if (metrics) body.appendChild(renderKV(metrics, "metrics"));
    if (args.notes) body.appendChild(el("div", "attempt-notes", String(args.notes)));
    return;
  }
  if (args.code != null) {
    body.appendChild(codeBlock(String(args.code), { julia: true }));
    return;
  }
  if (args.command != null) {
    body.appendChild(codeBlock(String(args.command))); // shell, not Julia
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
  const policy = TOOL_POLICY[msg.name] || {};
  if (!card) {
    finalizeAssistant();
    finalizeReasoning();
    const details = el("details", "block tool");
    details.open = !policy.collapsed; // quiet read-only steps start collapsed
    const sum = el("summary");
    sum.appendChild(el("span", "tool-name", msg.label || msg.name));
    const preview = el("span", "tool-preview", argPreview(msg.args, msg.name));
    sum.appendChild(preview);
    const chip = el("span", "chip-status running");
    chip.innerHTML = '<span class="spinner"></span>';
    sum.appendChild(chip);
    const body = el("div", "body");
    fillToolBody(body, msg, policy);
    addCopyButtons(body);
    const out = el("pre", "tool-output");
    out.hidden = true;
    body.appendChild(out);
    details.append(sum, body);
    add(details);
    card = { details, body, chip, out, preview, raw: "" };
    toolCards.set(msg.tool_call_id, card);
  }
  if (msg.event === "delta") {
    // Live kernel output (run_julia/execute): append and re-render so the user
    // watches it stream, instead of waiting for the whole result at the end.
    if (msg.content && policy.rawOutput !== false) {
      card.raw += msg.content;
      card.streamed = true;
      renderOutput(card);
    }
    return;
  }
  if (msg.event === "finished") {
    card.chip.textContent = "done";
    card.chip.className = "chip-status";
    if (policy.note && msg.content) appendNote(card, policy.note(msg.content));
    if (msg.content && policy.rawOutput !== false) {
      if (!card.streamed) {
        setOutput(card, msg.content); // non-streaming tool: the result is all we have
      } else {
        // The deltas carry the raw REPL output *with* ANSI coloring; the final
        // result is the cleaned (decolored) capture and also appends the value repr
        // and any stderr, which are NOT streamed. Keep the colored streamed output
        // and add just that trailing part, so the card stays colored yet complete.
        const tail = tailBeyond(stripAnsi(applyCarriageReturns(card.raw)), String(msg.content));
        if (tail) {
          card.raw += (card.raw.endsWith("\n") ? "" : "\n") + tail;
          renderOutput(card);
        }
      }
    }
  } else if (msg.event === "error") {
    card.chip.textContent = "error";
    card.chip.className = "chip-status error";
    if (msg.content) setOutput(card, msg.content); // always surface errors
  }
}

// Append a short result summary to a card's preview line (e.g. "model.jl · 42 lines").
function appendNote(card, note) {
  if (!card.preview) return;
  const base = card.preview.textContent;
  card.preview.textContent = base ? `${base} · ${note}` : note;
}

function summarizeArgs(args) {
  return Object.entries(args)
    .map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join("\n");
}

// Keep tool output compact: cap very long results (a progress-bar spam or a
// giant dump shouldn't flood the chat). The box is also height-limited in CSS.
function clampOutput(text) {
  const lines = text.split("\n");
  if (lines.length > 60) {
    const hidden = lines.length - 52;
    return `${lines.slice(0, 40).join("\n")}\n  … ${hidden} more lines …\n${lines.slice(-12).join("\n")}`;
  }
  return text.length > 6000 ? text.slice(0, 6000) + "\n  … truncated …" : text;
}

// Kernel output is raw terminal text. Apply each line's last carriage return
// (progress bars overwrite their line with \r) so a <pre> shows the final state.
function applyCarriageReturns(raw) {
  return String(raw)
    .split("\n")
    .map((line) => {
      const cr = line.lastIndexOf("\r");
      return cr >= 0 ? line.slice(cr + 1) : line;
    })
    .join("\n");
}

// Standard ANSI SGR foreground colors, tuned to read on the output background.
const ANSI_FG = {
  30: "#3b4252", 31: "#c0392b", 32: "#2f9e44", 33: "#b8860b", 34: "#1f6feb",
  35: "#a626a4", 36: "#0b7285", 37: "#9aa0a8", 90: "#7a828e", 91: "#e05561",
  92: "#37b24d", 93: "#d6a200", 94: "#4098ff", 95: "#c678dd", 96: "#56b6c2", 97: "#cfd3da",
};

// Render ANSI color codes as spans so run_julia output looks like a Julia REPL
// (errors red, types colored, …) instead of stripped or as escape soup. Text is
// HTML-escaped; unbalanced spans (e.g. across a clamp) are closed at the end.
function ansiToHtml(text) {
  // Drop OSC (window-title) sequences and any CSI that isn't an SGR (color) code:
  // cursor moves and line clears from progress bars would otherwise render as
  // literal "␛[A" junk in the output.
  text = text.replace(/\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)/g, "");
  const re = /\x1b\[([0-9;?]*)([@-~])/g;
  let html = "";
  let last = 0;
  let open = 0;
  let m;
  while ((m = re.exec(text))) {
    html += escapeHtml(text.slice(last, m.index));
    last = re.lastIndex;
    if (m[2] !== "m") continue; // non-SGR CSI (cursor move, clear): drop it
    const codes = m[1].split(";").filter((s) => s !== "").map(Number);
    if (codes.length === 0 || codes.includes(0)) {
      html += "</span>".repeat(open);
      open = 0;
      continue;
    }
    const styles = [];
    for (const c of codes) {
      if (c === 1) styles.push("font-weight:600");
      else if (ANSI_FG[c]) styles.push("color:" + ANSI_FG[c]);
    }
    if (styles.length) {
      html += `<span style="${styles.join(";")}">`;
      open++;
    }
  }
  html += escapeHtml(text.slice(last)) + "</span>".repeat(open);
  return html;
}

// Strip every ANSI escape (colors, cursor moves, OSC) — used to compare the raw
// streamed output against the kernel's cleaned final result.
function stripAnsi(s) {
  return String(s)
    .replace(/\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)/g, "")
    .replace(/\x1b\[[0-9;?]*[@-~]/g, "");
}

// The part of the cleaned final result `full` that comes after the (de-ANSI'd)
// streamed text `shown` — i.e. the value repr / stderr the kernel appends only to
// the final result, never to the live stream. "" when the two don't align, in
// which case the streamed output already stands on its own.
function tailBeyond(shown, full) {
  const head = shown.replace(/\s+$/, "");
  if (head && full.length > head.length && full.startsWith(head)) {
    return full.slice(head.length).replace(/^\n+/, "");
  }
  return "";
}

function renderOutput(card) {
  const text = clampOutput(applyCarriageReturns(card.raw));
  // Tail the output box to its newest line (like a terminal), unless the user has
  // scrolled up inside it to read earlier output.
  const box = card.out;
  const wasTailing = box.scrollHeight - box.scrollTop - box.clientHeight < 24;
  keepingBottom(() => {
    box.hidden = false;
    box.innerHTML = ansiToHtml(text);
    addCopyButtons(box.parentElement);
  });
  if (wasTailing) box.scrollTop = box.scrollHeight;
}

function setOutput(card, content) {
  card.raw = String(content);
  renderOutput(card);
}

// Add a hover "Copy" button to code blocks (idempotent via data-copy).
function addCopyButtons(scope) {
  if (!scope) return;
  for (const pre of scope.querySelectorAll("pre:not([data-copy])")) {
    pre.setAttribute("data-copy", "1");
    pre.style.position = "relative";
    const btn = el("button", "copy-btn", "Copy");
    btn.onclick = (e) => {
      e.stopPropagation();
      const code = pre.querySelector("code") || pre;
      navigator.clipboard.writeText(code.textContent || "").then(() => {
        btn.textContent = "Copied";
        setTimeout(() => (btn.textContent = "Copy"), 1200);
      });
    };
    pre.appendChild(btn);
  }
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
  // "Always allow" (when the action's category permits it): approve now and
  // auto-approve matching actions for the rest of the session, like the TUI.
  if (msg.allowed_decisions.includes("approve") && msg.allowlist && msg.allowlist.length) {
    const label = msg.allowlist.length === 1 && msg.allowlist[0] === "file_edits"
      ? "always allow edits"
      : "always allow";
    const btn = el("button", "btn", label);
    btn.title = "Approve, and don't ask again for this kind of action this session";
    btn.onclick = () => sendDecision("always_allow");
    buttons.appendChild(btn);
  }
  card.appendChild(buttons);
  if (msg.allowed_decisions.includes("respond")) {
    card.appendChild(el("div", "approval-hint", "…or type a reply below to send feedback."));
    promptEl.placeholder = "Reply to the agent…";
  }
  // The turn is paused on the user, so free the composer (it is not "working").
  setBusy(false);
  // An approval needs the user's attention, so bring the card into view even if
  // they had scrolled up — otherwise it can land below the fold.
  requestAnimationFrame(() => card.scrollIntoView({ behavior: "smooth", block: "center" }));
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
  addCopyButtons(thread); // code blocks in the now-final assistant text
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
  setWarming(false); // a turn completed, so the kernel is warm
  refreshHistory(); // the session now has a title (and may be newly added)
  notifyDone("The agent finished your turn.");
}

function notifyDone(body) {
  // Ping the user only when they've tabbed away from a (possibly long) turn.
  if (document.hidden && "Notification" in window && Notification.permission === "granted") {
    try {
      new Notification("jutul-agent", { body });
    } catch {
      /* notifications are best-effort */
    }
  }
}

function onError(message) {
  finalizeAssistant();
  const card = add(el("div", "error-card"));
  card.appendChild(el("div", "err-msg", message));
  if (lastPrompt && !pendingInterrupt) {
    const retry = el("button", "btn", "Retry");
    retry.onclick = () => {
      card.remove();
      addUserBubble(lastPrompt);
      ws.send(JSON.stringify({ type: "prompt", text: lastPrompt }));
      setBusy(true);
      showWorking();
    };
    card.appendChild(retry);
  }
  setBusy(false);
}

let lastInputTokens = 0;
let lastUsage = null;
function onUsage(msg) {
  // Show the latest turn's input size as context used — a percentage of the
  // model's window when known, else the absolute token count.
  lastInputTokens = msg.input_tokens || lastInputTokens;
  lastUsage = msg.input_tokens ? msg : lastUsage;
  const usage = document.getElementById("usage");
  if (usage && lastInputTokens) {
    usage.textContent = contextWindow
      ? `${Math.round((lastInputTokens / contextWindow) * 100)}% ctx`
      : `${formatTokens(lastInputTokens)} ctx`;
    usage.title = `${formatTokens(lastInputTokens)}${contextWindow ? " / " + formatTokens(contextWindow) : ""} context tokens`;
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
    lastPrompt = text;
    pushHistory(text);
    requestNotifyPermission();
    ws.send(JSON.stringify({ type: "prompt", text }));
    setBusy(true);
    showWorking();
  }
  promptEl.value = "";
  resize();
}

// Submitted-prompt history, navigable with ↑/↓ like a shell.
const promptHistory = [];
let historyPos = -1; // -1 = the live draft; 0..n-1 = a past prompt
let historyDraft = "";

function pushHistory(text) {
  if (promptHistory[promptHistory.length - 1] !== text) promptHistory.push(text);
  historyPos = -1;
}

function recallHistory(dir) {
  if (!promptHistory.length) return false;
  if (historyPos === -1) {
    if (dir > 0) return false; // already at the draft; nothing newer
    historyDraft = promptEl.value;
    historyPos = promptHistory.length - 1;
  } else {
    historyPos += dir < 0 ? -1 : 1;
  }
  if (historyPos < 0) historyPos = 0; // clamp at the oldest
  if (historyPos >= promptHistory.length) {
    historyPos = -1;
    promptEl.value = historyDraft;
  } else {
    promptEl.value = promptHistory[historyPos];
  }
  resize();
  const end = promptEl.value.length;
  promptEl.setSelectionRange(end, end);
  return true;
}

// Ask once, lazily, so a finished long turn can ping you when the tab is hidden.
let notifyAsked = false;
function requestNotifyPermission() {
  if (notifyAsked || !("Notification" in window) || Notification.permission !== "default") return;
  notifyAsked = true;
  Notification.requestPermission().catch(() => {});
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
  { name: "/transcript", hint: "[md]", desc: "download the conversation to share", run: cmdTranscript },
  { name: "/memory", desc: "view the workspace memory", run: cmdMemory },
  { name: "/compact", desc: "summarize older turns to free context", run: cmdCompact },
  { name: "/add-dir", hint: "<path>", desc: "give the agent another folder", run: cmdAddDir },
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

// Fetch the full context panel (rendered server-side, identical to the TUI) and
// show it as a markdown card — the category breakdown, bar, and auto-compact
// buffer the client can't compute on its own.
async function showContext() {
  if (!sessionId) return addSystemNote("No active session.");
  const data = await fetch(`/sessions/${sessionId}/context`)
    .then((r) => r.json())
    .catch(() => ({}));
  if (!data.markdown) return addSystemNote("Could not read context usage.", "warn");
  finalizeAssistant();
  const card = add(el("div", "context-card markdown"));
  card.innerHTML = window.renderMarkdown(data.markdown);
  scrollDown();
}

function cmdModel(arg) {
  if (arg) {
    model = arg;
    metaEl.textContent = `${model} · ${(sessionId || "").slice(0, 13)}`;
    sendCommand("set_model", arg, `Switched the model to ${arg}.`);
    refreshContextWindow();
    return;
  }
  showModelMenu();
}

// Floating picker (like the slash menu) listing the selectable models, grouped by
// provider; click one — or arrow to it and press Enter — to switch the session.
let modelItems = []; // { id, el } in display order, for ↑/↓ navigation
let modelIndex = 0;
function showModelMenu() {
  if (!allModels.length) {
    return addSystemNote("No selectable models found. Usage: /model <provider:model>.");
  }
  modelMenu.innerHTML = "";
  modelMenu.appendChild(el("div", "slash-head", "Switch model"));
  modelItems = [];
  let provider = null;
  allModels.forEach((m) => {
    if (m.provider !== provider) {
      modelMenu.appendChild(el("div", "model-provider", m.provider));
      provider = m.provider;
    }
    const item = el("div", "slash-item");
    item.appendChild(el("span", "slash-name", m.label));
    item.appendChild(el("span", "slash-desc", m.id));
    item.onclick = () => chooseModel(m.id);
    modelMenu.appendChild(item);
    modelItems.push({ id: m.id, el: item });
  });
  // Start on the active model so ↑/↓ moves from where you are.
  modelIndex = Math.max(0, modelItems.findIndex((it) => it.id === model));
  highlightModel();
  modelMenu.hidden = false;
  promptEl.focus(); // keep keystrokes on the composer so ↑/↓/Enter drive the menu
}

function highlightModel() {
  modelItems.forEach((it, i) => {
    const on = i === modelIndex;
    it.el.classList.toggle("active", on);
    if (on) it.el.scrollIntoView({ block: "nearest" });
  });
}

function chooseModel(id) {
  modelMenu.hidden = true;
  cmdModel(id);
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

// Pin a server-rendered document (transcript, memory) into the canvas as a view.
function pinDoc(url, title, slot) {
  onViz({ url, title, kind: "report", slot });
}

function cmdTranscript(arg) {
  if (!sessionId) return addSystemNote("No active session.");
  const fmt = arg === "md" || arg === "markdown" ? "md" : "html";
  const a = document.createElement("a");
  a.href = `/sessions/${sessionId}/transcript?format=${fmt}`;
  a.download = `transcript.${fmt}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  addSystemNote(`Downloading the transcript (${fmt}) to share.`);
}

function cmdMemory() {
  if (!sessionId) return addSystemNote("No active session.");
  pinDoc(`/sessions/${sessionId}/memory`, "Workspace memory", "memory");
}

function cmdCompact() {
  if (busy) return addSystemNote("Finish the current turn before compacting.");
  addSystemNote("Compacting the conversation…");
  setBusy(true);
  showWorking();
  sendCommand("compact", "");
}

function cmdAddDir(arg) {
  sendCommand("add_dir", arg);
}

// Autocomplete menu above the composer.
const slashMenu = el("div", "slash-menu");
slashMenu.hidden = true;
document.querySelector(".composer-wrap").prepend(slashMenu);

// The model picker (shown by `/model` with no argument); dismissed on outside click.
const modelMenu = el("div", "slash-menu model-menu");
modelMenu.hidden = true;
document.querySelector(".composer-wrap").prepend(modelMenu);
document.addEventListener("click", (e) => {
  if (!modelMenu.hidden && !modelMenu.contains(e.target)) modelMenu.hidden = true;
});

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
  if (e.key === "Escape") {
    if (!modelMenu.hidden) return (modelMenu.hidden = true);
    if (!slashMenu.hidden) return (slashMenu.hidden = true);
    if (busy) return stop(); // cancel a running turn
  }
  // The model picker grabs the arrow keys and Enter while it's open.
  if (!modelMenu.hidden && modelItems.length) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      modelIndex = (modelIndex + 1) % modelItems.length;
      return highlightModel();
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      modelIndex = (modelIndex - 1 + modelItems.length) % modelItems.length;
      return highlightModel();
    }
    if (e.key === "Enter" || e.key === "Tab") {
      e.preventDefault();
      return chooseModel(modelItems[modelIndex].id);
    }
  }
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
    if (e.key === "Tab" || e.key === "Enter") {
      // Both complete the highlighted command; the next Enter sends/dispatches it.
      e.preventDefault();
      return completeSlash(slashItems[slashIndex]);
    }
  } else if (e.key === "ArrowUp" && atComposerStart()) {
    e.preventDefault(); // walk back through past prompts
    if (recallHistory(-1)) return;
  } else if (e.key === "ArrowDown" && historyPos !== -1) {
    e.preventDefault(); // walk forward toward the draft
    if (recallHistory(1)) return;
  }
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
});

// The caret is at the very start (so ↑ should recall history, not move a line up).
function atComposerStart() {
  return promptEl.selectionStart === 0 && promptEl.selectionEnd === 0;
}
sendEl.onclick = () => {
  if (busy && !promptEl.value.trim().startsWith("/")) return stop();
  send();
};
document.getElementById("new-chat").onclick = newChat;

// --- file upload (attach button + drag-drop) ------------------------------

const attachBtn = document.getElementById("attach");
const fileInput = document.getElementById("file-input");
attachBtn.onclick = () => fileInput.click();
fileInput.onchange = () => {
  for (const f of fileInput.files) uploadFile(f);
  fileInput.value = "";
};

async function uploadFile(file) {
  if (!sessionId) return addSystemNote("Start a session before uploading.", "warn");
  const fd = new FormData();
  fd.append("file", file);
  const note = addSystemNote(`Uploading ${file.name}…`);
  try {
    const resp = await fetch(`/sessions/${sessionId}/upload`, { method: "POST", body: fd });
    if (!resp.ok) throw new Error(await resp.text());
    const { path } = await resp.json();
    note.textContent = `Uploaded ${path} — referenced below; ask the agent to use it.`;
    promptEl.value += (promptEl.value && !/\s$/.test(promptEl.value) ? " " : "") + path + " ";
    resize();
    promptEl.focus();
  } catch (e) {
    note.textContent = `Upload failed: ${e}`;
    note.classList.add("warn");
  }
}

// Drag a file anywhere over the conversation pane to upload it.
const dropPane = document.querySelector(".app");
let dragDepth = 0;
dropPane.addEventListener("dragenter", (e) => {
  if (e.dataTransfer && [...e.dataTransfer.types].includes("Files")) {
    dragDepth++;
    dropPane.classList.add("dropping");
  }
});
dropPane.addEventListener("dragover", (e) => {
  if (dropPane.classList.contains("dropping")) e.preventDefault();
});
dropPane.addEventListener("dragleave", () => {
  if (--dragDepth <= 0) {
    dragDepth = 0;
    dropPane.classList.remove("dropping");
  }
});
dropPane.addEventListener("drop", (e) => {
  e.preventDefault();
  dragDepth = 0;
  dropPane.classList.remove("dropping");
  for (const f of e.dataTransfer.files) uploadFile(f);
});

// --- session history (left sidebar) ---------------------------------------

const sidebar = document.getElementById("sidebar");
const sidebarToggle = document.getElementById("sidebar-toggle");
const historyList = document.getElementById("history-list");

// Restore the collapsed state; default open on a wide screen, closed on a narrow one.
if (localStorage.getItem("ja_sidebar") === "collapsed" ||
    (localStorage.getItem("ja_sidebar") === null && window.innerWidth <= 760)) {
  sidebar.classList.add("collapsed");
}
sidebarToggle.onclick = () => {
  const collapsed = sidebar.classList.toggle("collapsed");
  localStorage.setItem("ja_sidebar", collapsed ? "collapsed" : "open");
};

// Pull the resumable sessions and paint the list. Cheap, so it runs on load and
// whenever the set or a title may have changed (new chat, resume, turn end, rename).
async function refreshHistory() {
  const data = await fetch("/sessions/history").then((r) => r.json()).catch(() => ({}));
  renderHistory(data.sessions || []);
}

function renderHistory(sessions) {
  historyList.innerHTML = "";
  // A session earns a title from its first prompt; ones without are empty/abandoned
  // new-chats, so leave them out to keep the list to real conversations.
  sessions = sessions.filter((s) => s.title);
  if (!sessions.length) {
    historyList.appendChild(el("div", "history-empty", "No past sessions yet."));
    return;
  }
  for (const s of sessions) {
    const item = el("button", "history-item" + (s.id === sessionId ? " current" : ""));
    item.dataset.id = s.id;
    item.appendChild(el("div", "h-title", s.title || "Untitled session"));
    item.title = s.title || "Untitled session";
    item.appendChild(el("div", "h-meta", `${s.sim} · ${timeAgo(s.started)}`));
    item.onclick = () => {
      if (s.id !== sessionId) resumeSession(s.id, s.sim);
    };
    historyList.appendChild(item);
  }
}

function timeAgo(iso) {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  if (s < 7 * 86400) return `${Math.floor(s / 86400)}d ago`;
  return new Date(iso).toLocaleDateString();
}

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
    // Store the width as a fraction of the viewport, not pixels, so the split
    // stays proportional when the window is resized or moved to another screen.
    const frac = Math.min(Math.max((window.innerWidth - e.clientX) / window.innerWidth, 0.3), 0.62);
    document.documentElement.style.setProperty("--canvas-w", (frac * 100).toFixed(1) + "%");
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
  replaySession,
  refreshHistory,
  setPrompt: (v) => { promptEl.value = v; updateSlashMenu(); },
};

init();
