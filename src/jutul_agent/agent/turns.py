"""Turn runner for streaming agent messages and HITL interrupts.

Consumes deepagents' v3 ``astream_events`` stream via the typed projections
(``run.messages`` / ``run.tool_calls`` / ``run.interrupts`` / ``run.output``).
Owns the trace contract for user messages and HITL requests/responses so
call sites don't have to remember.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessageChunk, BaseMessage
from langgraph.types import Command

from jutul_agent.agent.tool_output import is_interrupt_payload, normalize_tool_output
from jutul_agent.trace import TraceLog

MessageCallback = Callable[[Any], Awaitable[None] | None]
ResumePayload = dict[str, dict[str, list[dict[str, str]]]]


@dataclass(frozen=True)
class TurnInterrupt:
    """A pending human-in-the-loop approval request."""

    interrupt_id: str
    value: Any


@dataclass(frozen=True)
class TurnRunResult:
    """Messages and pending interrupts emitted by one agent run."""

    messages: list[BaseMessage]
    interrupts: list[TurnInterrupt]


@dataclass(frozen=True)
class TurnReasoningDelta:
    """Incremental assistant reasoning text surfaced separately from the answer."""

    text: str


@dataclass(frozen=True)
class TurnToolEvent:
    """Lifecycle event for one streamed tool call."""

    event: str
    tool_name: str
    tool_call_id: str | None = None
    args: dict[str, Any] | None = None
    content: str = ""


class TurnRunner:
    """Run one agent turn over the v3 typed-projection stream."""

    def __init__(
        self,
        agent: Any,
        *,
        thread_id: str,
        trace: TraceLog | None = None,
    ) -> None:
        self._agent = agent
        self._config = {"configurable": {"thread_id": thread_id}}
        self._trace = trace

    async def run_prompt(
        self,
        prompt: str,
        *,
        on_message: MessageCallback | None = None,
    ) -> TurnRunResult:
        if self._trace is not None:
            self._trace.append("message_user", {"content": prompt})
        return await self._run(
            {"messages": [{"role": "user", "content": prompt}]},
            on_message=on_message,
        )

    async def resume(
        self,
        resume_payload: ResumePayload,
        *,
        on_message: MessageCallback | None = None,
    ) -> TurnRunResult:
        if self._trace is not None:
            for interrupt_id, payload in resume_payload.items():
                self._trace.append(
                    "hitl_response",
                    {"interrupt_id": interrupt_id, "payload": payload},
                )
        return await self._run(Command(resume=resume_payload), on_message=on_message)

    async def _run(
        self,
        stream_input: dict[str, Any] | Command,
        *,
        on_message: MessageCallback | None,
    ) -> TurnRunResult:
        run = await self._agent.astream_events(
            stream_input,
            config=self._config,
            version="v3",
        )

        # Drain the projection streams concurrently. Each owns its own
        # arrival-order iterator; ordering across projections is not strict,
        # but the TUI keys tool blocks by tool_call_id so that's fine.
        await asyncio.gather(
            _drain_messages(run, on_message),
            _drain_tool_calls(run, on_message),
        )

        interrupts = await _collect_interrupts(run, self._trace)
        messages = await _final_messages(run)
        return TurnRunResult(messages=messages, interrupts=interrupts)


# ---------------------------------------------------------------------------
# Projection drains.


async def _drain_messages(run: Any, on_message: MessageCallback | None) -> None:
    """Stream text + reasoning + tool-call deltas from ``run.messages``."""

    async for message_stream in run.messages:
        await asyncio.gather(
            _drain_text(message_stream, on_message),
            _drain_reasoning(message_stream, on_message),
            _drain_tool_call_chunks(message_stream, on_message),
        )
        if on_message is not None:
            await _emit(on_message, AIMessageChunk(content="", chunk_position="last"))


async def _drain_text(message_stream: Any, on_message: MessageCallback | None) -> None:
    if on_message is None:
        async for _ in message_stream.text:
            pass
        return
    async for delta in message_stream.text:
        if delta:
            await _emit(on_message, AIMessageChunk(content=delta))


async def _drain_reasoning(message_stream: Any, on_message: MessageCallback | None) -> None:
    if on_message is None:
        async for _ in message_stream.reasoning:
            pass
        return
    async for delta in message_stream.reasoning:
        if delta:
            await _emit(on_message, TurnReasoningDelta(text=delta))


async def _drain_tool_call_chunks(
    message_stream: Any, on_message: MessageCallback | None
) -> None:
    """Surface a ``requested`` TurnToolEvent once each tool call finalizes.

    The tool-call projection is both async-iterable (partial chunks) and
    awaitable (the finalized list). We only need the finalized view, but
    we have to exhaust the iterator first so the awaitable resolves.
    """

    try:
        async for _ in message_stream.tool_calls:
            pass
        finalized = await message_stream.tool_calls
    except (TypeError, AttributeError):
        return

    if on_message is None:
        return

    seen: set[str] = set()
    for call in finalized or ():
        tool_id = str(call.get("id") or "")
        if not tool_id or tool_id in seen:
            continue
        name = call.get("name")
        if not isinstance(name, str) or not name:
            continue
        seen.add(tool_id)
        args = call.get("args") if isinstance(call.get("args"), dict) else {}
        await _emit(
            on_message,
            TurnToolEvent(
                event="requested",
                tool_name=name,
                tool_call_id=tool_id,
                args=args,
            ),
        )


async def _drain_tool_calls(run: Any, on_message: MessageCallback | None) -> None:
    """Stream ``tool-started`` / ``tool-finished`` / ``tool-error`` lifecycle."""

    async for call in run.tool_calls:
        tool_name = getattr(call, "tool_name", None) or "tool"
        tool_call_id = getattr(call, "tool_call_id", None)
        args = getattr(call, "input", None)
        args_dict = args if isinstance(args, dict) else None

        if on_message is not None:
            await _emit(
                on_message,
                TurnToolEvent(
                    event="started",
                    tool_name=tool_name,
                    tool_call_id=tool_call_id,
                    args=args_dict,
                ),
            )

        # Stream partial tool output when the graph exposes output deltas.
        try:
            async for delta in call.output_deltas:
                if on_message is not None and delta:
                    await _emit(
                        on_message,
                        TurnToolEvent(
                            event="delta",
                            tool_name=tool_name,
                            tool_call_id=tool_call_id,
                            content=str(delta),
                        ),
                    )
        except (TypeError, AttributeError):
            pass

        if on_message is None:
            continue
        if call.error is not None:
            if _should_skip_tool_error(call.error):
                continue
            await _emit(
                on_message,
                TurnToolEvent(
                    event="error",
                    tool_name=tool_name,
                    tool_call_id=tool_call_id,
                    content=_stringify_tool_output(call.error),
                ),
            )
        else:
            await _emit(
                on_message,
                TurnToolEvent(
                    event="finished",
                    tool_name=tool_name,
                    tool_call_id=tool_call_id,
                    content=_stringify_tool_output(call.output),
                ),
            )


async def _collect_interrupts(run: Any, trace: TraceLog | None) -> list[TurnInterrupt]:
    """Read ``run.interrupts`` after the stream drains."""

    raw = await _maybe_await(getattr(run, "interrupts", []))
    interrupts: list[TurnInterrupt] = []
    seen: set[str] = set()
    for itp in raw or ():
        interrupt_id = str(getattr(itp, "id", "") or "")
        if not interrupt_id or interrupt_id in seen:
            continue
        seen.add(interrupt_id)
        value = getattr(itp, "value", None)
        interrupts.append(TurnInterrupt(interrupt_id=interrupt_id, value=value))
        if trace is not None:
            trace.append(
                "hitl_request",
                {"interrupt_id": interrupt_id, "value": value},
            )
    return interrupts


async def _final_messages(run: Any) -> list[BaseMessage]:
    output = await _maybe_await(getattr(run, "output", None))
    if isinstance(output, dict):
        items = output.get("messages") or []
        return [m for m in items if isinstance(m, BaseMessage)]
    return []


# ---------------------------------------------------------------------------
# Misc helpers.


async def _maybe_await(value: Any) -> Any:
    if callable(value):
        value = value()
    if inspect.isawaitable(value):
        return await value
    return value


def _stringify_tool_output(value: Any) -> str:
    return normalize_tool_output(value)


def _should_skip_tool_error(value: Any) -> bool:
    return is_interrupt_payload(_stringify_tool_output(value))


async def _emit(callback: MessageCallback, message: Any) -> None:
    result = callback(message)
    if inspect.isawaitable(result):
        await result
