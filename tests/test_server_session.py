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


def _manager(
    agent_factory: Callable[[], Any], tmp_path: Path, *, max_live: int = 16
) -> SessionManager:
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

    return SessionManager(host_factory=host_factory, max_live=max_live)


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
    # Each simulator carries its display name and starter prompts for a welcome screen.
    detail = body["details"]["jutuldarcy"]
    assert detail["display_name"] == "JutulDarcy"
    assert detail["examples"] and all(isinstance(e, str) for e in detail["examples"])


def test_bound_simulator_uses_one_and_rejects_mismatch(tmp_path: Path) -> None:
    # A server bound to a simulator (the `serve` case) uses it for every session
    # and refuses a request for a different one — one folder, one simulator, no
    # in-place switching. Without a bound simulator the caller's choice is honoured.
    manager = _manager(echo_agent, tmp_path)
    with TestClient(create_app(manager, default_sim="jutuldarcy")) as client:
        assert client.get("/simulators").json()["default"] == "jutuldarcy"
        assert client.post("/sessions", json={"sim": "jutuldarcy"}).status_code == 200
        assert client.post("/sessions", json={}).status_code == 200  # omitted → the bound one
        mismatch = client.post("/sessions", json={"sim": "battmo"})
        assert mismatch.status_code == 409 and "bound" in mismatch.json()["detail"]


def test_unbound_server_requires_a_simulator(tmp_path: Path) -> None:
    # No bound simulator (tests / a future multi-folder launcher): the caller must
    # name one, and an omitted simulator is a clear 400 rather than a crash.
    with _client(echo_agent, tmp_path) as client:
        assert client.post("/sessions", json={}).status_code == 400


def test_manager_caps_live_sessions(tmp_path: Path) -> None:
    # Each live session pins a Julia kernel, so the manager keeps only the most
    # recent ``max_live`` and closes the rest (they stay resumable on disk).
    manager = _manager(echo_agent, tmp_path, max_live=2)
    with TestClient(create_app(manager)) as client:
        ids = [
            client.post("/sessions", json={"sim": "demo"}).json()["session_id"] for _ in range(3)
        ]
        live = client.get("/sessions").json()["sessions"]
    assert set(live) == {ids[1], ids[2]}  # the oldest was evicted


async def test_eviction_skips_attached_sessions(tmp_path: Path) -> None:
    # A session a client is connected to must not be torn down mid-turn: eviction
    # skips attached hosts and takes the oldest idle one instead, even when the
    # attached host is the oldest.
    manager = _manager(echo_agent, tmp_path, max_live=2)
    a = await manager.create(sim="demo")
    a.attach()  # a live connection now holds the oldest session
    b = await manager.create(sim="demo")
    c = await manager.create(sim="demo")  # over cap → evict the oldest *idle* host (b)
    live = set(manager.list_ids())
    assert a.session_id in live  # attached, so kept despite being oldest
    assert c.session_id in live
    assert b.session_id not in live


def test_second_connection_to_a_session_is_refused(tmp_path: Path) -> None:
    # Two live sockets on one session would run turns on one kernel concurrently;
    # the second is refused, and once the first closes a new one can attach.
    with _client(echo_agent, tmp_path) as client:
        sid = client.post("/sessions", json={"sim": "demo"}).json()["session_id"]
        with (
            client.websocket_connect(f"/sessions/{sid}/stream"),  # first holds the session
            client.websocket_connect(f"/sessions/{sid}/stream") as ws2,
        ):
            refused = ws2.receive_json()
        assert refused["type"] == "error" and "another window" in refused["message"]
        # The first socket has closed, so a fresh connection attaches and runs.
        with client.websocket_connect(f"/sessions/{sid}/stream") as ws3:
            ws3.send_json({"type": "prompt", "text": "hi"})
            assert _drain_turn(ws3)[-1]["type"] == "turn_end"


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


