"""Middleware that records model and tool events to a `TraceLog`."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, ToolCallRequest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.types import Command

from jutul_agent.trace import TraceLog
from jutul_agent.trace.messages import content_to_str, reasoning_to_str


class TraceRecorder(AgentMiddleware):
    """Append model responses and tool round-trips to a trace log."""

    def __init__(self, trace: TraceLog) -> None:
        super().__init__()
        self._trace = trace
        self._last_compaction: Any = None

    def _record_compaction(self, state: Any) -> None:
        """Emit a ``context_compaction`` event when the stock summarizer compacts.

        deepagents' SummarizationMiddleware is non-mutating: on the turns it
        compacts, it records a ``_summarization_event`` (a fresh summary message,
        a cutoff index, and the offload path). We surface that into the trace
        here, keyed on the summary message so each compaction is recorded once.
        """
        event = state.get("_summarization_event") if isinstance(state, dict) else None
        if not isinstance(event, dict):
            return
        marker = getattr(event.get("summary_message"), "id", None) or event.get("cutoff_index")
        if marker == self._last_compaction:
            return
        self._last_compaction = marker
        self._trace.append(
            "context_compaction",
            {
                "cutoff_index": event.get("cutoff_index"),
                "offloaded": event.get("file_path") is not None,
            },
        )

    async def aafter_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        self._record_compaction(state)
        messages = (
            state.get("messages") if isinstance(state, dict) else getattr(state, "messages", None)
        )
        if not messages:
            return None
        last = messages[-1]
        if not isinstance(last, AIMessage):
            return None
        # ``content_blocks`` normalizes provider-specific shapes (e.g. OpenAI
        # keeps reasoning summaries under a raw ``summary`` key that the
        # projection helpers don't know about).
        blocks = getattr(last, "content_blocks", None) or last.content
        reasoning = reasoning_to_str(blocks)
        if reasoning.strip():
            self._trace.append("message_reasoning", {"content": reasoning})
        content = content_to_str(blocks)
        if content.strip():
            self._trace.append("message_assistant", {"content": content})
        usage = getattr(last, "usage_metadata", None)
        if usage:
            # Token accounting per model turn; cost and efficiency analyses
            # read these events instead of re-deriving counts from text.
            self._trace.append("model_usage", dict(usage))
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
        try:
            result = await handler(request)
        except GraphBubbleUp:
            # Control-flow signals (approval interrupts, parent commands,
            # graph-drain bubbles) must propagate untouched. (Cancellation and
            # KeyboardInterrupt are BaseException, so `except Exception` below
            # never catches them.)
            raise
        except Exception as exc:
            # A tool raised instead of returning a result. Don't let one failed
            # tool call abort the entire turn: hand the error back to the model
            # as a tool result so it can recover (retry, pick another tool, fix
            # its arguments).
            result = _tool_error_result(call, exc)

        if isinstance(result, ToolMessage):
            self._trace.append(
                "tool_result",
                {
                    "tool_call_id": getattr(result, "tool_call_id", None),
                    "name": getattr(result, "name", None),
                    "content": content_to_str(result.content),
                    "status": getattr(result, "status", None),
                },
            )
        return result


def _tool_error_result(call: dict[str, Any], exc: Exception) -> ToolMessage:
    """Turn a raised tool exception into an error ``ToolMessage`` for the model."""

    name = call.get("name") or "tool"
    content = f"Error running tool `{name}`: {type(exc).__name__}: {exc}"
    return ToolMessage(
        content=content,
        tool_call_id=call.get("id") or "",
        name=call.get("name"),
        status="error",
    )
