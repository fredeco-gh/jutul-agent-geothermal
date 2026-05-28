"""Local Textual widgets for the jutul-agent TUI."""

from __future__ import annotations

import ast
import asyncio
import json
import time
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.containers import Vertical
from textual.widgets import Markdown, Static

from jutul_agent.agent.tool_output import is_interrupt_payload, normalize_tool_output
from jutul_agent.interfaces.tui._rendering import (
    shorten,
    shorten_single_line,
    truncate_preview,
)
from jutul_agent.interfaces.tui.approval import ApprovalCard, approval_ui_hints
from jutul_agent.interfaces.tui.tool_display import (
    display_path,
    display_tool_body,
    uses_compact_display,
)

if TYPE_CHECKING:
    from textual.widgets._markdown import MarkdownStream

_TOOL_LANGUAGES: dict[str, str] = {
    "julia_eval": "julia",
    "execute": "sh",
}
_PREVIEW_LINES = 3
_PREVIEW_CHARS = 240
_TOOL_PREVIEW_LIMITS: dict[str, tuple[int, int]] = {
    "execute": (6, 1200),
    "julia_eval": (14, 2200),
}
_TODO_PREVIEW_ITEMS = 3
_TODO_PREVIEW_TEXT = 72
_TODO_FULL_TEXT = 140


class MessageBlock(Vertical):
    """Generic conversation card for user, assistant, system, and error messages."""

    DEFAULT_CSS = """
    MessageBlock {
        border: solid $surface-lighten-1;
        padding: 0 1;
        margin: 1 0 0 0;
        height: auto;
        background: $surface;
    }

    MessageBlock.user {
        background: $surface-darken-1;
    }

    MessageBlock.assistant {
        background: $panel;
    }

    MessageBlock.assistant Markdown {
        max-height: 24;
        overflow-y: auto;
    }

    MessageBlock.reasoning {
        background: $surface-darken-1;
        border: solid $surface;
    }

    MessageBlock.reasoning .message-body {
        color: $text-muted;
    }

    MessageBlock.system {
        background: $surface;
    }

    MessageBlock.error {
        border: solid $error;
    }

    MessageBlock.welcome {
        background: $surface;
    }

    MessageBlock Markdown,
    MessageBlock .message-body {
        padding: 0;
        margin: 0;
        height: auto;
    }
    """

    def __init__(
        self,
        role_label: str,
        role_class: str,
        content: str = "",
        *,
        markdown: bool = False,
    ) -> None:
        super().__init__()
        self.add_class(role_class)
        self.border_title = role_label
        self._content = content
        self._markdown = markdown
        self._body_widget: Static | Markdown | None = None
        self._stream: MarkdownStream | None = None

    def compose(self):
        if self._markdown:
            yield Markdown(self._content, id="message-body")
            return
        yield Static(self._content, classes="message-body", id="message-body", markup=False)

    def on_mount(self) -> None:
        self._body_widget = self.query_one("#message-body")
        self.refresh_for_width()

    async def _ensure_body(self) -> None:
        if self._body_widget is not None:
            return
        if not self.is_mounted:
            await self._mounted_event.wait()
        self._body_widget = self.query_one("#message-body")

    def _get_markdown(self) -> Markdown:
        if self._body_widget is None:
            raise RuntimeError("MessageBlock body is not mounted yet")
        if not isinstance(self._body_widget, Markdown):
            raise TypeError("MessageBlock markdown stream requested for non-markdown body")
        return self._body_widget

    def _ensure_stream(self) -> MarkdownStream:
        if self._stream is None:
            self._stream = Markdown.get_stream(self._get_markdown())
        return self._stream

    def refresh_for_width(self) -> None:
        if self._body_widget is not None:
            self._body_widget.refresh(layout=True)
        self.refresh(layout=True)

    async def append_content(self, content: str) -> None:
        if not content:
            return
        await self._ensure_body()
        if not self._markdown:
            await self.set_content(self._content + content)
            return
        self._content += content
        stream = self._ensure_stream()
        await stream.write(content)

    async def stop_stream(self) -> None:
        if self._stream is not None:
            await self._stream.stop()
            self._stream = None
            await self._get_markdown().update(self._content)
            self.refresh_for_width()

    async def set_content(self, content: str) -> None:
        self._content = content
        await self._ensure_body()
        if isinstance(self._body_widget, Markdown):
            if self._stream is not None:
                await self._stream.stop()
                self._stream = None
            await self._body_widget.update(content)
        else:
            self._body_widget.update(content)
        self.refresh_for_width()


