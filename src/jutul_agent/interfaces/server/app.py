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
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from jutul_agent.agent.approval import build_resume_payload
from jutul_agent.interfaces.server import protocol
from jutul_agent.interfaces.server.manager import SessionManager
from jutul_agent.interfaces.server.session_host import SessionHost

# The bundled web UI lives next to this module.
WEB_DIR = Path(__file__).resolve().parent / "web"


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


def create_app(
    manager: SessionManager | None = None,
    *,
    ui: bool = True,
    default_sim: str | None = None,
) -> FastAPI:
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

    @app.get("/simulators")
    def list_simulators() -> dict[str, Any]:
        from jutul_agent.simulators import registry

        return {"simulators": registry.names(), "default": default_sim}

    def _workspace_for(sim: str, requested: str | None) -> Path | None:
        """The workspace a session for ``sim`` should run in.

        An explicit request wins. The launched (default) simulator uses the
        server's own workspace (the cwd, or whatever ``set_workspace_root`` set),
        preserving single-simulator behaviour. Any other simulator picked at
        runtime gets its own cached environment under the state home, so switching
        simulators doesn't rebuild the one shared workspace each time.
        """
        if requested:
            return Path(requested)
        if default_sim is None or sim == default_sim:
            return None  # SessionHost.start falls back to workspace_root()
        from jutul_agent.paths import state_home

        ws = state_home() / "web-workspaces" / sim
        ws.mkdir(parents=True, exist_ok=True)
        return ws

    @app.post("/sessions")
    async def create_session(req: CreateSessionRequest) -> dict[str, str]:
        try:
            host = await manager.create(
                sim=req.sim,
                model=req.model,
                approval_mode=req.approval_mode,
                workspace=_workspace_for(req.sim, req.workspace),
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
                workspace=_workspace_for(req.sim, req.workspace),
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

    @app.get("/sessions/{session_id}/transcript")
    def get_transcript(session_id: str, format: str = "html") -> Response:
        """The session transcript, as a page to view (html) or a file to save (md)."""
        host = manager.get(session_id)
        if host is None:
            raise HTTPException(status_code=404, detail="no such session")
        from jutul_agent.trace import TraceLog
        from jutul_agent.transcript import render_html, render_markdown

        with TraceLog(host.session.state_dir / "trace.sqlite") as log:
            events = list(log.iter_events())
        if format in ("md", "markdown"):
            return PlainTextResponse(
                render_markdown(events),
                media_type="text/markdown",
                headers={"Content-Disposition": "attachment; filename=transcript.md"},
            )
        return HTMLResponse(render_html(events))

    @app.get("/sessions/{session_id}/memory")
    def get_memory(session_id: str) -> Response:
        """The session's workspace memory, rendered as a page for the canvas."""
        host = manager.get(session_id)
        if host is None:
            raise HTTPException(status_code=404, detail="no such session")
        from jutul_agent.agent.memory import render_memory_overview
        from jutul_agent.transcript.markdown_html import render_markdown_html

        body = render_markdown_html(render_memory_overview(host.memory_dir))
        return HTMLResponse(_doc_page("Memory", body))

    @app.websocket("/sessions/{session_id}/stream")
    async def stream(websocket: WebSocket, session_id: str) -> None:
        await _serve_stream(websocket, manager.get(session_id))

    # The bundled web UI is mounted last so the API routes above take precedence.
    if ui and WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")

    return app


def _artifact_url(session_id: str, rel: str) -> str:
    """The fetch URL for a session artifact given its workspace-relative path."""
    rel = rel[len("artifacts/") :] if rel.startswith("artifacts/") else rel
    return f"/sessions/{session_id}/artifacts/{rel}"


def artifact_wire_events(payloads: list[dict[str, Any]], session_id: str) -> list[dict[str, Any]]:
    """Wire events for produced artifacts: interactive HTML as ``viz``, the rest as ``artifact``.

    An HTML artifact (an interactive plot, or a written report) becomes a ``viz``
    the front end pins to its canvas, carrying the artifact's ``kind``, ``slot``,
    and a ``poster`` image URL when one was saved alongside.
    """
    events: list[dict[str, Any]] = []
    for payload in payloads:
        url = _artifact_url(session_id, str(payload.get("path") or ""))
        # A live plot is served from the session's Bonito server (its widgets work),
        # so it carries a live_url and its recorded file is the PNG poster. A static
        # plot or report is an HTML artifact embedded at its own URL. Everything else
        # (a saved image, a file) is a plain artifact.
        live_url = payload.get("live_url")
        poster = payload.get("poster")
        if live_url or payload.get("mime") == "text/html":
            events.append(
                protocol.viz_to_wire(
                    str(live_url) if live_url else url,
                    title=payload.get("caption"),
                    kind=str(payload.get("kind") or "plot"),
                    poster=_artifact_url(session_id, str(poster)) if poster else None,
                    slot=payload.get("slot"),
                )
            )
        else:
            events.append(protocol.artifact_to_wire(payload, url=url))
    return events


def _doc_page(title: str, body_html: str) -> str:
    """Wrap rendered HTML in a minimal, self-contained page for the canvas iframe."""
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>" + title + "</title><style>"
        "body{margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;"
        "color:#1f2328;background:#fff;line-height:1.6}"
        ".page{max-width:760px;margin:0 auto;padding:2rem 1.6rem}"
        "h1,h2,h3{line-height:1.3;letter-spacing:-0.01em}h1{font-size:1.5rem}"
        "code{font-family:ui-monospace,Consolas,monospace;background:#f0f1ee;padding:.1em .35em;"
        "border-radius:5px;font-size:.88em}"
        "pre{background:#f0f1ee;border:1px solid #e3e3df;border-radius:10px;padding:.8rem;"
        "overflow:auto}"
        "pre code{background:none;padding:0}a{color:#0e7490}"
        "</style></head><body><div class='page'>" + body_html + "</div></body></html>"
    )


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
        elif kind == "command":
            await self._handle_command(message)
        else:
            await _safe_send(self._ws, {"type": "error", "message": f"unknown message {kind!r}"})

    async def _handle_command(self, message: dict[str, Any]) -> None:
        """Apply a session setting (model, approval policy) mid-conversation.

        Rebuilds the agent in place — the kernel, the conversation history, and the
        live Julia state all survive — so a front end can offer these as commands.
        """
        if self._busy():
            await _safe_send(
                self._ws,
                {"type": "error", "message": "finish the current turn before changing settings"},
            )
            return
        command = message.get("command")
        arg = str(message.get("arg") or "")
        try:
            if command == "set_model":
                self._host.reconfigure(model=arg)
            elif command == "set_approval":
                self._host.reconfigure(approval_mode=arg)
            elif command == "add_dir":
                await _safe_send(self._ws, protocol.notice_to_wire(self._host.add_dir(arg)))
            elif command == "compact":
                await _safe_send(self._ws, protocol.notice_to_wire(await self._host.compact()))
            else:
                await _safe_send(
                    self._ws, {"type": "error", "message": f"unknown command {command!r}"}
                )
                return
        except Exception as exc:  # surface a bad model/mode, keep the session alive
            await _safe_send(
                self._ws, {"type": "error", "message": f"could not apply {command}: {exc}"}
            )

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
        since_id = self._latest_event_id()
        try:
            result = await factory()
        except asyncio.CancelledError:
            await self._emit_new_outputs(since_id)
            await _safe_send(self._ws, {"type": "turn_end", "text": "", "cancelled": True})
            raise
        except Exception as exc:  # surface the failure, then end the turn
            await _safe_send(self._ws, {"type": "error", "message": str(exc)})
            await _safe_send(self._ws, {"type": "turn_end", "text": ""})
            return
        await self._emit_new_outputs(since_id)
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

    def _latest_event_id(self) -> int:
        events = self._host.session.trace.iter_events()
        return events[-1].id if events else 0

    async def _emit_new_outputs(self, since_id: int) -> None:
        """Forward the side outputs a turn produced: artifacts (plots, reports) and
        UI commands a tool emitted. Keyed on trace event id so each is sent once."""
        for event in self._host.session.trace.iter_events():
            if event.id <= since_id:
                continue
            if event.kind == "artifact":
                for wire in artifact_wire_events([event.payload], self._host.session_id):
                    await _safe_send(self._ws, wire)
            elif event.kind == "ui":
                action = str(event.payload.get("action") or "")
                payload = event.payload.get("payload")
                await _safe_send(self._ws, protocol.ui_command(action, payload))

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
