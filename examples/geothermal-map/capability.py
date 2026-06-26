"""The geothermal map capability: tools that let the agent drive the native map
panel (see ``canvas/MapPanel.tsx`` in jutul-agent's webapp) by well name or
location.

Each tool below emits a `ui` trace event targeted at the map's own canvas view
(``target="slot:geothermal-map"``), which ``MapPanel.tsx`` picks up via its
``useUiActions`` hook — the same agent-to-UI pattern Phase 0's throwaway demo
proved (``fly_test_map``), just for a real well lookup instead of bare
coordinates. There is no dedicated Julia kernel and no second server here: the
map panel lives in the same process and the same session as the chat, ported
from geothermal-viz's ``web/js/app.js`` (rendering) and
``examples/geothermal-viz-app/capability.py`` (this file's predecessor).

This module is the skeleton for growing the agent's reach into the map: adding
a new ability means adding one ``_make_..._tool`` factory below, wiring it into
``geothermal_map_capability``'s ``tools`` tuple, and adding the matching case to
``MapPanel.tsx``'s `ui` action dispatch. Nothing else needs to change to pick
it up — serve.py passes whatever this returns straight into the session.

A tool that *asks* the map to do something (like ``set_map_view``) can return
right away — there's nothing to get wrong. But ``go_to_well``/``go_to_well_park``
resolve the well themselves, against the same GeoJSON file the map renders
from (read directly off disk here — no HTTP self-call, since the tool and the
data live in the same process now), so the agent can give an honest answer
immediately instead of waiting for the browser to report back on the *next*
message (see docs/server-interface.md's ui_event queueing).

Running a Fimbul simulation from this map is not wired up yet — that is a
later phase; right now this capability only resolves well lookups and drives
the map's camera/selection.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from jutul_agent.agent.capabilities import Capability
from jutul_agent.session import Session

# The map panel's fixed canvas slot: stable across every tool call in a
# session, so re-pinning (see _ensure_map_pinned) refreshes the same view
# instead of stacking a new tab, and `target` always reaches the same panel.
_MAP_SLOT = "geothermal-map"
_MAP_TARGET = f"slot:{_MAP_SLOT}"

# Matched first, exactly (case-insensitive): a well or well-park number.
_EXACT_FIELDS = ("brønnNr", "brønnParkNr")
# Matched next, as a substring, so a vaguer request still has a chance to resolve.
_LOOSE_FIELDS = (*_EXACT_FIELDS, "brønnpOmrNavn", "beskrivelse", "oppdragstaker")

# Same idea, but restricted to the well-park identifier itself — excludes
# `brønnNr` so a well-park lookup can't accidentally land on an unrelated well
# whose own number happens to match the park identifier given.
_PARK_EXACT_FIELDS = ("brønnParkNr",)
_PARK_LOOSE_FIELDS = ("brønnParkNr", "brønnpOmrNavn", "beskrivelse", "oppdragstaker")

# Cached per data path rather than per call: the dataset only changes when the
# offline scripts/process_data.jl reruns, so re-reading the (multi-MB) file on
# every tool call would be wasted work.
_wells_cache: dict[str, list[dict[str, Any]]] = {}

# Sessions that already have the map panel pinned. A fixed slot makes
# re-pinning idempotent in the canvas itself, but the store still appends a
# fresh chip to the thread on every viz message regardless — this guards
# against spamming one per tool call within the same session.
_map_pinned: set[str] = set()


def _load_well_features(data_path: str) -> list[dict[str, Any]]:
    cached = _wells_cache.get(data_path)
    if cached is not None:
        return cached
    geojson = json.loads(Path(data_path).read_text(encoding="utf-8"))
    features = geojson.get("features", [])
    _wells_cache[data_path] = features
    return features


def _find_well(
    features: list[dict[str, Any]],
    identifier: str,
    *,
    exact_fields: tuple[str, ...] = _EXACT_FIELDS,
    loose_fields: tuple[str, ...] = _LOOSE_FIELDS,
) -> dict[str, Any] | None:
    needle = str(identifier).strip().lower()
    if not needle:
        return None
    for feature in features:
        props = feature.get("properties", {})
        if any(str(props.get(f, "")).lower() == needle for f in exact_fields):
            return feature
    for feature in features:
        props = feature.get("properties", {})
        if any(needle in str(props.get(f, "")).lower() for f in loose_fields):
            return feature
    return None


def _ensure_map_pinned(session: Session) -> None:
    """Pin the map panel into the canvas the first time any map tool runs in
    this session. The file written here is never read by MapPanel itself (it
    renders natively, not in an iframe) — it only exists to satisfy the
    artifact plumbing that produces the `viz` wire message."""
    if session.session_id in _map_pinned:
        return
    _map_pinned.add(session.session_id)
    rel = "artifacts/geothermal-map.html"
    path = session.output_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("<!doctype html><title>Geothermal map</title>", encoding="utf-8")
    session.trace.append(
        "artifact",
        {
            "path": rel,
            "mime": "text/html",
            "kind": "map",
            "slot": _MAP_SLOT,
            "caption": "Geothermal map",
        },
    )


def _make_set_map_view_tool(session: Session):
    @tool
    async def set_map_view(lon: float, lat: float, zoom: float = 14.0) -> str:
        """Move the geothermal map to a location.

        Args:
            lon: Longitude in degrees (WGS84).
            lat: Latitude in degrees (WGS84).
            zoom: Map zoom level — roughly 0 for the whole world, 18 for street
                level. Defaults to 14, which frames a single borehole site.
        """
        _ensure_map_pinned(session)
        session.trace.append(
            "ui",
            {
                "action": "set_map_view",
                "payload": {"lon": lon, "lat": lat, "zoom": zoom},
                "target": _MAP_TARGET,
            },
        )
        return f"Moved the map to ({lat}, {lon}) at zoom {zoom}."

    return set_map_view


def _make_go_to_well_tool(session: Session, data_path: str):
    @tool
    async def go_to_well(identifier: str) -> str:
        """Fly the map to a specific well and select it, as if the user clicked it.

        Args:
            identifier: A well or well-park number (e.g. "12345"), or other
                identifying text (area name, contractor, description) to match
                loosely if no well/park number matches exactly.
        """
        try:
            features = _load_well_features(data_path)
        except Exception as exc:
            return f"Could not read the borehole data to look up wells: {exc}"
        feature = _find_well(features, identifier)
        if feature is None:
            return (
                f"No well matching '{identifier}' was found in the loaded borehole "
                "data — tell the user it doesn't exist rather than saying you moved "
                "the map."
            )
        lon, lat = feature["geometry"]["coordinates"]
        _ensure_map_pinned(session)
        session.trace.append(
            "ui",
            {
                "action": "go_to_well",
                "payload": {"lon": lon, "lat": lat, "feature": feature},
                "target": _MAP_TARGET,
            },
        )
        return f"Found well '{identifier}' and moved the map to it."

    return go_to_well


def _make_go_to_well_park_tool(session: Session, data_path: str):
    @tool
    async def go_to_well_park(identifier: str) -> str:
        """Fly the map to a well park itself and select it, as if the user
        clicked it directly — use this when asked about a well *park* rather
        than one of the individual wells inside it.

        Args:
            identifier: A well-park number (e.g. "12345"), or other identifying
                text (area name, contractor, description) to match loosely if
                no park number matches exactly.
        """
        try:
            features = _load_well_features(data_path)
        except Exception as exc:
            return f"Could not read the borehole data to look up well parks: {exc}"
        # Well parks are their own feature ("layer" == "BrønnPark"), with their
        # own coordinates — distinct from the individual wells that merely
        # reference one via `brønnParkNr`. Restricting the search to that
        # layer is what actually lands on the park itself; without it, an
        # ordinary well sharing the same park number (the data lists those
        # before any park feature) would match first instead.
        parks = [f for f in features if f.get("properties", {}).get("layer") == "BrønnPark"]
        feature = _find_well(
            parks,
            identifier,
            exact_fields=_PARK_EXACT_FIELDS,
            loose_fields=_PARK_LOOSE_FIELDS,
        )
        if feature is None:
            return (
                f"No well park matching '{identifier}' was found in the loaded "
                "borehole data — tell the user it doesn't exist rather than "
                "saying you moved the map."
            )
        lon, lat = feature["geometry"]["coordinates"]
        _ensure_map_pinned(session)
        # Reuses the same go_to_well ui action: the map only ever flies to and
        # selects one feature regardless of whether it's a well or a well park,
        # so no new action/dispatch case is needed.
        session.trace.append(
            "ui",
            {
                "action": "go_to_well",
                "payload": {"lon": lon, "lat": lat, "feature": feature},
                "target": _MAP_TARGET,
            },
        )
        return f"Found well park '{identifier}' and moved the map to it."

    return go_to_well_park


_PROMPT_FRAGMENT = (
    "This app shows a map of Norwegian borehole data next to the chat (it "
    "appears the first time you use one of the tools below). Call "
    "`set_map_view` to fly it to a raw location, `go_to_well` to fly to and "
    "select a specific well by its number or other identifying text, or "
    "`go_to_well_park` to do the same for a well park itself (e.g. when asked "
    "about a BTES site as a whole, not one of its individual wells) — both "
    "tell you directly if no such well/park exists, so trust their return "
    "value rather than assuming success. The user can also click things on "
    "the map themselves (e.g. selecting a well); when they do, a note "
    "describing it is prepended to their next message as '[UI events since "
    "your last message]', so you'll see it as part of what they sent."
)


def geothermal_map_capability(data_path: str) -> Capability:
    """The web capability for the geothermal map: well-lookup tools that drive
    the native ``map`` canvas panel (see ``canvas/MapPanel.tsx``).

    ``data_path`` is the absolute path to the borehole GeoJSON file
    (``examples/geothermal-map/data/all_boreholes.geojson``) — read directly
    off disk, since the tool and the file live in the same process now.
    """
    return Capability(
        name="geothermal-map",
        tools=(
            _make_set_map_view_tool,
            lambda session: _make_go_to_well_tool(session, data_path),
            lambda session: _make_go_to_well_park_tool(session, data_path),
        ),
        prompt_fragment=_PROMPT_FRAGMENT,
        surfaces=("web",),
    )