class WelcomeBlock(MessageBlock):
    """Landing card shown when the TUI starts or the visible log is cleared."""

    def __init__(
        self,
        *,
        simulator_label: str,
        session_id: str,
        model_label: str | None,
        approval_mode_label: str | None = None,
    ) -> None:
        super().__init__(
            "Session",
            "welcome",
            _render_welcome_message(
                simulator_label=simulator_label,
                session_id=session_id,
                model_label=model_label,
                approval_mode_label=approval_mode_label,
            ),
            markdown=True,
        )


class ApprovalBlock(Vertical):
    """Structured card for a pending approval request and the chosen response."""

    DEFAULT_CSS = """
    ApprovalBlock {
        border: solid $surface-lighten-1;
        padding: 0 1;
        margin: 1 0 0 0;
        height: auto;
        background: $surface;
    }

    ApprovalBlock.approve {
        border: solid $success;
    }

    ApprovalBlock.reject {
        border: solid $error;
    }

    ApprovalBlock.respond {
        border: solid $accent;
    }

    ApprovalBlock Markdown {
        padding: 0;
        margin: 0;
    }

    ApprovalBlock .approval-hint {
        color: $text-muted;
        height: auto;
    }
    """

    def __init__(self, card: ApprovalCard) -> None:
        super().__init__()
        self._card = card
        self._state = "pending"
        self._body_widget: Markdown | None = None
        self._message: str | None = None
        self._hint_widget: Static | None = None
        self.border_title = card.title

    @property
    def tool_name(self) -> str:
        return self._card.tool_name

    def compose(self):
        yield Markdown(self._card.body, id="approval-body")
        yield Static("", classes="approval-hint", id="approval-hint", markup=False)

    def on_mount(self) -> None:
        self._body_widget = self.query_one("#approval-body", Markdown)
        self._hint_widget = self.query_one("#approval-hint", Static)
        self.refresh_for_width()
        self._refresh()

    def refresh_for_width(self) -> None:
        if self._body_widget is not None:
            self._body_widget.refresh(layout=True)
        if self._hint_widget is not None:
            self._hint_widget.refresh(layout=True)
        self.refresh(layout=True)

    async def set_decision(self, decision_type: str, message: str | None = None) -> None:
        self._state = decision_type
        self._message = message or None
        self._refresh()

    def _refresh(self) -> None:
        if self._hint_widget is None:
            return

        self.remove_class("approve")
        self.remove_class("reject")
        self.remove_class("respond")
        if self._state != "pending":
            self.add_class(self._state)
        self.border_subtitle = _approval_status_text(self._state, self._message)
        self._hint_widget.update(_approval_command_hint(self._card.allowed_decisions))


def _render_welcome_message(
    *,
    simulator_label: str,
    session_id: str,
    model_label: str | None,
    approval_mode_label: str | None = None,
) -> str:
    lines = [
        f"**jutul-agent** is ready for **{simulator_label}**.",
        f"Session `{session_id[:8]}`",
    ]
    if model_label:
        lines[-1] += f" · model `{shorten(model_label, 48)}`"
    if approval_mode_label:
        lines[-1] += f" · approvals `{approval_mode_label}`"
    lines.extend(
        [
            "",
            "Ask a question or describe a task.",
            "Shift+Tab cycles approval mode "
            "(*workspace* auto-approves file edits; *auto* skips all prompts).",
        ]
    )
    return "\n".join(lines)


def _approval_status_text(decision_type: str, message: str | None) -> str:
    if decision_type == "approve":
        return "approved"
    if decision_type == "reject":
        if message:
            return f"rejected: {message}"
        return "rejected"
    if decision_type == "respond":
        if message:
            return f"responded: {shorten_single_line(message, 72)}"
        return "responded"
    return "awaiting review"