def test_ws_always_allow_auto_approves_future_interrupts(tmp_path: Path) -> None:
    # "Always allow" approves now and remembers the category, so a later interrupt
    # of the same kind auto-approves without asking the user again (like the TUI).
    def agent() -> Any:
        return interrupt_agent(tool_name="write_file", allowed_decisions=["approve", "reject"])

    with _client(agent, tmp_path) as client:
        sid = client.post("/sessions", json={"sim": "demo"}).json()["session_id"]
        with client.websocket_connect(f"/sessions/{sid}/stream") as ws:
            ws.send_json({"type": "prompt", "text": "edit a file"})
            interrupt = _drain_turn(ws)[-1]
            assert interrupt["type"] == "interrupt"
            assert interrupt["allowlist"] == ["file_edits"]  # offered to the front end

            ws.send_json({"type": "decision", "decision": "always_allow"})
            assert _drain_turn(ws)[-1]["type"] == "turn_end"

            # A second file-edit interrupt is now resolved automatically: the client
            # sees the turn complete and is never asked to approve again.
            ws.send_json({"type": "prompt", "text": "edit another file"})
            second = _drain_turn(ws)
            assert second[-1]["type"] == "turn_end"
            assert not any(e["type"] == "interrupt" for e in second)


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


def test_command_compact_and_add_dir(tmp_path: Path) -> None:
    # /compact and /add-dir reply with a `notice`; the host methods are stubbed
    # (the real ones summarize via a model / mutate the backend).
    manager = _manager(echo_agent, tmp_path)
    with TestClient(create_app(manager)) as client:
        sid = client.post("/sessions", json={"sim": "jutuldarcy"}).json()["session_id"]
        host = manager.get(sid)
        host.add_dir = lambda arg: f"added:{arg}"  # type: ignore[method-assign]

        async def fake_compact() -> str:
            return "compacted:ok"

        host.compact = fake_compact  # type: ignore[method-assign]
        with client.websocket_connect(f"/sessions/{sid}/stream") as ws:
            ws.send_json({"type": "command", "command": "add_dir", "arg": "/data"})
            n1 = ws.receive_json()
            ws.send_json({"type": "command", "command": "compact"})
            n2 = ws.receive_json()
    assert n1 == {"type": "notice", "text": "added:/data"}
    assert n2 == {"type": "notice", "text": "compacted:ok"}


def test_transcript_and_memory_endpoints(tmp_path: Path) -> None:
    with _client(echo_agent, tmp_path) as client:
        sid = client.post("/sessions", json={"sim": "jutuldarcy"}).json()["session_id"]
        html = client.get(f"/sessions/{sid}/transcript")
        assert html.status_code == 200 and "text/html" in html.headers["content-type"]
        md = client.get(f"/sessions/{sid}/transcript", params={"format": "md"})
        assert md.status_code == 200 and "markdown" in md.headers["content-type"]
        mem = client.get(f"/sessions/{sid}/memory")
        assert mem.status_code == 200 and "Memory" in mem.text
        assert client.get("/sessions/nope/transcript").status_code == 404


def test_context_endpoint_renders_panel(tmp_path: Path) -> None:
    # /context renders the same panel as the TUI. It reads the trace from a fresh
    # connection because the endpoint runs in a threadpool and the session's own
    # SQLite connection is bound to the thread it was created on — a regression
    # guard for the cross-thread error that returned a 500.
    from jutul_agent.trace import TraceLog

    manager = _manager(echo_agent, tmp_path)
    with TestClient(create_app(manager)) as client:
        sid = client.post("/sessions", json={"sim": "jutuldarcy"}).json()["session_id"]
        state_dir = manager.get(sid).session.state_dir  # type: ignore[union-attr]
        with TraceLog(state_dir / "trace.sqlite") as log:  # own connection (test thread)
            log.append("model_usage", {"input_tokens": 1200, "output_tokens": 80})
        resp = client.get(f"/sessions/{sid}/context")
        assert resp.status_code == 200
        assert resp.json()["markdown"].strip()
        assert client.get("/sessions/nope/context").status_code == 404


def test_history_endpoint_shape(tmp_path: Path) -> None:
    with _client(echo_agent, tmp_path) as client:
        body = client.get("/sessions/history").json()
    assert isinstance(body.get("sessions"), list)
    for s in body["sessions"]:
        assert {"id", "title", "started", "sim"} <= set(s)


