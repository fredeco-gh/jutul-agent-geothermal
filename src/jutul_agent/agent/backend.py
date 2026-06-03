"""Filesystem backends for the agent's mounted routes.

``ReadOnlyFilesystemBackend`` serves reads and search but rejects writes; it
backs the read-only ``/packages/<Package>/`` mounts (editing the shared Julia
depot would corrupt it for every project). ``WorkspaceShellBackend`` is the
writable default at ``/``.
"""

from __future__ import annotations

from pathlib import Path

from deepagents.backends import FilesystemBackend, LocalShellBackend
from deepagents.backends.protocol import EditResult, WriteResult

_READ_ONLY_MSG = (
    "Error: '{path}' is read-only package source mounted under /packages/. "
    "It's reference material — read and grep it freely, but don't edit it. "
    "Write your own code in the workspace, or to change the package itself, "
    "`Pkg.develop` it (jutul-agent init --source-path ...) and edit the checkout."
)


class ReadOnlyFilesystemBackend(FilesystemBackend):
    """``FilesystemBackend`` that allows reads and search but refuses writes.

    ``awrite``/``aedit`` delegate to these sync methods, so overriding the sync
    side also covers the async tools.
    """

    def write(self, file_path: str, content: str) -> WriteResult:
        return WriteResult(error=_READ_ONLY_MSG.format(path=file_path))

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        return EditResult(error=_READ_ONLY_MSG.format(path=file_path))


class WorkspaceShellBackend(LocalShellBackend):
    """Workspace default backend that tolerates a file's real absolute path.

    Under ``virtual_mode`` every path is treated as relative to the workspace
    root. ``_resolve_path`` first strips the workspace-root prefix so an absolute
    path that already points inside the workspace resolves to the real file
    rather than a re-rooted ``<ws>/home/...`` copy. The file tools and
    ``julia_eval`` (whose cwd is the workspace) then agree whether the agent uses
    a workspace-relative path (``model.jl``), a virtual one (``/model.jl``), or
    the real on-disk path.

    An absolute path outside the workspace (``/root/x.jl``, ``/tmp/...``) is the
    agent mistaking the file tools for the real filesystem; ``write``/``edit``
    reject it with a corrective message.
    """

    def _resolve_path(self, key: str) -> Path:
        if self.virtual_mode and key.startswith("/"):
            root = str(self.cwd)
            if key == root:
                key = "/"
            elif key.startswith(root + "/"):
                key = key[len(root) :]  # keep the leading "/" of the remainder
        return super()._resolve_path(key)

    def _outside_workspace_reason(self, key: str) -> str | None:
        """Corrective message if ``key`` is an absolute host path outside the workspace.

        A leading segment that is itself a real top-level directory (``/root``,
        ``/tmp``, ``/home``, …) marks a host path; ``/model.jl`` or
        ``/experiments/`` don't collide with one and map under the workspace.
        """

        if not (self.virtual_mode and key.startswith("/")):
            return None
        root = str(self.cwd)
        if key == root or key.startswith(root + "/"):
            return None  # a real path inside the workspace — _resolve_path handles it
        first = key.lstrip("/").split("/", 1)[0]
        if not first or not Path("/" + first).is_dir():
            return None  # e.g. /model.jl, /experiments/foo.csv — a workspace-relative path
        name = key.rstrip("/").rsplit("/", 1)[-1] or "file"
        return (
            f"'{key}' is outside the workspace. Write your files with a "
            f"workspace-relative path (e.g. '{name}'); the REPL's working directory "
            f'is the workspace, so `include("{name}")` then finds it.'
        )

    def write(self, file_path: str, content: str) -> WriteResult:
        reason = self._outside_workspace_reason(file_path)
        if reason is not None:
            return WriteResult(error="Error: " + reason)
        return super().write(file_path, content)

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        reason = self._outside_workspace_reason(file_path)
        if reason is not None:
            return EditResult(error="Error: " + reason)
        return super().edit(file_path, old_string, new_string, replace_all=replace_all)
