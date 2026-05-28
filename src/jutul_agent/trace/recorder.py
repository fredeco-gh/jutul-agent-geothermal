"""Middleware that records model and tool events to a `TraceLog`."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, ToolCallRequest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import Command

from jutul_agent.trace import TraceLog
from jutul_agent.trace.messages import content_to_str, reasoning_to_str


class TraceRecorder(AgentMiddleware):
    """Append model responses and tool round-trips to a trace log."""

    def __init__(self, trace: TraceLog) -> None:
        super().__init__()
        self._trace = trace

    async def aafter_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        messages = (
            state.get("messages") if isinstance(state, dict) else getattr(state, "messages", None)
        )
        if not messages:
            return None
        last = messages[-1]
        if not isinstance(last, AIMessage):
            return None
        reasoning = reasoning_to_str(last.content)
        if reasoning.strip():
            self._trace.append("message_reasoning", {"content": reasoning})
        content = content_to_str(last.content)
        if content.strip():
            self._trace.append("message_assistant", {"content": content})
        return None

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        call = request.tool_call
        self._trace.append(
            "tool_call",
            {"id": call.get("id"), "name": call.get("name"), "args": call.get("args")},
        )
        result = await handler(request)
        if isinstance(result, ToolMessage):
            self._trace.append(
                "tool_result",
                {
                    "tool_call_id": getattr(result, "tool_call_id", None),
                    "name": getattr(result, "name", None),
                    "content": content_to_str(result.content),
                },
            )
        return result