def _approval_command_hint(allowed_decisions: frozenset[str]) -> str:
    hints = approval_ui_hints(allowed_decisions)
    if not hints:
        return "Approval is pending. This request cannot be resolved from the TUI."
    return "Available: " + hints


class PromptGuide(Static):
    """Dynamic helper line under the prompt for commands, history, and activity."""

    DEFAULT_CSS = """
    PromptGuide {
        height: auto;
        color: $text-muted;
        padding: 0 1;
    }
    """

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id, markup=False)
        self._message = ""
        self._activity = "ready"

    @property
    def message(self) -> str:
        return self._message

    def set_message(self, message: str) -> None:
        self._message = message
        self.refresh()

    def set_activity(self, activity: str) -> None:
        self._activity = activity
        self.refresh()

    def render(self) -> Text:
        text = Text()
        text.append(self._activity, style=_status_style(self._activity))
        if self._message:
            text.append(" · ", style="dim")
            text.append(self._message, style="dim")
        return text


class StatusBar(Static):
    """Compact bottom status bar with session context and live state."""

    DEFAULT_CSS = """
    StatusBar {
        dock: top;
        height: 1;
        padding: 0 1;
        background: $surface-darken-1;
        color: $text-muted;
    }
    """

    def __init__(
        self,
        *,
        simulator_label: str,
        session_id: str,
        model_label: str | None = None,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id, markup=False)
        self._simulator_label = simulator_label
        self._session_id = session_id
        self._model_label = model_label
        self._pending_count = 0
        self._tool_toggle_available = False
        self._approval_mode_label = "default"
        self._busy = False

    def set_state(
        self,
        *,
        pending_count: int = 0,
        tool_toggle_available: bool = False,
        approval_mode_label: str = "default",
        busy: bool = False,
    ) -> None:
        self._pending_count = pending_count
        self._tool_toggle_available = tool_toggle_available
        self._approval_mode_label = approval_mode_label
        self._busy = busy
        self.refresh()

    def render(self) -> Text:
        text = Text()
        text.append("jutul-agent", style="bold")
        text.append(" · ", style="dim")
        text.append(self._simulator_label, style="bold cyan")

        if self._model_label:
            text.append(" · ", style="dim")
            text.append(shorten(self._model_label, 28), style="dim")

        text.append(" · ", style="dim")
        text.append(self._session_id[:8], style="dim")

        if self._approval_mode_label:
            text.append(" · ", style="dim")
            text.append(self._approval_mode_label, style="cyan")

        if self._pending_count:
            label = "approval" if self._pending_count == 1 else "approvals"
            text.append(" · ", style="dim")
            text.append(f"{self._pending_count} {label}", style="yellow")

        if self._busy:
            text.append(" · ", style="dim")
            text.append("Ctrl+G cancel", style="bold yellow")

        if self._tool_toggle_available:
            text.append(" · ", style="dim")
            text.append("details available", style="dim")

        return text


