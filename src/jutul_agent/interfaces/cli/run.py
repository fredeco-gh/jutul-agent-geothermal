"""``jutul-agent`` (run / TUI / headless turn) subcommand."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
import uuid
from pathlib import Path
from typing import Any

from jutul_agent import __version__
from jutul_agent.agent.builder import DEFAULT_MODEL, MODEL_ENV_VAR
from jutul_agent.interfaces.cli._helpers import (
    add_workspace_flags,
    known_packages_map,
)
from jutul_agent.paths import workspace_root
from jutul_agent.session import session_dir, write_last_session
from jutul_agent.simulators import registry
from jutul_agent.workspace import (
    auto_detect_simulator,
    load_workspace_config,
    resolve_julia_project,
    sync_julia_env_with_template,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jutul-agent",
        description=(
            "Specialized scientific agent for AD-enabled simulators built on the Jutul framework."
        ),
        epilog=(
            "Other commands: `jutul-agent init|setup [--sim <name>]`, "
            "`jutul-agent doctor`, `jutul-agent transcript [<id>]`. "
            "(`setup` is an alias for `init`.)"
        ),
    )
    parser.add_argument("--version", action="version", version=f"jutul-agent {__version__}")
    parser.add_argument(
        "--sim",
        choices=registry.names(),
        required=False,
        help="Active simulator. Required if not set in workspace config and not auto-detectable.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "LLM identifier (provider:model) for this run. Precedence: --model > "
            f"workspace config > user config > ${MODEL_ENV_VAR} > {DEFAULT_MODEL}."
        ),
    )
    parser.add_argument(
        "--julia-project",
        type=Path,
        default=None,
        help="Override the resolved workspace Julia project.",
    )
    parser.add_argument(
        "--add-dir",
        type=Path,
        action="append",
        default=None,
        metavar="DIR",
        dest="add_dir",
        help=(
            "Mount an extra folder so the agent can read and edit it, alongside "
            "the workspace. Repeatable. Also available at runtime via /add-dir."
        ),
    )
    add_workspace_flags(parser)
    parser.add_argument(
        "--ephemeral-memory",
        action="store_true",
        help=(
            "Use a throwaway memory directory for this session. Nothing is "
            "persisted to workspace memory on disk."
        ),
    )
    parser.add_argument(
        "--approval-mode",
        choices=["ask", "workspace", "auto"],
        default=None,
        help=(
            "Human-in-the-loop policy: ask (default) prompts before shell and "
            "file edits; workspace auto-allows write_file/edit_file; auto "
            "allows all side-effecting tools."
        ),
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        help="Prompt for a single headless turn. Omit to launch the TUI.",
    )
    return parser


def dispatch(args: argparse.Namespace) -> int:
    import asyncio

    ws = workspace_root()
    config = load_workspace_config(ws)
    sim_name = args.sim or config.simulator or auto_detect_simulator(known_packages_map(), ws)
    if sim_name is None:
        print(
            "error: --sim is required (or set [workspace].simulator in "
            ".jutul-agent/config.toml). Known: " + ", ".join(registry.names()) + ".",
            file=sys.stderr,
        )
        return 2

    try:
        adapter = registry.get(sim_name)
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        return asyncio.run(_run_session(args, adapter, config))
    except KeyboardInterrupt:
        # Ctrl+C during the synchronous startup (Julia kernel, env bootstrap,
        # warm-up) — before the TUI takes over input. Exit cleanly instead of
        # dumping a traceback.
        print("\nStartup interrupted.", file=sys.stderr)
        return 130


async def _run_session(
    args: argparse.Namespace,
    adapter: Any,
    config: Any,
) -> int:
    from jutul_agent.julia.requirements import JuliaRequirementError, require_julia
    from jutul_agent.juliakernel import JuliaStartupError, KernelConfig
    from jutul_agent.simulators.env_setup import (
        EnvSetupError,
        bootstrap_workspace,
        is_workspace_env_ready,
    )

    try:
        require_julia()
    except JuliaRequirementError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    ws = workspace_root()
    julia_project = args.julia_project or resolve_julia_project(ws)

    if args.julia_project is not None:
        if not (julia_project / "Project.toml").exists():
            print(
                f"error: --julia-project {julia_project} has no Project.toml.",
                file=sys.stderr,
            )
            return 2
    elif not is_workspace_env_ready(ws):
        # Implicit auto-bootstrap (without dev or precompile — those are init's job).
        try:
            bootstrap_workspace(adapter, workspace=ws)
        except EnvSetupError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        _ensure_simulator_installed(adapter, ws, julia_project, args.sim or config.simulator)
        _ensure_env_warmed(adapter, ws, julia_project, args.sim or config.simulator)
    else:
        _prepare_existing_env(adapter, ws, julia_project, args.sim or config.simulator)

    session_id = str(uuid.uuid4())
    state_dir = session_dir(session_id)
    state_dir.mkdir(parents=True, exist_ok=True)

    print(f"Workspace:     {ws}", file=sys.stderr)
    print(f"Julia project: {julia_project}", file=sys.stderr)
    _warn_if_plotting_unavailable()

    # On headless Linux, plotting needs a virtual display. We manage Xvfb directly
    # rather than via `xvfb-run`, whose `2>&1` would merge the stdout/stderr the
    # kernel keeps on separate pipes. The Julia process inherits it through DISPLAY.
    from contextlib import ExitStack

    with ExitStack() as display_stack:
        kernel_env = _open_headless_display(display_stack)
        kernel_config = KernelConfig(
            julia_project=julia_project,
            stderr_file=state_dir / "julia-startup.log",
            cwd=ws,
            env=kernel_env,
        )
        try:
            return await _run_with_backend(
                kernel_config, args, adapter, config, session_id, state_dir
            )
        except JuliaStartupError as exc:
            print(f"\nerror: {exc}", file=sys.stderr)
            print("Run `jutul-agent doctor` to check your setup.", file=sys.stderr)
            return 1


def _open_headless_display(stack: Any) -> dict[str, str] | None:
    """Start a virtual display for headless plotting, returning ``{DISPLAY: ...}``.

    Returns ``None`` when no virtual display is needed (a real display is present,
    non-Linux, or the user opted out) or when Xvfb can't start — the Julia process
    then simply inherits the ambient environment.
    """

    from jutul_agent.agent.render_profile import managed_display, should_wrap_xvfb

    if not should_wrap_xvfb():
        return None
    try:
        display = stack.enter_context(managed_display())
    except Exception as exc:  # Xvfb missing or slow to start — don't block the session.
        print(
            f"warning: could not start a virtual display for plotting ({exc}); "
            "GLMakie plotting will be unavailable. Run `jutul-agent doctor` for help.",
            file=sys.stderr,
        )
        return None
    return {"DISPLAY": display}


def _warn_if_plotting_unavailable() -> None:
    """One-line heads-up at launch when GLMakie has no display here.

    On headless Linux without ``xvfb-run`` (or with it opted out), the native
    plotters can't render and ``julia_plot`` errors at use-time — but simulation,
    eval, and the file tools all still work, so this is a warning, not a failure.
    Surfacing it at launch means the user learns before their first plot, not
    mid-session when a ``plot_reservoir`` call fails.
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
        "warning: no display and xvfb not available — plotting (GLMakie) is "
        f"unavailable; simulation still works. To enable plots, {hint}. "
        "Run `jutul-agent doctor` for details.",
        file=sys.stderr,
    )


