"""``jutul-agent doctor`` — diagnose a workspace's setup.

One command a user can run (and paste the output of) when launch fails.
Each check prints PASS / WARN / FAIL with a one-line remediation, so the
common setup mistakes are obvious without reading a traceback.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tomllib
from pathlib import Path

from jutul_agent.interfaces.cli._helpers import (
    add_workspace_flags,
    known_packages_map,
)
from jutul_agent.julia.requirements import MIN_JULIA_VERSION, check_julia
from jutul_agent.paths import workspace_root
from jutul_agent.simulators import registry
from jutul_agent.workspace import (
    auto_detect_simulator,
    load_workspace_config,
    resolve_julia_project,
)

_AGENTREPL_PKG = "AgentREPL"
_PROVIDER_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"

_MARK = {PASS: "[ok]  ", WARN: "[warn]", FAIL: "[FAIL]"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jutul-agent doctor",
        description="Check that this workspace is ready to run jutul-agent.",
    )
    parser.add_argument(
        "--sim",
        choices=registry.names(),
        required=False,
        help="Simulator to check against (default: workspace config / auto-detect).",
    )
    add_workspace_flags(parser)
    return parser


class _Report:
    def __init__(self) -> None:
        self.worst = PASS

    def line(self, status: str, label: str, detail: str = "", fix: str = "") -> None:
        if status == FAIL or (status == WARN and self.worst != FAIL):
            self.worst = status
        msg = f"{_MARK[status]} {label}"
        if detail:
            msg += f": {detail}"
        print(msg)
        if fix and status != PASS:
            print(f"        -> {fix}")


def run(args: argparse.Namespace) -> int:
    ws = workspace_root()
    config = load_workspace_config(ws)
    sim_name = args.sim or config.simulator or auto_detect_simulator(known_packages_map(), ws)

    report = _Report()
    print(f"jutul-agent doctor - workspace: {ws}\n")

    julia = _check_julia(report)
    _check_provider_key(report)
    sim_name = _check_simulator(report, sim_name)
    project = _check_julia_project(report, ws)
    has_agentrepl = _check_agentrepl_dep(report, project)
    _check_simulator_installed(report, project, sim_name)

    # Only attempt the (slow) load if the cheap checks passed — otherwise the
    # error would just restate what we already reported.
    if julia.ok and project is not None and has_agentrepl:
        _check_agentrepl_loads(report, project)
    else:
        report.line(WARN, f"`using {_AGENTREPL_PKG}` loads", "skipped (fix the items above first)")

    print()
    if report.worst == FAIL:
        print("Setup has problems — fix the [FAIL] items above, then re-run `jutul-agent doctor`.")
        return 1
    if report.worst == WARN:
        print("Setup looks usable, but see the [warn] items above.")
        return 0
    print("All checks passed. You're ready to run `jutul-agent`.")
    return 0


def _check_julia(report: _Report):
    julia = check_julia()
    min_str = ".".join(str(n) for n in MIN_JULIA_VERSION)
    if not julia.found:
        report.line(
            FAIL,
            "Julia on PATH",
            "`julia` not found",
            f"Install Julia {min_str}+ via juliaup, then open a new terminal.",
        )
    elif julia.version is None:
        report.line(WARN, "Julia on PATH", julia.error or "version unknown", julia.path or "")
    elif not julia.version_ok:
        report.line(
            FAIL,
            "Julia version",
            f"{julia.version_str} (need {min_str}+)",
            f"juliaup add {min_str} && juliaup default {min_str}",
        )
    else:
        report.line(PASS, "Julia version", f"{julia.version_str} ({julia.path})")
    return julia


def _check_provider_key(report: _Report) -> None:
    present = [k for k in _PROVIDER_KEYS if os.environ.get(k)]
    if present:
        report.line(PASS, "Provider API key", f"{', '.join(present)} set")
    else:
        report.line(
            FAIL,
            "Provider API key",
            "no ANTHROPIC_API_KEY or OPENAI_API_KEY",
            "Add one to your .env (see .env.example) or export it in this shell.",
        )


def _check_simulator(report: _Report, sim_name: str | None) -> str | None:
    if sim_name is None:
        report.line(
            FAIL,
            "Simulator",
            "not set and not auto-detected",
            "Run `jutul-agent init --sim <name>`. Known: " + ", ".join(registry.names()) + ".",
        )
        return None
    if sim_name not in registry.names():
        report.line(
            FAIL, "Simulator", f"unknown: {sim_name}", "Known: " + ", ".join(registry.names())
        )
        return None
    report.line(PASS, "Simulator", sim_name)
    return sim_name


def _check_julia_project(report: _Report, ws: Path) -> Path | None:
    project = resolve_julia_project(ws)
    proj_toml = project / "Project.toml"
    using_root = (ws / "Project.toml").resolve() == proj_toml.resolve()
    where = (
        "workspace root Project.toml" if using_root else "workspace-local .jutul-agent/julia-env"
    )
    if not proj_toml.exists():
        report.line(
            FAIL,
            "Julia project",
            f"no Project.toml at {project}",
            "Run `jutul-agent init --sim <name>` in this directory.",
        )
        return None
    detail = f"{project} ({where})"
    if using_root:
        report.line(
            WARN,
            "Julia project",
            detail,
            "A root Project.toml takes precedence over .jutul-agent/julia-env — "
            "make sure it includes AgentREPL and the simulator.",
        )
    else:
        report.line(PASS, "Julia project", detail)
    return project


def _check_simulator_installed(report: _Report, project: Path | None, sim_name: str | None) -> None:
    """Verify the simulator's package is resolved in the env's manifest.

    `_check_agentrepl_loads` only proves AgentREPL works; a workspace whose
    Project lists the simulator but whose Manifest never resolved it still
    passes that check, then fails at runtime on `using <Sim>`. This closes
    that gap cheaply (a manifest read, no Julia subprocess).
    """

    if project is None or sim_name is None or sim_name not in registry.names():
        return
    from jutul_agent.simulators.env_setup import manifest_has_package

    adapter = registry.get(sim_name)
    pkg = adapter.primary_package
    # Placeholder simulators (e.g. vocsim) declare a package they don't load.
    if pkg not in adapter.package_imports:
        return
    if manifest_has_package(project, pkg):
        report.line(PASS, f"{pkg} resolved in env")
        return
    report.line(
        FAIL,
        f"{pkg} resolved in env",
        f"{pkg} is in Project.toml but not in Manifest.toml (env not instantiated)",
        f"Run `jutul-agent init --sim {sim_name} --precompile` to install it.",
    )


def _check_agentrepl_dep(report: _Report, project: Path | None) -> bool:
    if project is None:
        return False
    proj_toml = project / "Project.toml"
    try:
        data = tomllib.loads(proj_toml.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        report.line(FAIL, "AgentREPL in project deps", f"could not read Project.toml: {exc}")
        return False
    if _AGENTREPL_PKG in (data.get("deps") or {}):
        report.line(PASS, "AgentREPL in project deps")
        return True
    report.line(
        FAIL,
        "AgentREPL in project deps",
        f"{_AGENTREPL_PKG} not in [deps]",
        "Run `jutul-agent init --force` to refresh the env from the template.",
    )
    return False


def _check_agentrepl_loads(report: _Report, project: Path) -> None:
    argv = [
        "julia",
        f"--project={project}",
        "--startup-file=no",
        "-e",
        f"using {_AGENTREPL_PKG}",
    ]
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=600, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        report.line(FAIL, f"`using {_AGENTREPL_PKG}` loads", str(exc))
        return
    if result.returncode == 0:
        report.line(PASS, f"`using {_AGENTREPL_PKG}` loads")
        return
    tail = "\n".join((result.stderr or result.stdout or "").strip().splitlines()[-12:])
    report.line(
        FAIL,
        f"`using {_AGENTREPL_PKG}` loads",
        "Julia could not load AgentREPL",
        "Run `jutul-agent init --sim <name> --precompile --force` to rebuild the env.",
    )
    if tail:
        print("        Julia said:", file=sys.stderr)
        for line in tail.splitlines():
            print(f"          {line}", file=sys.stderr)
