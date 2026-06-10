"""Slash-command catalog, input history, and Suggester for the TUI prompt.

The state machines are plain dataclasses with no Textual dependency aside
from the ``Suggester`` adapter at the bottom.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from textual.suggester import Suggester


@dataclass(frozen=True)
class SlashCommandSpec:
    """One slash command with a human-readable help string and optional argument hint."""

    name: str
    description: str
    argument_hint: str = ""

    @property
    def decision(self) -> str:
        """Strip the leading slash; matches deepagents' decision names for approval commands."""

        return self.name.removeprefix("/")

    @property
    def handler_attr(self) -> str:
        """Name of the TUIApp coroutine that executes this command.

        Derived from the command name (``/add-dir`` → ``_command_add_dir``), so
        declaring a spec here and defining that method is all it takes to add a
        command; help text, completion, and dispatch stay in sync by
        construction (a test asserts every spec resolves to a handler).
        """

        return "_command_" + self.decision.replace("-", "_")


BASE_COMMANDS: tuple[SlashCommandSpec, ...] = (
    SlashCommandSpec("/help", "show available commands"),
    SlashCommandSpec("/transcript", "write transcript (HTML; append 'md' for markdown)"),
    SlashCommandSpec("/copy", "copy the last assistant message to the clipboard"),
    SlashCommandSpec("/clear", "clear the visible log"),
    SlashCommandSpec(
        "/add-dir",
        "mount an extra folder so the agent can read and edit it",
        "<path>",
    ),
    SlashCommandSpec(
        "/model",
        "open the model selector, or switch to a given model",
        "[provider:model]",
    ),
    SlashCommandSpec(
        "/approval-mode",
        "set approval policy for this session",
        "[ask|workspace|auto]",
    ),
    SlashCommandSpec("/quit", "exit the TUI"),
)

APPROVAL_COMMANDS: tuple[SlashCommandSpec, ...] = (
    SlashCommandSpec("/approve", "approve the pending tool actions"),
    SlashCommandSpec("/reject", "reject the pending tool actions", "[reason]"),
    SlashCommandSpec("/respond", "reply to the pending tool actions", "<message>"),
)

ALL_COMMANDS: tuple[SlashCommandSpec, ...] = BASE_COMMANDS + APPROVAL_COMMANDS


def find_command(name: str) -> SlashCommandSpec | None:
    """The spec for ``name``, searched across every command.

    Dispatch matches against all commands (not just the active ones) so an
    approval command typed with nothing pending reaches its handler and gets
    the precise "no approval is pending" answer instead of "unknown command".
    """

    return next((spec for spec in ALL_COMMANDS if spec.name == name), None)


def active_commands(allowed_decisions: frozenset[str]) -> list[SlashCommandSpec]:
    """Base commands plus the approval commands the current interrupt permits."""

    specs = list(BASE_COMMANDS)
    for spec in APPROVAL_COMMANDS:
        if spec.decision in allowed_decisions:
            specs.append(spec)
    return specs


def matching_specs(prefix: str, specs: list[SlashCommandSpec]) -> list[SlashCommandSpec]:
    """Subset of ``specs`` whose names start with ``prefix``."""

    if not prefix.startswith("/"):
        return []
    return [spec for spec in specs if spec.name.startswith(prefix)]


class InputHistory:
    """Up/Down history navigation for the prompt input.

    Holds a list of past submissions plus a cursor. ``up`` and ``down`` return
    the value the prompt should display; ``record`` appends a new submission;
    ``reset`` is called whenever the user edits the prompt by hand, so the
    next ``up`` starts from a fresh draft.
    """

    def __init__(self) -> None:
        self._entries: list[str] = []
        self._index: int | None = None
        self._draft = ""

    @property
    def position(self) -> tuple[int, int] | None:
        """``(1-based index, total)`` while navigating, else ``None``."""

        if self._index is None:
            return None
        return self._index + 1, len(self._entries)

    @property
    def is_navigating(self) -> bool:
        return self._index is not None

    def record(self, text: str) -> None:
        if not self._entries or self._entries[-1] != text:
            self._entries.append(text)

    def reset(self) -> None:
        self._index = None
        self._draft = ""

    def up(self, current_value: str) -> str | None:
        """Move one step back through history; return the new prompt value, or ``None``."""

        if not self._entries:
            return None
        if self._index is None:
            self._draft = current_value
            self._index = len(self._entries) - 1
        elif self._index > 0:
            self._index -= 1
        return self._entries[self._index]

    def down(self) -> str | None:
        """Move one step forward; return the new prompt value (or the saved draft)."""

        if self._index is None:
            return None
        if self._index < len(self._entries) - 1:
            self._index += 1
            return self._entries[self._index]
        draft = self._draft
        self._index = None
        self._draft = ""
        return draft


class SlashCommandSuggester(Suggester):
    """Textual ``Suggester`` that ghosts the unique matching slash command.

    The command list is queried via ``commands_provider`` on every keystroke
    so that approval commands appear and disappear with the interrupt state.
    """

    def __init__(self, commands_provider: Callable[[], list[SlashCommandSpec]]) -> None:
        super().__init__(use_cache=False, case_sensitive=True)
        self._commands_provider = commands_provider

    async def get_suggestion(self, value: str) -> str | None:
        if not value.startswith("/") or " " in value:
            return None
        matches = matching_specs(value, self._commands_provider())
        if len(matches) != 1:
            return None
        spec = matches[0]
        if spec.argument_hint:
            return spec.name + " "
        return spec.name