def _prepare_existing_env(
    adapter: Any,
    ws: Path,
    julia_project: Path,
    sim_name: str | None,
) -> None:
    """Ready an existing workspace env for the active simulator.

    A workspace holds one simulator. A managed env (``.jutul-agent/julia-env``)
    built for a *different* simulator can't be reconciled — e.g. BattMo and
    JutulDarcy pin incompatible shared deps — so we rebuild it from the active
    template rather than merging into an unsatisfiable env. A user-owned root
    ``Project.toml`` is never touched. Otherwise we just pick up new template
    deps and heal an un-instantiated manifest.
    """

    if not (ws / "Project.toml").exists():
        foreign = _foreign_simulator(julia_project, adapter)
        if foreign is not None:
            _rebuild_managed_env(adapter, ws, sim_name, reason=f"was built for {foreign}")
            return

    _sync_workspace_env(adapter, ws, julia_project, sim_name)
    _ensure_simulator_installed(adapter, ws, julia_project, sim_name)
    _ensure_env_warmed(adapter, ws, julia_project, sim_name)


def _foreign_simulator(julia_project: Path, adapter: Any) -> str | None:
    """Display name of another simulator whose package this env declares.

    Shared Jutul-stack packages (e.g. JutulDarcy for Fimbul) are in the active
    adapter's ``package_imports`` and don't count — only a different
    simulator's primary package marks the env as built for something else.
    """

    from jutul_agent.simulators import registry
    from jutul_agent.simulators.env_setup import project_has_package

    for name in registry.names():
        other = registry.get(name)
        if other.name == adapter.name or other.primary_package in adapter.package_imports:
            continue
        if project_has_package(julia_project, other.primary_package):
            return other.display_name
    return None


