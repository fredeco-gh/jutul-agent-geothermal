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

from fakes import make_fake_adapter
from jutul_agent.agent.backend import ReadOnlyFilesystemBackend, WorkspaceShellBackend
from jutul_agent.agent.builder import PackageSource, build_backend
from jutul_agent.agent.packages_backend import PackagesBackend


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


def test_workspace_backend_real_absolute_path_resolves_to_real_file(tmp_path: Path) -> None:
    # The agent often reuses a file's real absolute path (e.g. from pwd()/Julia).
    # Plain virtual_mode would re-root it into a phantom <ws>/<abs> tree; here it
    # must map to the real file so the file tools and the REPL agree.
    ws = tmp_path.resolve()
    backend = WorkspaceShellBackend(root_dir=ws, virtual_mode=True, inherit_env=True)

    backend.write(str(ws / "model.jl"), "x = 1\n")
    assert (ws / "model.jl").read_text() == "x = 1\n"
    # No phantom copy mirroring the absolute path was created: the only model.jl
    # under the workspace is the one at its root.
    assert list(ws.rglob("model.jl")) == [ws / "model.jl"]

    # Real-absolute, virtual-absolute, and relative paths read the same file.
    for key in (str(ws / "model.jl"), "/model.jl", "model.jl"):
        result = backend.read(key)
        assert result.error is None
        assert "x = 1" in result.file_data["content"]


def test_workspace_backend_virtual_paths_still_nest(tmp_path: Path) -> None:
    ws = tmp_path.resolve()
    backend = WorkspaceShellBackend(root_dir=ws, virtual_mode=True, inherit_env=True)
    backend.write("/sub/dir/a.jl", "y = 2\n")
    assert (ws / "sub" / "dir" / "a.jl").read_text() == "y = 2\n"


def test_workspace_backend_rejects_out_of_workspace_absolute(tmp_path: Path) -> None:
    # The agent sometimes writes to a real host path thinking the file tools see
    # the real filesystem; that must error, not silently make a phantom tree.
    ws = tmp_path.resolve()
    backend = WorkspaceShellBackend(root_dir=ws, virtual_mode=True, inherit_env=True)

    # A real absolute path outside the workspace (a sibling of it). Cross-platform:
    # it carries a drive on Windows and a real top-level dir on POSIX.
    outside = tmp_path.parent / "model.jl"
    res = backend.write(str(outside), "x = 1")
    assert res.error is not None
    assert "outside the workspace" in res.error
    assert not outside.exists()  # nothing written

    ed = backend.edit(str(outside), "x", "y")
    assert ed.error is not None
    assert "outside the workspace" in ed.error

    # A plain virtual path (maps under the workspace) is still fine.
    ok = backend.write("/model.jl", "x = 1")
    assert ok.error is None
    assert (ws / "model.jl").exists()


def test_build_backend_mounts_package_source_read_only(tmp_path: Path, source_dir: Path) -> None:
    adapter = make_fake_adapter(tmp_path)
    backend = build_backend(
        adapter,
        workspace=tmp_path,
        package_sources=[PackageSource(name="BattMo", path=source_dir)],
    )

    pkgs = backend.routes["/packages/"]
    assert isinstance(pkgs, PackagesBackend)
    assert pkgs.package_names() == ["BattMo"]
    # readable through the composite
    assert backend.read("/packages/BattMo/examples/demo.jl").error is None
    # not writable (registry install)
    assert backend.write("/packages/BattMo/examples/x.jl", "y").error is not None


def test_build_backend_mounts_developed_source_writable(tmp_path: Path, source_dir: Path) -> None:
    adapter = make_fake_adapter(tmp_path)
    backend = build_backend(
        adapter,
        workspace=tmp_path,
        package_sources=[PackageSource(name="BattMo", path=source_dir, writable=True)],
    )
    # A developed checkout is writable through the composite.
    result = backend.write("/packages/BattMo/examples/x.jl", "y = 1")
    assert result.error is None
    assert (source_dir / "examples" / "x.jl").exists()


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
    pkgs = backend.routes["/packages/"]
    assert isinstance(pkgs, PackagesBackend)
    assert pkgs.package_names() == ["Fimbul", "JutulDarcy"]


def test_build_backend_skips_missing_and_absent_sources(tmp_path: Path) -> None:
    adapter = make_fake_adapter(tmp_path)
    # No package sources at all: no /packages/ route is created.
    backend = build_backend(adapter, workspace=tmp_path, package_sources=None)
    assert not any(route.startswith("/packages/") for route in backend.routes)

    # A declared source whose path doesn't exist is silently skipped, leaving the
    # /packages/ route present but empty.
    backend = build_backend(
        adapter,
        workspace=tmp_path,
        package_sources=[PackageSource(name="Ghost", path=tmp_path / "nope")],
    )
    assert backend.routes["/packages/"].package_names() == []
