"""``jutul-agent serve`` subcommand: run the HTTP + WebSocket server.

Front ends talk to this server to drive sessions; the wire contract is in
docs/server-interface.md. The server needs the ``[server]`` extra installed.
"""

from __future__ import annotations

import argparse
import contextlib
import sys

from jutul_agent.interfaces.cli._helpers import add_workspace_flags


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jutul-agent serve",
        description="Run the jutul-agent server (HTTP + WebSocket).",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Address to bind (default 127.0.0.1, localhost only).",
    )
    parser.add_argument("--port", type=int, default=8742, help="Port to bind (default 8742).")
    parser.add_argument(
        "--sim",
        default=None,
        help=(
            "Simulator this folder's sessions use (e.g. jutuldarcy). One folder is "
            "bound to one simulator; defaults to the folder's saved choice or "
            "auto-detection. Use another simulator by serving from another folder."
        ),
    )
    add_workspace_flags(parser)
    return parser


def _resolve_simulator(args: argparse.Namespace) -> str | None:
    """The one simulator this folder is bound to, or ``None`` if none can be found.

    Same precedence the CLI uses everywhere: the ``--sim`` flag, then the folder's
    saved ``[workspace] simulator``, then auto-detection from its packages. The
    resolved choice is saved back so a later launch here needs no flag. The web UI
    deliberately does not switch simulators in place — a different simulator means
    a different folder, each with its own Julia environment.
    """
    from dataclasses import replace as dc_replace

    from jutul_agent.interfaces.cli._helpers import known_packages_map
    from jutul_agent.paths import workspace_root
    from jutul_agent.simulators import registry
    from jutul_agent.workspace import (
        auto_detect_simulator,
        load_workspace_config,
        write_workspace_config,
    )

    ws = workspace_root()
    config = load_workspace_config(ws)
    sim = args.sim or config.simulator or auto_detect_simulator(known_packages_map(), ws)
    if sim is None:
        print(
            "error: no simulator for this folder. Pass --sim <name>, or run "
            "`jutul-agent init --sim <name>` here first. Known: "
            + ", ".join(registry.names())
            + ".",
            file=sys.stderr,
        )
        return None
    try:
        registry.get(sim)
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None
    if config.simulator != sim:  # remember the folder's simulator for next time
        with contextlib.suppress(OSError):
            write_workspace_config(dc_replace(config, simulator=sim), workspace=ws)
    return sim


def run(args: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ModuleNotFoundError:
        print(
            "error: the server needs the optional [server] dependency. "
            "Install it with `pip install 'jutul-agent[server]'` (or "
            "`uv sync --extra server`).",
            file=sys.stderr,
        )
        return 1

    from jutul_agent.interfaces.cli._helpers import apply_workspace_flags

    apply_workspace_flags(args)  # bind the server to its --workspace folder (or the cwd)

    sim = _resolve_simulator(args)
    if sim is None:
        return 2

    from jutul_agent.interfaces.server.app import create_app

    print(
        f"jutul-agent server on http://{args.host}:{args.port} (simulator: {sim})",
        file=sys.stderr,
    )
    uvicorn.run(create_app(default_sim=sim), host=args.host, port=args.port)
    return 0
