"""Render a trace log as a self-contained HTML transcript."""

from __future__ import annotations

import html
import json
from collections.abc import Iterable
from typing import Any

from jutul_agent.trace import Event
from jutul_agent.transcript.events import ArtifactPayload
from jutul_agent.transcript.highlight import (
    PLAIN_OUTPUT_TOOLS,
    SIMULATOR_TOOLS,
    highlight_code,
    highlight_code_blocks_in_html,
    infer_tool_code_language,
    is_julia_source,
    pygments_css,
)
from jutul_agent.transcript.markdown_html import (
    looks_like_markdown,
    render_markdown_html,
    strip_line_number_prefixes,
    strip_yaml_frontmatter,
)

_STYLES = """
:root {
  color-scheme: light dark;
  --bg: #f8f9fb;
  --surface: #ffffff;
  --border: #d8dee9;
  --text: #1f2937;
  --muted: #6b7280;
  --user: #2563eb;
  --assistant: #059669;
  --reasoning: #7c3aed;
  --tool: #d97706;
  --approval: #dc2626;
  --artifact: #0891b2;
  --session: #475569;
  --code-bg: #f6f8fa;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0f1419;
    --surface: #1a2332;
    --border: #334155;
    --text: #e2e8f0;
    --muted: #94a3b8;
    --code-bg: #0d1117;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.5;
}
.wrap { max-width: 960px; margin: 0 auto; padding: 1.5rem 1rem 3rem; }
header {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 1.25rem 1.5rem;
  margin-bottom: 1rem;
}
header h1 { margin: 0 0 0.5rem; font-size: 1.35rem; }
.meta { color: var(--muted); font-size: 0.9rem; margin: 0.25rem 0; }
.badges { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.75rem; }
.badge {
  font-size: 0.75rem;
  padding: 0.15rem 0.55rem;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--bg);
}
.controls {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 0.75rem 1rem;
  margin-bottom: 1rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem 1.25rem;
  align-items: center;
}
.controls fieldset {
  border: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem 1rem;
  align-items: center;
}
.controls legend { font-size: 0.85rem; color: var(--muted); margin-right: 0.25rem; }
.controls label { font-size: 0.85rem; cursor: pointer; }
.controls button {
  font-size: 0.85rem;
  padding: 0.35rem 0.75rem;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
  cursor: pointer;
}
.timeline { display: flex; flex-direction: column; gap: 0.75rem; }
.event {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 0.85rem 1rem;
}
.event h3 {
  margin: 0.15rem 0 0.5rem;
  font-size: 1rem;
  font-weight: 600;
}
.event h4 {
  margin: 0.75rem 0 0.35rem;
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.event-header {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: baseline;
  margin-bottom: 0.5rem;
  font-size: 0.85rem;
}
.event-kind { font-weight: 600; }
.event-kind.user { color: var(--user); }
.event-kind.assistant { color: var(--assistant); }
.event-kind.reasoning { color: var(--reasoning); }
.event-kind.tool { color: var(--tool); }
.event-kind.approval { color: var(--approval); }
.event-kind.artifact { color: var(--artifact); }
.event-kind.session { color: var(--session); }
.event-kind.unknown { color: var(--muted); }
.event time { color: var(--muted); font-variant-numeric: tabular-nums; }
.md-content { line-height: 1.6; word-break: break-word; }
.md-content > :first-child { margin-top: 0; }
.md-content > :last-child { margin-bottom: 0; }
.md-content h1, .md-content h2, .md-content h3, .md-content h4 {
  margin: 1rem 0 0.4rem;
  line-height: 1.25;
}
.md-content h1 { font-size: 1.35rem; }
.md-content h2 { font-size: 1.15rem; margin-top: 1.1rem; }
.md-content h3 { font-size: 1.02rem; margin-top: 0.95rem; }
.md-content p { margin: 0.55rem 0; }
.md-content ul, .md-content ol { margin: 0.55rem 0 0.75rem; padding-left: 1.5rem; }
.md-content li { margin: 0.25rem 0; }
.md-content li > p { margin: 0.15rem 0; }
.md-content blockquote {
  margin: 0.5rem 0;
  padding: 0.25rem 0.75rem;
  border-left: 3px solid var(--border);
  color: var(--muted);
}
.md-content table {
  width: 100%;
  border-collapse: collapse;
  margin: 0.5rem 0;
  font-size: 0.9rem;
}
.md-content th, .md-content td {
  border: 1px solid var(--border);
  padding: 0.35rem 0.5rem;
  text-align: left;
}
.md-content th { background: var(--bg); }
.md-content img { max-width: 100%; height: auto; }
.md-content a { color: var(--user); }
.prose-plain { white-space: pre-wrap; word-break: break-word; }
.tool-output {
  margin: 0;
}
.inline-value {
  display: inline-block;
  padding: 0.1rem 0.35rem;
  border-radius: 4px;
  background: var(--bg);
  border: 1px solid var(--border);
  font-family: ui-monospace, "Cascadia Code", "Source Code Pro", monospace;
  font-size: 0.85rem;
}
.todo-list { list-style: none; margin: 0; padding: 0; }
.todo-item {
  display: flex;
  gap: 0.5rem;
  align-items: baseline;
  padding: 0.25rem 0;
  border-bottom: 1px solid var(--border);
}
.todo-item:last-child { border-bottom: none; }
.todo-status {
  flex: 0 0 auto;
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  padding: 0.1rem 0.4rem;
  border-radius: 999px;
  border: 1px solid var(--border);
  color: var(--muted);
}
.todo-status.completed { color: var(--assistant); }
.todo-status.in_progress { color: var(--tool); }
.todo-text { flex: 1; }
.share-note {
  margin-top: 1rem;
  padding: 0.75rem 1rem;
  border-radius: 8px;
  border: 1px dashed var(--border);
  color: var(--muted);
  font-size: 0.85rem;
}
pre, code {
  font-family: ui-monospace, "Cascadia Code", "Source Code Pro", monospace;
  font-size: 0.85rem;
}
pre {
  margin: 0;
  padding: 0.65rem 0.75rem;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-word;
}
.md-content pre {
  margin: 0.5rem 0;
}
.md-content pre code, .md-content code {
  font-family: ui-monospace, "Cascadia Code", "Source Code Pro", monospace;
  font-size: 0.85rem;
}
.md-content :not(pre) > code {
  padding: 0.1rem 0.3rem;
  border-radius: 4px;
  background: var(--bg);
  border: 1px solid var(--border);
}
dl { margin: 0; }
dt { font-weight: 600; font-size: 0.85rem; margin-top: 0.35rem; }
dd { margin: 0.15rem 0 0 0; }
details { margin-top: 0.35rem; }
details > summary { cursor: pointer; color: var(--muted); font-size: 0.9rem; }
.approval { border-left: 3px solid var(--approval); padding-left: 0.75rem; }
figure { margin: 0.5rem 0 0; }
figure img {
  max-width: 100%;
  height: auto;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg);
}
figcaption { font-size: 0.85rem; color: var(--muted); margin-top: 0.35rem; }
.artifact-meta { margin: 0.25rem 0 0.5rem; }
.artifact-meta .badge { margin-right: 0.35rem; }
.inline-artifact { margin-top: 0.75rem; padding-top: 0.5rem; border-top: 1px dashed var(--border); }
.inline-artifact figure img { max-height: 320px; object-fit: contain; }
.artifact-source { margin-top: 0.5rem; }
.session-end {
  text-align: center;
  color: var(--muted);
  font-size: 0.9rem;
  padding: 0.5rem;
}
"""

