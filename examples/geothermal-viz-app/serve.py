"""Serve jutul-agent's chat UI with the geothermal-viz MapLibre map pinned beside it.

This is the integration entry point for docs/server-interface.md's "host-app
extension" pattern applied to geothermal-viz: the bundled chat UI is unchanged,
and host-extension.js (loaded automatically, see web/index.html) pins the map as
a canvas view and bridges it to the agent over the existing session WebSocket.

Everything — the chat, the embedded map's own page, its GeoJSON data API, and
the simulation-parameter lookup its sidebar used to get from a second server —
is served by this single process. geothermal-viz's own ``run_server.jl`` is not
needed for this app: its static files and the two read-only data routes are
served directly from disk here, and ``/api/simulation/setup`` runs
simulation.jl's ``well_to_simulation_params`` in a dedicated Julia kernel this
process starts for itself (see ``_start_viz_host`` below) — separate from any
chat session's own kernel, and kept alive for as long as this process runs.
Loading and warming that kernel happens during startup, before uvicorn opens
the port: the single-process equivalent of the old two-process setup, where
``julia ... run_server.jl`` had already finished loading every package by the
time it printed "ready" and you opened the page. The only thing that still has
to happen separately, beforehand, is geothermal-viz's one-time data-processing
step (``process_geodatabase()``) that produces the GeoJSON files under
``processed_data/`` in the first place.

Run it with ``python examples/geothermal-viz-app/serve.py``. The first request
to this process — including its own startup — can take a while (Julia package
precompilation, if `jutul-agent init` hasn't already baked it); open the
printed URL once it says the simulation backend is ready.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Response

EXT_DIR = Path(__file__).resolve().parent
EXT_TEMPLATE = EXT_DIR / "host-extension.js"
EXT_RENDERED = EXT_DIR / "host-extension.generated.js"  # gitignored; written at startup

# geothermal-viz's repo, assumed checked out as a sibling of this one.
# simulation.jl is include()d from here into the agent's Julia kernel so its
# Fimbul/parameter-mapping logic runs unmodified — see capability.py. The web/
# and processed_data/ directories are served directly (see create_geothermal_app).
GEOTHERMAL_VIZ_REPO = EXT_DIR.parents[2] / "geothermal-viz"
SIMULATION_JL = GEOTHERMAL_VIZ_REPO / "src" / "simulation.jl"
GEOTHERMAL_VIZ_WEB_DIR = GEOTHERMAL_VIZ_REPO / "web"
GEOTHERMAL_VIZ_DATA_DIR = GEOTHERMAL_VIZ_REPO / "processed_data"

HOST = "127.0.0.1"
PORT = 8742

# Same origin as the chat itself now (the map is just another path on this
# server), so capability.py's well lookups can fetch it directly.
SERVER_ORIGIN = f"http://{HOST}:{PORT}"
# Where the map's own page is mounted (see create_geothermal_app) — the
# iframe src host-extension.js points the canvas at.
MAP_PATH = "/map/"


def _render_extension() -> Path:
    """Bake MAP_PATH into the template so no query string is needed."""
    template = EXT_TEMPLATE.read_text(encoding="utf-8")
    EXT_RENDERED.write_text(template.replace("%%MAP_URL%%", MAP_PATH), encoding="utf-8")
    return EXT_RENDERED


async def _host_factory(
    *, sim, model, approval_mode, workspace=None, resume, session_id, extensions=()
):
    """Stand up a normal fimbul session, with the geothermal-viz capability added.

    Mirrors manager.py's default host factory (same simulator lookup, same
    ``SessionHost.start`` call with the caller's workspace/approval_mode honoured)
    but prepends ``geothermal_viz_capability()`` to ``extensions`` — this is the
    seam a future tool gets added through, not a one-off wiring just for the map.
    """
    from capability import geothermal_viz_capability, start_simulation_warmup

    from jutul_agent.interfaces.server.session_host import SessionHost
    from jutul_agent.simulators import registry

    adapter = registry.get(sim)
    host = await SessionHost.start(
        simulator=adapter,
        model=model,
        approval_mode=approval_mode,
        workspace=workspace,
        resume=resume,
        session_id=session_id,
        extensions=[
            geothermal_viz_capability(SERVER_ORIGIN, str(SIMULATION_JL)),
            *extensions,
        ],
    )
    start_simulation_warmup(host.session, str(SIMULATION_JL))
    return host


# The dedicated, server-lifetime Julia kernel/session backing /api/simulation/setup
# — set by _start_viz_host (the app's on_startup hook) and torn down by
# _stop_viz_host (its on_shutdown hook). Deliberately not a chat session: unlike
# one of those (one per browser tab, recreated on every reload), this is started
# once when the process starts and lives until it exits, the same way
# geothermal-viz's own run_server.jl process used to.
_viz_host: Any = None


async def _start_viz_host() -> None:
    global _viz_host
    from capability import _warm_simulation_jl

    from jutul_agent.interfaces.server.session_host import SessionHost
    from jutul_agent.simulators import registry

    print(
        "Loading geothermal-viz's simulation backend "
        "(Fimbul, JutulDarcy, CairoMakie — can take a while the first time)...",
        flush=True,
    )
    adapter = registry.get("fimbul")
    _viz_host = await SessionHost.start(simulator=adapter, session_id="geothermal-viz-setup")
    await _warm_simulation_jl(_viz_host.session.julia, str(SIMULATION_JL))
    print("geothermal-viz simulation backend ready.", flush=True)


async def _stop_viz_host() -> None:
    global _viz_host
    if _viz_host is not None:
        await _viz_host.aclose()
        _viz_host = None


def _geothermal_viz_routes() -> APIRouter:
    """The map's own routes, replicated from geothermal-viz's ``server.jl``.

    ``/api/data/{layer}`` and ``/api/layers`` are plain file reads (no Julia
    involved). ``/api/simulation/setup`` runs against ``_viz_host``, the
    dedicated kernel started in ``_start_viz_host`` — not a chat session, so it
    works the same regardless of whether anyone has opened the chat yet.
    """
    from capability import _setup_simulation_params

    router = APIRouter()

    @router.get("/api/layers")
    def api_layers() -> list[str]:
        return sorted(p.stem for p in GEOTHERMAL_VIZ_DATA_DIR.glob("*.geojson"))

    @router.get("/api/data/{layer}")
    def api_data(layer: str) -> Response:
        path = GEOTHERMAL_VIZ_DATA_DIR / f"{layer}.geojson"
        if not path.is_file():
            raise HTTPException(404, f"Layer not found: {layer}")
        return Response(path.read_bytes(), media_type="application/geo+json")

    @router.post("/api/simulation/setup")
    async def api_simulation_setup(properties: Annotated[dict[str, Any], Body()]) -> dict[str, Any]:
        if _viz_host is None:
            raise HTTPException(503, "The simulation backend is still starting up.")
        return await _setup_simulation_params(_viz_host.session, str(SIMULATION_JL), properties)

    return router


def create_geothermal_app():
    from capability import make_run_simulation_action

    from jutul_agent.interfaces.server.app import create_app
    from jutul_agent.interfaces.server.manager import SessionManager

    manager = SessionManager(host_factory=_host_factory)
    return create_app(
        manager,
        ui=True,
        default_sim="fimbul",
        extra_static={"/host-extension.js": _render_extension()},
        extra_mounts={
            "/map": GEOTHERMAL_VIZ_WEB_DIR,
            # app.js falls back to fetching this directly if /api/data/... is
            # ever unavailable; keeping it reachable matches that fallback path.
            "/map/processed_data": GEOTHERMAL_VIZ_DATA_DIR,
        },
        extra_routes=_geothermal_viz_routes(),
        on_startup=_start_viz_host,
        on_shutdown=_stop_viz_host,
        actions={"run_simulation": make_run_simulation_action(str(SIMULATION_JL))},
    )


def main() -> int:
    import sys

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

    print(f"Starting jutul-agent + geothermal-viz on http://{HOST}:{PORT} ...")
    uvicorn.run(create_geothermal_app(), host=HOST, port=PORT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
