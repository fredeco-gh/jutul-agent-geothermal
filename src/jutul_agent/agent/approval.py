"""Human-in-the-loop approval modes for workspace file and shell tools."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from langchain.agents.middleware import InterruptOnConfig

# Tools that require human approval. Action name → human-readable description
# shown in the approval card. All entries use approve/reject only.
_APPROVAL_TOOLS: dict[str, str] = {
    "execute": "Run a shell command in the workspace.",
    "write_file": "Write a file in the workspace.",
    "edit_file": "Edit a file in the workspace.",
}

_WORKSPACE_EDIT_TOOLS = frozenset({"write_file", "edit_file"})
_SHELL_TOOLS = frozenset({"execute"})

# Session allowlist categories.
ALLOWLIST_FILE_EDITS = "file_edits"
ALLOWLIST_SHELL = "shell"


def interrupt_on_config() -> dict[str, InterruptOnConfig]:
    """``interrupt_on`` map keyed by tool name (used by `create_deep_agent`)."""

    return {
        name: {"allowed_decisions": ["approve", "reject"], "description": description}
        for name, description in _APPROVAL_TOOLS.items()
    }


class ApprovalMode(StrEnum):
    """How side-effecting Deep Agents tools are gated before execution."""

    ASK = "ask"
    """Prompt before execute, write_file, and edit_file (default)."""

    WORKSPACE = "workspace"
    """Auto-allow workspace write_file and edit_file; still prompt for execute."""

    AUTO = "auto"
    """Auto-allow all configured approval tools (non-interactive trust mode)."""

    def display_label(self) -> str:
        return {
            ApprovalMode.ASK: "default",
            ApprovalMode.WORKSPACE: "accept edits",
            ApprovalMode.AUTO: "auto",
        }[self]

    def cycle_next(self) -> ApprovalMode:
        order = (ApprovalMode.ASK, ApprovalMode.WORKSPACE, ApprovalMode.AUTO)
        index = order.index(self)
        return order[(index + 1) % len(order)]


class ToolAllowlist:
    """Per-session categories the user chose to always allow."""

    def __init__(self) -> None:
        self._categories: set[str] = set()

    def add(self, category: str) -> None:
        self._categories.add(category)

    def contains(self, category: str) -> bool:
        return category in self._categories

    def __bool__(self) -> bool:
        return bool(self._categories)

    def categories(self) -> frozenset[str]:
        return frozenset(self._categories)


def tool_allowlist_category(tool_name: str) -> str | None:
    if tool_name in _WORKSPACE_EDIT_TOOLS:
        return ALLOWLIST_FILE_EDITS
    if tool_name in _SHELL_TOOLS:
        return ALLOWLIST_SHELL
    return None


def categories_for_interrupt(value: Any) -> frozenset[str]:
    if not isinstance(value, dict):
        return frozenset()
    action_requests = value.get("action_requests")
    if not isinstance(action_requests, list):
        return frozenset()
    categories: set[str] = set()
    for action in action_requests:
        if not isinstance(action, dict):
            continue
        category = tool_allowlist_category(str(action.get("name") or ""))
        if category:
            categories.add(category)
    return frozenset(categories)


def interrupt_matches_allowlist(value: Any, allowlist: ToolAllowlist) -> bool:
    categories = categories_for_interrupt(value)
    if not categories:
        return False
    return all(allowlist.contains(category) for category in categories)


def parse_approval_mode(value: str | None) -> ApprovalMode:
    if not value:
        return ApprovalMode.ASK
    normalized = value.strip().lower()
    for mode in ApprovalMode:
        if mode == normalized:
            return mode
    raise ValueError(
        f"unknown approval mode {value!r}; expected one of: "
        + ", ".join(m.value for m in ApprovalMode)
    )


def interrupt_on_for_mode(mode: ApprovalMode) -> dict[str, InterruptOnConfig]:
    """Map an approval mode to Deep Agents ``interrupt_on`` configuration."""

    if mode == ApprovalMode.AUTO:
        return {}
    if mode == ApprovalMode.WORKSPACE:
        full = interrupt_on_config()
        return {name: cfg for name, cfg in full.items() if name == "execute"}
    return interrupt_on_config()


def interrupt_is_workspace_edits_only(value: Any) -> bool:
    """True when every action in an interrupt is write_file or edit_file."""

    if not isinstance(value, dict):
        return False
    action_requests = value.get("action_requests")
    if not isinstance(action_requests, list) or not action_requests:
        return False
    for action in action_requests:
        if not isinstance(action, dict):
            return False
        if action.get("name") not in _WORKSPACE_EDIT_TOOLS:
            return False
    return True


def should_auto_approve_interrupt(
    value: Any,
    mode: ApprovalMode,
    *,
    allowlist: ToolAllowlist | None = None,
) -> bool:
    if allowlist is not None and interrupt_matches_allowlist(value, allowlist):
        return True
    if mode == ApprovalMode.AUTO:
        return True
    if mode == ApprovalMode.WORKSPACE:
        return interrupt_is_workspace_edits_only(value)
    return False
