"""Backend-agnostic abstraction over a persistent Julia runtime.

The Protocol stays minimal: ``eval`` and ``reset`` plus the async
context-manager lifecycle. Add methods only when a concrete caller needs
them.
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
        """Kill any in-flight evaluation and respawn a fresh Julia worker.

        Used by the TUI's Ctrl+G cancel path. Backends that can't interrupt
        should still return an ``EvalResult`` rather than raising.
        """
        ...
