"""Construct the Deep Agents runtime for a Session.

This module wires everything ``create_deep_agent`` needs in one place:

- ``build_backend``: the CompositeBackend mounting the workspace plus the
  skill/memory/session routes.
- ``register_provider_profiles``: ``HarnessProfile`` registration per
  provider (disables the default general-purpose subagent; all prompt text
  lives in ``agent.prompts``).
- ``build_agent``: the entry point used by the CLI/TUI. Returns the agent
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
from jutul_agent.models import PROVIDERS, provider_of
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


_provider_profiles_registered = False


def resolve_model(
    explicit: Any | None = None,
    *,
    workspace_model: str | None = None,
    user_model: str | None = None,
) -> Any:
    """Resolve the model id by precedence, highest first.

    ``--model`` (``explicit``) > workspace config > user-global config >
    ``$JUTUL_AGENT_MODEL`` (a dev/CI override) > ``DEFAULT_MODEL``.
    """
    return (
        explicit or workspace_model or user_model or os.environ.get(MODEL_ENV_VAR) or DEFAULT_MODEL
    )


def register_provider_profiles() -> None:
    """Register the base HarnessProfile for every provider, once per process.

    deepagents has no wildcard profile key, so the same profile is registered
    under each provider in ``models.PROVIDERS``. The profile only disables the
    stock general-purpose subagent; every prompt rule lives in
    ``agent.prompts`` so each is stated exactly once.
    """

    global _provider_profiles_registered
    if _provider_profiles_registered:
        return

    profile = HarnessProfile(
        general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
    )
    for provider in PROVIDERS:
        register_harness_profile(provider, profile)
    _provider_profiles_registered = True


def _ollama_ctx_budget(default: int = 65536) -> int:
    """Most context (KV cache) to allocate for a local model; a memory cap,
    overridable with ``$JUTUL_AGENT_OLLAMA_NUM_CTX``."""
    try:
        return int(os.environ["JUTUL_AGENT_OLLAMA_NUM_CTX"])
    except (KeyError, ValueError):
        return default


def _ollama_num_ctx(model_id: str) -> int:
    """Context window to load a local model with: the model's own reported max,
    capped at the memory budget. Ollama defaults too small for the agent's
    prompt, and a flat constant ignores each model's real capability.
    """
    from jutul_agent import ollama_client

    budget = _ollama_ctx_budget()
    reported = ollama_client.context_window(ollama_client.model_name(model_id))
    return min(reported, budget) if reported else budget


def _resolve_model_for_agent(model: Any) -> Any:
    """A pre-built model instance for Ollama, the spec string otherwise.

    deepagents skips profile resolution for specs with more than one colon, so
    `ollama:<model>:<tag>` ids would otherwise get neither our harness profile
    nor a context setting. Passing an instance makes deepagents resolve the
    harness profile by provider, and lets us widen the context window local
    models need. Cloud providers keep the string so their provider profiles
    still apply; an already-built model is passed through untouched.
    """
    if isinstance(model, str) and provider_of(model) == "ollama":
        from langchain.chat_models import init_chat_model

        return init_chat_model(model, num_ctx=_ollama_num_ctx(model))
    return model


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
        model=_resolve_model_for_agent(resolve_model(model)),
        backend=backend,
        tools=tools,
        system_prompt=assemble_session_prompt(session.simulator, open_windows=session.open_windows),
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
