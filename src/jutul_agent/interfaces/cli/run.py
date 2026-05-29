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
            f"LLM identifier (provider:model). Precedence: --model > "
            f"${MODEL_ENV_VAR} > {DEFAULT_MODEL}."
        ),
    )
    parser.add_argument(
        "--julia-project",
        type=Path,
        default=None,
        help="Override the resolved workspace Julia project.",
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

    return asyncio.run(_run_session(args, adapter, config))


async def _run_session(
    args: argparse.Namespace,
    adapter: Any,
    config: Any,
) -> int:
    from jutul_agent.julia.backends.agentrepl import AgentREPLConfig, JuliaStartupError
    from jutul_agent.simulators.env_setup import (
        EnvSetupError,
        bootstrap_workspace,
        is_workspace_env_ready,
    )

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
    else:
        # Workspace env already exists. Pick up any deps the template gained
        # since this env was last bootstrapped (e.g. CSV/Interpolations added
        # to an investigation template) and install them so they're available.
        _sync_workspace_env(adapter, ws, julia_project, args.sim or config.simulator)

    session_id = str(uuid.uuid4())
    state_dir = session_dir(session_id)
    state_dir.mkdir(parents=True, exist_ok=True)
    repl_config = AgentREPLConfig(
        julia_project=julia_project,
        log_file=state_dir / "repl.log",
        stderr_file=state_dir / "julia-startup.log",
    )
    print(f"Workspace:     {ws}", file=sys.stderr)
    print(f"Julia project: {julia_project}", file=sys.stderr)
    try:
        return await _run_with_backend(repl_config, args, adapter, config, session_id, state_dir)
    except JuliaStartupError as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        return 1


def _sync_workspace_env(
    adapter: Any,
    ws: Path,
    julia_project: Path,
    sim_name: str | None,
) -> None:
    """Add template deps the workspace env is missing, then install them.

    Best-effort and self-healing: if resolve/instantiate fails (e.g. the new
    deps conflict with what's already pinned), we roll the Project.toml back
    to its previous contents so the env is left no worse than before, and
    point the user at the command that rebuilds it cleanly. Either way we
    proceed to launch — AgentREPL itself may still start fine.
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

    print(
        f"Added missing deps to workspace env: {', '.join(added)} — resolving and installing...",
        flush=True,
    )
    try:
        resolve_and_instantiate(julia_project)
    except EnvSetupError as exc:
        if before is not None:
            project_toml.write_text(before, encoding="utf-8")
        rebuild = "jutul-agent init --force --precompile"
        if sim_name:
            rebuild += f" --sim {sim_name}"
        print(
            f"warning: could not install {', '.join(added)} ({exc}).\n"
            f"         Rolled back the env so it still works as before. To rebuild it "
            f"cleanly, run:\n             {rebuild}\n"
            f"         Run `jutul-agent doctor` to check the result.",
            file=sys.stderr,
        )


async def _run_with_backend(
    repl_config: Any,
    args: argparse.Namespace,
    adapter: Any,
    config: Any,
    session_id: str,
    state_dir: Path,
) -> int:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from jutul_agent.agent.approval import parse_approval_mode
    from jutul_agent.agent.builder import build_agent, resolve_model
    from jutul_agent.julia.backends.agentrepl import AgentREPLBackend
    from jutul_agent.session import Session

    async with AgentREPLBackend(repl_config) as julia:
        session = Session.create(
            julia=julia,
            simulator=adapter,
            session_id=session_id,
            ephemeral_memory=args.ephemeral_memory,
        )
        write_last_session(session.session_id)
        warmup_task = _start_warmup(julia, adapter.warmup_code)
        try:
            ckpt_path = session.state_dir / "checkpoints.sqlite"
            async with AsyncSqliteSaver.from_conn_string(str(ckpt_path)) as checkpointer:
                model_label = resolve_model(args.model)
                approval_mode = parse_approval_mode(args.approval_mode or config.approval_mode)
                agent = build_agent(
                    session,
                    model=model_label,
                    checkpointer=checkpointer,
                    approval_mode=approval_mode,
                )
                if args.prompt:
                    return await _headless_turn(agent, session, args.prompt)
                from jutul_agent.interfaces.tui import TUIApp

                await TUIApp(
                    agent=agent,
                    session=session,
                    model_label=model_label,
                    approval_mode=approval_mode,
                ).run_async()
        finally:
            if warmup_task is not None and not warmup_task.done():
                warmup_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await warmup_task
            session.finalize()
    return 0


def _start_warmup(julia: Any, warmup_code: str) -> asyncio.Task[Any] | None:
    """Kick off the simulator's warmup eval in the background, if any.

    Best-effort: errors are swallowed and the task is cancelled on session
    teardown.
    """

    if not warmup_code.strip():
        return None

    async def _run_warmup() -> None:
        with contextlib.suppress(Exception):
            await julia.eval(warmup_code)

    return asyncio.create_task(_run_warmup(), name="julia-warmup")


async def _headless_turn(agent: Any, session: Any, prompt: str) -> int:
    from jutul_agent.agent.turns import TurnRunner

    runner = TurnRunner(agent, thread_id=session.session_id, trace=session.trace)
    result = await runner.run_prompt(prompt)
    if result.interrupts:
        print(
            "error: this turn requires approval, but headless resume is not implemented yet.",
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
