"""Canonical filesystem locations used across the package.

Three roots, cleanly separated:

- ``PACKAGE_ROOT`` — computed from this file. Read-only at runtime; per-
  simulator assets (julia envs, skills, adapter modules) live under
  ``PACKAGE_ROOT / "simulators" / <name>``.
- ``workspace_root()`` — the user's working directory at invocation time
  (or an explicit override). Read/write; default for shell and file tools.
- ``state_home()`` — sessions, traces, per-workspace state. Defaults to
  ``$XDG_DATA_HOME/jutul-agent`` or ``~/.local/share/jutul-agent``.

The workspace and state-home anchors are runtime-mutable so the CLI can set
them once on startup and library code can read them via the helpers.
"""

from __future__ import annotations

import hashlib
import os
from datetime import date
from pathlib import Path

PACKAGE_ROOT: Path = Path(__file__).resolve().parent

SHARED_SKILLS_DIR: Path = PACKAGE_ROOT / "simulators" / "shared_skills"

_workspace_root_override: Path | None = None
_state_home_override: Path | None = None


def set_workspace_root(path: Path | None) -> None:
    global _workspace_root_override
    _workspace_root_override = path.resolve() if path is not None else None


def workspace_root() -> Path:
    if _workspace_root_override is not None:
        return _workspace_root_override
    return Path.cwd().resolve()


def set_state_home(path: Path | None) -> None:
    global _state_home_override
    _state_home_override = path.resolve() if path is not None else None


def state_home() -> Path:
    if _state_home_override is not None:
        return _state_home_override
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg).resolve() / "jutul-agent"
    return Path.home() / ".local" / "share" / "jutul-agent"


def resolve_workspace_path(raw: str | Path) -> Path:
    """Resolve a user-supplied path to a real workspace path.

    The agent often passes virtual paths (``/experiments/...``,
    ``/workspace/experiments/...``) that match the deepagents virtual
    filesystem rather than the host filesystem. This helper accepts both
    virtual and real paths and returns a real path under the workspace.

    Cross-platform note: on POSIX a leading-slash string is host-absolute
    and ``Path.is_absolute()`` catches it; on Windows the same string is
    *not* absolute (no drive letter) and joining it onto the workspace
    silently collapses to a drive root (``ws / "/foo" -> C:\\foo``). We
    therefore route any leading-slash, non-absolute string through the
    virtual-path branch explicitly.
    """

    ws = workspace_root()
    text = str(raw)
    p = Path(text)

    def _under_workspace(rel: str) -> Path:
        if rel.startswith("workspace/"):
            rel = rel[len("workspace/") :]
        return ws / rel

    if text.startswith("/") and not p.is_absolute():
        return _under_workspace(text.lstrip("/"))

    if p.is_absolute():
        try:
            p.resolve().relative_to(ws.resolve())
            return p
        except ValueError:
            return _under_workspace(text.lstrip("/"))

    return ws / text


def workspace_hash(workspace: Path | None = None) -> str:
    """Stable 12-char hash of the workspace's resolved path."""
    ws = (workspace or workspace_root()).resolve()
    return hashlib.sha256(str(ws).encode("utf-8")).hexdigest()[:12]


def workspace_state_dir(workspace: Path | None = None) -> Path:
    """Per-workspace state directory under ``state_home()``."""
    return state_home() / "workspaces" / workspace_hash(workspace)


WORKSPACE_OUTPUT_DIRNAME = "jutul-agent-output"


def workspace_output_dir(workspace: Path | None = None) -> Path:
    """Root of the visible per-workspace output tree (``jutul-agent-output/``).

    Named distinctly from the hidden ``.jutul-agent/`` config/env dir so the two
    don't read as the same folder.
    """
    return (workspace or workspace_root()) / WORKSPACE_OUTPUT_DIRNAME


def session_output_dir(session_id: str, workspace: Path | None = None) -> Path:
    """Visible output directory for one session under the workspace.

    Layout: ``<workspace>/jutul-agent-output/sessions/<YYYY-MM-DD>-<short_id>/``

    This directory holds user-facing outputs (plots, transcripts, reports).
    Internal state (SQLite trace, REPL log) stays in ``workspace_state_dir``.
    """
    short_id = session_id[:8]
    date_str = date.today().isoformat()
    return workspace_output_dir(workspace) / "sessions" / f"{date_str}-{short_id}"


def workspace_memory_dir(workspace: Path | None = None) -> Path:
    """Per-workspace memory directory (index + per-fact note files).

    Lives alongside ``sessions/`` under the workspace's state dir so memory
    is automatically scoped to the workspace path the user invokes
    jutul-agent from. The agent maintains the contents via ``edit_file`` /
    ``write_file`` tools mounted at ``/memory/`` in the agent backend.
    """
    return workspace_state_dir(workspace) / "memory"
