"""Interactive TUI for jutul-agent built on Textual.

The interface keeps the runtime seam in ``TurnRunner`` and focuses on local
presentation: a scrollable conversation log, grouped tool cards, inline
approval cards, and a compact input bar.

Slash commands typed into the input box:

- ``/transcript``: render the current session's trace to HTML on disk.
- ``/transcript md``: render the transcript as markdown instead.
- ``/add-dir <path>``: mount an extra folder so the agent can read/edit it.
- ``/model [provider:model]``: open the model selector, or switch directly.
- ``/clear``: clear the visible log and restore the welcome card.
- ``/approve``: approve the currently pending tool actions.
- ``/reject [reason]``: reject the currently pending tool actions.
- ``/respond <message>``: answer on behalf of the pending tool actions.
- ``/approval-mode [ask|workspace|auto]``: cycle or set permission mode (Shift+Tab cycles).
- ``/quit``: quit the app (same as Ctrl+D).
- ``/help``: list available commands.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import urllib.parse
import urllib.request
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from langchain_core.messages import AIMessageChunk
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Markdown, Static

from jutul_agent.agent.approval import (
    ApprovalMode,
    ToolAllowlist,
    parse_approval_mode,
    should_auto_approve_interrupt,
)
from jutul_agent.agent.mounts import MountError, mount_dir, mounted_dirs
from jutul_agent.agent.turns import (
    TurnInterrupt,
    TurnReasoningDelta,
    TurnRunner,
    TurnRunResult,
    TurnToolEvent,
)
from jutul_agent.interfaces.tui.approval import (
    SUPPORTED_APPROVAL_DECISIONS,
    allowed_decisions_for_interrupt,
    approval_command_hints,
    render_interrupt_cards,
)
from jutul_agent.interfaces.tui.approval_menu import ApprovalMenu, build_approval_options
from jutul_agent.interfaces.tui.commands import (
    InputHistory,
    SlashCommandSpec,
    active_commands,
    find_command,
    matching_specs,
)
from jutul_agent.interfaces.tui.model_menu import (
    ApiKeyModal,
    ModelChoice,
    ModelMenu,
    OllamaPullModal,
)
from jutul_agent.interfaces.tui.prompt import PromptTextArea
from jutul_agent.interfaces.tui.widgets import (
    ApprovalBlock,
    MessageBlock,
    PromptGuide,
    StatusBar,
    ToolBlock,
    WelcomeBlock,
)
from jutul_agent.open_file import open_path
from jutul_agent.paths import workspace_root
from jutul_agent.recent_models import record_recent_model
from jutul_agent.session import Session
from jutul_agent.trace import TraceLog
from jutul_agent.trace.messages import content_to_str
from jutul_agent.transcript import render_html, render_markdown

if TYPE_CHECKING:
    from collections.abc import Callable

    from textual.timer import Timer

_RESIZE_DEBOUNCE_SECONDS = 0.05
_SCROLL_DEBOUNCE_SECONDS = 0.03


@dataclass
class _AssistantStream:
    """In-flight prose + reasoning blocks for one streamed assistant turn.

    Owns the two MessageBlocks the streaming path mounts so the call sites
    don't have to track them by hand. Call ``flush`` between
    streaming-eligible regions (e.g. before a tool call is mounted, after a
    ``message-finish`` event) to close the markdown stream and let a fresh
    block be mounted on the next chunk.

    Only genuine assistant text reaches here: the turn runner streams
    text/reasoning from the model node alone, so tool results and
    middleware-injected messages never arrive as prose (no content filtering
    is needed; see ``jutul_agent.agent.turns``).
    """

    prose: MessageBlock | None = None
    reasoning: MessageBlock | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def append_prose(self, log: VerticalScroll, text: str) -> None:
        if not text:
            return
        async with self._lock:
            block = self.prose
            if block is None:
                block = MessageBlock("Assistant", "assistant", "", markdown=True)
                self.prose = block
                await log.mount(block)
            elif not block.is_mounted:
                await block._mounted_event.wait()
            await block.append_content(text)

    async def append_reasoning(self, log: VerticalScroll, text: str) -> None:
        if not text:
            return
        async with self._lock:
            block = self.reasoning
            if block is None:
                block = MessageBlock("Reasoning", "reasoning", "")
                self.reasoning = block
                await log.mount(block)
            elif not block.is_mounted:
                await block._mounted_event.wait()
            await block.append_content(text)

    async def flush(self) -> None:
        async with self._lock:
            if self.prose is not None:
                await self.prose.stop_stream()
            if self.reasoning is not None:
                await self.reasoning.stop_stream()
            self.prose = None
            self.reasoning = None


class TUIApp(App[None]):
    CSS = """
    Screen {
        layout: vertical;
        background: $background;
    }
    #log {
        height: 1fr;
        padding: 0 1 0 1;
        background: $background;
    }
    #input-panel {
        dock: bottom;
        height: auto;
        padding: 0 1 1 1;
        background: $background;
        border-top: solid $surface-lighten-1;
    }
    #input-row {
        height: auto;
        max-height: 10;
        border: solid $surface-lighten-1;
        padding: 0 1;
        background: $surface;
    }
    #prompt-glyph {
        width: 2;
        content-align: left top;
        color: $text-muted;
        padding-top: 0;
    }
    #prompt {
        width: 1fr;
        height: auto;
        min-height: 1;
        max-height: 8;
    }
    #prompt-help {
        height: auto;
        color: $text-muted;
        padding: 0 1;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+c", "interrupt", "Interrupt / Copy / Quit", priority=True),
        Binding("ctrl+g", "cancel_turn", "Cancel", priority=True),
        Binding("ctrl+l", "clear_visible_log", "Clear Log", priority=True),
        Binding("ctrl+o", "toggle_tool_output", "Toggle Tool Output", priority=True),
        Binding("tab", "complete_prompt", "Complete Prompt", show=False, priority=True),
        Binding(
            "shift+tab",
            "cycle_approval_mode",
            "Cycle Permission Mode",
            show=False,
            priority=True,
        ),
    ]

    def __init__(
        self,
        *,
        agent: Any,
        session: Session,
        backend: Any | None = None,
        model_label: str | None = None,
        approval_mode: ApprovalMode | str | None = None,
        warmup_task: Any | None = None,
        agent_factory: Callable[[str, Any], tuple[Any, Any]] | None = None,
    ) -> None:
        super().__init__()
        self._agent = agent
        self._session = session
        self._backend = backend
        self._model_label = model_label
        self._agent_factory = agent_factory
        self._warmup_task = warmup_task
        self._warming = warmup_task is not None and not warmup_task.done()
        self._approval_mode = (
            approval_mode
            if isinstance(approval_mode, ApprovalMode)
            else parse_approval_mode(approval_mode)
        )
        self._tool_allowlist = ToolAllowlist()
        self._turn_runner = TurnRunner(agent, thread_id=session.session_id, trace=session.trace)
        self._turn_worker: Any = None
        self._cancel_requested = False
        self._julia_running_on_cancel = False
        self._pending_interrupts: list[TurnInterrupt] = []
        self._tool_blocks: list[ToolBlock] = []
        self._tools_expanded = False
        self._active_approval_blocks: list[ApprovalBlock] = []
        self._history = InputHistory()
        self._setting_prompt_value = False
        self._busy = False
        self._status_text = "ready"
        self._stream = _AssistantStream()
        self._resize_timer: Timer | None = None
        self._scroll_timer: Timer | None = None
        self._quit_armed = False
        self._quit_timer: Timer | None = None
        # Resolved in ``on_mount``; both widgets are always present.
        self._log: VerticalScroll = None  # type: ignore[assignment]
        self._prompt: PromptTextArea = None  # type: ignore[assignment]
        self._approval_menu: ApprovalMenu = None  # type: ignore[assignment]

    def compose(self) -> ComposeResult:
        yield StatusBar(
            simulator_label=self._session.simulator.display_name,
            session_id=self._session.session_id,
            model_label=self._model_label,
            id="status",
        )
        with VerticalScroll(id="log"):
            yield WelcomeBlock(
                simulator_label=self._session.simulator.display_name,
                session_id=self._session.session_id,
            )
        with Vertical(id="input-panel"):
            yield ApprovalMenu(id="approval-menu")
            with Horizontal(id="input-row"):
                yield Static(">", id="prompt-glyph", markup=False)
                yield PromptTextArea(
                    placeholder="Ask a question or describe a task",
                    id="prompt",
                )
            yield PromptGuide(id="prompt-guide")

    def on_mount(self) -> None:
        self.title = "jutul-agent"
        self._refresh_subtitle()
        self._log = self.query_one("#log", VerticalScroll)
        self._prompt = self.query_one("#prompt", PromptTextArea)
        self._approval_menu = self.query_one("#approval-menu", ApprovalMenu)
        self._prompt.set_approval_nav_handler(self._handle_approval_nav)
        self._set_status("ready")
        self._prompt.focus()
        self._refresh_prompt_guide()
        if self._model_label:
            record_recent_model(self._model_label)
        if self._warming:
            self.run_worker(self._watch_warmup(), name="warmup-watch")

    async def _watch_warmup(self) -> None:
        """Clear the 'warming up' indicator once the background warm-up ends.

        ``asyncio.shield`` keeps the warm-up running if this watcher is torn
        down; ``run.py`` owns the task's lifecycle and cancels it on exit.
        """
        task = self._warmup_task
        if task is None:
            return
        with contextlib.suppress(Exception, asyncio.CancelledError):
            await asyncio.shield(task)
        self._warming = False
        if self.is_mounted:
            self._refresh_prompt_guide()

    async def _handle_approval_nav(self, key: str) -> bool:
        if not self._approval_menu.visible or self._busy:
            return False
        if key == "up":
            self._approval_menu.action_move_up()
            return True
        if key == "down":
            self._approval_menu.action_move_down()
            return True
        if key in {"enter", "y"}:
            self._approval_menu.action_confirm()
            return True
        if key in {"escape", "n"}:
            self._approval_menu.action_select_reject()
            return True
        return False

    async def action_cycle_approval_mode(self) -> None:
        self._approval_mode = self._approval_mode.cycle_next()
        label = self._approval_mode.display_label()
        await self._note(f"Permission mode: {label}")
        self._refresh_prompt_guide()
        await self._auto_approve_pending_if_allowed()

    async def action_interrupt(self) -> None:
        """Ctrl+C: interrupt → copy → double-press to exit.

        Priority:
        1. A turn is running → interrupt it (same as Ctrl+G).
        2. Idle with a text selection → copy it (OSC 52). Textual turns mouse
           drags into a selection; this is what lets the user actually copy it
           instead of quitting. (No mouse? Use ``/copy`` for the last reply.)
        3. Idle, nothing selected → first press arms exit and shows a hint, a
           second press within the window quits.
        """
        if self._busy:
            self._disarm_quit()
            await self.action_cancel_turn()
            return

        selected: str | None = None
        with contextlib.suppress(Exception):
            selected = self.screen.get_selected_text()
        if selected:
            self.copy_to_clipboard(selected)
            with contextlib.suppress(Exception):
                self.screen.selections = {}
            self._disarm_quit()
            self.notify("Copied selection to clipboard.", timeout=2.0)
            return

        if self._quit_armed:
            self.exit()
            return
        self._arm_quit()

    def _arm_quit(self) -> None:
        self._quit_armed = True
        self.notify("Press Ctrl+C again to exit.", timeout=2.0)
        if self._quit_timer is not None:
            self._quit_timer.stop()
        self._quit_timer = self.set_timer(2.0, self._disarm_quit)

    def _disarm_quit(self) -> None:
        self._quit_armed = False
        if self._quit_timer is not None:
            self._quit_timer.stop()
            self._quit_timer = None

    async def _auto_approve_pending_if_allowed(self) -> None:
        """Resume an already-shown approval once a mode change clears it.

        Mirrors the menu-driven path: hide the menu and drop the transient
        approval cards before resuming so nothing stale lingers in the log.
        """
        if not (self._pending_interrupts and self._should_auto_approve_pending()):
            return
        self._hide_approval_menu()
        await self._clear_approval_blocks()
        resume_payload = self._build_resume_payload({"type": "approve"})
        await self._resume_turn(resume_payload)

    async def on_approval_menu_selected(self, event: ApprovalMenu.Selected) -> None:
        if not self._pending_interrupts or self._busy:
            return
        option = event.option
        for category in option.allowlist_categories:
            self._tool_allowlist.add(category)
            label = category.replace("_", " ")
            await self._note(f"Always allow {label} for this session.")
        self._hide_approval_menu()
        await self._resume_pending(option.decision)

    def on_markdown_link_clicked(self, event: Markdown.LinkClicked) -> None:
        """Open file:// links in the OS default application."""
        href = event.href
        if href.startswith("file://"):
            path = Path(urllib.request.url2pathname(urllib.parse.urlparse(href).path))
            open_path(path)
            event.prevent_default()

    def on_resize(self, _event: events.Resize) -> None:
        if self._resize_timer is not None:
            self._resize_timer.stop()
        self._resize_timer = self.set_timer(
            _RESIZE_DEBOUNCE_SECONDS,
            self._refresh_after_resize,
        )

    def _refresh_after_resize(self) -> None:
        # Textual handles widget layout on its own, but our markdown bodies
        # don't re-wrap until their content is re-rendered, so nudge each
        # wrapping widget explicitly. A whole-screen refresh covers the rest.
        self._resize_timer = None
        # This is a debounced timer callback; it can fire while the app is tearing
        # down (e.g. the test harness exiting), when there is no active screen.
        # Touching `self.screen` then raises ScreenStackError, so bail out.
        if not self.screen_stack:
            return
        for widget in (
            *self.query(MessageBlock),
            *self.query(ApprovalBlock),
            *self.query(ToolBlock),
        ):
            widget.refresh_for_width()
        self.screen.refresh(layout=True, repaint=True)

    def _schedule_scroll_end(self) -> None:
        if self._scroll_timer is not None:
            self._scroll_timer.stop()
        self._scroll_timer = self.set_timer(
            _SCROLL_DEBOUNCE_SECONDS,
            self._flush_scroll_end,
        )

    def _flush_scroll_end(self) -> None:
        self._scroll_timer = None
        if not self.is_mounted:
            return
        self._log.scroll_end(animate=False)

    def _set_status(self, text: str) -> None:
        self._status_text = text
        self.query_one("#status", StatusBar).set_state(
            pending_count=len(self._pending_interrupts),
            tool_toggle_available=any(block.expandable for block in self._tool_blocks),
            tools_expanded=self._tools_expanded,
            approval_mode_label=self._approval_mode.display_label(),
        )
        self._refresh_prompt_guide()

    def on_text_area_changed(self, event) -> None:
        if event.text_area.id != "prompt":
            return
        if getattr(event.text_area, "consume_changed_suppression", lambda: False)():
            return
        if self._setting_prompt_value:
            self._setting_prompt_value = False
        elif self._history.is_navigating:
            self._history.reset()
        self._refresh_prompt_guide()

    async def on_prompt_text_area_submitted(self, event: PromptTextArea.Submitted) -> None:
        if self._busy:
            return
        text = event.value.strip()
        if not text:
            return

        self._history.record(text)
        self._history.reset()
        self._prompt.clear()

        if text.startswith("/"):
            await self._handle_command(text)
            return

        if self._pending_interrupts:
            await self._note("approval is pending. Use the menu above or a slash command.")
            return

        self._prompt.disabled = True
        self._busy = True
        self._cancel_requested = False
        self._julia_running_on_cancel = False

        await self._mount_welcome_if_empty()
        user_block = MessageBlock("You", "user", text, markdown="\n" in text)
        await self._log.mount(user_block)
        self._log.scroll_end(animate=False)
        self._set_status("thinking…")

        self._turn_worker = self.run_worker(self._run_turn(text), exclusive=True, name="turn")

    def on_prompt_text_area_history_previous(self, event: PromptTextArea.HistoryPrevious) -> None:
        if self._prompt.disabled:
            return
        new_value = self._history.up(event.current_text)
        if new_value is None:
            return
        self._set_prompt_value(new_value)
        self._refresh_prompt_guide()

    def on_prompt_text_area_history_next(self, event: PromptTextArea.HistoryNext) -> None:
        if self._prompt.disabled:
            return
        new_value = self._history.down()
        if new_value is None:
            return
        self._set_prompt_value(new_value)
        self._refresh_prompt_guide()

    def action_complete_prompt(self) -> None:
        prompt_input = self._prompt
        if self.focused is not prompt_input or prompt_input.disabled:
            return

        command, separator, rest = prompt_input.value.partition(" ")
        if not command.startswith("/") or (separator and rest):
            return

        matches = matching_specs(command, self._command_specs())
        if len(matches) != 1:
            self._refresh_prompt_guide()
            return

        completed = matches[0].name
        if not separator and matches[0].argument_hint:
            completed += " "
        self._set_prompt_value(completed)
        self._refresh_prompt_guide()

    async def _handle_command(self, command: str) -> None:
        """Dispatch a slash command to its ``_command_<name>`` handler.

        The handler method is named by the spec (``SlashCommandSpec.handler_attr``),
        so declaring a spec in ``commands.py`` and defining the method here is all
        it takes to add a command.
        """
        head, _, tail = command.partition(" ")
        spec = find_command(head.lower())
        if spec is None:
            await self._note(f"unknown command: {head}. Try /help.")
            return
        await getattr(self, spec.handler_attr)(tail.strip())

    async def _command_transcript(self, arg: str) -> None:
        fmt = arg.lower()
        if fmt in ("", "html"):
            target = self._session.output_dir / "transcript.html"
            with TraceLog(self._session.state_dir / "trace.sqlite") as log_db:
                content = render_html(log_db.iter_events())
        elif fmt in ("md", "markdown"):
            target = self._session.output_dir / "transcript.md"
            with TraceLog(self._session.state_dir / "trace.sqlite") as log_db:
                content = render_markdown(log_db.iter_events())
        else:
            await self._note("usage: /transcript [md]")
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        open_path(target)
        await self._note(f"transcript written to {target}")

    async def _command_copy(self, _arg: str) -> None:
        await self._copy_last_assistant_message()

    async def _command_clear(self, _arg: str) -> None:
        await self._clear_visible_log()

    async def _command_quit(self, _arg: str) -> None:
        self.exit()

    async def _command_approve(self, _arg: str) -> None:
        await self._resume_pending({"type": "approve"})

    async def _command_reject(self, arg: str) -> None:
        decision: dict[str, str] = {"type": "reject"}
        if arg:
            decision["message"] = arg
        await self._resume_pending(decision)

    async def _command_respond(self, arg: str) -> None:
        if not arg:
            await self._note("usage: /respond <message>")
            return
        await self._resume_pending({"type": "respond", "message": arg})

    async def _command_help(self, _arg: str) -> None:
        lines = [f"{spec.name:<11} — {spec.description}" for spec in self._command_specs()]
        await self._note("\n".join(lines))

    async def _command_approval_mode(self, arg: str) -> None:
        if not arg:
            await self._note(
                f"approval mode is `{self._approval_mode.value}`. "
                "Usage: /approval-mode ask|workspace|auto"
            )
            return
        try:
            self._approval_mode = parse_approval_mode(arg)
        except ValueError as exc:
            await self._note(str(exc))
            return
        await self._note(
            f"approval mode set to `{self._approval_mode.value}` for this session. "
            "Restart jutul-agent to change which tools interrupt at build time."
        )
        await self._auto_approve_pending_if_allowed()
        self._refresh_prompt_guide()

    async def _note(self, text: str) -> None:
        await self._log.mount(MessageBlock("System", "system", text))
        self._schedule_scroll_end()

    async def _copy_last_assistant_message(self) -> None:
        """Copy the most recent assistant reply to the clipboard (OSC 52).

        A reliable alternative to mouse-selection when the terminal doesn't
        cooperate with Textual's text selection.
        """
        assistant_blocks = [
            block for block in self._log.query(MessageBlock) if block.has_class("assistant")
        ]
        if not assistant_blocks:
            await self._note("no assistant message to copy yet")
            return
        self.copy_to_clipboard(assistant_blocks[-1].content_text)
        await self._note("copied the last assistant message to the clipboard")

    async def _command_add_dir(self, raw: str) -> None:
        """Mount a folder into the agent filesystem, or list mounted folders.

        With no argument, lists the folders already mounted this session; with a
        path, mounts it writable under ``/dirs/<name>/`` so the file tools can
        reach it. The route is live for the agent's next tool call.
        """
        if self._backend is None:
            await self._note("adding folders isn't available in this session.")
            return

        path = raw.strip().strip("\"'")
        if not path:
            mounts = mounted_dirs(self._backend)
            if mounts:
                lines = ["Mounted folders:"]
                lines += [f"  `{mount.route}` -> {mount.path}" for mount in mounts]
                await self._note("\n".join(lines))
            else:
                await self._note(
                    "usage: /add-dir <path> — mount a folder so the agent can read and edit it"
                )
            return

        try:
            mount = mount_dir(self._backend, path, workspace=workspace_root())
        except MountError as exc:
            await self._note(f"could not add folder: {exc}")
            return

        await self._note(
            f"Mounted `{mount.path}` at `{mount.route}`. The agent can read, grep, "
            f"write, and edit it with the file tools; in Julia or shell use the "
            f"absolute path `{mount.path}`."
        )

    async def _command_model(self, raw: str) -> None:
        """Open the selector, or switch directly to a given ``provider:model``."""
        target = raw.strip().strip("\"'")
        if not target:
            self.push_screen(ModelMenu(current=self._model_label), self._after_model_menu)
            return
        await self._switch_model(target)

    def _after_model_menu(self, choice: ModelChoice | None) -> None:
        if choice is None:
            return
        model_id, scope = choice
        self.run_worker(self._switch_model(model_id, scope=scope), name="model-switch")

    async def _switch_model(self, model_id: str, *, scope: str = "workspace") -> None:
        """Switch to ``model_id``, prompting for a missing provider key first.

        Refused while a turn is running or an approval is pending. Local models
        go through ``_prepare_local_model`` instead of the key prompt.
        """
        if self._agent_factory is None:
            await self._note("switching models isn't available in this session.")
            return
        if self._busy or self._pending_interrupts:
            await self._note("finish or cancel the current turn before switching models.")
            return
        if model_id == self._model_label:
            await self._note(f"already using `{model_id}`.")
            return

        from jutul_agent.models import is_local

        if is_local(model_id):
            await self._prepare_local_model(model_id, scope)
            return

        from jutul_agent.credentials import missing_credential

        env_var = missing_credential(model_id)
        if env_var is not None:
            self._prompt_api_key(model_id, scope, env_var)
            return
        await self._apply_model(model_id, scope)

    async def _prepare_local_model(self, model_id: str, scope: str) -> None:
        """Check a local (Ollama) model is reachable, pulled, and tool-capable,
        then switch. Reports if the server is down; pulls the model if missing.
        """
        from jutul_agent import ollama_client
        from jutul_agent.models import is_ollama_cloud

        if not await ollama_client.is_reachable():
            await self._note(
                f"Ollama isn't reachable at {ollama_client.host()}. Start it with "
                "`ollama serve` (or install it from https://ollama.com), then try again."
            )
            return
        if is_ollama_cloud(model_id):
            # Hosted by Ollama (needs `ollama signin`); nothing to pull locally.
            await self._apply_model(model_id, scope)
            return
        name = ollama_client.model_name(model_id)
        if await ollama_client.is_installed(name):
            await self._apply_local_if_tool_capable(model_id, scope, name)
            return

        def _after_pull(ok: bool | None) -> None:
            if ok:
                self.run_worker(
                    self._apply_local_if_tool_capable(model_id, scope, name), name="model-switch"
                )
            else:
                self.run_worker(
                    self._note(f"`{name}` was not pulled; switch cancelled."),
                    name="model-note",
                )

        self.push_screen(OllamaPullModal(model_name=name), _after_pull)

    async def _apply_local_if_tool_capable(self, model_id: str, scope: str, name: str) -> None:
        """Switch only if the daemon exposes tool calling for the model; the
        agent is tool-driven, so a tool-less model can't run here."""
        from jutul_agent import ollama_client

        if not await ollama_client.supports_tools(name):
            await self._note(
                f"`{model_id}` doesn't support tool calling, which this agent requires. "
                "Pick a tool-capable model, or update Ollama and re-pull if it should "
                "support tools."
            )
            return
        await self._apply_model(model_id, scope)

    def _prompt_api_key(self, model_id: str, scope: str, env_var: str) -> None:
        """Collect the provider key in a modal, store it, then resume the switch."""
        from jutul_agent.models import provider_info

        info = provider_info(model_id)
        label = info.label if info else model_id

        def _on_key(key: str | None) -> None:
            if not key:
                self.run_worker(
                    self._note(f"`{model_id}` needs {env_var}; switch cancelled."),
                    name="model-note",
                )
                return
            from jutul_agent.credentials import store_credential

            store_credential(env_var, key)
            self.run_worker(self._apply_model(model_id, scope), name="model-switch")

        self.push_screen(ApiKeyModal(env_var=env_var, provider_label=label), _on_key)

    async def _apply_model(self, model_id: str, scope: str) -> None:
        """Rebuild the agent on the new model and persist the choice.

        The rebuilt agent shares the session's checkpointer and thread id, so
        the conversation continues; ``/add-dir`` mounts are re-applied.
        """
        dirs = [mount.path for mount in mounted_dirs(self._backend)] if self._backend else []
        try:
            agent, backend = self._agent_factory(model_id, dirs)
        except Exception as exc:
            await self._note(f"could not switch to `{model_id}`: {exc}")
            return

        self._agent = agent
        self._backend = backend
        self._model_label = model_id
        self._turn_runner = TurnRunner(
            agent, thread_id=self._session.session_id, trace=self._session.trace
        )
        self.query_one("#status", StatusBar).set_model(model_id)
        self._refresh_subtitle()
        record_recent_model(model_id)
        where = self._persist_model(model_id, scope)
        await self._note(f"model changed to `{model_id}` (saved to {where}).")

    def _persist_model(self, model_id: str, scope: str) -> str:
        """Save the model to the workspace or user-global config.

        Returns where it was saved, for the confirmation note.
        """
        from dataclasses import replace

        try:
            if scope == "global":
                from jutul_agent.user_config import load_user_config, write_user_config

                write_user_config(replace(load_user_config(), model=model_id))
                return "user config"
            ws = workspace_root()
            from jutul_agent.workspace import load_workspace_config, write_workspace_config

            write_workspace_config(replace(load_workspace_config(ws), model=model_id), workspace=ws)
            return "this workspace"
        except OSError:
            return "this session only (could not write config)"

    def _refresh_subtitle(self) -> None:
        parts = [self._session.simulator.display_name]
        if self._model_label:
            parts.append(self._model_label)
        parts.append(self._session.session_id[:8])
        self.sub_title = " · ".join(parts)

    async def _run_turn(self, prompt: str) -> None:
        self._set_status("thinking…")
        try:
            result = await self._turn_runner.run_prompt(prompt, on_message=self._render_message)
            await self._apply_turn_result(result)
        except asyncio.CancelledError:
            await self._render_turn_cancelled()
            raise
        except Exception as exc:
            await self._render_turn_error(exc)
        finally:
            await self._finish_turn()

    async def _resume_turn(
        self,
        resume_payload: dict[str, dict[str, list[dict[str, str]]]],
    ) -> None:
        self._set_status("resuming…")
        try:
            result = await self._turn_runner.resume(resume_payload, on_message=self._render_message)
            await self._apply_turn_result(result)
        except asyncio.CancelledError:
            await self._render_turn_cancelled()
            raise
        except Exception as exc:
            await self._render_turn_error(exc)
        finally:
            await self._finish_turn()

    async def _render_turn_cancelled(self) -> None:
        await self._flush_stream()
        await self._mark_running_tools_cancelled()
        self._reset_approval_state()
        if self._julia_running_on_cancel:
            # The kernel interrupts the running eval (SIGINT) and keeps the session,
            # unless the eval was wedged and had to be restarted.
            preserved = getattr(self._session.julia, "cancel_preserved_state", True)
            message = (
                "Turn cancelled. Interrupted the running Julia command; loaded "
                "packages and variables are intact."
                if preserved
                else "Turn cancelled. The Julia command wouldn't interrupt, so the "
                "session was restarted and its state cleared."
            )
        else:
            message = "Turn cancelled."
        await self._log.mount(MessageBlock("System", "system", message))
        self._schedule_scroll_end()

    async def action_cancel_turn(self) -> None:
        if not self._busy or self._cancel_requested:
            return
        self._cancel_requested = True
        self._julia_running_on_cancel = self._has_running_julia_tool()
        self._set_status(
            "cancelling… (interrupting Julia)" if self._julia_running_on_cancel else "cancelling…"
        )
        worker = self._turn_worker
        if worker is not None:
            with contextlib.suppress(Exception):
                worker.cancel()

    def _has_running_julia_tool(self) -> bool:
        return any(
            block.status == "running" and block.tool_name in {"julia_eval", "julia_plot"}
            for block in self._tool_blocks
        )

    async def _mark_running_tools_cancelled(self) -> None:
        for block in self._tool_blocks:
            if block.status == "running":
                await block.set_cancelled("turn cancelled")

    def _reset_approval_state(self) -> None:
        self._pending_interrupts = []
        self._active_approval_blocks = []
        self._hide_approval_menu()

    async def _apply_turn_result(self, result: TurnRunResult) -> None:
        await self._flush_stream()
        self._pending_interrupts = result.interrupts
        if self._pending_interrupts:
            if self._should_auto_approve_pending():
                resume_payload = self._build_resume_payload({"type": "approve"})
                await self._resume_turn(resume_payload)
                return
            await self._render_interrupts(result.interrupts)
            return
        self._active_approval_blocks = []

    def _should_auto_approve_pending(self) -> bool:
        if not self._pending_interrupts:
            return False
        return all(
            should_auto_approve_interrupt(
                interrupt.value,
                self._approval_mode,
                allowlist=self._tool_allowlist,
            )
            for interrupt in self._pending_interrupts
        )

    async def action_approve_pending(self) -> None:
        if not self._pending_interrupts or self._busy:
            return
        if "approve" not in self._pending_allowed_decisions():
            return
        await self._resume_pending({"type": "approve"})

    async def action_reject_pending(self) -> None:
        if not self._pending_interrupts or self._busy:
            return
        if "reject" not in self._pending_allowed_decisions():
            return
        await self._resume_pending({"type": "reject"})

    async def _render_turn_error(self, exc: Exception) -> None:
        await self._flush_stream()
        await self._mark_running_tools_cancelled()
        self._reset_approval_state()
        await self._log.mount(MessageBlock("Error", "error", str(exc)))
        await self._note(
            "The turn stopped early. You can retry your last message or continue from here."
        )
        self._schedule_scroll_end()

    async def _finish_turn(self) -> None:
        # The kernel self-heals a cancelled eval (SIGINT + drain, keeping state), so
        # there's no force-restart here anymore; see ``JuliaKernel.eval``.
        self._cancel_requested = False
        self._julia_running_on_cancel = False
        self._busy = False
        self._set_status("approval required" if self._pending_interrupts else "ready")
        if not self._pending_interrupts:
            self._hide_approval_menu()
            self._prompt.focus()
        self._prompt.disabled = False
        self._refresh_prompt_guide()

    def _show_approval_menu(self) -> None:
        allowed = self._pending_allowed_decisions()
        tool_names = self._pending_tool_names()
        interrupt_values = [
            interrupt.value if isinstance(interrupt.value, dict) else {}
            for interrupt in self._pending_interrupts
        ]
        options = build_approval_options(
            allowed_decisions=allowed,
            tool_names=tool_names,
            interrupt_values=interrupt_values,
        )
        self._approval_menu.set_options(options)
        self._approval_menu.show_menu()
        self._prompt.focus()
        self._refresh_prompt_guide()

    def _hide_approval_menu(self) -> None:
        if self._approval_menu is not None:
            self._approval_menu.hide_menu()

    def _pending_tool_names(self) -> list[str]:
        names: list[str] = []
        for interrupt in self._pending_interrupts:
            value = interrupt.value if isinstance(interrupt.value, dict) else {}
            action_requests = value.get("action_requests")
            if not isinstance(action_requests, list):
                continue
            for action in action_requests:
                if isinstance(action, dict):
                    name = str(action.get("name") or "")
                    if name:
                        names.append(name)
        return names

    async def _render_message(self, msg: Any) -> None:
        # TurnRunner emits exactly these three event types (see agent/turns.py);
        # tool results arrive as TurnToolEvents, never as raw ToolMessages.
        if isinstance(msg, TurnReasoningDelta):
            await self._render_reasoning_delta(msg)
            return

        if isinstance(msg, TurnToolEvent):
            await self._render_tool_event(msg)
            return

        if isinstance(msg, AIMessageChunk):
            await self._render_message_chunk(msg)

    async def _render_reasoning_delta(self, msg: TurnReasoningDelta) -> None:
        await self._stream.append_reasoning(self._log, msg.text)
        if msg.text:
            self._schedule_scroll_end()
            self._set_status("thinking…")

    async def _render_tool_event(self, msg: TurnToolEvent) -> None:
        await self._flush_stream()
        if msg.event == "delta":
            block = self._matching_tool_block(
                tool_call_id=msg.tool_call_id,
                tool_name=msg.tool_name,
            )
            if block is None:
                block = self._new_tool_block(msg.tool_name, tool_call_id=msg.tool_call_id)
                self._tool_blocks.append(block)
                await self._log.mount(block)
            await block.append_output(msg.content)
            self._schedule_scroll_end()
            return

        if msg.event in {"requested", "started"}:
            await self._mount_tool_call(
                {"name": msg.tool_name, "args": msg.args or {}, "id": msg.tool_call_id}
            )
            self._schedule_scroll_end()
            return

        block = self._matching_tool_block(
            tool_call_id=msg.tool_call_id,
            tool_name=msg.tool_name,
        )
        if block is None:
            block = self._new_tool_block(msg.tool_name, tool_call_id=msg.tool_call_id)
            await self._log.mount(block)
            self._tool_blocks.append(block)
        await block.set_result(msg.content, is_error=msg.event == "error")
        self._schedule_scroll_end()
        self._set_status("thinking…")

    async def _render_message_chunk(self, msg: AIMessageChunk) -> None:
        text = self._extract_chunk_text(msg)
        if text:
            await self._stream.append_prose(self._log, text)

        tool_calls = self._extract_chunk_tool_calls(msg)
        if tool_calls:
            await self._flush_stream()
            for call in tool_calls:
                await self._mount_tool_call(call)

        if getattr(msg, "chunk_position", None) == "last" and not tool_calls:
            await self._flush_stream()

        if text or tool_calls:
            self._schedule_scroll_end()

    async def _flush_stream(self) -> None:
        await self._stream.flush()

    async def _mount_tool_call(self, call: dict[str, Any]) -> None:
        name = call.get("name") or "tool"
        tool_call_id = str(call.get("id")) if call.get("id") else None
        existing = self._matching_tool_block(tool_call_id=tool_call_id, tool_name=name)
        if existing is not None:
            return

        block = self._new_tool_block(
            name,
            call.get("args") if isinstance(call.get("args"), dict) else None,
            tool_call_id=tool_call_id,
        )
        # Append before awaiting mount so concurrent emitters (e.g. the
        # ``requested`` event from the message stream racing the ``started``
        # event from the tool-call projection) see the block and dedupe.
        self._tool_blocks.append(block)
        await self._log.mount(block)
        if name in {"julia_eval", "julia_plot"}:
            block.start_elapsed_timer()
        self._set_status("updating plan…" if name == "write_todos" else f"running {name}…")

    def _extract_chunk_text(self, msg: AIMessageChunk) -> str:
        blocks = getattr(msg, "content_blocks", None)
        if isinstance(blocks, list):
            text_parts = [
                str(block.get("text") or "")
                for block in blocks
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            if text_parts:
                return "".join(text_parts)

        content = getattr(msg, "content", "")
        if isinstance(content, str):
            return content
        return content_to_str(content)

    def _extract_chunk_tool_calls(self, msg: AIMessageChunk) -> list[dict[str, Any]]:
        raw_calls = getattr(msg, "tool_calls", None)
        if isinstance(raw_calls, list) and raw_calls:
            return [
                call
                for raw_call in raw_calls
                if (call := self._normalize_tool_call(raw_call)) is not None
            ]

        blocks = getattr(msg, "content_blocks", None)
        if not isinstance(blocks, list):
            return []

        calls: list[dict[str, Any]] = []
        for block in blocks:
            if not isinstance(block, dict) or block.get("type") not in {
                "tool_call",
                "tool_call_chunk",
            }:
                continue
            normalized = self._normalize_tool_call(block)
            if normalized is not None:
                calls.append(normalized)
        return calls

    def _normalize_tool_call(self, raw_call: dict[str, Any]) -> dict[str, Any] | None:
        name = raw_call.get("name")
        if not isinstance(name, str) or not name:
            return None

        args = raw_call.get("args")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                return None
        if args is None:
            args = {}
        if not isinstance(args, dict):
            args = {"value": args}

        normalized: dict[str, Any] = {"name": name, "args": args}
        if raw_call.get("id"):
            normalized["id"] = str(raw_call["id"])
        return normalized

    async def _render_interrupts(self, interrupts: list[TurnInterrupt]) -> None:
        self._active_approval_blocks = []
        rendered_cards = 0
        for interrupt in interrupts:
            await self._mark_tool_blocks_pending_approval(interrupt)
            for card in render_interrupt_cards(
                interrupt.interrupt_id,
                interrupt.value,
                workspace_root=workspace_root(),
            ):
                block = ApprovalBlock(card)
                await self._log.mount(block)
                self._active_approval_blocks.append(block)
                rendered_cards += 1

        commands = ", ".join(self._approval_help_lines())
        if commands:
            prefix = "approval is pending" if rendered_cards else "approval required"
            await self._note(f"{prefix}. Select an option in the menu below.")
        else:
            await self._note("approval required. This request cannot be resolved from the TUI.")
        self._show_approval_menu()
        self._set_status("approval required")
        self._refresh_prompt_guide()
        self._schedule_scroll_end()

    async def _resume_pending(self, decision: dict[str, str]) -> None:
        if not self._pending_interrupts:
            await self._note("no approval is pending")
            return

        allowed = self._pending_allowed_decisions()
        decision_type = decision["type"]
        if decision_type not in allowed:
            rendered = ", ".join(sorted(allowed)) or "(none)"
            await self._note(f"`{decision_type}` is not allowed here. Allowed: {rendered}.")
            return

        self._hide_approval_menu()
        resume_payload = self._build_resume_payload(decision)
        self._prompt.disabled = True
        self._busy = True
        self._cancel_requested = False
        self._julia_running_on_cancel = False
        await self._preview_pending_decision(decision)
        self._set_status("resuming…")
        self._turn_worker = self.run_worker(
            self._resume_turn(resume_payload), exclusive=True, name="turn"
        )

    async def action_clear_visible_log(self) -> None:
        await self._clear_visible_log()

    async def action_toggle_tool_output(self) -> None:
        """Ctrl+O: toggle verbose tool output for every tool card in the log."""
        self._tools_expanded = not self._tools_expanded
        for block in list(self._tool_blocks):
            await block.set_expanded(self._tools_expanded)
        self._set_status(self._status_text)
        self._schedule_scroll_end()

    async def _clear_visible_log(self) -> None:
        if self._busy:
            await self._note("cannot clear the log while a turn is running")
            return
        if self._pending_interrupts:
            await self._note("cannot clear the log while approval is pending")
            return

        await self._log.remove_children()
        self._stream = _AssistantStream()
        self._tool_blocks.clear()
        self._active_approval_blocks.clear()
        await self._mount_welcome_if_empty()
        self._set_status("ready")
        self._refresh_prompt_guide()

    async def _mount_welcome_if_empty(self) -> None:
        if self._log.children:
            return
        await self._log.mount(
            WelcomeBlock(
                simulator_label=self._session.simulator.display_name,
                session_id=self._session.session_id,
            )
        )
        self._schedule_scroll_end()

    def _approval_help_lines(self) -> list[str]:
        return approval_command_hints(self._pending_allowed_decisions())

    def _command_specs(self) -> list[SlashCommandSpec]:
        return active_commands(self._pending_allowed_decisions())

    def _refresh_prompt_guide(self) -> None:
        guide = self.query_one("#prompt-guide", PromptGuide)
        guide.set_message(self._compute_prompt_guide())
        guide.set_activity(self._activity_label())

    def _activity_label(self) -> str:
        # Lives in the bottom bar (next to the input) and composes the turn
        # status with the background warm-up so warming stays visible during a
        # turn instead of being replaced by "thinking…".
        if self._pending_interrupts:
            return "approval required"
        parts: list[str] = []
        if self._busy:
            parts.append(self._status_text)
        if self._warming:
            parts.append("warming Julia")
        return " · ".join(parts) if parts else "ready"

    def _compute_prompt_guide(self) -> str:
        position = self._history.position
        if position is not None:
            idx, total = position
            return f"History {idx}/{total} · Ctrl+P/↑ prev · Ctrl+N/↓ next"
        if self._pending_interrupts:
            value = self._prompt.value
            if value.startswith("/"):
                return self._command_guide(value)
            if self._approval_menu.visible:
                return "↑/↓ select · Enter confirm · Esc reject · Shift+Tab cycle mode"
            return "approval pending"
        if self._busy:
            return "Ctrl+G cancel"
        value = self._prompt.value
        if value.startswith("/"):
            return self._command_guide(value)
        if self._tools_expanded:
            tool_hint = " · Ctrl+O collapse tool output"
        elif any(block.expandable for block in self._tool_blocks):
            tool_hint = " · Ctrl+O expand tool output"
        else:
            tool_hint = ""
        mode_hint = f" · {self._approval_mode.display_label()}"
        return (
            "Enter send · Shift+Enter newline · Ctrl+P/↑ history · Shift+Tab cycle mode"
            f"{tool_hint}{mode_hint}"
        )

    def _command_guide(self, value: str) -> str:
        command, separator, rest = value.partition(" ")
        specs = self._command_specs()
        exact = next((spec for spec in specs if spec.name == command), None)

        if separator and not rest and exact and exact.argument_hint:
            return f"{exact.name} {exact.argument_hint} · Enter send · Up/Down history"

        matches = matching_specs(command, specs)
        if len(matches) == 1 and exact is not None:
            detail = exact.description
            if exact.argument_hint and not separator:
                detail += f" · {exact.argument_hint}"
            return f"{exact.name} · {detail}"

        if matches:
            rendered = " · ".join(spec.name for spec in matches[:5])
            if len(matches) > 5:
                rendered += " · ..."
            return f"Tab completes unique match · {rendered}"

        return "Unknown command · /help lists available commands"

    def _set_prompt_value(self, value: str) -> None:
        prompt_input = self._prompt
        self._setting_prompt_value = True
        prompt_input.suppress_next_changed()
        prompt_input.value = value

    def _pending_allowed_decisions(self) -> frozenset[str]:
        """Decisions every pending interrupt accepts, scoped to what the TUI can do."""

        shared: frozenset[str] | None = None
        for interrupt in self._pending_interrupts:
            allowed = allowed_decisions_for_interrupt(interrupt.value)
            shared = allowed if shared is None else shared & allowed
        if shared is None:
            return frozenset()
        return shared & SUPPORTED_APPROVAL_DECISIONS

    def _build_resume_payload(
        self,
        decision: dict[str, str],
    ) -> dict[str, dict[str, list[dict[str, str]]]]:
        payload: dict[str, dict[str, list[dict[str, str]]]] = {}
        for interrupt in self._pending_interrupts:
            value = interrupt.value if isinstance(interrupt.value, dict) else {}
            action_requests = value.get("action_requests")
            count = len(action_requests) if isinstance(action_requests, list) else 1
            payload[interrupt.interrupt_id] = {
                "decisions": [deepcopy(decision) for _ in range(count)]
            }
        return payload

    def _new_tool_block(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        *,
        tool_call_id: str | None = None,
    ) -> ToolBlock:
        """Construct a tool card that honours the current verbose mode."""
        return ToolBlock(name, args, tool_call_id=tool_call_id, expanded=self._tools_expanded)

    def _matching_tool_block(
        self,
        *,
        tool_call_id: str | None,
        tool_name: str,
    ) -> ToolBlock | None:
        if tool_call_id is not None:
            for block in reversed(self._tool_blocks):
                if block.tool_call_id == tool_call_id:
                    return block
        for block in reversed(self._tool_blocks):
            if block.tool_name == tool_name and not block.has_output:
                return block
        return None

    async def _mark_tool_blocks_pending_approval(self, interrupt: TurnInterrupt) -> None:
        value = interrupt.value if isinstance(interrupt.value, dict) else {}
        action_requests = value.get("action_requests")
        if not isinstance(action_requests, list):
            return

        used: set[int] = set()
        for action in action_requests:
            if not isinstance(action, dict):
                continue
            tool_name = str(action.get("name") or "tool")
            for block in reversed(self._tool_blocks):
                if id(block) in used or block.tool_name != tool_name or block.has_output:
                    continue
                await block.set_pending_approval()
                used.add(id(block))
                break

    async def _clear_approval_blocks(self) -> None:
        """Remove the pending approval cards from the log.

        The cards are transient: their only job is to show the diff/command
        while the user decides. Once decided, the outcome is carried by the
        tool card (running / rejected) and the durable record lives in the
        SQLite trace, so leaving a stale colored card in the log just clutters
        the conversation.
        """
        for block in self._active_approval_blocks:
            with contextlib.suppress(Exception):
                await block.remove()
        self._active_approval_blocks = []

    async def _preview_pending_decision(self, decision: dict[str, str]) -> None:
        decision_type = decision.get("type") or "pending"
        reason = decision.get("message")

        await self._clear_approval_blocks()

        if decision_type == "approve":
            for block in self._tool_blocks:
                if not block.has_output:
                    await block.set_running()
            return

        if decision_type == "reject":
            for block in self._tool_blocks:
                if not block.has_output:
                    await block.set_rejected(reason)
