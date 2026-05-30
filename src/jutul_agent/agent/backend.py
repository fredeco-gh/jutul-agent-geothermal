"""Read-only filesystem backend for mounting installed simulator source.

The agent works in one virtual filesystem (see ``agent.builder.build_backend``):
the workspace at ``/``, plus mounted routes for ``/skills/``, ``/memory/``,
``/session/``, and — when the active simulator's package is resolved —
``/simulator/`` pointing at its source on disk (``pkgdir``). That last mount
lets the agent ``read_file`` / ``glob`` / ``grep`` examples and source with the
same tools it uses for workspace files, instead of reaching outside the
workspace with shell idioms it routinely gets wrong.

Registry packages live in the shared Julia depot and must not be edited (it
would corrupt the install for every project). ``ReadOnlyFilesystemBackend``
serves reads/search but turns writes into a clear error. A developed package
(``Pkg.develop``) is the user's own checkout and is mounted writable instead.
"""

from __future__ import annotations

from deepagents.backends import FilesystemBackend
from deepagents.backends.protocol import EditResult, WriteResult

_READ_ONLY_MSG = (
    "Error: '{path}' is read-only simulator source mounted under /simulator/. "
    "It's reference material — read and grep it freely, but don't edit it. "
    "Write your own code in the workspace, or to change the package itself, "
    "`Pkg.develop` it (jutul-agent init --source-path ...) and edit the checkout."
)


class ReadOnlyFilesystemBackend(FilesystemBackend):
    """``FilesystemBackend`` that allows reads and search but refuses writes.

    ``awrite``/``aedit`` delegate to these synchronous methods (via
    ``asyncio.to_thread``), so overriding the sync side covers the async tools.
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