def _rebuild_managed_env(adapter: Any, ws: Path, sim_name: str | None, *, reason: str) -> None:
    """Replace the managed workspace env with the active simulator's template."""

    from jutul_agent.simulators.env_setup import EnvSetupError, bootstrap_workspace

    print(
        f"Workspace Julia env {reason}; rebuilding it for {adapter.display_name} "
        "from the template (one-time, can take a few minutes)...",
        flush=True,
    )
    try:
        bootstrap_workspace(adapter, workspace=ws, force=True, precompile=True)
    except EnvSetupError as exc:
        _warn_rebuild(adapter.primary_package, sim_name, exc)


def _warn_rebuild(pkg: str, sim_name: str | None, exc: Exception) -> None:
    rebuild = "jutul-agent init --force --precompile"
    if sim_name:
        rebuild += f" --sim {sim_name}"
    print(
        f"warning: could not prepare {pkg} ({exc}).\n"
        f"         The agent may fail to load it. Rebuild the env with:\n"
        f"             {rebuild}",
        file=sys.stderr,
    )


def _sync_workspace_env(
    adapter: Any,
    ws: Path,
    julia_project: Path,
    sim_name: str | None,
) -> None:
    """Bring the workspace env up to date with its simulator template, then install.

    Self-healing: when an upstream change adds packages to the template (e.g. the
    JutulAgent warm-up packages), ``sync_julia_env_with_template`` brings the deps
    — and the ``[sources]`` paths and package directories they need — into the env,
    so a plain ``git pull`` + launch keeps working without a manual rebuild. We only
    resolve and instantiate here so the install is quick; the warm-up bake runs
    afterwards in :func:`_ensure_env_warmed` (with visible progress).

    Best-effort: if the install fails (e.g. the new deps conflict with what is
    pinned), we roll the Project.toml back so the env is no worse than before and
    point at the clean-rebuild command. Either way we proceed to launch.
    """

    from jutul_agent.simulators.env_setup import EnvSetupError, resolve_and_instantiate

    project_toml = julia_project / "Project.toml"
    before = project_toml.read_text(encoding="utf-8") if project_toml.exists() else None

    try:
        added = sync_julia_env_with_template(adapter.julia_env_template_path, workspace=ws)
    except Exception as exc:
        print(f"warning: env sync failed: {exc}", file=sys.stderr)
        return

    if not added:
        return

    print(f"Updating workspace env with {', '.join(added)} (added upstream)...", flush=True)
    try:
        resolve_and_instantiate(julia_project, precompile=False, capture=True)
    except EnvSetupError as exc:
        if before is not None:
            project_toml.write_text(before, encoding="utf-8")
        rebuild = "jutul-agent init --force --precompile"
        if sim_name:
            rebuild += f" --sim {sim_name}"
        print(
            f"warning: could not install {', '.join(added)} — rolled the env back, so it "
            "still works as before and the agent will start normally.\n"
            f"         To rebuild it cleanly, run: {rebuild}\n"
            f"         (cause: {exc})",
            file=sys.stderr,
        )


