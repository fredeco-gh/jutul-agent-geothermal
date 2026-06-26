"""Tests for the example demo app's Python wiring (no Julia or browser needed)."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

from fakes import FakeJulia, make_fake_adapter
from jutul_agent.session import Session

_DEMO_PATH = Path(__file__).resolve().parents[1] / "examples" / "demo-app" / "demo.py"


def _load_demo():
    spec = importlib.util.spec_from_file_location("demo_app", _DEMO_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


demo = _load_demo()


def _session(tmp_path: Path) -> Session:
    return Session.create(
        julia=FakeJulia(), simulator=make_fake_adapter(tmp_path), state_root=tmp_path
    )


def test_capability_is_web_with_four_tools() -> None:
    cap = demo.demo_capability()
    assert cap.surfaces == ("web",)
    assert len(cap.tools) == 4
    assert cap.prompt_fragment


def test_set_param_emits_ui_event(tmp_path: Path) -> None:
    session = _session(tmp_path)
    set_param = demo._make_set_param_tool(session)
    out = asyncio.run(set_param.ainvoke({"p": 5}))
    assert "5" in out
    ui_events = [e for e in session.trace.iter_events() if e.kind == "ui"]
    assert ui_events[-1].payload == {"action": "set_param", "payload": {"p": 5.0}}


def test_plot_response_records_html_artifact(tmp_path: Path) -> None:
    session = _session(tmp_path)
    plot_response = demo._make_plot_tool(session)
    out = asyncio.run(plot_response.ainvoke({"p": 3}))
    assert "3" in out
    artifacts = [e for e in session.trace.iter_events() if e.kind == "artifact"]
    assert artifacts[-1].payload["mime"] == "text/html"
    assert artifacts[-1].payload["path"].endswith(".html")
    # The tool drove the Julia export.
    assert any("Bonito.export_static" in code for code in session.julia.calls)


def test_show_test_map_pins_a_map_artifact(tmp_path: Path) -> None:
    session = _session(tmp_path)
    show_test_map = demo._make_show_test_map_tool(session)
    asyncio.run(show_test_map.ainvoke({}))
    artifacts = [e for e in session.trace.iter_events() if e.kind == "artifact"]
    assert artifacts[-1].payload["kind"] == "map"
    assert artifacts[-1].payload["slot"] == "test-map"
    assert (session.output_dir / artifacts[-1].payload["path"]).is_file()


def test_fly_test_map_emits_a_targeted_ui_event(tmp_path: Path) -> None:
    session = _session(tmp_path)
    fly_test_map = demo._make_fly_test_map_tool(session)
    out = asyncio.run(fly_test_map.ainvoke({"lng": 10, "lat": 20, "zoom": 5}))
    assert "10" in out
    ui_events = [e for e in session.trace.iter_events() if e.kind == "ui"]
    assert ui_events[-1].payload == {
        "action": "fly_to",
        "payload": {"lng": 10.0, "lat": 20.0, "zoom": 5.0},
        "target": "slot:test-map",
    }
