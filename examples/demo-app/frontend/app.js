// Minimal jutul-agent web client. It speaks the documented wire protocol over
// one WebSocket per session: see docs/server-interface.md. Replace it with a real
// front end (React, Svelte, MapLibre, ...) as needed; the protocol is the contract.

const log = document.getElementById("log");
const promptInput = document.getElementById("prompt");
const sendButton = document.getElementById("send");
const viz = document.getElementById("viz");
const slider = document.getElementById("p");
const pval = document.getElementById("pval");

let ws = null;
let sessionId = null;
let assistantEl = null; // the in-progress assistant bubble

function bubble(cls, text) {
  const el = document.createElement("div");
  el.className = "msg " + cls;
  el.textContent = text; // textContent, never innerHTML: model output is untrusted
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
  return el;
}

async function start() {
  const resp = await fetch("/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sim: "demo" }),
  });
  sessionId = (await resp.json()).session_id;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/sessions/${sessionId}/stream`);
  ws.onmessage = (event) => handle(JSON.parse(event.data));
  ws.onclose = () => bubble("tool", "[connection closed]");
}

function handle(msg) {
  switch (msg.type) {
    case "text":
      if (!assistantEl) assistantEl = bubble("assistant", "");
      assistantEl.textContent += msg.text;
      log.scrollTop = log.scrollHeight;
      break;
    case "reasoning":
      bubble("reasoning", msg.text);
      break;
    case "tool":
      if (msg.event === "started" || msg.event === "requested")
        bubble("tool", `→ ${msg.label || msg.name}`);
      else if (msg.event === "error") bubble("tool", `✗ ${msg.label || msg.name}: ${msg.content}`);
      break;
    case "viz":
      viz.src = msg.url; // self-contained interactive HTML, same origin
      break;
    case "artifact":
      bubble("tool", `[artifact] ${msg.url}`);
      break;
    case "interrupt":
      showApproval(msg);
      break;
    case "ui":
      if (msg.action === "set_param" && msg.payload && typeof msg.payload.p === "number") {
        slider.value = msg.payload.p;
        pval.textContent = msg.payload.p;
      }
      break;
    case "turn_end":
      assistantEl = null;
      setBusy(false);
      break;
    case "error":
      bubble("tool", `[error] ${msg.message}`);
      setBusy(false);
      break;
  }
}

function showApproval(msg) {
  const el = bubble("interrupt", `Approval needed: ${msg.actions.map((a) => a.label || a.name).join(", ")}`);
  for (const decision of msg.allowed_decisions) {
    const btn = document.createElement("button");
    btn.textContent = decision;
    btn.onclick = () => {
      ws.send(JSON.stringify({ type: "decision", decision }));
      el.remove();
    };
    el.appendChild(btn);
  }
}

function setBusy(busy) {
  promptInput.disabled = busy;
  sendButton.disabled = busy;
  if (!busy) promptInput.focus();
}

function send() {
  const text = promptInput.value.trim();
  if (!text || !ws) return;
  bubble("user", text);
  ws.send(JSON.stringify({ type: "prompt", text }));
  promptInput.value = "";
  setBusy(true);
}

sendButton.onclick = send;
promptInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") send();
});
slider.addEventListener("input", () => {
  pval.textContent = slider.value;
  if (ws) ws.send(JSON.stringify({ type: "ui_event", payload: { p: Number(slider.value) } }));
});

start();