class ToolBlock(Vertical):
    """Richer single-card rendering for a tool call and its eventual result."""

    DEFAULT_CSS = """
    ToolBlock {
        border: solid $surface-lighten-1;
        padding: 0 1;
        margin: 1 0 0 0;
        height: auto;
        background: $surface;
    }

    ToolBlock.approval {
        border: solid $warning;
    }

    ToolBlock.rejected,
    ToolBlock.cancelled,
    ToolBlock.error {
        border: solid $error;
    }

    ToolBlock.compact {
        border: none;
        border-left: tall $surface-lighten-1;
        margin: 0;
        padding: 0 1;
        background: transparent;
    }

    ToolBlock.compact Markdown {
        color: $text-muted;
    }

    ToolBlock Markdown {
        padding: 0;
        margin: 0;
    }
    """

    def __init__(
        self,
        tool_name: str,
        args: dict[str, Any] | None = None,
        *,
        tool_call_id: str | None = None,
    ) -> None:
        super().__init__()
        self._tool_name = tool_name
        self._args = args or {}
        self._tool_call_id = tool_call_id
        self._status = "running"
        self._output = ""
        self._streamed = ""
        self._expanded = False
        self._is_error = False
        self._reject_reason: str | None = None
        self._body_widget: Markdown | None = None
        self._elapsed_task: asyncio.Task[None] | None = None
        self.border_title = _tool_title(tool_name)
        self.border_subtitle = _status_text(self._status, self._reject_reason)

    def compose(self):
        yield Markdown("", id="tool-body")

    async def on_mount(self) -> None:
        self._body_widget = self.query_one("#tool-body", Markdown)
        await self._refresh()

    async def _ensure_body(self) -> None:
        if self._body_widget is not None:
            return
        if not self.is_mounted:
            await self._mounted_event.wait()
        self._body_widget = self.query_one("#tool-body", Markdown)

    def start_elapsed_timer(self) -> None:
        """Update the subtitle with elapsed seconds while the tool is running."""

        self.stop_elapsed_timer()

        async def _tick() -> None:
            start = time.monotonic()
            while self._status == "running":
                elapsed = time.monotonic() - start
                self.border_subtitle = f"running · {elapsed:.0f}s"
                self.refresh()
                await asyncio.sleep(1.0)

        self._elapsed_task = asyncio.create_task(_tick())

    def stop_elapsed_timer(self) -> None:
        if self._elapsed_task is not None:
            self._elapsed_task.cancel()
            self._elapsed_task = None

    def refresh_for_width(self) -> None:
        if self._body_widget is not None:
            self._body_widget.refresh(layout=True)
        self.refresh(layout=True)

    @property
    def tool_name(self) -> str:
        return self._tool_name

    @property
    def tool_call_id(self) -> str | None:
        return self._tool_call_id

    @property
    def expandable(self) -> bool:
        if not self._output:
            return False
        return _is_expandable(self._output, tool_name=self._tool_name)

    @property
    def has_output(self) -> bool:
        return bool(self._output)

    @property
    def status(self) -> str:
        return self._status

    async def set_running(self) -> None:
        self._status = "running"
        self._reject_reason = None
        await self._refresh()

    async def set_pending_approval(self) -> None:
        self._status = "approval"
        await self._refresh()

    async def set_rejected(self, reason: str | None = None) -> None:
        self.stop_elapsed_timer()
        self._status = "rejected"
        self._reject_reason = reason or None
        await self._refresh()

    async def set_cancelled(self, reason: str | None = None) -> None:
        self.stop_elapsed_timer()
        self._status = "cancelled"
        self._reject_reason = reason or None
        await self._refresh()

    async def append_output(self, delta: str) -> None:
        if not delta:
            return
        self._streamed += delta
        self._output = self._streamed
        self._status = "running"
        await self._ensure_body()
        await self._refresh()

    async def set_result(self, content: str, *, is_error: bool = False) -> None:
        self.stop_elapsed_timer()
        self._output = normalize_tool_output(content)
        self._streamed = ""
        self._is_error = is_error
        if is_error and is_interrupt_payload(self._output):
            self._status = "approval"
        else:
            self._status = "error" if is_error else "success"
        await self._refresh()

    async def toggle_output(self) -> None:
        if not self.expandable:
            return
        self._expanded = not self._expanded
        await self._refresh()

    async def _refresh(self) -> None:
        if self._body_widget is None:
            return

        # Only the bordered statuses get a CSS class; the others share the
        # default ``ToolBlock`` styling and don't need a marker.
        for css_class in ("approval", "rejected", "cancelled", "error", "compact"):
            self.remove_class(css_class)
        if self._status in {"approval", "rejected", "cancelled", "error"}:
            self.add_class(self._status)
        elif (
            self._status == "success"
            and uses_compact_display(
                self._tool_name,
                is_error=self._is_error,
                output=self._output,
            )
            and not self._expanded
        ):
            self.add_class("compact")
        self.border_subtitle = _status_text(self._status, self._reject_reason)

        body = _render_tool_body(
            self._tool_name,
            self._args,
            output=self._output,
            expanded=self._expanded,
            reject_reason=self._reject_reason,
            is_error=self._is_error,
        )
        await self._body_widget.update(body)
        self.refresh_for_width()


