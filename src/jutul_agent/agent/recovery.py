"""Recover the turn when the model's tool calls fail to parse.

A reply whose only tool calls are invalid (malformed JSON arguments) never
routes to the tool node: the loop treats it as a final answer and the agent
falls silent with no work done. This middleware feeds the parse errors back
as error tool results — the same shape the tool node uses — and sends the
model around for another attempt, so a recoverable formatting slip costs one
round-trip instead of the turn.

The motivating case was a local model that *intermittently* serializes two
parallel tool calls into a single call's argument string (``{...}{...}``).
Parallel calls are normal and wanted; the rare malformed serialization is a
generation-quality fault, so the fix belongs here — a generic, provider-
agnostic net — not in a prompt that would suppress parallel calls for every
turn to hedge against the occasional bad one.
"""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

# Consecutive recoveries allowed before giving up: a model that cannot emit
# valid JSON twice in a row will not manage it on the third spin either, and
# the turn has to end somewhere the user can see.
_MAX_CONSECUTIVE_RECOVERIES = 2

_RECOVERY_MARK = "invalid_tool_call_recovery"


class InvalidToolCallRecoveryMiddleware(AgentMiddleware):
    """Turn unparseable tool calls into error results and retry the model."""

    @hook_config(can_jump_to=["model"])
    def after_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        return _recover(state)

    @hook_config(can_jump_to=["model"])
    async def aafter_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        return _recover(state)


def _recover(state: Any) -> dict[str, Any] | None:
    messages = state.get("messages") if isinstance(state, dict) else getattr(state, "messages", [])
    if not messages:
        return None
    last = messages[-1]
    if not isinstance(last, AIMessage):
        return None
    if last.tool_calls or not last.invalid_tool_calls:
        return None
    if _consecutive_recoveries(messages) >= _MAX_CONSECUTIVE_RECOVERIES:
        return None

    errors = [
        ToolMessage(
            content=(
                f"Tool call could not be parsed: {call.get('error') or 'invalid arguments'}. "
                "Re-issue it as a single tool call with one valid JSON object as arguments."
            ),
            tool_call_id=str(call.get("id") or "invalid_tool_call"),
            name=call.get("name") or "tool",
            status="error",
            additional_kwargs={_RECOVERY_MARK: True},
        )
        for call in last.invalid_tool_calls
    ]
    return {"messages": errors, "jump_to": "model"}


def _consecutive_recoveries(messages: list[Any]) -> int:
    """Recovery results issued since the user last spoke."""
    count = 0
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            break
        if isinstance(message, ToolMessage) and (message.additional_kwargs or {}).get(
            _RECOVERY_MARK
        ):
            count += 1
    return count
