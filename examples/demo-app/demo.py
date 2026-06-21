"""A minimal jutul-agent webapp, end to end.

This example wires the agent into a tiny web app to show the moving parts in one
place: a session over the server, a tool the agent calls, an interactive plot
embedded in the page, and the two-way link to the page's controls. It runs on a
toy library (``DemoSim``) and a small web capability, both added through the
extension seam rather than the built-in registry, so it doubles as a template
for wiring in a simulator and front end of your own.

Run it with ``python -m examples.demo-app.demo`` (or ``python demo.py`` from this
directory) after installing the server extra. The first run instantiates the
Julia env.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from langchain_core.tools import tool

from jutul_agent.agent.capabilities import Capability
from jutul_agent.session import Session
from jutul_agent.simulators.base import SimulatorAdapter

DEMO_DIR = Path(__file__).resolve().parent
JULIA_ENV = DEMO_DIR / "julia_env"
WORKSPACE = DEMO_DIR / "workspace"
FRONTEND = DEMO_DIR / "frontend"

_PROMPT_FRAGMENT = (
    "This app runs DemoSim, a toy library with one function, "
    "`DemoSim.response(p; n)`, returning `(; x, y)` for a damped sinusoid whose "
    "frequency scales with the parameter `p`. To show the user a figure, call "
    "`plot_response(p)`; it renders an interactive plot they can rotate and zoom. "
    "To move the parameter control in their interface, call `set_param(p)`. The "
    "user can also move that control themselves, which you will be told about."
)

DEMO_ADAPTER = SimulatorAdapter(
    name="demo",
    display_name="DemoSim",
    module_dir=DEMO_DIR,
    package_imports=("DemoSim",),
    primary_package="DemoSim",
    domain_hints="A toy example simulator exposing one function, DemoSim.response(p).",
)


def _make_set_param_tool(session: Session):
    @tool
    async def set_param(p: float) -> str:
        """Move the parameter control on the user's interface to ``p``."""
        session.trace.append("ui", {"action": "set_param", "payload": {"p": p}})
        return f"Set the parameter control to p = {p}."

    return set_param


def _make_plot_tool(session: Session):
    @tool
    async def plot_response(p: float) -> str:
        """Plot DemoSim.response(p) as an interactive figure embedded in the app."""
        rel = f"artifacts/demo-{uuid4().hex[:8]}.html"
        target = session.output_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        result = await session.julia.eval(_export_snippet(p, target))
        if result.error:
            return f"ERROR: {result.error}"
        session.trace.append(
            "artifact",
            {"path": rel, "mime": "text/html", "caption": f"DemoSim response (p={p})"},
        )
        return f"Plotted the interactive response for p = {p}."

    return plot_response


def _export_snippet(p: float, target: Path) -> str:
    """Julia to render DemoSim.response(p) with WGLMakie and export it as HTML."""
    return (
        "begin\n"
        "    using DemoSim, WGLMakie, Bonito\n"
        f"    local d = DemoSim.response({float(p)})\n"
        "    local fig = WGLMakie.lines(d.x, d.y)\n"
        f'    Bonito.export_static(raw"{target.as_posix()}", Bonito.App(fig))\n'
        '    "ok"\n'
        "end"
    )


def demo_capability() -> Capability:
    """The web capability for the demo: an interactive-plot tool and a UI control."""
    return Capability(
        name="demosim-web",
        tools=(_make_set_param_tool, _make_plot_tool),
        prompt_fragment=_PROMPT_FRAGMENT,
        surfaces=("web",),
    )


def create_demo_app():
    """Build the demo server: the standard app, plus the static front end."""
    from fastapi.staticfiles import StaticFiles

    from jutul_agent.interfaces.server.app import create_app
    from jutul_agent.interfaces.server.manager import SessionManager
    from jutul_agent.interfaces.server.session_host import SessionHost

    WORKSPACE.mkdir(exist_ok=True)

    async def host_factory(
        *, sim, model, approval_mode, workspace=None, resume, session_id, extensions=()
    ):
        # The demo always runs DemoSim from its own prepared env, ignoring the
        # requested simulator/workspace; a real deployment would honour them.
        return await SessionHost.start(
            simulator=DEMO_ADAPTER,
            model=model,
            approval_mode=approval_mode,
            workspace=WORKSPACE,
            julia_project=JULIA_ENV,
            prepare_env=False,
            surface="web",
            extensions=[demo_capability(), *extensions],
            resume=resume,
            session_id=session_id,
        )

    app = create_app(SessionManager(host_factory=host_factory), ui=False)
    app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
    return app


def ensure_env() -> None:
    """Instantiate the demo Julia env on first run (resolves DemoSim/WGLMakie/Bonito)."""
    if (JULIA_ENV / "Manifest.toml").exists():
        return
    print("Instantiating the demo Julia env (first run, this can take a while)...")
    subprocess.run(
        ["julia", f"--project={JULIA_ENV}", "-e", "using Pkg; Pkg.instantiate()"],
        check=True,
    )


def main() -> int:
    try:
        import uvicorn
    except ModuleNotFoundError:
        print("The web stack is missing; reinstall jutul-agent (or `uv sync`).", file=sys.stderr)
        return 1
    ensure_env()
    print("Demo app on http://127.0.0.1:8742")
    uvicorn.run(create_demo_app(), host="127.0.0.1", port=8742)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
