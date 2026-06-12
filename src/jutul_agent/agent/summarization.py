"""Conversation compaction: automatic summarization plus manual /compact.

Both paths run langchain's ``SummarizationMiddleware``: automatically as the
context approaches the model's window, and on demand against the thread's
checkpointed state. Older turns are replaced by a summary message while the
newest messages are preserved verbatim; each compaction is recorded in the
session trace as a ``context_compaction`` event.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain.agents.middleware import SummarizationMiddleware

from jutul_agent.trace import TraceLog

# Summarize when the conversation reaches this share of the model's window.
_TRIGGER_FRACTION = 0.8
# Without profile data or a daemon-reported window the absolute trigger has to
# be safe for every supported cloud model rather than tuned to one.
_FALLBACK_TRIGGER_TOKENS = 100_000
# Messages preserved verbatim after a compaction. The manual count is public
# so the TUI can explain why a short conversation has nothing to compact.
_AUTO_KEEP: tuple[str, int] = ("messages", 20)
MANUAL_KEEP_MESSAGES = 8
_MANUAL_KEEP: tuple[str, int] = ("messages", MANUAL_KEEP_MESSAGES)


def auto_compact_trigger_tokens(window: int | None) -> int:
    """The context size at which auto-compaction triggers for ``window``."""
    return int(window * _TRIGGER_FRACTION) if window else _FALLBACK_TRIGGER_TOKENS


class TraceSummarizationMiddleware(SummarizationMiddleware):
    """SummarizationMiddleware that records each compaction in the trace."""

    def __init__(self, trace: TraceLog | None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._trace = trace

    def _record(self, state: dict[str, Any], update: dict[str, Any] | None) -> None:
        if update is None or self._trace is None:
            return
        self._trace.append(
            "context_compaction",
            {
                "messages_before": len(state["messages"]),
                # The update is [RemoveMessage(all), summary, *preserved].
                "messages_after": len(update["messages"]) - 1,
            },
        )

    def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        update = super().before_model(state, runtime)
        self._record(state, update)
        return update

    async def abefore_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        update = await super().abefore_model(state, runtime)
        self._record(state, update)
        return update


def build_summarization_middleware(
    model: Any,
    *,
    model_id: str | None = None,
    trace: TraceLog | None = None,
) -> TraceSummarizationMiddleware:
    """Auto-compaction middleware for ``model`` (string spec or instance).

    Fractional triggers need the model's profile data; models without it
    (local models, unknown ids) fall back to an absolute token trigger sized
    from the reported context window when one is available.
    """
    try:
        return TraceSummarizationMiddleware(
            trace,
            model=model,
            trigger=("fraction", _TRIGGER_FRACTION),
            keep=_AUTO_KEEP,
        )
    except ValueError:
        window = None
        if model_id is not None:
            from jutul_agent.models import context_window

            window = context_window(model_id)
        tokens = auto_compact_trigger_tokens(window)
        return TraceSummarizationMiddleware(
            trace,
            model=model,
            trigger=("tokens", tokens),
            keep=_AUTO_KEEP,
        )


@dataclass(frozen=True)
class CompactResult:
    messages_before: int
    messages_after: int


async def compact_thread(
    agent: Any,
    *,
    thread_id: str,
    model: Any,
    trace: TraceLog | None = None,
) -> CompactResult | None:
    """Summarize the thread's older turns now, in place.

    Reads the checkpointed state, runs the summarization pass with an
    always-on trigger, and writes the replacement messages back, so the next
    turn starts from the compacted history. Returns ``None`` when there is
    nothing to compact (too few messages or no state).
    """
    aget_state = getattr(agent, "aget_state", None)
    aupdate_state = getattr(agent, "aupdate_state", None)
    if aget_state is None or aupdate_state is None:
        return None

    config = {"configurable": {"thread_id": thread_id}}
    state = await aget_state(config)
    messages = (getattr(state, "values", None) or {}).get("messages") or []
    if len(messages) <= _MANUAL_KEEP[1]:
        return None

    middleware = SummarizationMiddleware(
        model=model,
        trigger=("messages", 1),  # unconditional: the user asked
        keep=_MANUAL_KEEP,
    )
    update = await middleware.abefore_model({"messages": list(messages)}, None)
    if update is None:
        return None

    await aupdate_state(config, update)
    result = CompactResult(
        messages_before=len(messages),
        messages_after=len(update["messages"]) - 1,
    )
    if trace is not None:
        trace.append(
            "context_compaction",
            {
                "messages_before": result.messages_before,
                "messages_after": result.messages_after,
                "manual": True,
            },
        )
    return result
