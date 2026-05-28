"""Top-level dispatcher for ``jutul-agent``.

Three modes, dispatched on the first argument:

- ``jutul-agent init|setup [--sim <name>]``  bootstrap the current workspace.
- ``jutul-agent transcript [<id>]``         render a session trace.
- ``jutul-agent [--sim <name>] [prompt]``   launch the TUI, or run one turn.

The active *workspace* is ``--workspace`` if given, else the current
working directory. State (sessions, traces) lives under ``--state-home``
or its default (``$XDG_DATA_HOME/jutul-agent``).
"""

from __future__ import annotations

import sys

from dotenv import load_dotenv

from jutul_agent.interfaces.cli import init as init_cmd
from jutul_agent.interfaces.cli import run as run_cmd
from jutul_agent.interfaces.cli import transcript as transcript_cmd
from jutul_agent.interfaces.cli._helpers import apply_workspace_flags


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    argv = sys.argv[1:] if argv is None else argv

    if argv and argv[0] in init_cmd.INIT_COMMANDS:
        sub = argv[0]
        args = init_cmd.build_parser(prog=f"jutul-agent {sub}").parse_args(argv[1:])
        apply_workspace_flags(args)
        return init_cmd.run(args)

    if argv and argv[0] == "transcript":
        args = transcript_cmd.build_parser().parse_args(argv[1:])
        apply_workspace_flags(args)
        return transcript_cmd.run(args)

    args = run_cmd.build_parser().parse_args(argv)
    apply_workspace_flags(args)
    return run_cmd.dispatch(args)
