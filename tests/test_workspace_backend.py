"""Tests for the read-only simulator-source backend and its ``/simulator/`` mount.

Installed simulator source is mounted at ``/simulator/`` so the agent can read
and grep examples/source with the normal file tools. Registry packages live in
the shared Julia depot and must not be edited; the mount is read-only there and
writable only for ``Pkg.develop`` checkouts.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from deepagents.backends import FilesystemBackend

from fakes import make_fake_adapter
from jutul_agent.agent.backend import ReadOnlyFilesystemBackend
from jutul_agent.agent.builder import build_backend


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


def test_build_backend_mounts_simulator_source_read_only(tmp_path: Path, source_dir: Path) -> None:
    adapter = make_fake_adapter(tmp_path)
    backend = build_backend(adapter, workspace=tmp_path, simulator_source=source_dir)

    assert "/simulator/" in backend.routes
    assert isinstance(backend.routes["/simulator/"], ReadOnlyFilesystemBackend)
    # readable through the composite
    assert backend.read("/simulator/examples/demo.jl").error is None
    # not writable through the composite
    assert backend.write("/simulator/examples/x.jl", "y").error is not None


def test_build_backend_mounts_developed_source_writable(tmp_path: Path, source_dir: Path) -> None:
    adapter = make_fake_adapter(tmp_path)
    backend = build_backend(
        adapter,
        workspace=tmp_path,
        simulator_source=source_dir,
        simulator_source_writable=True,
    )
    route = backend.routes["/simulator/"]
    assert isinstance(route, FilesystemBackend)
    assert not isinstance(route, ReadOnlyFilesystemBackend)


def test_build_backend_skips_source_route_when_absent(tmp_path: Path) -> None:
    adapter = make_fake_adapter(tmp_path)
    backend = build_backend(adapter, workspace=tmp_path, simulator_source=None)
    assert "/simulator/" not in backend.routes
