"""Filesystem backends for the agent's mounted routes.

``ReadOnlyFilesystemBackend`` serves reads and search but rejects writes; it
backs the read-only ``/packages/<Package>/`` mounts (editing the shared Julia
depot would corrupt it for every project). ``WorkspaceShellBackend`` is the
writable default at ``/``. ``RecursiveGrepBackend`` is the top-level composite,
fixing a grep glob that otherwise silently skips subdirectories.
"""

from __future__ import annotations

from pathlib import Path

from deepagents.backends import CompositeBackend, FilesystemBackend, LocalShellBackend
from deepagents.backends.protocol import EditResult, GrepResult, WriteResult

_READ_ONLY_MSG = (
    "Error: '{path}' is read-only package source mounted under /packages/. "
    "It's reference material — read and grep it freely, but don't edit it. "
    "Write your own code in the workspace, or to change the package itself, "
    "`Pkg.develop` it (jutul-agent init --source-path ...) and edit the checkout."
)


def _is_host_path(key: str) -> bool:
    """Whether ``key`` is a real host path rather than a virtual workspace path.

    A Windows drive (``C:\\...``) is unambiguous. On POSIX a leading-slash path
    can still be virtual (``/model.jl`` means a workspace file), so it only counts
    as a host path when its first segment is a real top-level directory
    (``/etc``, ``/home``, …).
    """

    if Path(key).drive:
        return True
    first = key.lstrip("/").split("/", 1)[0] if key.startswith("/") else ""
    return bool(first) and Path("/" + first).is_dir()


def _recursive_glob(glob: str | None) -> str | None:
    """Make a slash-free grep filter recursive.

    deepagents matches a bare ``*.jl`` glob only against files directly in the
    searched directory, so a type-filtered grep silently skips subdirectories
    (e.g. a package's ``src/ext/``, where Julia keeps extension code). ripgrep and
    the agent's expectation treat it as recursive, so rewrite ``*.jl`` to
    ``**/*.jl``. Patterns that already carry a path (``src/*.jl``, ``**/*.jl``)
    are left alone.
    """

    if glob and "/" not in glob:
        return f"**/{glob}"
    return glob


class RecursiveGrepBackend(CompositeBackend):
    """Top-level composite whose grep recurses on a bare ``*.ext`` filter.

    See :func:`_recursive_glob`. Normalizing here, the one backend the grep tool
    calls, fixes every route, including the nested ``/packages/`` composite, since
    the composite forwards the same glob to the sub-backend it resolves to.
    """

    def grep(self, pattern: str, path: str | None = None, glob: str | None = None) -> GrepResult:
        return super().grep(pattern, path=path, glob=_recursive_glob(glob))

    async def agrep(
        self, pattern: str, path: str | None = None, glob: str | None = None
    ) -> GrepResult:
        return await super().agrep(pattern, path=path, glob=_recursive_glob(glob))


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
        if self.virtual_mode:
            path = Path(key)
            if path.is_absolute():
                try:
                    rel = path.relative_to(self.cwd)
                except ValueError:
                    rel = None
                if rel is not None:
                    # An absolute path inside the workspace → rewrite it
                    # workspace-relative so it maps to the real file rather than a
                    # re-rooted phantom.
                    key = "/" + rel.as_posix()
        return super()._resolve_path(key)

    def _outside_workspace_reason(self, key: str) -> str | None:
        """Corrective message if ``key`` is an absolute host path outside the workspace.

        An absolute path inside the workspace is fine (``_resolve_path`` maps it).
        An absolute path *outside* it is the agent mistaking the file tools for the
        real filesystem.
        """

        if not self.virtual_mode:
            return None
        path = Path(key)
        if not path.is_absolute():
            return None  # workspace-relative
        try:
            path.relative_to(self.cwd)
            return None  # inside the workspace — _resolve_path handles it
        except ValueError:
            pass
        if not _is_host_path(key):
            return None
        name = key.rstrip("/").rstrip("\\").replace("\\", "/").rsplit("/", 1)[-1] or "file"
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
