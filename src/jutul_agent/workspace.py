"""Workspace detection, configuration, and Julia-env bootstrap.

A *workspace* is the user's CWD when they invoke jutul-agent (or an
explicit ``--workspace`` override). It owns:

- ``.jutul-agent/config.toml`` — workspace-local config (active simulator,
  per-simulator overrides like a dev'd source path).
- ``.jutul-agent/julia-env/`` — a workspace-local Julia env, copied from
  the install's template the first time around. Skipped if the workspace
  already has its own ``Project.toml`` at the root.

Per-workspace *session* storage lives outside the workspace, under
``state_home()/workspaces/<hash>/`` — see ``paths.workspace_state_dir``.
"""

from __future__ import annotations

import shutil
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

from jutul_agent.paths import workspace_root

WORKSPACE_DIRNAME = ".jutul-agent"
WORKSPACE_CONFIG_FILENAME = "config.toml"
WORKSPACE_JULIA_ENV_DIRNAME = "julia-env"


# ---------------------------------------------------------------------------
# Path helpers.


def workspace_dir(workspace: Path | None = None) -> Path:
    return (workspace or workspace_root()) / WORKSPACE_DIRNAME


def workspace_config_path(workspace: Path | None = None) -> Path:
    return workspace_dir(workspace) / WORKSPACE_CONFIG_FILENAME


def workspace_julia_env(workspace: Path | None = None) -> Path:
    """Where the workspace-local Julia env lives by default."""
    return workspace_dir(workspace) / WORKSPACE_JULIA_ENV_DIRNAME


def resolve_julia_project(workspace: Path | None = None) -> Path:
    """Which Julia project should this workspace use?

    Preference: the workspace's own root ``Project.toml`` if present;
    otherwise the workspace-local ``.jutul-agent/julia-env/``.
    """
    ws = workspace or workspace_root()
    if (ws / "Project.toml").exists():
        return ws
    return workspace_julia_env(ws)


# ---------------------------------------------------------------------------
# Workspace config TOML schema.


@dataclass(frozen=True)
class SimulatorConfig:
    """Per-simulator overrides set in the workspace config."""

    source_path: Path | None = None


@dataclass(frozen=True)
class WorkspaceConfig:
    """Loaded contents of ``.jutul-agent/config.toml``.

    Empty config is fine — every field defaults sensibly.
    """

    simulator: str | None = None
    simulators: dict[str, SimulatorConfig] = field(default_factory=dict)
    approval_mode: str | None = None

    def simulator_config(self, name: str) -> SimulatorConfig:
        return self.simulators.get(name) or SimulatorConfig()


def load_workspace_config(workspace: Path | None = None) -> WorkspaceConfig:
    """Read ``.jutul-agent/config.toml`` if present; else return an empty config."""

    path = workspace_config_path(workspace)
    if not path.exists():
        return WorkspaceConfig()

    data = tomllib.loads(path.read_text(encoding="utf-8"))

    sim_name = (data.get("workspace") or {}).get("simulator")
    approval_mode = (data.get("workspace") or {}).get("approval_mode")
    simulators_raw = data.get("simulator") or {}
    simulators: dict[str, SimulatorConfig] = {}
    for name, body in simulators_raw.items():
        if not isinstance(body, dict):
            continue
        source = body.get("source_path")
        simulators[name] = SimulatorConfig(
            source_path=Path(source).expanduser() if source else None,
        )

    return WorkspaceConfig(
        simulator=sim_name,
        simulators=simulators,
        approval_mode=approval_mode,
    )


