"""Tests for the geothermal-map example's Python wiring (no Julia or browser needed)."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path

from fakes import FakeJulia, make_fake_adapter
from jutul_agent.session import Session

_CAPABILITY_PATH = (
    Path(__file__).resolve().parents[1] / "examples" / "geothermal-map" / "capability.py"
)


def _load_capability():
    spec = importlib.util.spec_from_file_location(
        "geothermal_map_capability_module", _CAPABILITY_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


capability = _load_capability()

_FEATURES = [
    {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [10.7, 59.9]},
        "properties": {"layer": "EnergiBrønn", "brønnNr": "100", "beskrivelse": "Test well"},
    },
    {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [10.8, 60.0]},
        "properties": {"layer": "BrønnPark", "brønnParkNr": "200", "brønnpOmrNavn": "Test park"},
    },
]


def _session(tmp_path: Path) -> Session:
    return Session.create(
        julia=FakeJulia(), simulator=make_fake_adapter(tmp_path), state_root=tmp_path
    )


def _data_path(tmp_path: Path) -> str:
    path = tmp_path / "boreholes.geojson"
    path.write_text(
        json.dumps({"type": "FeatureCollection", "features": _FEATURES}), encoding="utf-8"
    )
    return str(path)


def test_capability_is_web_with_three_tools() -> None:
    cap = capability.geothermal_map_capability("unused")
    assert cap.surfaces == ("web",)
    assert len(cap.tools) == 3
    assert cap.prompt_fragment


def test_set_map_view_emits_a_targeted_ui_action(tmp_path: Path) -> None:
    session = _session(tmp_path)
    set_map_view = capability._make_set_map_view_tool(session)
    out = asyncio.run(set_map_view.ainvoke({"lon": 10.5, "lat": 59.9, "zoom": 12}))
    assert "10.5" in out
    ui_events = [e for e in session.trace.iter_events() if e.kind == "ui"]
    assert ui_events[-1].payload == {
        "action": "set_map_view",
        "payload": {"lon": 10.5, "lat": 59.9, "zoom": 12.0},
        "target": "slot:geothermal-map",
    }


def test_go_to_well_finds_an_exact_number_match(tmp_path: Path) -> None:
    session = _session(tmp_path)
    go_to_well = capability._make_go_to_well_tool(session, _data_path(tmp_path))
    out = asyncio.run(go_to_well.ainvoke({"identifier": "100"}))
    assert "100" in out
    ui_events = [e for e in session.trace.iter_events() if e.kind == "ui"]
    payload = ui_events[-1].payload
    assert payload["action"] == "go_to_well"
    assert payload["target"] == "slot:geothermal-map"
    assert payload["payload"]["lon"] == 10.7
    assert payload["payload"]["lat"] == 59.9
    assert payload["payload"]["feature"]["properties"]["brønnNr"] == "100"


def test_go_to_well_reports_not_found_without_claiming_success(tmp_path: Path) -> None:
    session = _session(tmp_path)
    go_to_well = capability._make_go_to_well_tool(session, _data_path(tmp_path))
    out = asyncio.run(go_to_well.ainvoke({"identifier": "no-such-well"}))
    assert "No well matching" in out
    assert not [e for e in session.trace.iter_events() if e.kind == "ui"]


def test_go_to_well_park_only_matches_park_features(tmp_path: Path) -> None:
    session = _session(tmp_path)
    go_to_well_park = capability._make_go_to_well_park_tool(session, _data_path(tmp_path))
    out = asyncio.run(go_to_well_park.ainvoke({"identifier": "200"}))
    assert "200" in out
    ui_events = [e for e in session.trace.iter_events() if e.kind == "ui"]
    feature = ui_events[-1].payload["payload"]["feature"]
    assert feature["properties"]["layer"] == "BrønnPark"

    # A well sharing the park's number (none here) must not satisfy the park
    # lookup — only the park's own number/area fields qualify (_PARK_*_FIELDS).
    out2 = asyncio.run(go_to_well_park.ainvoke({"identifier": "100"}))
    assert "No well park matching" in out2


def test_map_is_pinned_once_per_session(tmp_path: Path) -> None:
    session = _session(tmp_path)
    set_map_view = capability._make_set_map_view_tool(session)
    asyncio.run(set_map_view.ainvoke({"lon": 1, "lat": 2}))
    asyncio.run(set_map_view.ainvoke({"lon": 3, "lat": 4}))
    artifacts = [e for e in session.trace.iter_events() if e.kind == "artifact"]
    assert len(artifacts) == 1
    assert artifacts[0].payload["kind"] == "map"
    assert artifacts[0].payload["slot"] == "geothermal-map"
