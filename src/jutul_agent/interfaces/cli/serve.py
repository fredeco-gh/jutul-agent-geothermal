"""``jutul-agent serve`` subcommand: run the HTTP + WebSocket server.

Front ends talk to this server to drive sessions; the wire contract is in
docs/server-interface.md. The server needs the ``[server]`` extra installed.
"""

from __future__ import annotations

import argparse
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
    add_workspace_flags(parser)
    return parser


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

    from jutul_agent.interfaces.server.app import create_app

    print(f"jutul-agent server on http://{args.host}:{args.port}", file=sys.stderr)
    uvicorn.run(create_app(), host=args.host, port=args.port)
    return 0
