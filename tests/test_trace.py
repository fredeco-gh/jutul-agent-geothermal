"""Unit tests for the trace log."""

from __future__ import annotations

from pathlib import Path

from jutul_agent.trace import TraceLog


def test_append_and_iter(tmp_path: Path) -> None:
    log = TraceLog(tmp_path / "trace.sqlite")
    try:
        log.append("session_start", {"session_id": "abc"})
        log.append("message_user", {"content": "hi"})
        log.append("tool_call", {"name": "julia_eval", "args": {"code": "1+1"}})
        log.append("tool_result", {"name": "julia_eval", "content": "2"})
        log.append("session_end", {"session_id": "abc"})
        events = log.iter_events()
    finally:
        log.close()

    kinds = [e.kind for e in events]
    assert kinds == [
        "session_start",
        "message_user",
        "tool_call",
        "tool_result",
        "session_end",
    ]
    assert events[2].payload["args"] == {"code": "1+1"}
    assert all(e.timestamp for e in events)
    assert [e.id for e in events] == sorted(e.id for e in events)


def test_creates_parent_dir(tmp_path: Path) -> None:
    db = tmp_path / "nested" / "deeper" / "trace.sqlite"
    log = TraceLog(db)
    log.append("session_start", {"session_id": "x"})
    log.close()
    assert db.exists()
