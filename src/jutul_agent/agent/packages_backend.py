"""A single ``/packages/`` route that mirrors the active Julia environment.

Its sub-routes are derived from what the environment resolves
(``Pkg.dependencies()``): every package the agent can ``using`` — simulator,
dependency, or just-installed — is browsable at ``/packages/<Package>/``,
matching where Julia keeps it on disk. ``PackageMounts`` refreshes the set when
the env's ``Manifest.toml`` changes, so an install made through ``julia_eval``
shows up on the next call. Registry installs are read-only; ``Pkg.develop``
checkouts (``is_tracking_path``) are mounted writable.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from deepagents.backends import CompositeBackend, FilesystemBackend
from deepagents.backends.protocol import BackendProtocol

from jutul_agent.agent.backend import ReadOnlyFilesystemBackend
from jutul_agent.julia.session import JuliaSession

# One tab-separated line per resolved package: name, on-disk source dir, and
# whether it is a `Pkg.develop` checkout (writable) rather than a registry install.
_ENUMERATE_CODE = (
    "import Pkg\n"
    "for (_u, _i) in Pkg.dependencies()\n"
    "    _i.source === nothing && continue\n"
    '    println("JPKG\\t", _i.name, "\\t", _i.source, "\\t", _i.is_tracking_path ? 1 : 0)\n'
    "end\n"
)


@dataclass(frozen=True)
class PackageSource:
    """An installed Julia package's source dir, to mount under ``/packages/``.

    ``name`` is the Julia package name, so the route is the same whether it is a
    registry install or a local ``Pkg.develop`` checkout. ``writable`` is set
    only for a developed checkout; registry installs stay read-only.
    """

    name: str
    path: Path
    writable: bool = False


class PackagesBackend(CompositeBackend):
    """``/packages/`` backend with one sub-route per package, rebuilt on demand.

    A nested ``CompositeBackend``: ``ls("/packages/")`` lists the packages and
    ``/packages/<Package>/...`` resolves to that package's source. Call
    :meth:`set_packages` to (re)point the routes; sub-backends are cached by
    ``(path, writable)`` so refreshing is cheap.
    """

    def __init__(self) -> None:
        # Empty default backend: unmatched paths read as not-found instead of
        # leaking the workspace, and `ls("/packages/")` shows only real packages.
        empty_root = Path(tempfile.mkdtemp(prefix="jutul-pkgroot-"))
        super().__init__(
            default=FilesystemBackend(root_dir=empty_root, virtual_mode=True),
            routes={},
        )
        self._cache: dict[tuple[str, bool], BackendProtocol] = {}

    def set_packages(self, sources: Iterable[PackageSource]) -> None:
        routes: dict[str, BackendProtocol] = {}
        for src in sources:
            if not src.path.is_dir():
                continue
            key = (str(src.path), src.writable)
            backend = self._cache.get(key)
            if backend is None:
                cls = FilesystemBackend if src.writable else ReadOnlyFilesystemBackend
                backend = cls(root_dir=src.path, virtual_mode=True)
                self._cache[key] = backend
            routes[f"/{src.name}/"] = backend
        self.routes = routes
        # Keep the longest-prefix-first ordering the composite relies on.
        self.sorted_routes = sorted(routes.items(), key=lambda item: len(item[0]), reverse=True)

    def package_names(self) -> list[str]:
        return sorted(route.strip("/") for route in self.routes)


class PackageMounts:
    """Keeps a :class:`PackagesBackend` in sync with the active Julia env.

    Seeded at startup with the env's resolved packages so ``/packages/`` is
    populated before the first REPL call. ``refresh`` re-enumerates via the live
    session but only re-queries Julia when ``Manifest.toml`` has changed, so it
    is cheap to call after every ``julia_eval``.
    """

    def __init__(
        self,
        backend: PackagesBackend,
        julia: JuliaSession,
        julia_project: Path,
        *,
        seed: Sequence[PackageSource] = (),
    ) -> None:
        self._backend = backend
        self._julia = julia
        self._manifest = Path(julia_project) / "Manifest.toml"
        self._seed = {src.name: src for src in seed}
        self._mtime: float | None = None
        self._populated = False
        backend.set_packages(self._seed.values())

    async def refresh(self, *, force: bool = False) -> None:
        mtime = self._manifest.stat().st_mtime if self._manifest.exists() else None
        if not force and self._populated and mtime == self._mtime:
            return
        self._mtime = mtime
        enumerated = await self._enumerate()
        if not enumerated and not self._populated:
            # First refresh failed (e.g. an unresolved env). Keep the seed so the
            # simulator packages stay browsable; try again on the next change.
            return
        merged = dict(self._seed)
        merged.update(enumerated)  # live env wins (current path + dev/writable)
        self._backend.set_packages(merged.values())
        self._populated = True

    async def _enumerate(self) -> dict[str, PackageSource]:
        result = await self._julia.eval(_ENUMERATE_CODE)
        if result.error:
            return {}
        sources: dict[str, PackageSource] = {}
        for line in result.output.splitlines():
            parts = line.split("\t")
            if len(parts) != 4 or parts[0] != "JPKG":
                continue
            _, name, source, is_dev = parts
            path = Path(source)
            if path.is_dir():
                sources[name] = PackageSource(name=name, path=path, writable=is_dev == "1")
        return sources
