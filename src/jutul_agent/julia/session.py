"""Backend-agnostic abstraction over a persistent Julia runtime.

The Protocol stays minimal: ``eval``, ``reset``, and ``restart`` plus the async
context-manager lifecycle. Add methods only when a concrete caller needs them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class EvalResult:
    """Outcome of a single Julia evaluation."""

    output: str
    error: str | None = None


class JuliaSession(Protocol):
    """A persistent Julia runtime accessible via async tool calls."""

    async def __aenter__(self) -> JuliaSession: ...

    async def __aexit__(self, *exc_info: object) -> None: ...

    async def eval(self, code: str) -> EvalResult:
        """Evaluate ``code`` and return its result."""
        ...

    async def reset(self) -> EvalResult:
        """Respawn a fresh Julia worker, clearing all state.

        A cooperative reset that talks to the running runtime; backends that
        can't reset should still return an ``EvalResult`` rather than raising.
        """
        ...

    async def restart(self) -> None:
        """Force the runtime down and start fresh, without relying on it responding.

        The hard recovery for when an evaluation can't be interrupted and the
        runtime is wedged (the TUI's cancel path). Unlike ``reset``, it must not
        depend on the current session being responsive.
        """
        ...
