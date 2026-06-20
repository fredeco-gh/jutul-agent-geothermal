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
        {
            "path": "artifacts/scene.html",
            "mime": "text/html",
            "caption": "interactive",
            "kind": "plot",
            "poster": "artifacts/scene.png",
            "slot": "scene",
        },
        {
            "path": "artifacts/report.html",
            "mime": "text/html",
            "caption": "Run report",
            "kind": "report",
            "slot": "report",
        },
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
    # An interactive plot becomes a viz carrying its kind, slot, and poster URL.
    assert events[1] == {
        "type": "viz",
        "url": "/sessions/sid/artifacts/scene.html",
        "title": "interactive",
        "kind": "plot",
        "poster": "/sessions/sid/artifacts/scene.png",
        "slot": "scene",
    }
    # A written report is a viz too, of kind "report" and with no poster.
    assert events[2] == {
        "type": "viz",
        "url": "/sessions/sid/artifacts/report.html",
        "title": "Run report",
        "kind": "report",
        "poster": None,
        "slot": "report",
    }


def test_artifact_wire_events_live_plot_uses_live_url() -> None:
    # A live-served plot carries a live_url (the session's Bonito server); the viz
    # points there instead of the static export, but the poster is still served
    # as a session artifact.
    # A live plot's durable record is the PNG (mime image/png); the live_url is
    # where the figure is actually served, so the viz points there, not at the PNG.
    payloads = [
        {
            "path": "artifacts/reservoir.png",
            "mime": "image/png",
            "caption": "Reservoir",
            "kind": "plot",
            "poster": "artifacts/reservoir.png",
            "slot": "reservoir",
            "live_url": "http://127.0.0.1:9123/viz/reservoir",
        },
    ]
    (event,) = artifact_wire_events(payloads, "sid")
    assert event == {
        "type": "viz",
        "url": "http://127.0.0.1:9123/viz/reservoir",
        "title": "Reservoir",
        "kind": "plot",
        "poster": "/sessions/sid/artifacts/reservoir.png",
        "slot": "reservoir",
    }


def test_command_reconfigures_session(tmp_path: Path) -> None:
    # A `command` message rebuilds the agent in place (model / approval policy).
    # reconfigure is stubbed here (the real one rebuilds a provider-backed agent);
    # a following unknown command, whose error we read, proves the first was
    # processed in order.
    manager = _manager(echo_agent, tmp_path)
    with TestClient(create_app(manager)) as client:
        sid = client.post("/sessions", json={"sim": "jutuldarcy"}).json()["session_id"]
        calls: list[dict] = []
        manager.get(sid).reconfigure = lambda **kw: calls.append(kw)  # type: ignore[method-assign]
        with client.websocket_connect(f"/sessions/{sid}/stream") as ws:
            ws.send_json({"type": "command", "command": "set_model", "arg": "anthropic:c"})
            ws.send_json({"type": "command", "command": "set_approval", "arg": "auto"})
            ws.send_json({"type": "command", "command": "bogus"})
            err = ws.receive_json()
    assert calls == [{"model": "anthropic:c"}, {"approval_mode": "auto"}]
    assert err["type"] == "error" and "bogus" in err["message"]


@pytest.mark.parametrize("agent_factory", [echo_agent])
def test_unknown_simulator_is_400(agent_factory: Callable[[], Any], tmp_path: Path) -> None:
    # The default manager (no injected factory) resolves the simulator registry,
    # so an unknown name is a client error rather than a server crash.
    with TestClient(create_app(SessionManager())) as client:
        resp = client.post("/sessions", json={"sim": "does-not-exist"})
    assert resp.status_code == 400
