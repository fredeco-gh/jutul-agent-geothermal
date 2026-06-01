"""Local Ollama integration: reachability, installed models, and streaming pull.

Thin async wrapper over the ``ollama`` package. The default host is
``http://localhost:11434`` (override with ``$OLLAMA_HOST``). If the server is
down, ``is_reachable`` is ``False`` and the checks return empty rather than
raising.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass

DEFAULT_HOST = "http://localhost:11434"


def host() -> str:
    """Ollama server URL the client will talk to."""
    return os.environ.get("OLLAMA_HOST") or DEFAULT_HOST


def model_name(model_id: str) -> str:
    """The Ollama model tag from an ``ollama:<name>`` id (``<name>``)."""
    _, sep, rest = model_id.partition(":")
    return rest if sep else model_id


@dataclass(frozen=True)
class PullProgress:
    """One progress update from a streaming pull."""

    status: str
    fraction: float | None  # 0..1 when the layer reports total + completed


def _client():
    from ollama import AsyncClient

    return AsyncClient()


async def is_reachable() -> bool:
    """True if the Ollama server answers (and the package is importable)."""
    try:
        await _client().list()
        return True
    except Exception:
        return False


async def installed_models() -> list[str]:
    """Names (tags) of the models pulled locally; empty if the server is down."""
    names: list[str] = []
    with contextlib.suppress(Exception):
        resp = await _client().list()
        for model in getattr(resp, "models", None) or []:
            name = getattr(model, "model", None)
            if name is None and isinstance(model, dict):
                name = model.get("model")
            if name:
                names.append(name)
    return names


def _matches(installed: str, name: str) -> bool:
    # Installed tags carry a version (e.g. "llama3.1:latest"); match a bare name
    # against the tag's base so "llama3.1" finds "llama3.1:latest".
    if installed == name:
        return True
    return ":" not in name and installed.split(":", 1)[0] == name


async def is_installed(name: str) -> bool:
    """True if ``name`` (a bare model name or full tag) is already pulled."""
    return any(_matches(installed, name) for installed in await installed_models())


async def pull(name: str) -> AsyncIterator[PullProgress]:
    """Stream a model pull, yielding ``PullProgress`` until it completes.

    Raises whatever the ``ollama`` client raises (e.g. a connection error).
    """
    stream = await _client().pull(name, stream=True)
    async for chunk in stream:
        status = getattr(chunk, "status", None) or ""
        total = getattr(chunk, "total", None)
        completed = getattr(chunk, "completed", None)
        fraction = completed / total if total and completed is not None else None
        yield PullProgress(status=status, fraction=fraction)
