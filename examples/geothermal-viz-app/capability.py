"""The geothermal-viz capability: tools that let the agent drive the embedded map.

Each tool below emits a `ui` trace event (`session.trace.append("ui", {...})`),
which host-extension.js forwards into the map iframe as a `postMessage`, and
geothermal-viz's jutul-agent-bridge.js applies by looking the action name up in
its own dispatch table — the same agent-to-UI pattern as examples/demo-app/demo.py's
`set_param`, just on this app's map instead of a parameter slider.

This module is the skeleton for growing the agent's reach into geothermal-viz:
adding a new ability means adding one `_make_..._tool` factory below, listing it
in `_TOOL_FACTORIES`, and adding the matching case to jutul-agent-bridge.js's
action dispatch table. Nothing else needs to change to pick it up — serve.py
passes whatever `geothermal_viz_capability()` returns straight into the session.
"""

from __future__ import annotations

from langchain_core.tools import tool

from jutul_agent.agent.capabilities import Capability
from jutul_agent.session import Session


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


def _make_go_to_well_tool(session: Session):
    @tool
    async def go_to_well(identifier: str) -> str:
        """Fly the map to a specific well and select it, as if the user clicked it.

        Args:
            identifier: A well or well-park number (e.g. "12345"), or any other
                identifying text (area name, contractor, description) to match
                loosely if no well/park number matches exactly. The well data
                lives in the browser, not here, so this is resolved client-side;
                if nothing matches, you'll be told via a `goToWellNotFound` event
                on your next message rather than getting an error back now.
        """
        session.trace.append("ui", {"action": "go_to_well", "payload": {"identifier": identifier}})
        return f"Asked the map to go to well '{identifier}'."

    return go_to_well


# One tool factory per agent ability on the map. Add a new one here, and a
# matching action handler in geothermal-viz/web/js/jutul-agent-bridge.js.
_TOOL_FACTORIES = (_make_set_map_view_tool, _make_go_to_well_tool)

_PROMPT_FRAGMENT = (
    "This app embeds the geothermal-viz map (a MapLibre view of Norwegian "
    "borehole data) next to the chat, always visible. Call `set_map_view` to fly "
    "it to a raw location, or `go_to_well` to fly to and select a specific well "
    "by its number or other identifying text. The user can also click things on "
    "the map themselves (e.g. selecting a well); when they do, a note describing "
    "it is prepended to their next message as '[UI events since your last "
    "message]', so you'll see it as part of what they sent."
)


def geothermal_viz_capability() -> Capability:
    """The web capability for the geothermal-viz integration: map-control tools."""
    return Capability(
        name="geothermal-viz",
        tools=_TOOL_FACTORIES,
        prompt_fragment=_PROMPT_FRAGMENT,
        surfaces=("web",),
    )