def _status_style(message: str) -> str:
    lowered = message.lower()
    if "approval" in lowered:
        return "bold yellow"
    if "thinking" in lowered or "running" in lowered or "resuming" in lowered:
        return "yellow"
    if "error" in lowered or "failed" in lowered:
        return "red"
    return "green"


def _status_text(status: str, reject_reason: str | None) -> str:
    if status == "running":
        return "running"
    if status == "success":
        return "completed"
    if status == "approval":
        return "waiting for approval"
    if status == "rejected":
        if reject_reason:
            return f"rejected: {reject_reason}"
        return "rejected"
    if status == "cancelled":
        if reject_reason:
            return f"cancelled: {reject_reason}"
        return "cancelled"
    if status == "error":
        return "tool error"
    return status


def _render_tool_body(
    tool_name: str,
    args: dict[str, Any],
    *,
    output: str,
    expanded: bool,
    reject_reason: str | None,
    is_error: bool = False,
) -> str:
    if output:
        return _render_tool_output(
            tool_name,
            output,
            expanded=expanded,
            args=args,
            is_error=is_error,
        )

    # julia_* tools show the Code section while running (before any output).
    if tool_name in {"julia_eval", "julia_plot"}:
        body = display_tool_body(
            tool_name,
            args,
            output=output,
            expanded=expanded,
            is_error=is_error,
        )
        if reject_reason:
            body += f"\n\n> Reject reason: {reject_reason}"
        return body

    body = _render_request_preview(tool_name, args)
    if reject_reason:
        body += f"\n\n> Reject reason: {reject_reason}"
    return body


def _render_tool_output(
    tool_name: str,
    output: str,
    *,
    expanded: bool,
    args: dict[str, Any] | None = None,
    is_error: bool = False,
) -> str:
    if tool_name == "write_todos":
        rendered = _render_todo_output(output, expanded=expanded)
        if rendered is not None:
            return rendered

    return display_tool_body(
        tool_name,
        args or {},
        output=output,
        expanded=expanded,
        is_error=is_error,
    )


def _render_request_preview(tool_name: str, args: dict[str, Any]) -> str:
    if tool_name == "write_todos":
        rendered = _render_todo_request(args)
        if rendered is not None:
            return rendered
    return f"_{_format_tool_display(tool_name, args)}_"


def _format_tool_display(tool_name: str, args: dict[str, Any]) -> str:
    if tool_name in {"write_file", "edit_file", "read_file"}:
        path_value = args.get("path") or args.get("file_path")
        if path_value is not None:
            path = display_path(str(path_value))
            return f"{tool_name}({path})"

    if tool_name == "execute" and args.get("command"):
        command = shorten_single_line(str(args["command"]), 80)
        return f'execute("{command}")'

    if tool_name == "julia_eval" and args.get("code"):
        code = shorten_single_line(str(args["code"]), 80)
        return f'julia_eval("{code}")'

    if tool_name == "write_todos":
        todos = args.get("todos")
        if isinstance(todos, list):
            count = len(todos)
            label = "item" if count == 1 else "items"
            return f"write_todos({count} {label})"

    if not args:
        return f"{tool_name}()"

    rendered_args = ", ".join(
        f"{key}={shorten_single_line(str(value), 30)}" for key, value in list(args.items())[:3]
    )
    if len(args) > 3:
        rendered_args += ", ..."
    return f"{tool_name}({rendered_args})"


def _preview_limits(tool_name: str | None) -> tuple[int, int]:
    if tool_name is None:
        return (_PREVIEW_LINES, _PREVIEW_CHARS)
    return _TOOL_PREVIEW_LIMITS.get(tool_name, (_PREVIEW_LINES, _PREVIEW_CHARS))


def _truncate_preview(text: str, *, tool_name: str | None = None) -> str:
    line_limit, char_limit = _preview_limits(tool_name)
    return truncate_preview(
        text,
        max_lines=line_limit,
        max_chars=char_limit,
        marker="\n... [output truncated]",
    )


def _is_expandable(text: str, *, tool_name: str | None = None) -> bool:
    line_limit, char_limit = _preview_limits(tool_name)
    return len(text) > char_limit or text.count("\n") + 1 > line_limit


