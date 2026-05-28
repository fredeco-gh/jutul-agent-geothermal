"""AgentREPL.jl backend for ``JuliaSession`` via MCP-over-stdio.

The only module in jutul-agent that knows AgentREPL.jl-specific wire
details; everything else talks through the ``JuliaSession`` Protocol.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from jutul_agent.julia.backends.agentrepl.text import render_terminal_output
from jutul_agent.julia.session import EvalResult

_START_SERVER_SNIPPET = "using AgentREPL; AgentREPL.start_server()"


@dataclass(frozen=True)
class AgentREPLConfig:
    """Configuration for spawning AgentREPL.jl as an MCP subprocess."""

    julia_executable: str = "julia"
    julia_project: Path | None = None
    extra_args: tuple[str, ...] = field(default_factory=lambda: ("--startup-file=no",))
    log_file: Path | None = None


class AgentREPLBackend:
    """``JuliaSession``-compatible backend backed by AgentREPL.jl."""

    def __init__(self, config: AgentREPLConfig | None = None) -> None:
        self._config = config or AgentREPLConfig()
        self._stdio_cm = None
        self._session_cm = None
        self._session: ClientSession | None = None

    async def __aenter__(self) -> Self:
        self._stdio_cm = stdio_client(self._make_params())
        read, write = await self._stdio_cm.__aenter__()
        self._session_cm = ClientSession(read, write)
        self._session = await self._session_cm.__aenter__()
        await self._session.initialize()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        try:
            if self._session_cm is not None:
                await self._session_cm.__aexit__(*exc_info)
        finally:
            if self._stdio_cm is not None:
                await self._stdio_cm.__aexit__(*exc_info)
            self._session = None
            self._session_cm = None
            self._stdio_cm = None

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
        return StdioServerParameters(
            command=self._config.julia_executable,
            args=args,
            env=env,
        )


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
