"""Integration test: real Julia + CairoMakie via julia_plot."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from jutul_agent.agent.julia_plot import make_julia_plot_tool
from jutul_agent.julia.backends.agentrepl import AgentREPLBackend, AgentREPLConfig
from jutul_agent.session import Session
from jutul_agent.simulators.battmo import BATTMO
from jutul_agent.simulators.jutuldarcy import JUTULDARCY
from jutul_agent.trace import TraceLog

JUTULDARCY_ENV = JUTULDARCY.julia_env_template_path
BATTMO_ENV = BATTMO.julia_env_template_path


def _julia_available() -> bool:
    return shutil.which("julia") is not None


def _env_ready(env_dir: Path) -> bool:
    return (env_dir / "Project.toml").exists() and (env_dir / "Manifest.toml").exists()


pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    not _julia_available() or not _env_ready(JUTULDARCY_ENV),
    reason="Julia and the jutuldarcy env template are required",
)
async def test_julia_plot_real_cairomakie(tmp_path: Path) -> None:
    config = AgentREPLConfig(julia_project=JUTULDARCY_ENV)
    async with AgentREPLBackend(config) as julia:
        session = Session.create(
            julia=julia,
            state_root=tmp_path,
            simulator=JUTULDARCY,
            session_id="plot-integration",
        )
        tool = make_julia_plot_tool(session)
        code = (
            "using CairoMakie\n"
            "fig = Figure(size = (400, 300))\n"
            'ax = Axis(fig[1, 1], title = "Integration test")\n'
            "lines!(ax, 1:5, (1:5) .^ 2)\n"
            "fig"
        )
        msg = await tool.ainvoke(
            {
                "type": "tool_call",
                "name": "julia_plot",
                "id": "call_plot_integration",
                "args": {"code": code, "caption": "integration plot"},
            }
        )
        result = str(getattr(msg, "content", msg))
        assert "saved plot to" in result
        assert "/artifacts/plot-" in result
        assert "format=png" in result

        log = TraceLog(session.state_dir / "trace.sqlite")
        try:
            artifact = next(ev for ev in log.iter_events() if ev.kind == "artifact")
            rel_path = artifact.payload["path"]
            assert artifact.payload["format"] == "png"
            assert artifact.payload["source_code"] == code
            png_path = session.output_dir / rel_path
            assert png_path.exists()
            header = png_path.read_bytes()[:8]
            assert header.startswith(b"\x89PNG\r\n\x1a\n")
        finally:
            log.close()
            session.finalize()


@pytest.mark.skipif(
    not _julia_available() or not _env_ready(BATTMO_ENV),
    reason="Julia and the battmo env template are required",
)
async def test_julia_plot_battmo_inline_makie(tmp_path: Path) -> None:
    config = AgentREPLConfig(julia_project=BATTMO_ENV)
    async with AgentREPLBackend(config) as julia:
        session = Session.create(
            julia=julia,
            state_root=tmp_path,
            simulator=BATTMO,
            session_id="battmo-plot-integration",
        )
        tool = make_julia_plot_tool(session)
        code = (
            "using CairoMakie\n"
            "fig = Figure(size = (400, 300))\n"
            'ax = Axis(fig[1, 1], title = "BattMo integration test")\n'
            "lines!(ax, 1:5, (1:5) .^ 2)\n"
            "fig"
        )
        msg = await tool.ainvoke(
            {
                "type": "tool_call",
                "name": "julia_plot",
                "id": "call_battmo_plot",
                "args": {"code": code, "slot": "battmo_smoke"},
            }
        )
        result = str(getattr(msg, "content", msg))
        assert "/artifacts/battmo_smoke.png" in result

        png_path = session.output_dir / "artifacts" / "battmo_smoke.png"
        assert png_path.exists()
        assert png_path.read_bytes()[:8].startswith(b"\x89PNG\r\n\x1a\n")
        session.finalize()