_SCRIPT = """
(function () {
  const events = document.querySelectorAll(".event[data-filter]");
  const checkboxes = document.querySelectorAll(".kind-filter");
  function applyFilters() {
    const hidden = new Set(
      [...checkboxes].filter((cb) => !cb.checked).map((cb) => cb.dataset.filter)
    );
    events.forEach((el) => {
      el.style.display = hidden.has(el.dataset.filter) ? "none" : "";
    });
  }
  checkboxes.forEach((cb) => cb.addEventListener("change", applyFilters));
  document.getElementById("collapse-all")?.addEventListener("click", () => {
    document.querySelectorAll("details").forEach((d) => { d.open = false; });
  });
  document.getElementById("expand-all")?.addEventListener("click", () => {
    document.querySelectorAll("details").forEach((d) => { d.open = true; });
  });
})();
"""

_FILTER_GROUPS: dict[str, str] = {
    "message_user": "user",
    "message_assistant": "assistant",
    "message_reasoning": "reasoning",
    "tool_call": "tools",
    "tool_result": "tools",
    "hitl_request": "approval",
    "hitl_response": "approval",
    "artifact": "artifact",
}

_FILTER_LABELS: dict[str, str] = {
    "user": "User",
    "assistant": "Assistant",
    "reasoning": "Reasoning",
    "tools": "Tools",
    "approval": "Approval",
    "artifact": "Artifact",
}