def test_messages_endpoint_replays_conversation(tmp_path: Path) -> None:
    from jutul_agent.trace import TraceLog

    manager = _manager(echo_agent, tmp_path)
    with TestClient(create_app(manager)) as client:
        sid = client.post("/sessions", json={"sim": "jutuldarcy"}).json()["session_id"]
        state_dir = manager.get(sid).session.state_dir  # type: ignore[union-attr]
        with TraceLog(state_dir / "trace.sqlite") as log:  # own connection (test thread)
            log.append("message_user", {"content": "set up a reservoir"})
            log.append("message_reasoning", {"content": "I'll build a small grid"})
            log.append(
                "tool_call",
                {"id": "c1", "name": "run_julia", "args": {"code": "1+1"}},
            )
            log.append(
                "tool_result",
                {"tool_call_id": "c1", "name": "run_julia", "content": "2", "status": "success"},
            )
            log.append("message_assistant", {"content": "done — here it is"})
        msgs = client.get(f"/sessions/{sid}/messages").json()["messages"]
    assert {"type": "user", "text": "set up a reservoir"} in msgs
    assert {"type": "reasoning", "text": "I'll build a small grid"} in msgs
    assert {"type": "assistant", "text": "done — here it is"} in msgs
    # A tool replays as a requested card followed by its finished result, so the
    # resumed chat shows the full tool card with its output (not just text).
    requested = next(m for m in msgs if m["type"] == "tool" and m["event"] == "requested")
    assert requested["tool_call_id"] == "c1" and requested["args"] == {"code": "1+1"}
    finished = next(m for m in msgs if m["type"] == "tool" and m["event"] == "finished")
    assert finished["tool_call_id"] == "c1" and finished["content"] == "2"


def test_first_turn_generates_llm_title(tmp_path: Path, monkeypatch: Any) -> None:
    # After the first turn the server replaces the first-prompt title with a
    # content-aware one (best-effort) and nudges the front end to refresh history.
    from jutul_agent import session as session_mod
    from jutul_agent.agent import titling

    async def fake_title(model_id: Any, conversation: str) -> str:
        return "Reservoir Sweep Study"

    monkeypatch.setattr(titling, "generate_session_title", fake_title)

    with _client(echo_agent, tmp_path) as client:
        sid = client.post("/sessions", json={"sim": "jutuldarcy"}).json()["session_id"]
        with client.websocket_connect(f"/sessions/{sid}/stream") as ws:
            ws.send_json({"type": "prompt", "text": "set up a small reservoir"})
            events = _drain_turn(ws)
            renamed = ws.receive_json()  # the post-turn history-refresh signal
    assert events[-1]["type"] == "turn_end"
    assert renamed["type"] == "ui" and renamed["action"] == "history_changed"
    assert renamed["payload"]["title"] == "Reservoir Sweep Study"
    # The new title is persisted, so a history listing shows it.
    titles = [s.title for s in session_mod.list_sessions(state_root=tmp_path)]
    assert "Reservoir Sweep Study" in titles


def test_upload_writes_to_workspace(tmp_path: Path) -> None:
    manager = _manager(echo_agent, tmp_path)
    with TestClient(create_app(manager)) as client:
        sid = client.post("/sessions", json={"sim": "jutuldarcy"}).json()["session_id"]
        manager.get(sid).workspace = tmp_path  # type: ignore[union-attr]
        resp = client.post(
            f"/sessions/{sid}/upload",
            files={"file": ("my data.csv", b"a,b\n1,2\n", "text/csv")},
        )
    assert resp.status_code == 200
    assert resp.json()["path"] == "uploads/my_data.csv"  # basename + sanitized
    assert (tmp_path / "uploads" / "my_data.csv").read_bytes() == b"a,b\n1,2\n"


@pytest.mark.parametrize("agent_factory", [echo_agent])
def test_unknown_simulator_is_400(agent_factory: Callable[[], Any], tmp_path: Path) -> None:
    # The default manager (no injected factory) resolves the simulator registry,
    # so an unknown name is a client error rather than a server crash.
    with TestClient(create_app(SessionManager())) as client:
        resp = client.post("/sessions", json={"sim": "does-not-exist"})
    assert resp.status_code == 400