def write_workspace_config(
    config: WorkspaceConfig,
    *,
    workspace: Path | None = None,
) -> Path:
    """Persist ``config`` to ``.jutul-agent/config.toml``. Returns the path."""

    path = workspace_config_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    workspace_lines: list[str] = []
    if config.simulator:
        workspace_lines.append(f'simulator = "{config.simulator}"')
    if config.approval_mode:
        workspace_lines.append(f'approval_mode = "{config.approval_mode}"')
    if workspace_lines:
        lines.append("[workspace]")
        lines.extend(workspace_lines)

    for name, sim in sorted(config.simulators.items()):
        if sim.source_path is None:
            continue
        if lines:
            lines.append("")
        lines.append(f"[simulator.{name}]")
        lines.append(f'source_path = "{sim.source_path}"')

    body = "\n".join(lines)
    path.write_text(body + "\n" if body else "", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Simulator auto-detection.


def auto_detect_simulator(
    known_packages: dict[str, str],
    workspace: Path | None = None,
) -> str | None:
    """Guess the active simulator from a workspace ``Project.toml``.

    ``known_packages`` maps Julia package name → simulator name, e.g.
    ``{"JutulDarcy": "jutuldarcy", "BattMo": "battmo"}``. Returns the
    simulator name if any package matches the workspace's ``[deps]`` or
    the project's own ``name`` (handy when the workspace *is* the
    simulator source). ``None`` if no match.
    """

    ws = workspace or workspace_root()
    proj = ws / "Project.toml"
    if not proj.exists():
        return None
    try:
        data = tomllib.loads(proj.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return None

    deps = data.get("deps") or {}
    for pkg, sim in known_packages.items():
        if pkg in deps:
            return sim

    project_name = data.get("name")
    if project_name in known_packages:
        return known_packages[project_name]
    return None


def workspace_is_simulator_source(
    package_name: str,
    workspace: Path | None = None,
) -> bool:
    """True if the workspace's own ``Project.toml`` declares ``package_name``."""

    ws = workspace or workspace_root()
    proj = ws / "Project.toml"
    if not proj.exists():
        return False
    try:
        data = tomllib.loads(proj.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return False
    return data.get("name") == package_name


# ---------------------------------------------------------------------------
# Bootstrap.


class WorkspaceBootstrapError(RuntimeError):
    pass


def sync_julia_env_with_template(
    template_path: Path,
    *,
    workspace: Path | None = None,
) -> list[str]:
    """Add any deps the template declares that the workspace env is missing.

    Returns the list of newly added dep names (empty if nothing changed).
    The workspace's ``Manifest.toml`` is left alone; the caller should
    follow up with ``Pkg.instantiate()`` so the new deps actually install.
    Skipped silently if the workspace owns its own root ``Project.toml``.
    """

    ws = (workspace or workspace_root()).resolve()
    if (ws / "Project.toml").exists():
        return []

    target_proj = workspace_julia_env(ws) / "Project.toml"
    template_proj = template_path / "Project.toml"
    if not (target_proj.exists() and template_proj.exists()):
        return []

    target_text = target_proj.read_text(encoding="utf-8")
    template_text = template_proj.read_text(encoding="utf-8")
    try:
        target = tomllib.loads(target_text)
        template = tomllib.loads(template_text)
    except tomllib.TOMLDecodeError:
        return []

    target_deps = target.get("deps", {})
    template_deps = template.get("deps", {})
    missing = {k: v for k, v in template_deps.items() if k not in target_deps}
    if not missing:
        return []

    new_text = _append_deps(target_text, missing)
    target_proj.write_text(new_text, encoding="utf-8")
    return sorted(missing)


def _append_deps(project_toml_text: str, deps: dict[str, str]) -> str:
    """Insert ``deps`` into the ``[deps]`` table of a Project.toml text.

    Preserves the existing key order and adds new entries at the end of
    the ``[deps]`` table. If no ``[deps]`` table exists, appends one.
    """

    lines = project_toml_text.splitlines()
    out: list[str] = []
    in_deps = False
    inserted = False
    deps_entries = [f'{k} = "{v}"' for k, v in deps.items()]

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_deps and not inserted:
                out.extend(deps_entries)
                out.append("")
                inserted = True
            in_deps = stripped == "[deps]"
        out.append(line)

    if in_deps and not inserted:
        # File ended while still in [deps] — append entries directly.
        out.extend(deps_entries)
        inserted = True

    if not inserted:
        if out and out[-1].strip():
            out.append("")
        out.append("[deps]")
        out.extend(deps_entries)

    text = "\n".join(out)
    if not text.endswith("\n"):
        text += "\n"
    return text


def bootstrap_julia_env(
    template_path: Path,
    *,
    workspace: Path | None = None,
    force: bool = False,
) -> Path:
    """Copy the simulator's template env into the workspace.

    Skipped if:
      - The workspace has its own root ``Project.toml`` (the user owns
        the env; we return the workspace itself).
      - The workspace-local env already exists and ``force`` is False.

    Returns the path to the resolved Julia project, regardless of whether
    a copy happened.
    """

    ws = (workspace or workspace_root()).resolve()
    if (ws / "Project.toml").exists():
        return ws

    target = workspace_julia_env(ws)
    if target.exists() and not force:
        return target

    if not template_path.exists():
        raise WorkspaceBootstrapError(
            f"no Julia env template at {template_path}"
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(template_path, target)
    return target


def merge_simulator_config(
    config: WorkspaceConfig,
    name: str,
    *,
    source_path: Path | None = None,
) -> WorkspaceConfig:
    """Return a copy of ``config`` with ``simulators[name]`` updated."""

    sims = dict(config.simulators)
    sims[name] = SimulatorConfig(source_path=source_path)
    return replace(config, simulators=sims)
