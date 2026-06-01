"""Mount additional working directories into the agent's filesystem.

A workspace normally exposes only the launch directory at ``/`` plus the fixed
skill/memory/session/simulator routes (see ``agent.builder.build_backend``).
Adding a folder mounts it as a new writable route under ``/dirs/<name>/`` in
the live ``CompositeBackend`` so the agent reads, greps, writes, and edits
it with the same file tools it uses for
workspace files — instead of the shell idioms it routinely gets wrong when
reaching outside the workspace.

Mounting mutates the composite's route table in place. The same backend object
is shared with the filesystem middleware, so a folder added mid-session (via the
TUI ``/add-dir`` command) is visible to the very next tool call without
rebuilding the agent. Mounts are session-scoped — they live until the process
exits and are not persisted to the workspace config.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from deepagents.backends import CompositeBackend, FilesystemBackend

from jutul_agent.paths import workspace_root

MOUNTED_DIRS_ROOT = "/dirs/"

# Route names become virtual-path segments, so keep them prefix-match- and
# filesystem-friendly: collapse anything outside this set to a single dash.
_UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


class MountError(ValueError):
    """A folder could not be mounted (missing path, not a directory, ...)."""


@dataclass(frozen=True)
class Mount:
    """A directory mounted into the agent filesystem under ``/dirs/<name>/``."""

    name: str
    route: str
    path: Path


def _route_for(name: str) -> str:
    return f"{MOUNTED_DIRS_ROOT}{name}/"


def _slugify(path: Path) -> str:
    """A safe, human-readable route name derived from the folder's basename."""

    base = _UNSAFE_NAME_CHARS.sub("-", path.name).strip("-._")
    return base or "dir"


def _unique_name(taken: set[str], desired: str) -> str:
    """``desired`` if free, else ``desired-2``, ``desired-3``, ... so two
    folders that share a basename get distinct mount points."""

    if desired not in taken:
        return desired
    index = 2
    while f"{desired}-{index}" in taken:
        index += 1
    return f"{desired}-{index}"


def resolve_dir(raw: str | Path, *, workspace: Path | None = None) -> Path:
    """Resolve a user-supplied folder to an absolute, existing directory.

    ``~`` and relative paths are resolved against the workspace root (the
    user's launch directory), matching how they'd read the path at the prompt.
    Raises ``MountError`` if the path is missing or not a directory.
    """

    base = (workspace or workspace_root()).resolve()
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    candidate = candidate.resolve()
    if not candidate.exists():
        raise MountError(f"no such directory: {candidate}")
    if not candidate.is_dir():
        raise MountError(f"not a directory: {candidate}")
    return candidate


def mounted_dirs(backend: CompositeBackend) -> list[Mount]:
    """The directories currently mounted under ``/dirs/`` on ``backend``."""

    mounts: list[Mount] = []
    for route, route_backend in backend.routes.items():
        if not route.startswith(MOUNTED_DIRS_ROOT) or route == MOUNTED_DIRS_ROOT:
            continue
        name = route[len(MOUNTED_DIRS_ROOT) : -1]
        # ``FilesystemBackend`` stores the resolved root as ``cwd``; fall back
        # to the name if a custom backend doesn't expose it.
        root = getattr(route_backend, "cwd", None)
        mounts.append(Mount(name=name, route=route, path=Path(root) if root else Path(name)))
    mounts.sort(key=lambda mount: mount.name)
    return mounts


def mount_dir(
    backend: CompositeBackend,
    raw: str | Path,
    *,
    workspace: Path | None = None,
) -> Mount:
    """Resolve ``raw`` and mount it *writable* under ``/dirs/<name>/`` on ``backend``.

    Idempotent: if the same directory is already mounted, the existing ``Mount``
    is returned unchanged. The workspace root is rejected — it is already mounted
    at ``/``. Raises ``MountError`` for a missing or non-directory path.
    """

    ws = (workspace or workspace_root()).resolve()
    path = resolve_dir(raw, workspace=ws)
    if path == ws:
        raise MountError("the workspace is already mounted at / — no need to add it")

    current = mounted_dirs(backend)
    for mount in current:
        if mount.path == path:
            return mount

    name = _unique_name({mount.name for mount in current}, _slugify(path))
    route = _route_for(name)
    backend.routes[route] = FilesystemBackend(root_dir=path, virtual_mode=True)
    # Keep the longest-prefix-first ordering the composite relies on for routing.
    backend.sorted_routes = sorted(
        backend.routes.items(), key=lambda item: len(item[0]), reverse=True
    )
    return Mount(name=name, route=route, path=path)
