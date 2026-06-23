"""Serve jutul-agent's chat UI with the geothermal-viz MapLibre map pinned beside it.

This is the integration entry point for docs/server-interface.md's "host-app
extension" pattern applied to geothermal-viz: the bundled chat UI is unchanged,
and host-extension.js (loaded automatically, see web/index.html) pins the map as
a canvas view and bridges it to the agent over the existing session WebSocket.

geothermal-viz keeps running its own server (its Julia HTTP server, the same way
you already run it) for the map page and its data API; this server is jutul-agent's,
bound to the fimbul simulator, and reachable from the map's different origin via CORS.

Run it with ``python examples/geothermal-viz-app/serve.py`` once geothermal-viz's
own server is up, then open the printed URL — the plain host:port, no query
string needed; the map URL is baked into the served extension script below.
"""

from __future__ import annotations

from pathlib import Path

EXT_DIR = Path(__file__).resolve().parent
EXT_TEMPLATE = EXT_DIR / "host-extension.js"
EXT_RENDERED = EXT_DIR / "host-extension.generated.js"  # gitignored; written at startup

# geothermal-viz's own server (its Julia HTTP.jl server, ``scripts/run_server.jl``).
GEOTHERMAL_VIZ_ORIGIN = "http://127.0.0.1:8080"

HOST = "127.0.0.1"
PORT = 8742


def _render_extension() -> Path:
    """Bake GEOTHERMAL_VIZ_ORIGIN into the template so no query string is needed."""
    template = EXT_TEMPLATE.read_text(encoding="utf-8")
    EXT_RENDERED.write_text(
        template.replace("%%MAP_URL%%", GEOTHERMAL_VIZ_ORIGIN), encoding="utf-8"
    )
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
    from capability import geothermal_viz_capability

    from jutul_agent.interfaces.server.session_host import SessionHost
    from jutul_agent.simulators import registry

    adapter = registry.get(sim)
    return await SessionHost.start(
        simulator=adapter,
        model=model,
        approval_mode=approval_mode,
        workspace=workspace,
        resume=resume,
        session_id=session_id,
        extensions=[geothermal_viz_capability(GEOTHERMAL_VIZ_ORIGIN), *extensions],
    )


def create_geothermal_app():
    from fastapi.middleware.cors import CORSMiddleware

    from jutul_agent.interfaces.server.app import create_app
    from jutul_agent.interfaces.server.manager import SessionManager

    app = create_app(
        SessionManager(host_factory=_host_factory),
        ui=True,
        default_sim="fimbul",
        extra_static={"/host-extension.js": _render_extension()},
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[GEOTHERMAL_VIZ_ORIGIN],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return app


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

    print(f"jutul-agent + geothermal-viz map on http://{HOST}:{PORT}")
    print(f"(expects geothermal-viz's own server already running at {GEOTHERMAL_VIZ_ORIGIN})")
    uvicorn.run(create_geothermal_app(), host=HOST, port=PORT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
