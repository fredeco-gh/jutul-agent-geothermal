"""Construct the Deep Agents runtime for a Session.

This module wires everything ``create_deep_agent`` needs in one place:

- ``build_backend`` — the CompositeBackend mounting the workspace plus the
  skill/memory/session routes.
- ``register_provider_profiles`` — provider-specific ``HarnessProfile``
  registration (disables the default general-purpose subagent, appends a
  short prompt suffix).
- ``build_agent`` — the entry point used by the CLI/TUI. Returns the agent
  together with its live backend, so callers can mount extra folders
  mid-session (``/add-dir``).
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from deepagents.backends import CompositeBackend, FilesystemBackend

from jutul_agent.agent.approval import ApprovalMode, interrupt_on_for_mode, parse_approval_mode
from jutul_agent.agent.backend import RecursiveGrepBackend, WorkspaceShellBackend
from jutul_agent.agent.julia_plot import (
    make_close_plots_tool,
    make_julia_plot_tool,
    make_recapture_tool,
)
from jutul_agent.agent.memory import (
    build_memory_middleware,
    ensure_memory_dir,
    make_remember_tool,
    memory_backend_route,
)
from jutul_agent.agent.mounts import mount_dir
from jutul_agent.agent.packages_backend import PackageMounts, PackagesBackend, PackageSource
from jutul_agent.agent.prompts import assemble_session_prompt
from jutul_agent.agent.tools import (
    make_julia_eval_tool,
    make_record_attempt_tool,
    make_reset_julia_tool,
    make_write_report_tool,
)
from jutul_agent.paths import SHARED_SKILLS_DIR, workspace_memory_dir, workspace_root
from jutul_agent.session import Session
from jutul_agent.simulators.base import SimulatorAdapter
from jutul_agent.trace import TraceRecorder
from jutul_agent.workspace import resolve_julia_project

__all__ = ["PackageSource", "build_agent", "build_backend", "resolve_model"]

DEFAULT_MODEL = "openai:gpt-5.4-mini"
MODEL_ENV_VAR = "JUTUL_AGENT_MODEL"

_SHARED_SKILLS_ROUTE = "/skills/shared/"
_SIMULATOR_SKILLS_ROUTE = "/skills/simulator/"
_SESSION_ROUTE = "/session/"
_PACKAGES_ROUTE = "/packages/"


# Appended to the base deepagents prompt closest to the conversation. Keep
# provider-specific divergence here; the static prompt assembled in
# ``agent.prompts`` stays simulator-bound.
_PROMPT_SUFFIX = (
    "When any tool or Julia call fails, read the full error output before continuing. "
    "Diagnose the root cause (wrong path, missing package, API mismatch, stale REPL "
    "state) and retry with a concrete fix — do not repeat the same failing call. "
    "The REPL's working directory is the workspace, so refer to files you create "
    "by a plain workspace-relative path (`model.jl`, `experiments/foo.csv`) — it "
    "resolves to the same file in the file tools and in `julia_eval` / `execute` "
    '(`include("model.jl")`); the file\'s real absolute path works in both too. '
    "Don't pass a leading-slash virtual path like `/model.jl` to Julia, and don't "
    "invent a `/workspace/` subfolder. The installed source of every package the "
    "environment resolves — the simulator, what it builds on, and anything you "
    "`Pkg.add` — is browsable under `/packages/<Package>/` (e.g. "
    "`/packages/JutulDarcy/`); `read_file`, `glob`, and `grep` it to study "
    "examples (`/packages/<Package>/examples/`) and source "
    "(`/packages/<Package>/src/`) with the same tools you use for workspace files. "
    "Folders the user adds to the session "
    "are mounted writable at `/dirs/<name>/` — read, grep, write, and edit them with "
    "the file tools (in `julia_eval` / `execute` use their absolute on-disk paths, "
    "not the `/dirs/` virtual path). Use `julia_eval` `@doc` / `methods` / "
    "`names` for exact signatures and docstrings. If a Julia package is missing, "
    "check what is already in the workspace env, use a stdlib alternative, "
    "or `Pkg.add` it when the task needs it. Prefer reading "
    "`/packages/`, probing the REPL, or reading skills over guessing. "
    "Never invoke `julia` (or `julia --project ...`, `julia -e ...`) through "
    "`execute`; use `julia_eval` / `julia_plot` for all Julia code. `execute` "
    "is for non-Julia shell work only (grep, find, ls, git). "
    "The user already sees every tool result in the UI — file contents you "
    "read, `grep`/`glob` results, REPL output, your MEMORY.md index, and skill "
    "text. Never paste any of that back into a reply or wrap it in a code "
    "fence. Refer to files and findings by path, summarise the relevant part in "
    "your own words, and quote at most a line or two when it's genuinely "
    "necessary. Your replies are for conclusions and next steps, not for "
    "echoing what a tool just returned."
)

_SUPPORTED_PROVIDERS: tuple[str, ...] = ("openai", "anthropic")

_provider_profiles_registered = False


def resolve_model(explicit: Any | None = None) -> Any:
    if explicit:
        return explicit
    return os.environ.get(MODEL_ENV_VAR) or DEFAULT_MODEL


def register_provider_profiles() -> None:
    """Register per-provider HarnessProfiles once per process."""

    global _provider_profiles_registered
    if _provider_profiles_registered:
        return

    profile = HarnessProfile(
        general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        system_prompt_suffix=_PROMPT_SUFFIX,
    )
    for provider in _SUPPORTED_PROVIDERS:
        register_harness_profile(provider, profile)
    _provider_profiles_registered = True


def build_backend(
    adapter: SimulatorAdapter,
    *,
    workspace: Path | None = None,
    memory_dir: Path | None = None,
    session_dir: Path | None = None,
    package_sources: Sequence[PackageSource] | None = None,
    mounted_dirs: Sequence[str | Path] | None = None,
) -> CompositeBackend:
    """Mount the workspace plus the skill, memory, session, and package routes.

    The shell default is rooted at ``workspace`` (defaults to
    ``workspace_root()``). Skill markdown is mounted under ``/skills/shared/`` and
    ``/skills/simulator/``, the per-workspace memory dir at ``/memory/``, and the
    live session state read-only at ``/session/`` when ``session_dir`` is set.
    When ``package_sources`` is given, a ``/packages/`` :class:`PackagesBackend`
    exposes one ``/packages/<name>/`` sub-route per package. Any ``mounted_dirs``
    are added writable under ``/dirs/<name>/`` (see ``agent.mounts``).
    """

    routes: dict[str, Any] = {}
    if SHARED_SKILLS_DIR.exists():
        routes[_SHARED_SKILLS_ROUTE] = FilesystemBackend(
            root_dir=SHARED_SKILLS_DIR, virtual_mode=True
        )
    if adapter.skills_dir.exists():
        routes[_SIMULATOR_SKILLS_ROUTE] = FilesystemBackend(
            root_dir=adapter.skills_dir, virtual_mode=True
        )
    if memory_dir is not None:
        route, backend = memory_backend_route(memory_dir)
        routes[route] = backend
    if session_dir is not None:
        routes[_SESSION_ROUTE] = FilesystemBackend(root_dir=session_dir, virtual_mode=True)
    if package_sources is not None:
        # One /packages/ route whose sub-routes mirror the active env; seeded
        # with the simulator packages here and refreshed by PackageMounts when the env changes.
        packages_backend = PackagesBackend()
        packages_backend.set_packages(package_sources)
        routes[_PACKAGES_ROUTE] = packages_backend

    ws = workspace or workspace_root()
    backend = RecursiveGrepBackend(
        default=WorkspaceShellBackend(
            root_dir=ws,
            virtual_mode=True,
            inherit_env=True,
        ),
        routes=routes,
    )
    for raw in mounted_dirs or ():
        mount_dir(backend, raw, workspace=ws)
    return backend


def skill_sources(adapter: SimulatorAdapter) -> list[str | tuple[str, str]]:
    """Skill sources for `SkillsMiddleware`, with explicit labels."""

    sources: list[str | tuple[str, str]] = []
    if SHARED_SKILLS_DIR.exists():
        sources.append((_SHARED_SKILLS_ROUTE, "Built-in"))
    if adapter.skills_dir.exists():
        sources.append((_SIMULATOR_SKILLS_ROUTE, adapter.display_name))
    return sources


def build_agent(
    session: Session,
    *,
    model: Any | None = None,
    checkpointer: Any | None = None,
    approval_mode: ApprovalMode | str | None = None,
    package_sources: Sequence[PackageSource] | None = None,
    mounted_dirs: Sequence[str | Path] | None = None,
) -> tuple[Any, CompositeBackend]:
    """Build the session agent and return it with its live ``CompositeBackend``.

    The backend is returned alongside the agent because it's the same object the
    filesystem middleware uses: callers keep it to mount more folders mid-session
    (the TUI ``/add-dir`` command), and a route added to it is visible to the
    agent's next tool call. Callers that don't need it just ignore the second
    element.
    """

    register_provider_profiles()

    memory_dir = ensure_memory_dir(session.memory_dir(workspace_memory=workspace_memory_dir()))
    backend = build_backend(
        session.simulator,
        memory_dir=memory_dir,
        session_dir=session.state_dir,
        package_sources=package_sources,
        mounted_dirs=mounted_dirs,
    )

    # Keep /packages/ in sync with the env: refreshed after each julia_eval so a
    # package installed via `Pkg.add` becomes browsable under /packages/<Pkg>/.
    package_mounts: PackageMounts | None = None
    packages_backend = backend.routes.get(_PACKAGES_ROUTE)
    if isinstance(packages_backend, PackagesBackend):
        package_mounts = PackageMounts(
            packages_backend,
            session.julia,
            resolve_julia_project(workspace_root()),
            seed=package_sources or (),
        )

    tools = [
        make_julia_eval_tool(session, package_mounts=package_mounts),
        make_reset_julia_tool(session),
        make_julia_plot_tool(session),
        make_recapture_tool(session),
        make_close_plots_tool(session),
        make_record_attempt_tool(session),
        make_write_report_tool(session),
        make_remember_tool(memory_dir),
    ]
    mode = (
        approval_mode
        if isinstance(approval_mode, ApprovalMode)
        else parse_approval_mode(approval_mode)
    )
    subagents = [factory(session) for factory in session.simulator.subagent_factories]
    agent = create_deep_agent(
        model=resolve_model(model),
        backend=backend,
        tools=tools,
        system_prompt=assemble_session_prompt(session.simulator),
        skills=skill_sources(session.simulator),
        subagents=subagents,
        interrupt_on=interrupt_on_for_mode(mode),
        middleware=[
            build_memory_middleware(backend),
            TraceRecorder(session.trace),
        ],
        checkpointer=checkpointer,
    )
    return agent, backend
