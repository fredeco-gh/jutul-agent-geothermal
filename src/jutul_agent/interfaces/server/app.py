"""The FastAPI application: REST lifecycle plus the per-session turn WebSocket.

REST creates, lists, resumes, and closes sessions, and serves the files a
session produces. The WebSocket at ``/sessions/{id}/stream`` carries one turn at
a time: the client sends a prompt (or an approval decision, or a cancel), and
the server streams the agent's events back, serialized by ``protocol``.

``create_app`` takes a ``SessionManager`` so tests can inject one whose sessions
wrap fakes; the default manager stands up real sessions.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

from jutul_agent.agent.approval import build_resume_payload
from jutul_agent.interfaces.server import protocol
from jutul_agent.interfaces.server.manager import SessionManager
from jutul_agent.interfaces.server.session_host import SessionHost


class HttpToolSpecModel(BaseModel):
    """A host application's operation, declared so the agent gets a tool for it."""

    name: str
    description: str
    endpoint: str
    parameters: dict[str, dict[str, Any]] = {}


class CreateSessionRequest(BaseModel):
    sim: str
    model: str | None = None
    approval_mode: str | None = None
    workspace: str | None = None
    tools: list[HttpToolSpecModel] | None = None


class ResumeSessionRequest(BaseModel):
    sim: str
    model: str | None = None
    approval_mode: str | None = None
    workspace: str | None = None


def _request_extensions(tools: list[HttpToolSpecModel] | None) -> list:
    """Turn declared HTTP tool specs into a host-app capability, if any were sent."""
    if not tools:
        return []
    from jutul_agent.agent.capabilities import HttpToolSpec, http_tool_capability

    specs = [
        HttpToolSpec(
            name=tool.name,
            description=tool.description,
            endpoint=tool.endpoint,
            parameters=tool.parameters,
        )
        for tool in tools
    ]
    return [http_tool_capability("host-app", specs)]


def create_app(manager: SessionManager | None = None) -> FastAPI:
    manager = manager or SessionManager()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        await manager.aclose()

    app = FastAPI(
        title="jutul-agent",
        summary="Drive a jutul-agent session over HTTP and WebSocket.",
        lifespan=lifespan,
    )
    app.state.manager = manager

    @app.get("/models")
    def list_models() -> dict[str, Any]:
        from jutul_agent.models import DEFAULT_MODEL, PROVIDERS

        return {"default": DEFAULT_MODEL, "providers": sorted(PROVIDERS)}

    @app.post("/sessions")
    async def create_session(req: CreateSessionRequest) -> dict[str, str]:
        try:
            host = await manager.create(
                sim=req.sim,
                model=req.model,
                approval_mode=req.approval_mode,
                workspace=req.workspace,
                extensions=_request_extensions(req.tools),
            )
        except KeyError as exc:  # unknown simulator
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"session_id": host.session_id}

    @app.get("/sessions")
    def list_sessions() -> dict[str, list[str]]:
        return {"sessions": manager.list_ids()}

    @app.post("/sessions/{session_id}/resume")
    async def resume_session(session_id: str, req: ResumeSessionRequest) -> dict[str, str]:
        try:
            host = await manager.resume(
                session_id,
                sim=req.sim,
                model=req.model,
                approval_mode=req.approval_mode,
                workspace=req.workspace,
            )
        except (KeyError, FileNotFoundError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"session_id": host.session_id}

    @app.delete("/sessions/{session_id}")
    async def delete_session(session_id: str) -> dict[str, bool]:
        if not await manager.close(session_id):
            raise HTTPException(status_code=404, detail="no such session")
        return {"ok": True}

    @app.get("/sessions/{session_id}/artifacts/{path:path}")
    def get_artifact(session_id: str, path: str) -> FileResponse:
        host = manager.get(session_id)
        if host is None:
            raise HTTPException(status_code=404, detail="no such session")
        target = _resolve_artifact(host, path)
        if target is None:
            raise HTTPException(status_code=404, detail="no such artifact")
        return FileResponse(target)

    @app.websocket("/sessions/{session_id}/stream")
    async def stream(websocket: WebSocket, session_id: str) -> None:
        await _serve_stream(websocket, manager.get(session_id))

    return app