def _summarize_output(text: str) -> str:
    line_count = max(1, text.count("\n") + 1)
    line_label = "line" if line_count == 1 else "lines"
    char_count = len(text)
    char_label = "char" if char_count == 1 else "chars"
    return f"{line_count} {line_label} · {char_count} {char_label}"


def _quote_block(text: str) -> str:
    if not text:
        return ">"
    return "\n".join(f"> {line}" if line else ">" for line in text.splitlines())


def _prefer_fenced_preview(tool_name: str) -> bool:
    return tool_name in {"julia_eval"}


def _tool_title(tool_name: str) -> str:
    if tool_name == "write_todos":
        return "Plan"
    if tool_name == "task":
        return "Delegate"
    if tool_name == "julia_eval":
        return "Julia · run"
    if tool_name == "julia_plot":
        return "Julia · plot"
    if tool_name == "record_attempt":
        return "Record attempt"
    if tool_name == "write_report":
        return "Write report"
    if tool_name == "execute":
        return "Shell · run"
    return tool_name


def _render_todo_request(args: dict[str, Any]) -> str | None:
    items = _parse_todo_items(args.get("todos"))
    if items is None:
        return None
    return _render_todo_lines(items, preview=True, label="plan")


def _render_todo_output(output: str, *, expanded: bool) -> str | None:
    items = _parse_todo_items(output)
    if items is None:
        return None
    return _render_todo_lines(items, preview=not expanded, label="plan updated")


def _render_todo_lines(items: list[Any], *, preview: bool, label: str) -> str:
    total = len(items)
    summary = _summarize_todos(items)
    limit = _TODO_PREVIEW_ITEMS if preview else total

    lines = [f"_{label} · {summary}_", ""]
    for item in items[:limit]:
        marker = _todo_marker(item)
        text = _todo_text(item)
        short = shorten_single_line(text, _TODO_PREVIEW_TEXT if preview else _TODO_FULL_TEXT)
        lines.append(f"- [{marker}] {short}")

    hidden = total - limit
    if hidden > 0:
        item_label = "item" if hidden == 1 else "items"
        lines.append(f"- ... {hidden} more {item_label}")
    return "\n".join(lines)


def _parse_todo_items(value: Any) -> list[Any] | None:
    if isinstance(value, list):
        return value

    if isinstance(value, dict):
        todos = value.get("todos")
        if isinstance(todos, list):
            return todos
        return None

    if not isinstance(value, str):
        return None

    candidate = value.strip()
    if not candidate:
        return []

    for raw_candidate in (candidate, _extract_serialized_collection(candidate)):
        if raw_candidate is None:
            continue
        for parser in (json.loads, ast.literal_eval):
            try:
                parsed = parser(raw_candidate)
            except (ValueError, SyntaxError, json.JSONDecodeError, TypeError):
                continue
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict) and isinstance(parsed.get("todos"), list):
                return parsed["todos"]
    return None


def _extract_serialized_collection(text: str) -> str | None:
    starts = [index for index in (text.find("["), text.find("{")) if index >= 0]
    if not starts:
        return None

    start = min(starts)
    opener = text[start]
    closer = "]" if opener == "[" else "}"
    end = text.rfind(closer)
    if end <= start:
        return None
    return text[start : end + 1]


def _summarize_todos(items: list[Any]) -> str:
    completed = sum(
        1 for item in items if isinstance(item, dict) and item.get("status") == "completed"
    )
    active = sum(
        1 for item in items if isinstance(item, dict) and item.get("status") == "in_progress"
    )
    pending = max(0, len(items) - completed - active)
    parts = [f"{len(items)} items"]
    if active:
        parts.append(f"{active} active")
    if pending:
        parts.append(f"{pending} pending")
    if completed:
        parts.append(f"{completed} done")
    return " · ".join(parts)


def _todo_marker(item: Any) -> str:
    status = item.get("status") if isinstance(item, dict) else None
    if status == "completed":
        return "x"
    if status == "in_progress":
        return "~"
    return " "


def _todo_text(item: Any) -> str:
    if isinstance(item, dict):
        content = item.get("content")
        if isinstance(content, str):
            return content
    return str(item)
