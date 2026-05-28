"""Tests for the julia_plot tool."""

from __future__ import annotations

from pathlib import Path

from fakes import FakeJulia, make_fake_adapter
from jutul_agent.agent.julia_plot import make_julia_plot_tool
from jutul_agent.julia.session import EvalResult
from jutul_agent.session import Session
from jutul_agent.trace import TraceLog


async def _plot_call(tool, args: dict, *, tool_call_id: str) -> str:
    msg = await tool.ainvoke(
        {
            "type": "tool_call",
            "name": "julia_plot",
            "id": tool_call_id,
            "args": args,
        }
    )
    return str(getattr(msg, "content", msg))


def _make_plot_eval_handler(written: list[str], *, accept_figure: bool = True):
    async def fake_eval(code: str) -> EvalResult:
        if code.strip() == "using CairoMakie":
            return EvalResult(output="")
        if "module JutulAgentPlots" in code:
            return EvalResult(output="")
        if code.strip().startswith("include("):
            return EvalResult(output="")
        if "JutulAgentPlots.plot_and_save" in code:
            if not accept_figure:
                return EvalResult(
                    output="",
                    error="julia_plot: code must evaluate to a Makie Figure; got Int64",
                )
            for line in code.splitlines():
                if "path = raw" in line:
                    start = line.index('raw"') + 4
                    end = line.rindex('"')
                    path = line[start:end]
                    written.append(path)
                    Path(path).parent.mkdir(parents=True, exist_ok=True)
                    Path(path).write_bytes(b"\x89PNG\r\n")
            return EvalResult(output="")
        return EvalResult(output="")

    return fake_eval


async def test_julia_plot_records_artifact_and_writes_file(
    tmp_path: Path,
) -> None:
    written: list[str] = []

    julia = FakeJulia(eval_handler=_make_plot_eval_handler(written))
    adapter = make_fake_adapter(tmp_path)
    plot_session = Session.create(
        julia=julia,
        state_root=tmp_path,
        simulator=adapter,
        session_id="plot-test",
    )

    tool = make_julia_plot_tool(plot_session)
    result = await _plot_call(
        tool,
        {"code": "lines(1:10)", "caption": "line plot"},
        tool_call_id="call_plot_default",
    )

    assert "saved plot to" in result
    assert "/artifacts/plot-" in result
    assert "format=png" in result
    assert written
    assert Path(written[0]).exists()

    log = TraceLog(plot_session.state_dir / "trace.sqlite")
    try:
        artifact = next(ev for ev in log.iter_events() if ev.kind == "artifact")
        assert artifact.payload["mime"] == "image/png"
        assert artifact.payload["caption"] == "line plot"
        assert artifact.payload["path"].startswith("artifacts/plot-")
        assert artifact.payload["source_code"] == "lines(1:10)"
        assert artifact.payload["format"] == "png"
    finally:
        log.close()


async def test_julia_plot_svg_format(tmp_path: Path) -> None:
    written: list[str] = []
    julia = FakeJulia(eval_handler=_make_plot_eval_handler(written))
    adapter = make_fake_adapter(tmp_path)
    plot_session = Session.create(julia=julia, state_root=tmp_path, simulator=adapter)

    tool = make_julia_plot_tool(plot_session)
    result = await _plot_call(
        tool,
        {"code": "lines(1:3)", "format": "svg"},
        tool_call_id="call_plot_svg",
    )

    assert result.startswith("saved plot to")
    assert "/artifacts/plot-" in result
    assert "format=svg" in result
    assert written[0].endswith(".svg")

    log = TraceLog(plot_session.state_dir / "trace.sqlite")
    try:
        artifact = next(ev for ev in log.iter_events() if ev.kind == "artifact")
        assert artifact.payload["mime"] == "image/svg+xml"
        assert artifact.payload["format"] == "svg"
    finally:
        log.close()


