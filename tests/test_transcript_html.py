"""Tests for the HTML transcript renderer."""

from __future__ import annotations

from fakes import make_event
from jutul_agent.transcript import render_html


def test_render_html_is_complete_document(snapshot) -> None:
    events = [
        make_event(1, "session_start", {"session_id": "abc", "simulator": "jutuldarcy"}),
        make_event(2, "message_user", {"content": "what is 2+2?"}),
        make_event(3, "session_end", {"session_id": "abc"}),
    ]
    html = render_html(events)
    assert html.startswith("<!doctype html>")
    assert html == snapshot


def test_render_full_turn(snapshot) -> None:
    events = [
        make_event(1, "session_start", {"session_id": "abc", "simulator": "jutuldarcy"}),
        make_event(2, "message_user", {"content": "what is 2+2?"}),
        make_event(
            3,
            "tool_call",
            {"id": "call-1", "name": "julia_eval", "args": {"code": "2+2"}},
        ),
        make_event(
            4,
            "tool_result",
            {"tool_call_id": "call-1", "name": "julia_eval", "content": "4"},
        ),
        make_event(5, "message_assistant", {"content": "The answer is 4."}),
        make_event(6, "session_end", {"session_id": "abc"}),
    ]
    assert render_html(events) == snapshot


def test_render_escapes_html_in_payload(snapshot) -> None:
    events = [
        make_event(1, "message_user", {"content": "<script>alert(1)</script>"}),
    ]
    html = render_html(events)
    assert "&lt;script&gt;" in html
    assert "<script>alert(1)</script>" not in html
    assert html == snapshot


def test_render_assistant_markdown(snapshot) -> None:
    events = [
        make_event(
            1,
            "message_assistant",
            {"content": "### Heading\n\n1. **Create wells**\n\n```julia\nProd = 1\n```"},
        ),
    ]
    html = render_html(events)
    assert 'class="highlight"' in html
    assert html == snapshot


def test_render_tool_result_markdown(snapshot) -> None:
    events = [
        make_event(
            1,
            "tool_call",
            {"id": "call-1", "name": "read_file", "args": {"file_path": "SKILL.md"}},
        ),
        make_event(
            2,
            "tool_result",
            {
                "tool_call_id": "call-1",
                "name": "read_file",
                "content": "# Setting up wells\n\n## When to use\n\nUse this skill.",
            },
        ),
    ]
    assert render_html(events) == snapshot


def test_render_read_file_numbered_markdown_with_julia(snapshot) -> None:
    content = (
        "     1\t# Setting up wells\n"
        "     2\t\n"
        "     3\t```julia\n"
        "     4\tProd = setup_vertical_well(domain, 1, 1, name = :Producer)\n"
        "     5\t```\n"
    )
    events = [
        make_event(
            1,
            "tool_call",
            {"id": "call-1", "name": "read_file", "args": {"file_path": "SKILL.md"}},
        ),
        make_event(
            2,
            "tool_result",
            {
                "tool_call_id": "call-1",
                "name": "read_file",
                "content": content,
            },
        ),
    ]
    html = render_html(events)
    assert 'class="highlight"' in html
    assert html == snapshot


def test_render_todos_args(snapshot) -> None:
    events = [
        make_event(
            1,
            "tool_call",
            {
                "name": "write_todos",
                "args": {
                    "todos": [
                        {"content": "Inspect docs", "status": "completed"},
                        {"content": "Explain pattern", "status": "in_progress"},
                    ]
                },
            },
        ),
    ]
    html = render_html(events)
    assert "todo-list" in html
    assert html == snapshot


def test_filter_groups_merge_tools(snapshot) -> None:
    events = [
        make_event(1, "tool_call", {"name": "julia_eval", "args": {}}),
        make_event(2, "tool_result", {"name": "julia_eval", "content": "4"}),
    ]
    html = render_html(events)
    assert 'data-filter="tool_call"' not in html
    assert html == snapshot


def test_render_skips_empty_assistant(snapshot) -> None:
    events = [
        make_event(1, "message_assistant", {"content": ""}),
        make_event(2, "message_assistant", {"content": "hello"}),
    ]
    html = render_html(events)
    assert html.count('data-kind="message_assistant"') == 1
    assert html == snapshot


def test_render_reasoning_in_details(snapshot) -> None:
    events = [
        make_event(1, "message_reasoning", {"content": "thinking step by step"}),
    ]
    html = render_html(events)
    assert "<details>" in html
    assert html == snapshot


def test_render_hitl_events(snapshot) -> None:
    events = [
        make_event(
            1,
            "hitl_request",
            {
                "interrupt_id": "abc",
                "value": {"action_requests": [{"name": "execute", "args": {"command": "ls -la"}}]},
            },
        ),
        make_event(
            2,
            "hitl_response",
            {
                "interrupt_id": "abc",
                "payload": {"decisions": [{"type": "approve"}]},
            },
        ),
    ]
    assert render_html(events) == snapshot


def test_render_artifact_image(snapshot) -> None:
    events = [
        make_event(
            1,
            "artifact",
            {
                "path": "artifacts/plot-deadbeef.png",
                "mime": "image/png",
                "caption": "pressure field",
            },
        ),
    ]
    html = render_html(events)
    assert 'src="artifacts/plot-deadbeef.png"' in html
    assert html == snapshot


def test_render_artifact_with_provenance(snapshot) -> None:
    events = [
        make_event(
            1,
            "artifact",
            {
                "path": "artifacts/comparison.png",
                "mime": "image/png",
                "caption": "Well rates",
                "slot": "comparison",
                "format": "png",
                "size_px": [900, 500],
                "source_code": "well_rates_figure(wd)",
            },
        ),
    ]
    html = render_html(events)
    assert "slot: comparison" in html
    assert "artifact-source" in html
    assert html == snapshot


def test_render_unknown_kind_fallback(snapshot) -> None:
    events = [make_event(1, "custom_event", {"foo": "bar"})]
    html = render_html(events)
    assert "custom_event" in html
    assert html == snapshot