def _resolve_artifact(host: SessionHost, path: str):
    """The artifact file for ``path``, or ``None`` if it escapes the session dir."""
    base = (host.session.output_dir / "artifacts").resolve()
    target = (base / path).resolve()
    if not target.is_file() or not target.is_relative_to(base):
        return None
    return target


async def _serve_stream(websocket: WebSocket, host: SessionHost | None) -> None:
    await websocket.accept()
    if host is None:
        await _safe_send(websocket, {"type": "error", "message": "no such session"})
        await websocket.close()
        return

    state = _StreamState(websocket, host)
    try:
        while True:
            message = await websocket.receive_json()
            await state.handle(message)
    except WebSocketDisconnect:
        pass
    finally:
        await state.cancel_turn()


class _StreamState:
    """Per-connection turn state: at most one turn in flight, plus pending approvals."""

    def __init__(self, websocket: WebSocket, host: SessionHost) -> None:
        self._ws = websocket
        self._host = host
        self._pending: list[Any] = []
        self._turn: asyncio.Task[None] | None = None

    async def handle(self, message: dict[str, Any]) -> None:
        kind = message.get("type")
        if kind == "prompt":
            await self._start_prompt(str(message.get("text") or ""))
        elif kind == "decision":
            await self._start_decision(message)
        elif kind == "cancel":
            await self.cancel_turn()
        elif kind == "ui_event":
            self._host.session.trace.append("ui_event", {"payload": message.get("payload")})
        else:
            await _safe_send(self._ws, {"type": "error", "message": f"unknown message {kind!r}"})

    async def _start_prompt(self, text: str) -> None:
        if self._busy():
            await _safe_send(self._ws, {"type": "error", "message": "a turn is already running"})
            return
        runner = self._host.runner
        self._spawn(lambda: runner.run_prompt(text, on_message=self._on_message))

    async def _start_decision(self, message: dict[str, Any]) -> None:
        if self._busy():
            await _safe_send(self._ws, {"type": "error", "message": "a turn is already running"})
            return
        if not self._pending:
            await _safe_send(self._ws, {"type": "error", "message": "no approval is pending"})
            return
        decision: dict[str, str] = {"type": str(message.get("decision") or "approve")}
        if message.get("message"):
            decision["message"] = str(message["message"])
        payload = build_resume_payload(self._pending, decision)
        self._pending = []
        runner = self._host.runner
        self._spawn(lambda: runner.resume(payload, on_message=self._on_message))

    def _busy(self) -> bool:
        return self._turn is not None and not self._turn.done()

    def _spawn(self, factory) -> None:
        self._turn = asyncio.create_task(self._run_turn(factory))

    async def _run_turn(self, factory) -> None:
        try:
            result = await factory()
        except asyncio.CancelledError:
            await _safe_send(self._ws, {"type": "turn_end", "text": "", "cancelled": True})
            raise
        except Exception as exc:  # surface the failure, then end the turn
            await _safe_send(self._ws, {"type": "error", "message": str(exc)})
            await _safe_send(self._ws, {"type": "turn_end", "text": ""})
            return
        self._pending = list(result.interrupts)
        if self._pending:
            # The turn paused for approval. Send the requests and wait for a
            # decision; the turn ends only once it runs to completion.
            for interrupt in self._pending:
                await _safe_send(self._ws, protocol.interrupt_to_wire(interrupt))
            return
        usage = protocol.usage_to_wire(result.messages)
        if usage is not None:
            await _safe_send(self._ws, usage)
        await _safe_send(self._ws, protocol.turn_end_to_wire(result.messages))

    async def _on_message(self, event: Any) -> None:
        wire = protocol.to_wire(event)
        if wire is not None:
            await _safe_send(self._ws, wire)

    async def cancel_turn(self) -> None:
        if self._busy():
            self._turn.cancel()  # type: ignore[union-attr]
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._turn  # type: ignore[arg-type]


async def _safe_send(websocket: WebSocket, message: dict[str, Any]) -> None:
    """Send a JSON message, ignoring a socket that is already closing."""
    with contextlib.suppress(Exception):
        await websocket.send_json(message)
