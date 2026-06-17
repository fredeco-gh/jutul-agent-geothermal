"""Selectable approval menu for pending tool interrupts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from rich.text import Text
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Static

from jutul_agent.agent.approval import (
    ALLOWLIST_FILE_EDITS,
    ALLOWLIST_SHELL,
    categories_for_interrupt,
)
from jutul_agent.interfaces.tui.approval import SUPPORTED_APPROVAL_DECISIONS


@dataclass(frozen=True)
class ApprovalOption:
    """One row in the approval selection menu."""

    label: str
    decision: dict[str, str]
    allowlist_categories: frozenset[str] = frozenset()


def build_approval_options(
    *,
    allowed_decisions: frozenset[str],
    tool_names: list[str],
    interrupt_values: list[dict],
) -> list[ApprovalOption]:
    """Build Yes / always-allow / No options for the current interrupt."""

    supported = allowed_decisions & SUPPORTED_APPROVAL_DECISIONS
    options: list[ApprovalOption] = []

    if "approve" in supported:
        options.append(
            ApprovalOption(label="Yes", decision={"type": "approve"}),
        )
        always_label = _always_allow_label(tool_names, interrupt_values)
        if always_label:
            categories: set[str] = set()
            for value in interrupt_values:
                categories.update(categories_for_interrupt(value))
            options.append(
                ApprovalOption(
                    label=always_label,
                    decision={"type": "approve"},
                    allowlist_categories=frozenset(categories),
                ),
            )

    if "reject" in supported:
        options.append(ApprovalOption(label="No", decision={"type": "reject"}))

    return options


def _always_allow_label(tool_names: list[str], interrupt_values: list[dict]) -> str | None:
    categories: set[str] = set()
    for value in interrupt_values:
        categories.update(categories_for_interrupt(value))
    if not categories:
        return None
    # Shell approvals are always one-off; no broad "always allow shell" policy.
    if categories == {ALLOWLIST_SHELL}:
        return None
    if categories == {ALLOWLIST_FILE_EDITS}:
        return "Yes, and always allow file edits in this workspace"
    if len(categories) == 1:
        name = next(iter(categories)).replace("_", " ")
        return f"Yes, and always allow {name} in this workspace"
    return "Yes, and always allow these actions in this workspace"


class ApprovalMenu(Vertical):
    """Arrow-key menu shown while a tool approval is pending."""

    DEFAULT_CSS = """
    ApprovalMenu {
        height: auto;
        padding: 0 1 1 1;
        display: none;
        border-top: solid $surface-lighten-1;
    }

    ApprovalMenu.visible {
        display: block;
    }

    ApprovalMenu .approval-question {
        height: auto;
        text-style: bold;
        padding: 1 0 0 0;
    }

    ApprovalMenu .approval-options {
        height: auto;
        padding: 0;
    }

    ApprovalMenu .approval-hint {
        height: auto;
        color: $text-muted;
        padding: 0;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("up", "move_up", "Up", show=False, priority=True),
        Binding("down", "move_down", "Down", show=False, priority=True),
        Binding("enter", "confirm", "Confirm", show=False, priority=True),
        Binding("y", "confirm", "Yes", show=False, priority=True),
        Binding("escape", "select_reject", "Reject", show=False, priority=True),
        Binding("n", "select_reject", "No", show=False, priority=True),
    ]

    class Selected(Message):
        """Posted when the user confirms a menu option."""

        def __init__(self, option: ApprovalOption) -> None:
            self.option = option
            super().__init__()

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._options: list[ApprovalOption] = []
        self._index = 0

    def compose(self):
        yield Static("Do you want to proceed?", classes="approval-question", id="approval-question")
        yield Static("", classes="approval-options", id="approval-options")
        yield Static("", classes="approval-hint", id="approval-menu-hint")

    def on_mount(self) -> None:
        self._refresh()

    def set_options(self, options: list[ApprovalOption]) -> None:
        self._options = options
        self._index = 0
        self._refresh()

    def show_menu(self) -> None:
        self.add_class("visible")
        self._index = 0
        self._refresh()

    def hide_menu(self) -> None:
        self.remove_class("visible")
        self._options = []
        self._index = 0

    @property
    def visible(self) -> bool:
        return self.has_class("visible")

    def _refresh(self) -> None:
        if not self.is_mounted:
            return
        options_widget = self.query_one("#approval-options", Static)
        hint_widget = self.query_one("#approval-menu-hint", Static)

        if not self._options:
            options_widget.update("")
            hint_widget.update("")
            return

        text = Text()
        for index, option in enumerate(self._options):
            selected = index == self._index
            prefix = "> " if selected else "  "
            number = f"{index + 1}. "
            style = "bold cyan" if selected else "dim"
            text.append(prefix, style=style)
            text.append(number, style=style)
            text.append(option.label, style=style)
            text.append("\n")
        options_widget.update(text)
        hint_widget.update("↑/↓ select · Enter confirm · Esc reject")

    def action_move_up(self) -> None:
        if self._index > 0:
            self._index -= 1
            self._refresh()

    def action_move_down(self) -> None:
        if self._index < len(self._options) - 1:
            self._index += 1
            self._refresh()

    def action_confirm(self) -> None:
        if not self._options:
            return
        self.post_message(self.Selected(self._options[self._index]))

    def action_select_reject(self) -> None:
        for option in self._options:
            if option.decision.get("type") == "reject":
                self.post_message(self.Selected(option))
                return
