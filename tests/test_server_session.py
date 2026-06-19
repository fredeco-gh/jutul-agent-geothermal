"""End-to-end tests for the server: REST lifecycle and the turn WebSocket.

The agent and Julia kernel are fakes (see ``fakes``), so a turn runs through the
real ``TurnRunner`` and wire protocol without a provider API or a Julia process.
A test ``SessionManager`` is injected with a host factory that wraps those fakes.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fakes import (
    FakeJulia,
    echo_agent,
    interrupt_agent,
    make_fake_adapter,
    streaming_agent,
)
from jutul_agent.interfaces.server.app import artifact_wire_events, create_app
from jutul_agent.interfaces.server.manager import SessionManager
from jutul_agent.interfaces.server.session_host import SessionHost
from jutul_agent.session import Session, default_session_id


def _manager(agent_factory: Callable[[], Any], tmp_path: Path) -> SessionManager:
    """A manager whose sessions wrap a fresh fake agent and a real (fake-kernel) Session."""

    async def host_factory(
        *, sim, model, approval_mode, workspace, resume, session_id, extensions=()
    ) -> SessionHost:
        adapter = make_fake_adapter(tmp_path)
        sid = session_id or default_session_id()
        session = Session.create(
            julia=FakeJulia(), simulator=adapter, session_id=sid, state_root=tmp_path
        )
        return SessionHost(session=session, agent=agent_factory())

    return SessionManager(host_factory=host_factory)


def _client(agent_factory: Callable[[], Any], tmp_path: Path) -> TestClient:
    return TestClient(create_app(_manager(agent_factory, tmp_path)))


def _drain_turn(ws: Any) -> list[dict]:
    """Read events until the turn ends or pauses for approval."""
    events: list[dict] = []
    while True:
        event = ws.receive_json()
        events.append(event)
        if event["type"] in {"turn_end", "interrupt"}:
            return events


def test_models_endpoint(tmp_path: Path) -> None:
    with _client(echo_agent, tmp_path) as client:
        body = client.get("/models").json()
    assert "default" in body
    assert isinstance(body["providers"], list)


def test_simulators_endpoint(tmp_path: Path) -> None:
    with _client(echo_agent, tmp_path) as client:
        body = client.get("/simulators").json()
    assert "jutuldarcy" in body["simulators"]


def test_web_ui_is_served(tmp_path: Path) -> None:
    with _client(echo_agent, tmp_path) as client:
        root = client.get("/")
    assert root.status_code == 200
    assert "jutul-agent" in root.text


def test_create_list_delete(tmp_path: Path) -> None:
    with _client(echo_agent, tmp_path) as client:
        sid = client.post("/sessions", json={"sim": "demo"}).json()["session_id"]
        assert sid in client.get("/sessions").json()["sessions"]
        assert client.delete(f"/sessions/{sid}").json() == {"ok": True}
        assert client.get("/sessions").json()["sessions"] == []
        assert client.delete(f"/sessions/{sid}").status_code == 404


def test_ws_streaming_prompt(tmp_path: Path) -> None:
    with _client(streaming_agent, tmp_path) as client:
        sid = client.post("/sessions", json={"sim": "demo"}).json()["session_id"]
        with client.websocket_connect(f"/sessions/{sid}/stream") as ws:
            ws.send_json({"type": "prompt", "text": "hi"})
            events = _drain_turn(ws)
    texts = [e["text"] for e in events if e["type"] == "text"]
    assert "".join(texts) == "Hello world"
    assert events[-1]["type"] == "turn_end"


def test_ws_echo_prompt(tmp_path: Path) -> None:
    with _client(echo_agent, tmp_path) as client:
        sid = client.post("/sessions", json={"sim": "demo"}).json()["session_id"]
        with client.websocket_connect(f"/sessions/{sid}/stream") as ws:
            ws.send_json({"type": "prompt", "text": "hi"})
            events = _drain_turn(ws)
    assert any(e["type"] == "text" and "Echo:" in e["text"] for e in events)
    assert events[-1]["type"] == "turn_end"


def test_ws_interrupt_then_approve(tmp_path: Path) -> None:
    with _client(interrupt_agent, tmp_path) as client:
        sid = client.post("/sessions", json={"sim": "demo"}).json()["session_id"]
        with client.websocket_connect(f"/sessions/{sid}/stream") as ws:
            ws.send_json({"type": "prompt", "text": "please run"})
            paused = _drain_turn(ws)
            interrupt = paused[-1]
            assert interrupt["type"] == "interrupt"
            assert interrupt["actions"][0]["name"] == "execute"
            assert set(interrupt["allowed_decisions"]) == {"approve", "reject", "respond"}

            ws.send_json({"type": "decision", "decision": "approve"})
            resumed = _drain_turn(ws)
    assert any(e["type"] == "text" and "approval handled" in e["text"] for e in resumed)
    assert resumed[-1]["type"] == "turn_end"


def test_ws_unknown_session(tmp_path: Path) -> None:
    with (
        _client(echo_agent, tmp_path) as client,
        client.websocket_connect("/sessions/nope/stream") as ws,
    ):
        assert ws.receive_json() == {"type": "error", "message": "no such session"}


def test_ws_decision_without_pending_is_error(tmp_path: Path) -> None:
    with _client(echo_agent, tmp_path) as client:
        sid = client.post("/sessions", json={"sim": "demo"}).json()["session_id"]
        with client.websocket_connect(f"/sessions/{sid}/stream") as ws:
            ws.send_json({"type": "decision", "decision": "approve"})
            event = ws.receive_json()
    assert event["type"] == "error"
    assert "no approval" in event["message"]


def test_artifact_wire_events_png_and_html() -> None:
    payloads = [
        {"path": "artifacts/plot.png", "mime": "image/png", "caption": "fig"},
        {"path": "artifacts/scene.html", "mime": "text/html", "caption": "interactive"},
    ]
    events = artifact_wire_events(payloads, "sid")
    assert events[0] == {
        "type": "artifact",
        "url": "/sessions/sid/artifacts/plot.png",
        "mime": "image/png",
        "caption": "fig",
        "slot": None,
        "format": None,
    }
    assert events[1] == {
        "type": "viz",
        "url": "/sessions/sid/artifacts/scene.html",
        "title": "interactive",
    }


@pytest.mark.parametrize("agent_factory", [echo_agent])
def test_unknown_simulator_is_400(agent_factory: Callable[[], Any], tmp_path: Path) -> None:
    # The default manager (no injected factory) resolves the simulator registry,
    # so an unknown name is a client error rather than a server crash.
    with TestClient(create_app(SessionManager())) as client:
        resp = client.post("/sessions", json={"sim": "does-not-exist"})
    assert resp.status_code == 400