def _ensure_simulator_installed(
    adapter: Any, ws: Path, julia_project: Path, sim_name: str | None
) -> None:
    """Install the simulator package if the env declares but never resolved it.

    Catches the "`jutul-agent doctor` is happy but `using <Sim>` fails" trap:
    the Project lists the package but the Manifest never resolved it, so it
    loads neither at startup nor in the agent's first call. Cheap when the env
    is healthy (a manifest read); only pays the install cost when needed. If
    the resolve itself fails on a managed env (a broken or conflicted manifest),
    rebuild it from the template. Best-effort — on failure we warn and launch.
    """

    from jutul_agent.simulators.env_setup import (
        EnvSetupError,
        manifest_has_package,
        resolve_and_instantiate,
    )

    pkg = adapter.primary_package
    # Placeholder simulators (e.g. vocsim) declare a primary package they don't
    # actually load; only verify packages the agent will `using`.
    if pkg not in adapter.package_imports:
        return
    if manifest_has_package(julia_project, pkg):
        return

    print(
        f"Workspace Julia env has not resolved {pkg} yet — installing "
        "(one-time, can take a few minutes)...",
        flush=True,
    )
    try:
        # Resolve + install only; the warm-up bake is _ensure_env_warmed's job.
        resolve_and_instantiate(julia_project, precompile=False)
    except EnvSetupError as exc:
        # A user-owned root env is theirs to fix; only rebuild the managed env.
        if not (ws / "Project.toml").exists():
            _rebuild_managed_env(adapter, ws, sim_name, reason="could not be resolved")
            return
        _warn_rebuild(pkg, sim_name, exc)


def _ensure_env_warmed(adapter: Any, ws: Path, julia_project: Path, sim_name: str | None) -> None:
    """Precompile the managed env before launch, but only when something changed.

    The per-simulator ``JutulAgent<Sim>`` package's precompile runs the
    ``@recompile_invalidations`` solve that makes the first real solve fast
    (seconds instead of ~30 s). When the env changed (a fresh install, or new deps
    pulled in) we bake it here — blocking launch until it's ready, and streaming
    Julia's progress so it reads as work in progress, not a silent hang in the first
    eval. When nothing changed, a marker check skips it with no Julia process, so a
    plain launch stays fast. Best-effort: on failure the agent still starts.
    """

    from jutul_agent.simulators.env_setup import EnvSetupError, precompile_env
    from jutul_agent.workspace import (
        env_declares_warm_packages,
        env_precompile_is_current,
        mark_env_precompiled,
    )

    # Only the managed env carries the warm-up packages; a user-owned env is theirs.
    if (ws / "Project.toml").exists() or not env_declares_warm_packages(julia_project):
        return
    if env_precompile_is_current(julia_project):
        return  # nothing changed since the last bake — skip without spawning Julia

    print(
        "Precompiling the Julia env (one-time after a change; can take a few minutes)...",
        flush=True,
    )
    try:
        precompile_env(julia_project)
    except EnvSetupError as exc:
        retry = "jutul-agent init --precompile"
        if sim_name:
            retry += f" --sim {sim_name}"
        print(
            f"warning: env precompile did not finish ({exc}); the agent will start, "
            f"but the first solve may be slow. Retry with: {retry}",
            file=sys.stderr,
        )
        return
    mark_env_precompiled(julia_project)


