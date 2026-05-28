"""Tests for streamed tool-output normalization."""

from __future__ import annotations

from langchain_core.messages import ToolMessage

from jutul_agent.agent.tool_output import is_interrupt_payload, normalize_tool_output


def test_normalize_tool_message_object() -> None:
    message = ToolMessage(content="hello", tool_call_id="call-1", name="read_file")
    assert normalize_tool_output(message) == "hello"


def test_normalize_tool_message_repr() -> None:
    raw = (
        "[ToolMessage(content='     1\\tline one\\n     2\\tline two', "
        "name='read_file', tool_call_id='call-1', additional_kwargs={})]"
    )
    assert normalize_tool_output(raw) == "     1\tline one\n     2\tline two"


def test_interrupt_payload_detection() -> None:
    text = "Interrupt(value={'action_requests': [{'name': 'write_file'}]})"
    assert is_interrupt_payload(text) is True
