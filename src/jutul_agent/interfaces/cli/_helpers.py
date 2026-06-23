"""CLI helpers shared across subcommands."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from jutul_agent.paths import set_state_home, set_workspace_root
from jutul_agent.simulators import registry


def add_session_flags(parser: argparse.ArgumentParser) -> None:
    """Add the per-session config flags common to every interface.

    These select the model, Julia project/threads, extra readable folders, and
    throwaway memory. They mean the same thing whether a session is launched by
    ``run``/``tui`` (one session) or ``web`` (the default for the server's
    sessions), so they live here once rather than being duplicated per command.
    The simulator, resume/continue, and approval flags are command-specific and
    stay with their parsers.
    """
    from jutul_agent.julia.threads import THREADS_ENV_VAR
    from jutul_agent.models import DEFAULT_MODEL, MODEL_ENV_VAR

    parser.add_argument(
        "--model",
        default=None,
        help=(
            "LLM identifier (provider:model). Precedence: --model > workspace config "
            f"> user config > ${MODEL_ENV_VAR} > {DEFAULT_MODEL}."
        ),
    )
    parser.add_argument(
        "--julia-project",
        type=Path,
        default=None,
        help="Override the resolved workspace Julia project.",
    )
    parser.add_argument(
        "--threads",
        default=None,
        metavar="N",
        help=(
            "Julia compute threads: an integer, or 'auto' for all logical cores. "
            f"Precedence: --threads > ${THREADS_ENV_VAR} > default (physical cores "
            "minus one). The kernel adds one interactive thread on top."
        ),
    )
    parser.add_argument(
        "--add-dir",
        type=Path,
        action="append",
        default=None,
        metavar="DIR",
        dest="add_dir",
        help=(
            "Add an extra folder so the agent can read and edit it, alongside the "
            "workspace. Repeatable. Also available at runtime via /add-dir."
        ),
    )
    parser.add_argument(
        "--ephemeral-memory",
        action="store_true",
        help=(
            "Use a throwaway memory directory: nothing is persisted to workspace memory on disk."
        ),
    )


def resolve_add_dirs(raw_dirs: Any, ws: Path) -> list[Path]:
    """Resolve ``--add-dir`` paths, warning on (and skipping) bad ones.

    One unreadable folder shouldn't abort startup, so invalid entries are
    reported and dropped; the session launches with whatever resolved cleanly.
    """
    from jutul_agent.agent.added_dirs import AddDirError, resolve_dir

    resolved: list[Path] = []
    for raw in raw_dirs or ():
        try:
            path = resolve_dir(raw, workspace=ws)
        except AddDirError as exc:
            print(f"warning: --add-dir {raw}: {exc}", file=sys.stderr)
            continue
        if path not in resolved:
            resolved.append(path)
    return resolved


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
    # State home is set, so the global .env (at its root) can be loaded now.
    from jutul_agent.credentials import load_user_credentials

    load_user_credentials()


def known_packages_map() -> dict[str, str]:
    return {registry.get(name).primary_package: name for name in registry.names()}
