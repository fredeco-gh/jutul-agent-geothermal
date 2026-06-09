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
    WorkspaceConfig,
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
            "Run Pkg.instantiate after bootstrap and warm up GLMakie for "
            "julia_plot (slow on first run). --instantiate is a synonym."
        ),
    )
    add_workspace_flags(parser)
    return parser


def run(args: argparse.Namespace) -> int:
    from jutul_agent.julia.requirements import JuliaRequirementError, require_julia
    from jutul_agent.simulators.env_setup import EnvSetupError, bootstrap_workspace

    # Fail early with clear remediation if Julia is missing or too old.
    try:
        require_julia()
    except JuliaRequirementError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

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
        print("  precompile:    done (Pkg.instantiate + Pkg.precompile)")
        _note_headless_plotting()

    _maybe_prompt_for_provider_key(new_config)
    return 0


def _note_headless_plotting() -> None:
    """After --precompile, note when GLMakie can't render here (headless, no xvfb).

    The plot warm-up is best-effort and silently skipped on a headless box, so
    without this the user wouldn't learn that plotting needs xvfb until a plot
    call fails mid-session. Simulation itself is unaffected.
    """

    from jutul_agent.agent.render_profile import (
        plotting_display_available,
        xvfb_opted_out,
    )

    if plotting_display_available():
        return
    hint = (
        "unset JUTUL_AGENT_NO_XVFB and install xvfb"
        if xvfb_opted_out()
        else "install xvfb (e.g. `sudo apt-get install -y xvfb`)"
    )
    print(
        "  note:          no display and xvfb not available, so GLMakie plotting "
        f"is unavailable here.\n                 To enable plots, {hint}. "
        "Simulation works without it."
    )


def _maybe_prompt_for_provider_key(config: WorkspaceConfig) -> None:
    """Offer to save an API key when the resolved model's provider has none.

    Prompts only with a TTY; otherwise prints a note. Local models are skipped.
    """
    import getpass
    import sys

    from jutul_agent.agent.builder import resolve_model
    from jutul_agent.agent.models import provider_info
    from jutul_agent.credentials import missing_credential, store_credential
    from jutul_agent.user_config import load_user_config

    model_id = resolve_model(
        None, workspace_model=config.model, user_model=load_user_config().model
    )
    env_var = missing_credential(model_id)
    if env_var is None:
        return

    info = provider_info(model_id)
    label = info.label if info else model_id
    if not sys.stdin.isatty():
        print(
            f"\nNote: {label} needs {env_var}, which isn't set. Add it to your shell, "
            "a .env, or launch `jutul-agent` and pick a model to be prompted for it.",
            file=sys.stderr,
        )
        return

    print(f"\n{label} ({model_id}) needs an API key, but {env_var} isn't set.")
    try:
        value = getpass.getpass(
            f"Paste {env_var} to save it for future runs (leave blank to skip): "
        ).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if not value:
        print("Skipped — set it later via the model selector, a .env, or your shell.")
        return
    path = store_credential(env_var, value)
    print(f"Saved {env_var} to {path}.")
