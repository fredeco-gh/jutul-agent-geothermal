"""Serve jutul-agent's chat UI with the geothermal map capability wired in.

This is the integration point for the native-canvas-panel architecture
described in docs/web-ui.md's "Extending the canvas": the map is a React
component (``canvas/MapPanel.tsx``) registered into jutul-agent's own webapp,
not a separate page in an iframe — so there is exactly one process, one
server, one Julia kernel per chat session, and no dedicated standalone kernel
to keep warm (compare this file's size to its predecessor,
``examples/geothermal-viz-app/serve.py``).

Everything the agent needs is read straight off disk in the same process (see
capability.py's ``_load_well_features``); the only thing that has to happen
separately, beforehand, is the one-time data-processing step
(``scripts/process_data.jl``) that produced ``data/all_boreholes.geojson`` in
the first place.

This example runs on jutul-agent's built-in ``fimbul`` simulator and its
already-declared Julia environment — no extra Julia setup of its own. Run it
with ``python examples/geothermal-map/serve.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

EXAMPLE_DIR = Path(__file__).resolve().parent
DATA_DIR = EXAMPLE_DIR / "data"
DATA_PATH = DATA_DIR / "all_boreholes.geojson"

# Pinned rather than left to default to the launching shell's cwd: a session's
# Julia env (and its precompile-done marker) lives under <workspace>/.jutul-agent/,
# so if this varied by which directory you happened to run this script from,
# every run with a different cwd would bootstrap and precompile a brand new
# env from scratch.
WORKSPACE = EXAMPLE_DIR / "workspace"

HOST = "127.0.0.1"
PORT = 8742


async def _host_factory(
    *, sim, model, approval_mode, workspace=None, resume, session_id, extensions=()
):
    """Stand up a normal fimbul session, with the geothermal map capability added.

    Mirrors manager.py's default host factory (same simulator lookup, same
    ``SessionHost.start`` call with the caller's approval_mode honoured) but
    prepends ``geothermal_map_capability()`` to ``extensions`` — the seam a
    future tool (e.g. running a Fimbul simulation from the map) gets added
    through, not a one-off wiring just for well lookup.
    """
    from capability import geothermal_map_capability

    from jutul_agent.interfaces.server.session_host import SessionHost
    from jutul_agent.simulators import registry

    adapter = registry.get(sim)
    return await SessionHost.start(
        simulator=adapter,
        model=model,
        approval_mode=approval_mode,
        workspace=workspace or WORKSPACE,
        resume=resume,
        session_id=session_id,
        extensions=[geothermal_map_capability(str(DATA_PATH)), *extensions],
    )


def create_geothermal_map_app() -> Any:
    from jutul_agent.interfaces.server.app import create_app
    from jutul_agent.interfaces.server.manager import SessionManager

    WORKSPACE.mkdir(exist_ok=True)
    manager = SessionManager(host_factory=_host_factory)
    return create_app(
        manager,
        ui=True,
        default_sim="fimbul",
        # MapPanel.tsx fetches its borehole layer from here directly — a plain
        # static mount, no Julia or session involved (see canvas/MapPanel.tsx).
        extra_mounts={"/geothermal-data": DATA_DIR},
    )


def main() -> int:
    try:
        import uvicorn
    except ModuleNotFoundError:
        print("The web stack is missing; reinstall jutul-agent (or `uv sync`).", file=sys.stderr)
        return 1

    # Unlike `jutul-agent web`, this script doesn't go through the CLI's main(),
    # which is the only place .env normally gets loaded — so provider API keys
    # (e.g. OPENAI_API_KEY) would otherwise never reach the process.
    from dotenv import load_dotenv

    load_dotenv()

    print(f"Starting jutul-agent with the geothermal map on http://{HOST}:{PORT} ...")
    uvicorn.run(create_geothermal_map_app(), host=HOST, port=PORT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