async def test_julia_plot_slot_overwrites_path(tmp_path: Path) -> None:
    written: list[str] = []
    julia = FakeJulia(eval_handler=_make_plot_eval_handler(written))
    adapter = make_fake_adapter(tmp_path)
    plot_session = Session.create(julia=julia, state_root=tmp_path, simulator=adapter)

    tool = make_julia_plot_tool(plot_session)
    result = await _plot_call(
        tool,
        {"code": "lines(1:2)", "slot": "comparison"},
        tool_call_id="call_plot_slot",
    )

    assert "/artifacts/comparison.png" in result
    assert "slot=comparison" in result

    log = TraceLog(plot_session.state_dir / "trace.sqlite")
    try:
        artifact = next(ev for ev in log.iter_events() if ev.kind == "artifact")
        assert artifact.payload["slot"] == "comparison"
        assert artifact.payload["path"] == "artifacts/comparison.png"
    finally:
        log.close()


async def test_julia_plot_records_tool_call_id(tmp_path: Path) -> None:
    written: list[str] = []
    julia = FakeJulia(eval_handler=_make_plot_eval_handler(written))
    adapter = make_fake_adapter(tmp_path)
    plot_session = Session.create(julia=julia, state_root=tmp_path, simulator=adapter)

    tool = make_julia_plot_tool(plot_session)
    await _plot_call(
        tool,
        {"code": "lines(1:2)", "caption": "rates"},
        tool_call_id="call_plot_99",
    )

    log = TraceLog(plot_session.state_dir / "trace.sqlite")
    try:
        artifact = next(ev for ev in log.iter_events() if ev.kind == "artifact")
        assert artifact.payload["tool_call_id"] == "call_plot_99"
    finally:
        log.close()


async def test_julia_plot_size_px_in_artifact(tmp_path: Path) -> None:
    written: list[str] = []
    julia = FakeJulia(eval_handler=_make_plot_eval_handler(written))
    adapter = make_fake_adapter(tmp_path)
    plot_session = Session.create(julia=julia, state_root=tmp_path, simulator=adapter)

    tool = make_julia_plot_tool(plot_session)
    await _plot_call(
        tool,
        {"code": "lines(1:2)", "size": (640, 480)},
        tool_call_id="call_plot_size",
    )

    log = TraceLog(plot_session.state_dir / "trace.sqlite")
    try:
        artifact = next(ev for ev in log.iter_events() if ev.kind == "artifact")
        assert artifact.payload["size_px"] == [640, 480]
    finally:
        log.close()


async def test_julia_plot_not_a_figure_error(tmp_path: Path) -> None:
    julia = FakeJulia(eval_handler=_make_plot_eval_handler([], accept_figure=False))
    adapter = make_fake_adapter(tmp_path)
    plot_session = Session.create(julia=julia, state_root=tmp_path, simulator=adapter)

    tool = make_julia_plot_tool(plot_session)
    result = await _plot_call(tool, {"code": "42"}, tool_call_id="call_plot_bad")

    assert result.startswith("ERROR:")
    assert "Figure" in result


async def test_julia_plot_missing_cairomakie(tmp_path: Path) -> None:
    async def fail_eval(code: str, *, session: str | None = None) -> EvalResult:
        if code.strip() == "using CairoMakie":
            return EvalResult(output="", error="Package CairoMakie not found")
        return EvalResult(output="")

    julia = FakeJulia(eval_handler=fail_eval)
    adapter = make_fake_adapter(tmp_path)
    plot_session = Session.create(julia=julia, state_root=tmp_path, simulator=adapter)

    tool = make_julia_plot_tool(plot_session)
    result = await _plot_call(tool, {"code": "lines(1:10)"}, tool_call_id="call_plot_no_cairo")

    assert result.startswith("ERROR:")
    assert "CairoMakie" in result


def test_battmo_project_includes_cairomakie() -> None:
    from jutul_agent.simulators.battmo import BATTMO

    text = (BATTMO.julia_env_template_path / "Project.toml").read_text(encoding="utf-8")
    assert "CairoMakie" in text
