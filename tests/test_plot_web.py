"""The web surface renders plots as interactive HTML (WGLMakie + Bonito)."""

from __future__ import annotations

from pathlib import Path

from fakes import FakeJulia, make_fake_adapter
from jutul_agent.agent.plot_julia import make_plot_julia_tool
from jutul_agent.julia.session import EvalResult
from jutul_agent.session import Session
from jutul_agent.trace import TraceLog


def _session(tmp_path: Path, julia: FakeJulia) -> Session:
    return Session.create(julia=julia, state_root=tmp_path, simulator=make_fake_adapter(tmp_path))


async def _call(tool, args: dict) -> str:
    msg = await tool.ainvoke({"type": "tool_call", "name": "plot_julia", "id": "c1", "args": args})
    return str(getattr(msg, "content", msg))


async def test_web_surface_exports_interactive_html(tmp_path: Path) -> None:
    seen: list[str] = []

    async def fake_eval(code: str) -> EvalResult:
        seen.append(code)
        if code.strip() == "CairoMakie.Makie === WGLMakie.Makie":
            return EvalResult(output="true")
        return EvalResult(output="")

    session = _session(tmp_path, FakeJulia(eval_handler=fake_eval))
    tool = make_plot_julia_tool(session, surface="web")

    result = await _call(tool, {"code": "lines(1:3, 1:3)", "caption": "field", "slot": "pres"})

    assert ".html" in result
    assert any("import CairoMakie, WGLMakie, Bonito" in c for c in seen)
    assert any("Bonito.export_static" in c and "resize_to = :parent" in c for c in seen)

    log = TraceLog(session.state_dir / "trace.sqlite")
    try:
        artifact = next(ev for ev in log.iter_events() if ev.kind == "artifact")
        assert artifact.payload["mime"] == "text/html"
        assert artifact.payload["format"] == "html"
        assert artifact.payload["path"] == "artifacts/pres.html"
    finally:
        log.close()


async def test_web_surface_reports_missing_backend(tmp_path: Path) -> None:
    async def fake_eval(code: str) -> EvalResult:
        if code.strip() == "import CairoMakie, WGLMakie, Bonito":
            return EvalResult(output="", error="ArgumentError: Package WGLMakie not found")
        return EvalResult(output="")

    session = _session(tmp_path, FakeJulia(eval_handler=fake_eval))
    tool = make_plot_julia_tool(session, surface="web")

    result = await _call(tool, {"code": "lines(1:3, 1:3)"})
    assert "WGLMakie" in result and "Bonito" in result


async def test_web_surface_reports_makie_mismatch(tmp_path: Path) -> None:
    async def fake_eval(code: str) -> EvalResult:
        if code.strip() == "CairoMakie.Makie === WGLMakie.Makie":
            return EvalResult(output="false")
        return EvalResult(output="")

    session = _session(tmp_path, FakeJulia(eval_handler=fake_eval))
    tool = make_plot_julia_tool(session, surface="web")

    result = await _call(tool, {"code": "lines(1:3, 1:3)"})
    assert "Makie" in result and "overlay" in result


async def test_tui_surface_still_uses_glmakie(tmp_path: Path) -> None:
    seen: list[str] = []

    async def fake_eval(code: str) -> EvalResult:
        seen.append(code)
        return EvalResult(output="")

    session = _session(tmp_path, FakeJulia(eval_handler=fake_eval))
    tool = make_plot_julia_tool(session)  # default surface = tui

    await _call(tool, {"code": "lines(1:3, 1:3)"})
    assert any(c.strip() == "using GLMakie" for c in seen)
    assert not any("Bonito.export_static" in c for c in seen)
