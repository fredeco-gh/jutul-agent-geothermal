"""AgentREPL.jl backend for ``JuliaSession`` via MCP-over-stdio.

The only module in jutul-agent that knows AgentREPL.jl-specific wire
details; everything else talks through the ``JuliaSession`` Protocol.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Self

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from jutul_agent.agent.render_profile import should_wrap_xvfb
from jutul_agent.julia.backends.agentrepl.text import render_terminal_output
from jutul_agent.julia.requirements import MIN_JULIA_VERSION, check_julia
from jutul_agent.julia.session import EvalResult

# Worker code that parallelizes over Distributed workers with a progress bar
# (e.g. GeoStats ensembles) makes this master process participate in the
# coordination, so ProgressMeter must be loadable here too. Otherwise, the work
# fails to deserialize on the master. Load it best-effort; envs that don't have
# it as a direct dependency simply skip it.
_START_SERVER_SNIPPET = (
    "using AgentREPL; "
    "try Core.eval(Main, :(using ProgressMeter)) catch end; "
    "AgentREPL.start_server()"
)


class JuliaStartupError(RuntimeError):
    """The Julia subprocess died before the MCP handshake completed.

    Carries the diagnostic context the MCP/anyio traceback throws away:
    which Julia and project were used, the tail of Julia's own stderr (the
    *actual* error, usually a package-load failure), and where the full log
    lives.
    """

    def __init__(
        self,
        summary: str,
        *,
        julia_executable: str,
        julia_project: Path | None,
        stderr_tail: str = "",
        log_file: Path | None = None,
    ) -> None:
        self.summary = summary
        self.julia_executable = julia_executable
        self.julia_project = julia_project
        self.stderr_tail = stderr_tail
        self.log_file = log_file
        super().__init__(self.format())

    def format(self) -> str:
        lines = [
            f"Julia failed to start before the agent could connect: {self.summary}",
            f"  julia:         {self.julia_executable}",
            f"  julia project: {self.julia_project if self.julia_project else '(default)'}",
        ]
        if self.stderr_tail.strip():
            lines.append("  Julia said:")
            lines.extend(f"    {line}" for line in self.stderr_tail.strip().splitlines())
        if self.log_file is not None:
            lines.append(f"  full log:      {self.log_file}")
        lines.append("  Run `jutul-agent doctor` to check your setup.")
        return "\n".join(lines)


@dataclass(frozen=True)
class AgentREPLConfig:
    """Configuration for spawning AgentREPL.jl as an MCP subprocess."""

    julia_executable: str = "julia"
    julia_project: Path | None = None
    extra_args: tuple[str, ...] = field(default_factory=lambda: ("--startup-file=no",))
    log_file: Path | None = None
    stderr_file: Path | None = None
    # Working directory for the Julia process. Set to the workspace so that
    # relative paths in agent code — ``include("candidate.jl")``,
    # ``CSV.read("experiments/data.csv")`` — resolve against the same files the
    # file tools write. Falls back to the parent process cwd when unset.
    cwd: Path | None = None


class AgentREPLBackend:
    """``JuliaSession``-compatible backend backed by AgentREPL.jl."""

    def __init__(self, config: AgentREPLConfig | None = None) -> None:
        self._config = config or AgentREPLConfig()
        self._session: ClientSession | None = None
        self._errlog: IO[str] | None = None
        # The MCP session is held open inside a dedicated task (``_run_session``)
        # so its anyio context is entered and exited on the same task, which
        # anyio requires. That lets ``restart()`` force the subprocess down and
        # respawn it from any task. The cancel path runs on a different task
        # than the one that started the session.
        self._session_task: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()
        self._shutdown = asyncio.Event()
        self._startup_exc: BaseException | None = None

    async def __aenter__(self) -> Self:
        # Fail fast with a clear message before we even spawn a subprocess —
        # a missing/old Julia otherwise surfaces as a cryptic FileNotFoundError
        # or a "Connection closed" once the MCP handshake times out.
        check = check_julia(self._config.julia_executable)
        if not check.found:
            raise JuliaStartupError(
                f"`{self._config.julia_executable}` is not on PATH",
                julia_executable=self._config.julia_executable,
                julia_project=self._config.julia_project,
            )
        if not check.version_ok:
            min_str = ".".join(str(n) for n in MIN_JULIA_VERSION)
            raise JuliaStartupError(
                f"Julia {min_str}+ is required, but found {check.version_str or 'unknown'}",
                julia_executable=self._config.julia_executable,
                julia_project=self._config.julia_project,
            )
        await self._spawn()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._teardown()

    async def restart(self) -> None:
        """Force the subprocess down and start a fresh session.

        Unlike ``reset`` (an MCP call that respawns AgentREPL's worker), this
        does not rely on the existing session responding — it tears the whole
        subprocess down (SIGTERM→SIGKILL) and spawns a new one. It is the
        recovery path when an eval can't be interrupted and the session is
        wedged, e.g. the cancel path while a long Julia call is running.
        """

        await self._teardown()
        await self._spawn()

    async def _spawn(self) -> None:
        """Start the session task and wait until it's ready (or failed)."""

        self._ready = asyncio.Event()
        self._shutdown = asyncio.Event()
        self._startup_exc = None
        self._session_task = asyncio.create_task(self._run_session())
        await self._ready.wait()

        exc = self._startup_exc
        if exc is None:
            return
        # Startup crashed. The MCP/anyio exception is noise; the real cause is
        # in Julia's stderr. Join the dead task, then re-raise something a human
        # can act on.
        task, self._session_task = self._session_task, None
        if task is not None:
            with contextlib.suppress(BaseException):
                await task
        if isinstance(exc, JuliaStartupError):
            raise exc
        raise JuliaStartupError(
            _summarize_startup_failure(exc),
            julia_executable=self._config.julia_executable,
            julia_project=self._config.julia_project,
            stderr_tail=self._read_stderr_tail(),
            log_file=self._config.stderr_file or self._config.log_file,
        ) from exc

    async def _run_session(self) -> None:
        """Own the MCP session's lifecycle on a single task.

        Holds the stdio transport and ``ClientSession`` open until ``_shutdown``
        is set, so both contexts are entered and exited on this task. On exit,
        ``stdio_client`` terminates the subprocess tree (SIGTERM→SIGKILL after a
        short grace period), which is what makes ``restart`` reliable even when
        the process is stuck in a runaway computation.
        """

        errlog = self._open_errlog() or self._default_errlog
        try:
            async with (
                stdio_client(self._make_params(), errlog=errlog) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                self._session = session
                self._ready.set()
                await self._shutdown.wait()
        except BaseException as exc:
            # A failure before we signalled ready is a startup error for _spawn
            # to surface; anything after is just teardown (expected on shutdown
            # or a killed subprocess) and not actionable.
            if not self._ready.is_set():
                self._startup_exc = exc
                self._ready.set()
        finally:
            self._session = None
            if self._errlog is not None:
                with contextlib.suppress(Exception):
                    self._errlog.close()
                self._errlog = None

    async def _teardown(self) -> None:
        """Signal the session task to exit and wait for the subprocess to die."""

        task, self._session_task = self._session_task, None
        if task is None:
            return
        self._shutdown.set()
        with contextlib.suppress(BaseException):
            await task
        self._session = None

    @property
    def _default_errlog(self) -> IO[str]:
        return sys.stderr

    def _open_errlog(self) -> IO[str] | None:
        """Redirect Julia's stderr to a file so we can replay it on failure.

        Without this, package-load errors scatter to the terminal interleaved
        with the Python traceback and are easy to miss.
        """

        if self._config.stderr_file is None:
            return None
        self._config.stderr_file.parent.mkdir(parents=True, exist_ok=True)
        # Held open for the subprocess lifetime; closed in __aexit__.
        self._errlog = open(  # noqa: SIM115
            self._config.stderr_file, "w", encoding="utf-8", errors="replace"
        )
        return self._errlog

    def _read_stderr_tail(self, max_lines: int = 40) -> str:
        if self._errlog is not None:
            with contextlib.suppress(Exception):
                self._errlog.flush()
        path = self._config.stderr_file
        if path is None or not path.exists():
            return ""
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return ""
        return "\n".join(lines[-max_lines:])

    async def eval(self, code: str) -> EvalResult:
        return await self._call("eval", {"code": code})

    async def reset(self) -> EvalResult:
        return await self._call("reset", {})

    async def _call(self, tool: str, args: dict[str, object]) -> EvalResult:
        if self._session is None:
            raise RuntimeError("AgentREPLBackend must be used inside an `async with` block")
        result = await self._session.call_tool(name=tool, arguments=args)
        text = _extract_text(result)
        if getattr(result, "isError", False) or _looks_like_tool_error(text):
            return EvalResult(output="", error=text)
        return EvalResult(output=text, error=None)

    def _make_params(self) -> StdioServerParameters:
        args: list[str] = []
        if self._config.julia_project is not None:
            args.append(f"--project={self._config.julia_project}")
        args.extend(self._config.extra_args)
        args.extend(["-e", _START_SERVER_SNIPPET])
        env: dict[str, str] | None = None
        if self._config.log_file is not None:
            env = dict(os.environ)
            env["JULIA_REPL_LOG"] = str(self._config.log_file.resolve())
            env["JULIA_REPL_VIEWER"] = "file"
        command = self._config.julia_executable
        if should_wrap_xvfb():
            # `xvfb-run -a` picks a free display and runs Julia (+ its inherited
            # Distributed worker) under a virtual X server for headless GLMakie.
            args = ["-a", "-s", "-screen 0 1280x1024x24", command, *args]
            command = "xvfb-run"
        return StdioServerParameters(
            command=command,
            args=args,
            env=env,
            cwd=str(self._config.cwd) if self._config.cwd is not None else None,
        )


def _summarize_startup_failure(exc: BaseException) -> str:
    """A short, human-facing reason for a startup crash.

    The MCP layer reports almost every premature subprocess exit as
    "Connection closed"; that tells the user nothing, so we translate the
    common cases and otherwise fall back to the exception type.
    """

    text = str(exc)
    if "Connection closed" in text or not text:
        return "the Julia process exited before responding (see Julia output below)"
    return text


def _extract_text(result: object) -> str:
    """Concatenate text content from an MCP ``CallToolResult``.

    AgentREPL captures stdout from a non-TTY worker, so what arrives here
    still contains the raw control bytes that ProgressMeter.jl, Jutul, and
    friends emit to overwrite their progress block in place (``\\r``,
    ``\\x1b[A`` cursor-up, ``\\x1b[K`` erase-line, …). We replay those
    sequences through a minimal terminal emulator so the result matches
    what a real terminal would show — a single final progress bar at 100%
    instead of every intermediate update stacked on top of each other.
    """

    content = getattr(result, "content", None) or []
    parts: list[str] = []
    for item in content:
        text = getattr(item, "text", None)
        if text is not None:
            parts.append(text)
    return render_terminal_output("\n".join(parts))


_JULIA_ERROR_LINE_RE = re.compile(
    r"(^|\n)(?:ERROR:\s+.*|(?:MethodError|UndefVarError|ArgumentError|BoundsError|"
    r"DomainError|TypeError|KeyError|LoadError|InitError|SystemError|IOError|"
    r"ParseError|StackOverflowError|TaskFailedException|InterruptException)\b)",
    re.MULTILINE,
)


def _looks_like_tool_error(text: str) -> bool:
    """AgentREPL.jl surfaces some Julia exceptions inline rather than via ``isError``."""

    return text.startswith("Internal error in ") or _JULIA_ERROR_LINE_RE.search(text) is not None
