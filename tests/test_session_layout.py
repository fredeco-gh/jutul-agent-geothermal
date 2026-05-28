"""Tests for session path helpers."""

from __future__ import annotations

from pathlib import Path

from jutul_agent.paths import set_state_home, set_workspace_root, workspace_state_dir
from jutul_agent.session import read_last_session, sessions_root, write_last_session


def test_last_session_round_trip_via_state_root(tmp_path: Path) -> None:
    write_last_session("session-abc", state_root=tmp_path)
    assert read_last_session(state_root=tmp_path) == "session-abc"


def test_last_session_round_trip_via_workspace_state_dir(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    state = tmp_path / "state"
    set_workspace_root(ws)
    set_state_home(state)

    write_last_session("session-xyz")
    assert read_last_session() == "session-xyz"
    assert (workspace_state_dir() / "last-session").exists()


def test_sessions_root_honours_explicit_state_root(tmp_path: Path) -> None:
    assert sessions_root(tmp_path) == tmp_path / "sessions"