async def _resolve_package_sources(adapter: Any, julia_project: Path, config: Any) -> list[Any]:
    """Resolve the source dirs to mount under ``/packages/`` for this session.

    Enumerates every package the environment resolves so the agent can browse
    the simulator, its dependencies, and anything it installs at
    ``/packages/<Package>/``. It is fully populated before the first turn. A
    ``Pkg.develop`` checkout is mounted writable (the agent can edit it);
    registry installs stay read-only. Resolution is one fast, no-compile Julia
    call run off the event loop.

    Falls back to just the simulator's key packages if the full enumeration
    can't run (e.g. an unresolved manifest); ``PackageMounts`` then fills in the
    rest after the first REPL call.
    """

    from jutul_agent.agent.builder import PackageSource
    from jutul_agent.simulators.env_setup import (
        resolve_env_package_sources,
        resolve_package_sources,
    )

    env = await asyncio.to_thread(resolve_env_package_sources, julia_project)
    if env:
        return [
            PackageSource(name=name, path=path, writable=is_dev)
            for name, (path, is_dev) in sorted(env.items())
        ]

    sources = await asyncio.to_thread(
        resolve_package_sources, julia_project, adapter.package_imports
    )
    primary_developed = config.simulator_config(adapter.name).source_path is not None
    return [
        PackageSource(
            name=name,
            path=path,
            writable=primary_developed and name == adapter.primary_package,
        )
        for name, path in sources.items()
    ]


def _resolve_add_dirs(raw_dirs: Any, ws: Path) -> list[Path]:
    """Resolve ``--add-dir`` paths, warning on (and skipping) bad ones.

    One unreadable folder shouldn't abort startup, so invalid entries are
    reported and dropped; the agent launches with whatever resolved cleanly.
    """

    from jutul_agent.agent.mounts import MountError, resolve_dir

    resolved: list[Path] = []
    for raw in raw_dirs or ():
        try:
            path = resolve_dir(raw, workspace=ws)
        except MountError as exc:
            print(f"warning: --add-dir {raw}: {exc}", file=sys.stderr)
            continue
        if path not in resolved:
            resolved.append(path)
    return resolved


async def _run_with_backend(
    kernel_config: Any,
    args: argparse.Namespace,
    adapter: Any,
    config: Any,
    session_id: str,
    state_dir: Path,
) -> int:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from jutul_agent.agent.approval import parse_approval_mode
    from jutul_agent.agent.builder import build_agent, resolve_model
    from jutul_agent.agent.mounts import mounted_dirs
    from jutul_agent.agent.render_profile import can_open_windows
    from jutul_agent.juliakernel import JuliaKernel
    from jutul_agent.session import Session
    from jutul_agent.user_config import load_user_config

    # A live window is shown only for an interactive session with a display; a
    # one-shot `--prompt` run and any headless box render offscreen to a PNG.
    open_windows = can_open_windows(interactive_session=not args.prompt)

    async with JuliaKernel(kernel_config) as julia:
        session = Session.create(
            julia=julia,
            simulator=adapter,
            session_id=session_id,
            ephemeral_memory=args.ephemeral_memory,
            open_windows=open_windows,
        )
        write_last_session(session.session_id)
        warmup_task = _start_warmup(julia, adapter.warm_package)
        try:
            ckpt_path = session.state_dir / "checkpoints.sqlite"
            async with AsyncSqliteSaver.from_conn_string(str(ckpt_path)) as checkpointer:
                user_config = load_user_config()
                model_label = resolve_model(
                    args.model,
                    workspace_model=config.model,
                    user_model=user_config.model,
                )
                approval_mode = parse_approval_mode(args.approval_mode or config.approval_mode)
                package_sources = await _resolve_package_sources(
                    adapter, kernel_config.julia_project, config
                )
                extra_dirs = _resolve_add_dirs(args.add_dir, kernel_config.cwd)

                def build(model_id: str, dirs: Any) -> Any:
                    # Rebuilds with the same checkpointer/session so the TUI can
                    # switch models without losing the conversation; ``dirs`` keeps
                    # any /add-dir mounts across the rebuild.
                    return build_agent(
                        session,
                        model=model_id,
                        checkpointer=checkpointer,
                        approval_mode=approval_mode,
                        package_sources=package_sources,
                        mounted_dirs=dirs,
                    )

                agent, backend = build(model_label, extra_dirs)
                if package_sources:
                    writable = [src.name for src in package_sources if src.writable]
                    summary = f"Packages: {len(package_sources)} mounted under /packages/"
                    if writable:
                        summary += f" ({len(writable)} writable dev: {', '.join(writable)})"
                    print(summary, file=sys.stderr)
                for mount in mounted_dirs(backend):
                    print(f"Added folder:  {mount.path} -> {mount.route}", file=sys.stderr)
                if args.prompt:
                    return await _headless_turn(agent, session, args.prompt)
                from jutul_agent.interfaces.tui import TUIApp

                await TUIApp(
                    agent=agent,
                    session=session,
                    backend=backend,
                    model_label=model_label,
                    approval_mode=approval_mode,
                    warmup_task=warmup_task,
                    agent_factory=build,
                ).run_async()
        finally:
            if warmup_task is not None and not warmup_task.done():
                warmup_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await warmup_task
            session.finalize()
    return 0


