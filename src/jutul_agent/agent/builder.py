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
from collections.abc import Callable, Sequence
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
from jutul_agent.agent.recovery import InvalidToolCallRecoveryMiddleware
from jutul_agent.agent.summarization import build_summarization_middleware
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

    Parallel tool calls are a first-class capability (the tool node runs them
    concurrently) and we do not suppress them per provider: local models emit
    clean parallel calls the vast majority of the time, and the rare malformed
    one is caught generically by ``InvalidToolCallRecoveryMiddleware`` rather
    than by crippling the capability through the prompt.
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


# Reasoning visibility: models that can reason get it requested explicitly.
# OpenAI's recent reasoning models default to effort "none" (no reasoning at
# all) and stream nothing during the thinking phase unless a summary is
# requested; Anthropic's extended thinking is off unless a budget is given;
# Gemini thinks by default but keeps the thoughts hidden.
_OPENAI_REASONING = {"effort": "medium", "summary": "auto"}
_ANTHROPIC_THINKING_BUDGET_TOKENS = 10_000
# Thinking spends from the same output budget as the answer, so the cap must
# clear the thinking budget with room for a long reply.
_ANTHROPIC_MAX_TOKENS = 24_000


def _model_profile(model_id: str) -> dict[str, Any]:
    """The provider package's bundled profile for the model (``{}`` unknown).

    Profiles are the maintained capability source — keying decisions on them
    means new models are covered by upgrading the provider package, never by
    editing a list here. Reading one builds the model, which needs the
    provider key; callers treat a raised error as "no settings".
    """
    from langchain.chat_models import init_chat_model

    return init_chat_model(model_id).profile or {}


def _ollama_settings(model_id: str) -> dict[str, Any]:
    from jutul_agent import ollama_client

    settings: dict[str, Any] = {"num_ctx": _ollama_num_ctx(model_id)}
    # Thinking-capable local models must have think mode requested
    # explicitly: left at the daemon default, the thinking segment is
    # dropped on the client side, so a turn the model spends entirely on
    # thinking surfaces as an empty reply with no tool calls — the agent
    # falls silent. Requested, the thinking is separated, tool calls parse
    # reliably, and the reasoning becomes visible like the cloud providers'.
    if ollama_client.thinks(ollama_client.model_name(model_id)):
        settings["reasoning"] = True
    return settings


def _openai_settings(model_id: str) -> dict[str, Any] | None:
    # The profile must also mark the temperature parameter unsupported: that
    # separates true reasoning models (which accept reasoning.effort) from
    # the -chat hybrids (which reject it).
    profile = _model_profile(model_id)
    if profile.get("reasoning_output") and profile.get("temperature") is False:
        return {"reasoning": dict(_OPENAI_REASONING)}
    return None


def _anthropic_settings(model_id: str) -> dict[str, Any] | None:
    if _model_profile(model_id).get("reasoning_output"):
        return {
            "thinking": {
                "type": "enabled",
                "budget_tokens": _ANTHROPIC_THINKING_BUDGET_TOKENS,
            },
            "max_tokens": _ANTHROPIC_MAX_TOKENS,
        }
    return None


def _google_settings(model_id: str) -> dict[str, Any] | None:
    # Gemini thinks by default (level "high" on Gemini 3+); include_thoughts
    # only makes the thinking visible. An empty profile means the model is
    # newer than the package's data — those all think; the data marks the
    # legacy non-thinking models explicitly.
    profile = _model_profile(model_id)
    if profile.get("reasoning_output") or not profile:
        return {"include_thoughts": True}
    return None


# Construction-time keyword arguments per provider, applied when a model spec
# string is resolved for the agent. The resolution loop is provider-agnostic:
# adding a provider is one entry here, providers without an entry (and any
# model whose resolver declines or fails) pass through as plain spec strings.
# Neither the agent framework nor langchain offers a cross-provider request
# shape for reasoning, so this registry is where the per-provider shapes live.
_MODEL_SETTINGS: dict[str, Callable[[str], dict[str, Any] | None]] = {
    "ollama": _ollama_settings,
    "openai": _openai_settings,
    "anthropic": _anthropic_settings,
    "google_genai": _google_settings,
}


def _resolve_model_for_agent(model: Any) -> Any:
    """A pre-built model instance when the model needs extra construction
    arguments, the spec string otherwise.

    Two reasons to pass an instance instead of the spec string. deepagents
    skips profile resolution for specs with more than one colon, so
    `ollama:<model>:<tag>` ids would otherwise get neither our harness
    profile nor a context setting (an instance resolves by provider). And
    models that can reason get it requested and made visible at construction
    (``_MODEL_SETTINGS``): without that the model reasons silently or, on
    recent OpenAI models, not at all. Everything else — unknown providers,
    models whose resolver declines, failures while probing — keeps the spec
    string so deepagents builds it exactly as before; an already-built model
    is passed through untouched.
    """
    if not isinstance(model, str):
        return model
    settings = _MODEL_SETTINGS.get(provider_of(model))
    if settings is None:
        return model
    try:
        kwargs = settings(model)
        if kwargs:
            from langchain.chat_models import init_chat_model

            return init_chat_model(model, **kwargs)
    except Exception:
        pass  # no key yet, unknown model, offline — run with the plain spec
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
    model_spec = resolve_model(model)
    resolved_model = _resolve_model_for_agent(model_spec)
    agent = create_deep_agent(
        model=resolved_model,
        backend=backend,
        tools=tools,
        system_prompt=assemble_session_prompt(
            session.simulator,
            open_windows=session.open_windows,
            resumed=session.resumed,
        ),
        skills=skill_sources(session.simulator),
        subagents=subagents,
        interrupt_on=interrupt_on_for_mode(mode),
        middleware=[
            build_memory_middleware(backend),
            build_summarization_middleware(
                resolved_model,
                model_id=model_spec if isinstance(model_spec, str) else None,
                trace=session.trace,
            ),
            # Before the recorder in the list so its after_model hook runs
            # *after* the recorder's (after_model composes in reverse): the
            # model call is traced before a recovery jump re-enters the model.
            InvalidToolCallRecoveryMiddleware(),
            TraceRecorder(session.trace),
        ],
        checkpointer=checkpointer,
    )
    return agent, backend
