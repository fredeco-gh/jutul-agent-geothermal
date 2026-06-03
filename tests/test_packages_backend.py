"""Tests for the dynamic /packages/ backend and its env-sync manager."""

from __future__ import annotations

from pathlib import Path

from deepagents.backends import CompositeBackend, LocalShellBackend

from fakes import FakeJulia
from jutul_agent.agent.packages_backend import (
    PackageMounts,
    PackagesBackend,
    PackageSource,
)
from jutul_agent.julia.session import EvalResult


def _make_pkg_tree(root: Path, name: str) -> Path:
    src = root / name / "src"
    src.mkdir(parents=True)
    (src / f"{name}.jl").write_text(f"module {name}\nfunction go end\nend\n")
    return root / name


def _outer(packages_backend: PackagesBackend, workspace: Path) -> CompositeBackend:
    """An outer composite that mounts the packages backend at /packages/."""
    outer = CompositeBackend(
        default=LocalShellBackend(root_dir=workspace, virtual_mode=True),
        routes={"/packages/": packages_backend},
    )
    outer.sorted_routes = sorted(outer.routes.items(), key=lambda x: len(x[0]), reverse=True)
    return outer


def test_set_packages_routes_by_name(tmp_path: Path) -> None:
    geo = _make_pkg_tree(tmp_path, "GeoStats")
    jd = _make_pkg_tree(tmp_path, "JutulDarcy")
    backend = PackagesBackend()
    backend.set_packages([PackageSource("GeoStats", geo), PackageSource("JutulDarcy", jd)])
    assert backend.package_names() == ["GeoStats", "JutulDarcy"]
    # Skips non-existent dirs.
    backend.set_packages([PackageSource("Ghost", tmp_path / "nope")])
    assert backend.package_names() == []


async def test_read_through_outer_composite(tmp_path: Path) -> None:
    geo = _make_pkg_tree(tmp_path, "GeoStats")
    backend = PackagesBackend()
    backend.set_packages([PackageSource("GeoStats", geo)])
    ws = tmp_path / "ws"
    ws.mkdir()
    outer = _outer(backend, ws)

    names = [e["path"] for e in (await outer.als("/packages/")).entries]
    assert names == ["/packages/GeoStats/"]

    result = await outer.aread("/packages/GeoStats/src/GeoStats.jl")
    assert result.error is None
    assert "module GeoStats" in result.file_data["content"]


async def test_registry_readonly_dev_writable(tmp_path: Path) -> None:
    reg = _make_pkg_tree(tmp_path, "Registry")
    dev = _make_pkg_tree(tmp_path, "Dev")
    backend = PackagesBackend()
    backend.set_packages(
        [
            PackageSource("Registry", reg, writable=False),
            PackageSource("Dev", dev, writable=True),
        ]
    )
    ws = tmp_path / "ws"
    ws.mkdir()
    outer = _outer(backend, ws)

    # Registry install refuses edits...
    blocked = await outer.awrite("/packages/Registry/src/new.jl", "x = 1")
    assert blocked.error is not None
    # ...but a developed checkout accepts them.
    ok = await outer.awrite("/packages/Dev/src/new.jl", "x = 1")
    assert ok.error is None
    assert (dev / "src" / "new.jl").exists()


def _enum_handler(mapping: dict[str, tuple[Path, bool]]):
    def handler(code: str) -> EvalResult:
        if "Pkg.dependencies()" not in code:
            return EvalResult(output="")
        lines = [
            f"JPKG\t{name}\t{path}\t{1 if dev else 0}" for name, (path, dev) in mapping.items()
        ]
        return EvalResult(output="\n".join(lines))

    return handler


async def test_refresh_adds_newly_installed_package(tmp_path: Path) -> None:
    project = tmp_path / "env"
    project.mkdir()
    manifest = project / "Manifest.toml"
    manifest.write_text("# manifest v1\n")

    jd = _make_pkg_tree(tmp_path, "JutulDarcy")
    backend = PackagesBackend()
    julia = FakeJulia(eval_handler=_enum_handler({"JutulDarcy": (jd, False)}))
    mounts = PackageMounts(backend, julia, project, seed=[PackageSource("JutulDarcy", jd)])
    # Seeded before any refresh.
    assert backend.package_names() == ["JutulDarcy"]

    # First refresh enumerates the env (manifest mtime differs from initial None).
    await mounts.refresh()
    assert backend.package_names() == ["JutulDarcy"]

    # Simulate an install: a new package resolves and the manifest changes.
    geo = _make_pkg_tree(tmp_path, "GeoStats")
    julia._eval_handler = _enum_handler({"JutulDarcy": (jd, False), "GeoStats": (geo, False)})
    manifest.write_text("# manifest v2 (changed)\n")
    import os

    os.utime(manifest, (manifest.stat().st_atime + 5, manifest.stat().st_mtime + 5))

    await mounts.refresh()
    assert backend.package_names() == ["GeoStats", "JutulDarcy"]


async def test_refresh_marks_dev_packages_writable(tmp_path: Path) -> None:
    project = tmp_path / "env"
    project.mkdir()
    (project / "Manifest.toml").write_text("# m\n")
    dev = _make_pkg_tree(tmp_path, "MyDev")
    backend = PackagesBackend()
    julia = FakeJulia(eval_handler=_enum_handler({"MyDev": (dev, True)}))
    mounts = PackageMounts(backend, julia, project)

    await mounts.refresh(force=True)
    ws = tmp_path / "ws"
    ws.mkdir()
    outer = _outer(backend, ws)
    ok = await outer.awrite("/packages/MyDev/src/extra.jl", "y = 2")
    assert ok.error is None


async def test_refresh_keeps_seed_when_enumeration_fails(tmp_path: Path) -> None:
    project = tmp_path / "env"
    project.mkdir()
    (project / "Manifest.toml").write_text("# m\n")
    jd = _make_pkg_tree(tmp_path, "JutulDarcy")
    backend = PackagesBackend()
    # Enumeration errors (e.g. unresolved env): keep the seed, don't wipe it.
    julia = FakeJulia(eval_handler=lambda code: EvalResult(output="", error="boom"))
    mounts = PackageMounts(backend, julia, project, seed=[PackageSource("JutulDarcy", jd)])
    await mounts.refresh(force=True)
    assert backend.package_names() == ["JutulDarcy"]
