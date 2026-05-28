"""CLI helpers shared across subcommands."""

from __future__ import annotations

import argparse
from pathlib import Path

from jutul_agent.paths import set_state_home, set_workspace_root
from jutul_agent.simulators import registry


def add_workspace_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Workspace directory (default: current working directory).",
    )
    parser.add_argument(
        "--state-home",
        type=Path,
        default=None,
        help=(
            "State home directory for sessions and traces. "
            "Default: $XDG_DATA_HOME/jutul-agent or ~/.local/share/jutul-agent."
        ),
    )


def apply_workspace_flags(args: argparse.Namespace) -> None:
    set_workspace_root(args.workspace)
    set_state_home(args.state_home)


def known_packages_map() -> dict[str, str]:
    return {registry.get(name).primary_package: name for name in registry.names()}