_KIND_LABELS: dict[str, str] = {
    "session_start": "Session",
    "session_end": "Session",
    **{kind: _FILTER_LABELS[group] for kind, group in _FILTER_GROUPS.items()},
}


def _esc(text: Any) -> str:
    return html.escape(str(text), quote=False)


def _esc_attr(text: Any) -> str:
    return html.escape(str(text), quote=True)


def _nl2br(text: str) -> str:
    return _esc(text).replace("\n", "<br>\n")


def _render_markdown(text: str) -> str:
    rendered = highlight_code_blocks_in_html(render_markdown_html(text.strip()))
    return f'<div class="md-content">{rendered}</div>'


def _render_prose(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    if looks_like_markdown(stripped):
        return _render_markdown(stripped)
    return f'<div class="prose-plain">{_nl2br(stripped)}</div>'


def _render_tool_content(content: str, *, tool_name: str | None = None) -> str:
    stripped = content.strip()
    if not stripped:
        return ""

    body = stripped

    if tool_name == "read_file":
        body = strip_line_number_prefixes(body)
        body = strip_yaml_frontmatter(body)
        if looks_like_markdown(body):
            return _render_markdown(body)
        language = infer_tool_code_language(body, tool_name)
        return highlight_code(body, language)

    if tool_name in PLAIN_OUTPUT_TOOLS:
        return highlight_code(body, "text")

    if tool_name in SIMULATOR_TOOLS:
        return highlight_code(body, "julia")

    if looks_like_markdown(body) and not is_julia_source(body):
        return _render_markdown(body)

    language = infer_tool_code_language(body, tool_name)
    return highlight_code(body, language)


def _fmt_todos(value: Any) -> str:
    if not isinstance(value, list):
        return f"<pre>{_esc(repr(value))}</pre>"
    items: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            items.append(f"<li><pre>{_esc(repr(item))}</pre></li>")
            continue
        status = str(item.get("status") or "pending").replace(" ", "_")
        content = str(item.get("content") or "")
        items.append(
            f'<li class="todo-item">'
            f'<span class="todo-status {_esc_attr(status)}">{_esc(status.replace("_", " "))}</span>'
            f'<span class="todo-text">{_esc(content)}</span>'
            f"</li>"
        )
    return f'<ul class="todo-list">{"".join(items)}</ul>'


def _fmt_arg_value(key: str, value: Any) -> str:
    if key == "todos":
        return _fmt_todos(value)
    if key == "code" and isinstance(value, str):
        return highlight_code(value, "julia")
    if isinstance(value, str):
        if "\n" in value or len(value) > 120:
            language = infer_tool_code_language(value)
            return highlight_code(value, language)
        return f'<span class="inline-value">{_esc(value)}</span>'
    if isinstance(value, (dict, list)):
        try:
            pretty = json.dumps(value, indent=2, default=str)
        except TypeError:
            pretty = repr(value)
        return highlight_code(pretty, "json")
    return f'<span class="inline-value">{_esc(repr(value))}</span>'


def _artifact_meta_html(artifact: ArtifactPayload) -> str:
    badges: list[str] = []
    if artifact.slot:
        badges.append(f'<span class="badge">slot: {_esc(artifact.slot)}</span>')
    if artifact.format:
        badges.append(f'<span class="badge">format: {_esc(artifact.format)}</span>')
    if artifact.size_px is not None:
        badges.append(
            f'<span class="badge">{_esc(artifact.size_px[0])}x{_esc(artifact.size_px[1])}</span>'
        )
    if not badges:
        return ""
    return f'<p class="artifact-meta">{"".join(badges)}</p>'


def _artifact_source_html(artifact: ArtifactPayload) -> str:
    if not artifact.source_code:
        return ""
    return (
        "<details class=\"artifact-source\">"
        "<summary>Source code</summary>"
        f"{highlight_code(artifact.source_code.rstrip(), 'julia')}"
        "</details>"
    )


def _fmt_args(args: Any) -> str:
    if not args:
        return "<p><em>(no args)</em></p>"
    if isinstance(args, dict):
        items = "".join(
            f"<dt>{_esc(k)}</dt><dd>{_fmt_arg_value(k, v)}</dd>" for k, v in args.items()
        )
        return f"<dl>{items}</dl>"
    return f"<pre>{_esc(repr(args))}</pre>"


def _fmt_hitl_request(payload: dict[str, Any]) -> str:
    interrupt_id = payload.get("interrupt_id") or "?"
    value = payload.get("value")
    if not isinstance(value, dict):
        return (
            f"<dl>"
            f"<dt>interrupt_id</dt><dd><pre>{_esc(repr(interrupt_id))}</pre></dd>"
            f"<dt>value</dt><dd><pre>{_esc(repr(value))}</pre></dd>"
            f"</dl>"
        )

    action_requests = value.get("action_requests") or []
    parts = [f"<dt>interrupt_id</dt><dd><pre>{_esc(repr(interrupt_id))}</pre></dd>"]
    if isinstance(action_requests, list) and action_requests:
        parts.append("<dt>actions</dt><dd><ul>")
        for action in action_requests:
            if not isinstance(action, dict):
                parts.append(f"<li><pre>{_esc(repr(action))}</pre></li>")
                continue
            name = action.get("name", "?")
            args = action.get("args")
            parts.append(f"<li><code>{_esc(name)}</code> <pre>{_esc(repr(args))}</pre></li>")
        parts.append("</ul></dd>")
    else:
        parts.append(f"<dt>value</dt><dd><pre>{_esc(repr(value))}</pre></dd>")
    return f"<dl>{''.join(parts)}</dl>"


def _fmt_hitl_response(payload: dict[str, Any]) -> str:
    interrupt_id = payload.get("interrupt_id") or "?"
    response = payload.get("payload")
    return (
        f"<dl>"
        f"<dt>interrupt_id</dt><dd><pre>{_esc(repr(interrupt_id))}</pre></dd>"
        f"<dt>payload</dt><dd><pre>{_esc(repr(response))}</pre></dd>"
        f"</dl>"
    )


def _event_header(kind: str, label: str, ts: str, css_kind: str) -> str:
    return (
        f'<div class="event-header">'
        f'<span class="event-kind {css_kind}">{_esc(label)}</span>'
        f"<time datetime=\"{_esc_attr(ts)}\">{_esc(ts)}</time>"
        f"</div>"
    )


def _tool_result_block(content: str, *, tool_name: str | None = None) -> str:
    lines = content.splitlines()
    rendered = _render_tool_content(content, tool_name=tool_name)
    if len(lines) > 20:
        return (
            f"<details>"
            f"<summary>Result ({len(lines)} lines)</summary>"
            f"{rendered}"
            f"</details>"
        )
    return rendered


def _event_attrs(kind: str) -> str:
    group = _FILTER_GROUPS.get(kind, kind)
    return f'data-kind="{_esc_attr(kind)}" data-filter="{_esc_attr(group)}"'


def _index_tool_results(events: list[Event]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for ev in events:
        if ev.kind != "tool_result":
            continue
        tool_call_id = ev.payload.get("tool_call_id")
        if tool_call_id is not None:
            indexed[str(tool_call_id)] = ev.payload
    return indexed


def _index_artifacts_by_tool_call(events: list[Event]) -> dict[str, ArtifactPayload]:
    indexed: dict[str, ArtifactPayload] = {}
    for ev in events:
        if ev.kind != "artifact":
            continue
        artifact = ArtifactPayload.from_payload(ev.payload)
        if artifact.tool_call_id is not None:
            indexed[artifact.tool_call_id] = artifact
    return indexed


def _inline_artifact_preview(artifact: ArtifactPayload | None) -> str:
    if artifact is None or not artifact.path or not artifact.is_image:
        return ""
    meta = _artifact_meta_html(artifact)
    return (
        f'<div class="inline-artifact">'
        f"{meta}"
        f"<figure>"
        f'<a href="{_esc_attr(artifact.path)}">'
        f'<img src="{_esc_attr(artifact.path)}" alt="{_esc_attr(artifact.caption)}">'
        f"</a>"
        f"<figcaption>{_esc(artifact.caption)}</figcaption>"
        f"</figure>"
        f"</div>"
    )


def _render_body(events: Iterable[Event]) -> tuple[str, dict[str, int]]:
    event_list = list(events)
    tool_results = _index_tool_results(event_list)
    artifacts_by_call = _index_artifacts_by_tool_call(event_list)
    consumed_results: set[str] = set()
    parts: list[str] = []
    kind_counts: dict[str, int] = {}

    session_id: str | None = None
    simulator: str | None = None
    started: str | None = None
    ended: str | None = None

    for ev in event_list:
        payload = ev.payload
        ts = ev.timestamp
        kind = ev.kind
        kind_counts[kind] = kind_counts.get(kind, 0) + 1

        if kind == "session_start":
            session_id = payload.get("session_id") or session_id
            simulator = payload.get("simulator") or "(none)"
            started = ts
            continue

        if kind == "session_end":
            ended = ts
            parts.append(
                f'<div class="session-end">Session ended · <time datetime="{_esc_attr(ts)}">'
                f"{_esc(ts)}</time></div>"
            )
            continue

        if kind == "message_user":
            parts.append(
                f'<article class="event" {_event_attrs(kind)}>'
                f'{_event_header(kind, "User", ts, "user")}'
                f'{_render_prose(str(payload.get("content", "")))}'
                f"</article>"
            )
            continue

        if kind == "message_reasoning":
            content = str(payload.get("content", ""))
            if not content.strip():
                continue
            parts.append(
                f'<article class="event" {_event_attrs(kind)}>'
                f'{_event_header(kind, "Reasoning", ts, "reasoning")}'
                f"<details>"
                f"<summary>Reasoning</summary>"
                f'{_render_prose(content)}'
                f"</details>"
                f"</article>"
            )
            continue

        if kind == "message_assistant":
            content = str(payload.get("content", ""))
            if not content.strip():
                continue
            parts.append(
                f'<article class="event" {_event_attrs(kind)}>'
                f'{_event_header(kind, "Assistant", ts, "assistant")}'
                f'{_render_prose(content)}'
                f"</article>"
            )
            continue

        if kind == "tool_call":
            name = payload.get("name", "?")
            tool_call_id = payload.get("id")
            result_payload = None
            if tool_call_id is not None:
                result_payload = tool_results.get(str(tool_call_id))
                if result_payload is not None:
                    consumed_results.add(str(tool_call_id))

            block = (
                f'<article class="event" {_event_attrs(kind)}>'
                f'{_event_header(kind, f"Tool · {name}", ts, "tool")}'
                f"<h3>{_esc(name)}</h3>"
                f"{_fmt_args(payload.get('args'))}"
            )
            if result_payload is not None:
                content = str(result_payload.get("content", ""))
                block += f"<h4>Result</h4>{_tool_result_block(content, tool_name=name)}"
            if tool_call_id is not None and name == "julia_plot":
                preview = _inline_artifact_preview(artifacts_by_call.get(str(tool_call_id)))
                if preview:
                    block += preview
            block += "</article>"
            parts.append(block)
            continue

        if kind == "tool_result":
            tool_call_id = payload.get("tool_call_id")
            if tool_call_id is not None and str(tool_call_id) in consumed_results:
                continue
            name = payload.get("name", "?")
            content = str(payload.get("content", ""))
            parts.append(
                f'<article class="event" {_event_attrs(kind)}>'
                f'{_event_header(kind, f"Tool result · {name}", ts, "tool")}'
                f"<h3>{_esc(name)}</h3>"
                f"{_tool_result_block(content, tool_name=name)}"
                f"</article>"
            )
            continue

        if kind == "hitl_request":
            parts.append(
                f'<article class="event approval" {_event_attrs(kind)}>'
                f'{_event_header(kind, "Approval request", ts, "approval")}'
                f'<div class="approval">{_fmt_hitl_request(payload)}</div>'
                f"</article>"
            )
            continue

        if kind == "hitl_response":
            parts.append(
                f'<article class="event approval" {_event_attrs(kind)}>'
                f'{_event_header(kind, "Approval response", ts, "approval")}'
                f'<div class="approval">{_fmt_hitl_response(payload)}</div>'
                f"</article>"
            )
            continue

        if kind == "artifact":
            artifact = ArtifactPayload.from_payload(payload)
            meta_html = _artifact_meta_html(artifact)
            source_html = _artifact_source_html(artifact)
            if artifact.is_image:
                parts.append(
                    f'<article class="event" {_event_attrs(kind)}>'
                    f'{_event_header(kind, "Artifact", ts, "artifact")}'
                    f"{meta_html}"
                    f"<figure>"
                    f'<img src="{_esc_attr(artifact.path)}" alt="{_esc_attr(artifact.caption)}">'
                    f"<figcaption>{_esc(artifact.caption)}</figcaption>"
                    f"</figure>"
                    f"{source_html}"
                    f"</article>"
                )
            else:
                parts.append(
                    f'<article class="event" {_event_attrs(kind)}>'
                    f'{_event_header(kind, "Artifact", ts, "artifact")}'
                    f"<p><a href=\"{_esc_attr(artifact.path)}\">"
                    f"{_esc(artifact.caption or artifact.path)}</a></p>"
                    f"</article>"
                )
            continue

        parts.append(
            f'<article class="event" {_event_attrs(kind)}>'
            f'{_event_header(kind, f"Event · {kind}", ts, "unknown")}'
            f"<details>"
            f"<summary>Raw payload</summary>"
            f"<pre>{_esc(repr(payload))}</pre>"
            f"</details>"
            f"</article>"
        )

    header_meta = ""
    if session_id:
        header_meta += f"<p class=\"meta\">Session <code>{_esc(session_id)}</code></p>"
    if simulator:
        header_meta += f"<p class=\"meta\">Simulator: {_esc(simulator)}</p>"
    if started:
        header_meta += (
            f'<p class="meta">Started: '
            f'<time datetime="{_esc_attr(started)}">{_esc(started)}</time></p>'
        )
    if ended:
        header_meta += (
            f'<p class="meta">Ended: '
            f'<time datetime="{_esc_attr(ended)}">{_esc(ended)}</time></p>'
        )

    group_counts: dict[str, int] = {}
    for kind, count in kind_counts.items():
        if kind in {"session_start", "session_end"}:
            label = _KIND_LABELS.get(kind, kind)
            group_counts[label] = group_counts.get(label, 0) + count
            continue
        group = _FILTER_GROUPS.get(kind, kind)
        label = _FILTER_LABELS.get(group, group)
        group_counts[label] = group_counts.get(label, 0) + count

    filter_groups = sorted(
        {
            _FILTER_GROUPS.get(k, k)
            for k in kind_counts
            if k not in {"session_start", "session_end"}
        }
    )
    filter_controls = "".join(
        f'<label><input type="checkbox" class="kind-filter" '
        f'data-filter="{_esc_attr(group)}" checked> '
        f"{_esc(_FILTER_LABELS.get(group, group))}</label>"
        for group in filter_groups
    )
    badges = "".join(
        f'<span class="badge">{_esc(label)}: {count}</span>'
        for label, count in sorted(group_counts.items())
    )

    header = (
        f"<header>"
        f"<h1>jutul-agent transcript</h1>"
        f"{header_meta}"
        f'<div class="badges">{badges}</div>'
        f"</header>"
        f'<div class="controls">'
        f"<fieldset><legend>Filter</legend>{filter_controls}</fieldset>"
        f'<button type="button" id="collapse-all">Collapse all</button>'
        f'<button type="button" id="expand-all">Expand all</button>'
        f"</div>"
        f'<div class="timeline">{"".join(parts)}</div>'
        f'<p class="share-note">To share this transcript, distribute the session folder '
        f"(<code>transcript.html</code> plus any <code>artifacts/</code>) or run "
        f"<code>jutul-agent transcript --bundle</code> to create a zip.</p>"
    )
    return header, kind_counts


def render_html(events: Iterable[Event]) -> str:
    """Render trace events as a complete, self-contained HTML document.

    Artifact paths are taken from each event's ``path`` payload field.
    """
    body, _ = _render_body(events)
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>jutul-agent transcript</title>\n"
        f"<style>{_STYLES}\n{pygments_css()}</style>\n"
        "</head>\n"
        "<body>\n"
        f'<div class="wrap">{body}</div>\n'
        f"<script>{_SCRIPT}</script>\n"
        "</body>\n"
        "</html>\n"
    )
