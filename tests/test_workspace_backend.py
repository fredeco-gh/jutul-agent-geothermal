"""Tests for the read-only package-source backend and its ``/packages/`` mounts.

Installed package source (the simulator plus the Jutul-stack packages it builds
on) is mounted under ``/packages/<Package>/`` so the agent can read and grep
examples/source with the normal file tools. Registry packages live in the
shared Julia depot and must not be edited; the mount is read-only there and
writable only for a ``Pkg.develop`` checkout the user owns.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from deepagents.backends import FilesystemBackend

from fakes import make_fake_adapter
from jutul_agent.agent.backend import ReadOnlyFilesystemBackend
from jutul_agent.agent.builder import PackageSource, build_backend


@pytest.fixture
def source_dir(tmp_path: Path) -> Path:
    pkg = tmp_path / "BattMo"
    (pkg / "examples").mkdir(parents=True)
    (pkg / "examples" / "demo.jl").write_text("println(1)\n", encoding="utf-8")
    return pkg


def test_read_only_backend_reads(source_dir: Path) -> None:
    backend = ReadOnlyFilesystemBackend(root_dir=source_dir, virtual_mode=True)
    result = backend.read("/examples/demo.jl")
    assert result.error is None
    assert result.file_data is not None


def test_read_only_backend_refuses_write(source_dir: Path) -> None:
    backend = ReadOnlyFilesystemBackend(root_dir=source_dir, virtual_mode=True)
    result = backend.write("/examples/new.jl", "x = 1")
    assert result.error is not None
    assert "read-only" in result.error
    assert not (source_dir / "examples" / "new.jl").exists()


def test_read_only_backend_refuses_edit(source_dir: Path) -> None:
    backend = ReadOnlyFilesystemBackend(root_dir=source_dir, virtual_mode=True)
    result = backend.edit("/examples/demo.jl", "1", "2")
    assert result.error is not None
    assert "read-only" in result.error
    assert "println(1)" in (source_dir / "examples" / "demo.jl").read_text(encoding="utf-8")


async def test_read_only_backend_async_write_also_refused(source_dir: Path) -> None:
    backend = ReadOnlyFilesystemBackend(root_dir=source_dir, virtual_mode=True)
    result = await backend.awrite("/examples/new.jl", "x = 1")
    assert result.error is not None


def test_build_backend_mounts_package_source_read_only(tmp_path: Path, source_dir: Path) -> None:
    adapter = make_fake_adapter(tmp_path)
    backend = build_backend(
        adapter,
        workspace=tmp_path,
        package_sources=[PackageSource(name="BattMo", path=source_dir)],
    )

    assert "/packages/BattMo/" in backend.routes
    assert isinstance(backend.routes["/packages/BattMo/"], ReadOnlyFilesystemBackend)
    # readable through the composite
    assert backend.read("/packages/BattMo/examples/demo.jl").error is None
    # not writable through the composite
    assert backend.write("/packages/BattMo/examples/x.jl", "y").error is not None


def test_build_backend_mounts_developed_source_writable(tmp_path: Path, source_dir: Path) -> None:
    adapter = make_fake_adapter(tmp_path)
    backend = build_backend(
        adapter,
        workspace=tmp_path,
        package_sources=[PackageSource(name="BattMo", path=source_dir, writable=True)],
    )
    route = backend.routes["/packages/BattMo/"]
    assert isinstance(route, FilesystemBackend)
    assert not isinstance(route, ReadOnlyFilesystemBackend)


def test_build_backend_mounts_multiple_packages_by_name(tmp_path: Path) -> None:
    # A Fimbul-like simulator mounts the package it builds on alongside its own.
    fimbul = tmp_path / "Fimbul"
    jutuldarcy = tmp_path / "JutulDarcy"
    fimbul.mkdir()
    jutuldarcy.mkdir()
    adapter = make_fake_adapter(tmp_path)
    backend = build_backend(
        adapter,
        workspace=tmp_path,
        package_sources=[
            PackageSource(name="Fimbul", path=fimbul),
            PackageSource(name="JutulDarcy", path=jutuldarcy),
        ],
    )
    assert "/packages/Fimbul/" in backend.routes
    assert "/packages/JutulDarcy/" in backend.routes


def test_build_backend_skips_missing_and_absent_sources(tmp_path: Path) -> None:
    adapter = make_fake_adapter(tmp_path)
    # No package sources at all.
    backend = build_backend(adapter, workspace=tmp_path, package_sources=None)
    assert not any(route.startswith("/packages/") for route in backend.routes)

    # A declared source whose path doesn't exist is silently skipped.
    backend = build_backend(
        adapter,
        workspace=tmp_path,
        package_sources=[PackageSource(name="Ghost", path=tmp_path / "nope")],
    )
    assert "/packages/Ghost/" not in backend.routes