def _start_warmup(julia: Any, warm_package: str) -> asyncio.Task[Any] | None:
    """Background warm-up: load the agent's precompiled Julia runtime, then
    initialise this session's GL context while the user reads the welcome card.

    The heavy compilation is already baked into the packages' precompile caches at
    ``init``, so loading the shared ``JutulAgent`` and the env's per-simulator
    ``warm_package`` here is just load latency; a tiny offscreen save then warms
    GLMakie's GL context. Best-effort: every step is wrapped so a missing piece
    never breaks startup, and the task is cancelled on session teardown.
    """

    from jutul_agent.simulators.warmup import GL_CONTEXT_WARMUP

    loads = ["try; @eval using JutulAgent; catch; end"]
    if warm_package:
        loads.append(f"try; @eval using {warm_package}; catch; end")
    bootstrap = "\n".join(loads)

    async def _run_warmup() -> None:
        with contextlib.suppress(Exception):
            await julia.eval(bootstrap)
        with contextlib.suppress(Exception):
            await julia.eval(GL_CONTEXT_WARMUP)

    return asyncio.create_task(_run_warmup(), name="julia-warmup")


async def _headless_turn(agent: Any, session: Any, prompt: str) -> int:
    from jutul_agent.agent.turns import TurnRunner

    runner = TurnRunner(agent, thread_id=session.session_id, trace=session.trace)
    result = await runner.run_prompt(prompt)
    if result.interrupts:
        print(
            "error: this turn paused for approval, but headless mode can't prompt for it yet.\n"
            "       Re-run with `--approval-mode auto` to let the agent run tools without "
            "approval,\n"
            "       or launch the interactive TUI (`uv run jutul-agent`) to approve steps as "
            "they come up.",
            file=sys.stderr,
        )
        print(f"\n[session {session.session_id}]", file=sys.stderr)
        return 3

    _print_final_message(result.messages)
    print(f"\n[session {session.session_id}]", file=sys.stderr)
    return 0


def _print_final_message(messages: list[Any]) -> None:
    if not messages:
        return
    last = messages[-1]
    content = getattr(last, "content", None)
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and "text" in part:
                parts.append(part["text"])
            else:
                parts.append(str(part))
        print("\n".join(parts))
    elif content is not None:
        print(content)
    else:
        print(last)
