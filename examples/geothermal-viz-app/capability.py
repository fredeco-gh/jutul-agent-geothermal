"""The geothermal-viz capability: tools that let the agent drive the embedded map.

Each tool below emits a `ui` trace event (`session.trace.append("ui", {...})`),
which host-extension.js forwards into the map iframe as a `postMessage`, and
geothermal-viz's jutul-agent-bridge.js applies by looking the action name up in
its own dispatch table — the same agent-to-UI pattern as examples/demo-app/demo.py's
`set_param`, just on this app's map instead of a parameter slider.

This module is the skeleton for growing the agent's reach into geothermal-viz:
adding a new ability means adding one `_make_..._tool` factory below, wiring it
into ``geothermal_viz_capability``'s ``tools`` tuple, and adding the matching
case to jutul-agent-bridge.js's action dispatch table. Nothing else needs to
change to pick it up — serve.py passes whatever this returns straight into the
session.

A tool that *asks* the map to do something (like ``set_map_view``) can return
right away — there's nothing to get wrong. But a tool that depends on data only
the browser holds (like which wells exist) must not just fire the UI action and
claim success: the browser's answer would only arrive on the *next* message (see
docs/server-interface.md's ui_event queueing), so the agent would confidently
report success in the same turn it actually failed. ``go_to_well`` instead
resolves the well itself, against geothermal-viz's own data API, so it can give
the agent an honest answer immediately.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from jutul_agent.agent.capabilities import Capability
from jutul_agent.session import Session

# Matched first, exactly (case-insensitive): a well or well-park number.
_EXACT_FIELDS = ("brønnNr", "brønnParkNr")
# Matched next, as a substring, so a vaguer request still has a chance to resolve.
_LOOSE_FIELDS = (*_EXACT_FIELDS, "brønnpOmrNavn", "beskrivelse", "oppdragstaker")

# Cached per map origin rather than per call: the dataset only changes when
# geothermal-viz's data-processing script reruns and its server restarts, so
# refetching the whole file on every `go_to_well` call would be wasted work.
_wells_cache: dict[str, list[dict[str, Any]]] = {}


async def _load_well_features(map_origin: str) -> list[dict[str, Any]]:
    cached = _wells_cache.get(map_origin)
    if cached is not None:
        return cached
    import httpx

    async with httpx.AsyncClient() as client:
        response = await client.get(f"{map_origin}/api/data/all_boreholes")
        response.raise_for_status()
        features = response.json().get("features", [])
    _wells_cache[map_origin] = features
    return features


def _find_well(features: list[dict[str, Any]], identifier: str) -> dict[str, Any] | None:
    needle = str(identifier).strip().lower()
    if not needle:
        return None
    for feature in features:
        props = feature.get("properties", {})
        if any(str(props.get(f, "")).lower() == needle for f in _EXACT_FIELDS):
            return feature
    for feature in features:
        props = feature.get("properties", {})
        if any(needle in str(props.get(f, "")).lower() for f in _LOOSE_FIELDS):
            return feature
    return None


def _make_set_map_view_tool(session: Session):
    @tool
    async def set_map_view(lon: float, lat: float, zoom: float = 14.0) -> str:
        """Move the geothermal-viz map to a location.

        Args:
            lon: Longitude in degrees (WGS84).
            lat: Latitude in degrees (WGS84).
            zoom: Map zoom level — roughly 0 for the whole world, 18 for street
                level. Defaults to 14, which frames a single borehole site.
        """
        session.trace.append(
            "ui",
            {"action": "set_map_view", "payload": {"lon": lon, "lat": lat, "zoom": zoom}},
        )
        return f"Moved the map to ({lat}, {lon}) at zoom {zoom}."

    return set_map_view


def _make_go_to_well_tool(session: Session, map_origin: str):
    @tool
    async def go_to_well(identifier: str) -> str:
        """Fly the map to a specific well and select it, as if the user clicked it.

        Args:
            identifier: A well or well-park number (e.g. "12345"), or other
                identifying text (area name, contractor, description) to match
                loosely if no well/park number matches exactly.
        """
        try:
            features = await _load_well_features(map_origin)
        except Exception as exc:
            return f"Could not reach geothermal-viz's data API to look up wells: {exc}"
        feature = _find_well(features, identifier)
        if feature is None:
            return (
                f"No well matching '{identifier}' was found in the loaded borehole "
                "data — tell the user it doesn't exist rather than saying you moved "
                "the map."
            )
        lon, lat = feature["geometry"]["coordinates"]
        session.trace.append(
            "ui",
            {"action": "go_to_well", "payload": {"lon": lon, "lat": lat, "feature": feature}},
        )
        return f"Found well '{identifier}' and moved the map to it."

    return go_to_well


_PROMPT_FRAGMENT = (
    "This app embeds the geothermal-viz map (a MapLibre view of Norwegian "
    "borehole data) next to the chat, always visible. Call `set_map_view` to fly "
    "it to a raw location, or `go_to_well` to fly to and select a specific well "
    "by its number or other identifying text — it tells you directly if no such "
    "well exists, so trust its return value rather than assuming success. The "
    "user can also click things on the map themselves (e.g. selecting a well); "
    "when they do, a note describing it is prepended to their next message as "
    "'[UI events since your last message]', so you'll see it as part of what "
    "they sent."
)


def geothermal_viz_capability(map_origin: str) -> Capability:
    """The web capability for the geothermal-viz integration: map-control tools.

    ``map_origin`` is geothermal-viz's own server (e.g. ``http://127.0.0.1:8080``)
    — tools that need to check the map's data, like ``go_to_well``, query it
    directly rather than trusting the browser to report back in time.
    """
    return Capability(
        name="geothermal-viz",
        tools=(
            _make_set_map_view_tool,
            lambda session: _make_go_to_well_tool(session, map_origin),
        ),
        prompt_fragment=_PROMPT_FRAGMENT,
        surfaces=("web",),
    )
