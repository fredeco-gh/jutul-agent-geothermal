"""``jutul-agent init`` / ``jutul-agent setup`` subcommand."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace as dc_replace
from pathlib import Path

from jutul_agent.interfaces.cli._helpers import (
    add_workspace_flags,
    known_packages_map,
)
from jutul_agent.paths import workspace_root
from jutul_agent.simulators import registry
from jutul_agent.workspace import (
    auto_detect_simulator,
    load_workspace_config,
    merge_simulator_config,
    workspace_config_path,
    write_workspace_config,
)

INIT_COMMANDS = frozenset({"init", "setup"})


def build_parser(prog: str = "jutul-agent init") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog)
    parser.add_argument(
        "--sim",
        choices=registry.names(),
        required=False,
        help="Simulator to bootstrap. If omitted, auto-detect from Project.toml.",
    )
    parser.add_argument(
        "--source-path",
        type=Path,
        default=None,
        help=(
            "Local checkout of the simulator package to ``Pkg.develop``. "
            "Persisted to .jutul-agent/config.toml."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Replace an existing workspace Julia env with a fresh copy of the "
            "simulator template (use after upgrading jutul-agent)."
        ),
    )
    parser.add_argument(
        "--precompile",
        "--instantiate",
        action="store_true",
        dest="precompile",
        help=(
            "Run Pkg.instantiate after bootstrap and warm up CairoMakie for "
            "julia_plot (slow on first run). --instantiate is a synonym."
        ),
    )
    add_workspace_flags(parser)
    return parser


def run(args: argparse.Namespace) -> int:
    from jutul_agent.simulators.env_setup import EnvSetupError, bootstrap_workspace

    ws = workspace_root()
    config = load_workspace_config(ws)

    sim_name = args.sim or config.simulator or auto_detect_simulator(known_packages_map(), ws)
    if sim_name is None:
        print(
            "error: no simulator specified. Use --sim <name> or add a Project.toml "
            "with a known simulator package. Known: " + ", ".join(registry.names()) + ".",
            file=sys.stderr,
        )
        return 2

    try:
        adapter = registry.get(sim_name)
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    sim_cfg = config.simulator_config(sim_name)
    source_path = args.source_path or sim_cfg.source_path

    try:
        project = bootstrap_workspace(
            adapter,
            workspace=ws,
            source_path=source_path,
            precompile=args.precompile,
            force=args.force,
        )
    except EnvSetupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    new_config = config
    if new_config.simulator != sim_name:
        new_config = dc_replace(new_config, simulator=sim_name)
    if source_path is not None:
        new_config = merge_simulator_config(new_config, sim_name, source_path=source_path)
    write_workspace_config(new_config, workspace=ws)

    print(f"Workspace ready at {ws}")
    print(f"  config:        {workspace_config_path(ws)}")
    print(f"  julia project: {project}")
    if source_path is not None:
        print(f"  dev source:    {source_path}")
    if args.force:
        print("  env:           replaced from template (--force)")
    if args.precompile:
        print("  precompile:    done (Pkg.instantiate + plot warm-up)")
    return 0
