"""Tests for TraceRecorder middleware."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from jutul_agent.trace import TraceLog, TraceRecorder


async def test_trace_recorder_logs_reasoning_and_assistant(tmp_path) -> None:
    log = TraceLog(tmp_path / "trace.sqlite")
    recorder = TraceRecorder(log)

    state = {
        "messages": [
            HumanMessage(content="hi"),
            AIMessage(
                content=[
                    {"type": "reasoning", "reasoning": "checking the workspace"},
                    {"type": "text", "text": "ready to help"},
                ]
            ),
        ]
    }
    await recorder.aafter_model(state, runtime=None)

    kinds = [event.kind for event in log.iter_events()]
    assert kinds == ["message_reasoning", "message_assistant"]
    log.close()


async def test_trace_recorder_logs_tool_round_trip(tmp_path) -> None:
    log = TraceLog(tmp_path / "trace.sqlite")
    recorder = TraceRecorder(log)

    request = type(
        "Req",
        (),
        {"tool_call": {"id": "call-1", "name": "echo", "args": {"value": "x"}}},
    )()

    async def handler(_request):
        return ToolMessage(content="x", tool_call_id="call-1", name="echo")

    result = await recorder.awrap_tool_call(request, handler)
    assert isinstance(result, ToolMessage)

    kinds = [event.kind for event in log.iter_events()]
    assert kinds == ["tool_call", "tool_result"]
    log.close()
