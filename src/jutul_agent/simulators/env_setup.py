"""Bootstrap a workspace's Julia environment from the simulator's template.

Each simulator ships a template env at ``simulators/<name>/julia_env/``
(already declaring the simulator's package dependencies). Bootstrap = copy
the template into the workspace, optionally ``Pkg.develop`` a user-provided
source path, optionally ``Pkg.instantiate`` to precompile.

A workspace that already has its own root ``Project.toml`` is left alone —
the user owns that env; we only run dev and instantiate on request.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from jutul_agent.simulators.base import SimulatorAdapter
from jutul_agent.workspace import (
    WorkspaceBootstrapError,
    bootstrap_julia_env,
    resolve_julia_project,
    workspace_is_simulator_source,
)


class EnvSetupError(RuntimeError):
    pass


def is_workspace_env_ready(workspace: Path | None = None) -> bool:
    """A workspace env is ready when its resolved project has a Project.toml."""

    project = resolve_julia_project(workspace)
    return (project / "Project.toml").exists()


_PLOT_WARMUP = (
    "using CairoMakie; "
    "fig = Figure(size = (64, 64)); "
    "lines!(Axis(fig[1, 1]), 1:2); "
    'save(joinpath(tempdir(), "jutul-agent-plot-warmup.png"), fig)'
)


def bootstrap_workspace(
    adapter: SimulatorAdapter,
    *,
    workspace: Path | None = None,
    source_path: Path | None = None,
    precompile: bool = False,
    force: bool = False,
) -> Path:
    """Prepare the workspace's Julia env for ``adapter``.

    Steps:
      1. If the workspace lacks both a root ``Project.toml`` and a
         workspace-local env, copy the template from the install.
         With ``force``, replace an existing workspace-local env first.
      2. If ``source_path`` is set, ``Pkg.develop(path=source_path)`` in
         the workspace env (idempotent; safe to re-run).
      3. If ``precompile``, ``Pkg.instantiate()`` then a tiny CairoMakie save
         to warm the plotting stack for ``julia_plot``.

    Returns the path to the resolved Julia project.
    """

    try:
        bootstrap_julia_env(
            adapter.julia_env_template_path, workspace=workspace, force=force
        )
    except WorkspaceBootstrapError as exc:
        raise EnvSetupError(str(exc)) from exc

    project = resolve_julia_project(workspace)

    # If the workspace itself is the simulator source, skip Pkg.develop —
    # the user is editing the package in place.
    is_source = workspace_is_simulator_source(adapter.primary_package, workspace)

    cmds: list[str] = ["using Pkg"]
    if source_path is not None and not is_source:
        cmds.append(f'Pkg.develop(path=raw"{source_path}")')
    if precompile:
        cmds.append("Pkg.instantiate()")

    if len(cmds) > 1:
        _run_pkg(project, cmds)
    if precompile:
        _warmup_plotting(project)

    return project


def resolve_and_instantiate(project: Path) -> None:
    """Re-resolve the manifest and install deps.

    Plain ``Pkg.instantiate`` errors if a dep appears in Project.toml but
    not the Manifest.toml (e.g. after auto-syncing new deps in). Running
    ``Pkg.resolve`` first updates the manifest from Project.toml before
    install.
    """

    _run_pkg(project, ["using Pkg", "Pkg.resolve()", "Pkg.instantiate()"])


def _warmup_plotting(project: Path) -> None:
    """Precompile CairoMakie save path used by ``julia_plot`` (best effort)."""

    try:
        _run_pkg(project, [_PLOT_WARMUP])
    except EnvSetupError:
        print(
            "warning: plot warm-up failed; julia_plot may be slow on first use",
            flush=True,
        )


def _run_pkg(project: Path, cmds: list[str]) -> None:
    if shutil.which("julia") is None:
        raise EnvSetupError("`julia` is not on PATH")

    argv = [
        "julia",
        f"--project={project}",
        "--startup-file=no",
        "-e",
        "; ".join(cmds),
    ]
    print(f"$ {' '.join(argv)}")
    result = subprocess.run(argv, check=False)
    if result.returncode != 0:
        raise EnvSetupError(
            f"Julia exited with code {result.returncode}; see output above"
        )
