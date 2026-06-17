"""Let the deepagents filesystem tools accept real Windows absolute paths.

The agent runs its filesystem backend in real-path mode (``virtual_mode=False``;
see :mod:`jutul_agent.agent.backend`), so every path a tool receives is a real OS
path — the same string the shell and the Julia REPL use. But deepagents'
``FilesystemMiddleware`` routes each path through ``validate_path`` *before* the
backend sees it, and that helper is written for *virtual* paths: it rejects
anything matching a Windows drive letter (``C:\\...``) outright.

On POSIX this is invisible — a real absolute path starts with ``/``, which
``validate_path`` accepts — so the mismatch only bites on Windows, where real
paths start with ``C:\\``. There it breaks the workflow the agent depends on:
``pkgdir(JutulDarcy)`` returns ``C:\\Users\\...\\.julia\\packages\\...``, and every
``read_file``/``grep``/``ls`` of installed package source is rejected, forcing the
model to shell out to PowerShell ``Get-Content`` for everything.

The fix wraps ``validate_path`` so a Windows drive-absolute path passes through
unchanged (the real-path backend resolves it directly, exactly as it already does
for the shell and REPL), while every other path keeps the original virtual-path
validation — traversal guards and POSIX normalization included. The middleware
looks ``validate_path`` up as a module global at call time, so replacing the name
on the middleware module reaches every file tool it builds.

This is a targeted shim over a deepagents internal; it can be dropped once
deepagents stops rejecting real Windows paths in real-path mode (e.g. gating
``validate_path`` on ``virtual_mode``).
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable

# A leading drive letter (``C:``, ``D:\\``, ``c:/``) marks a real Windows absolute
# path. ``validate_path`` rejects exactly this; we let it through instead.
_WIN_DRIVE = re.compile(r"^[A-Za-z]:")
# Marks an already-wrapped callable so installation is idempotent.
_PATCH_FLAG = "_jutul_agent_real_windows_paths"


def _wrap_validate_path(original: Callable[..., str]) -> Callable[..., str]:
    """Return a ``validate_path`` that passes real Windows absolute paths through.

    A drive-absolute path is handed back verbatim for the real-path backend to
    resolve; anything else defers to ``original`` (unchanged traversal checks and
    normalization). Already-wrapped callables are returned as-is.
    """

    if getattr(original, _PATCH_FLAG, False):
        return original

    def validate_path(path: str, *, allowed_prefixes=None) -> str:
        if isinstance(path, str) and _WIN_DRIVE.match(path):
            return path
        return original(path, allowed_prefixes=allowed_prefixes)

    validate_path.__wrapped__ = original  # type: ignore[attr-defined]
    setattr(validate_path, _PATCH_FLAG, True)
    return validate_path


def _install() -> None:
    """Replace ``validate_path`` with the Windows-aware wrapper everywhere it's bound.

    Patches the source module and the filesystem middleware that imported the
    name into its own namespace. Idempotent.
    """

    from deepagents.backends import utils
    from deepagents.middleware import filesystem as fs_middleware

    for module in (utils, fs_middleware):
        current = getattr(module, "validate_path", None)
        if current is not None:
            module.validate_path = _wrap_validate_path(current)


def enable_windows_real_paths() -> None:
    """On Windows, let the deepagents file tools accept real absolute paths.

    A no-op off Windows (POSIX real paths already validate) and idempotent, so it
    is safe to call on every agent build. Call before the filesystem tools run —
    the middleware resolves ``validate_path`` at call time, so patching the module
    global reaches tools already constructed.
    """

    if os.name != "nt":
        return
    _install()
