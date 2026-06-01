"""Tests for mounting extra working directories under ``/dirs/`` (``/add-dir``).

Added folders are mounted as writable routes on the live ``CompositeBackend``
so the agent reaches them with the normal file tools, and a folder added
mid-session is visible to the next tool call without rebuilding the agent.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from deepagents.backends import FilesystemBackend

from fakes import make_fake_adapter
from jutul_agent.agent.builder import build_backend
from jutul_agent.agent.mounts import (
    MOUNTED_DIRS_ROOT,
    MountError,
    mount_dir,
    mounted_dirs,
)


@pytest.fixture
def backend(tmp_path: Path):
    """A composite backend rooted at an empty workspace."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    adapter = make_fake_adapter(tmp_path)
    return build_backend(adapter, workspace=workspace)


@pytest.fixture
def extra(tmp_path: Path) -> Path:
    folder = tmp_path / "data"
    folder.mkdir()
    (folder / "notes.txt").write_text("hello from outside\n", encoding="utf-8")
    return folder


def test_mount_dir_adds_writable_route(backend, extra: Path) -> None:
    mount = mount_dir(backend, extra, workspace=backend.default.cwd)

    assert mount.route == f"{MOUNTED_DIRS_ROOT}data/"
    assert mount.route in backend.routes
    route = backend.routes[mount.route]
    assert isinstance(route, FilesystemBackend)

    # Readable and writable through the composite at the virtual route.
    assert "hello from outside" in (backend.read(f"{mount.route}notes.txt").file_data or {}).get(
        "content", ""
    )
    assert backend.write(f"{mount.route}new.txt", "added").error is None
    assert (extra / "new.txt").read_text(encoding="utf-8") == "added"


def test_mount_dir_appears_in_route_listing(backend, extra: Path) -> None:
    mount_dir(backend, extra, workspace=backend.default.cwd)
    routes = [entry["path"] for entry in (backend.ls("/").entries or [])]
    assert f"{MOUNTED_DIRS_ROOT}data/" in routes


def test_mount_dir_keeps_longest_prefix_ordering(backend, extra: Path) -> None:
    mount_dir(backend, extra, workspace=backend.default.cwd)
    lengths = [len(route) for route, _ in backend.sorted_routes]
    assert lengths == sorted(lengths, reverse=True)


def test_mount_dir_is_idempotent(backend, extra: Path) -> None:
    first = mount_dir(backend, extra, workspace=backend.default.cwd)
    second = mount_dir(backend, extra, workspace=backend.default.cwd)
    assert first == second
    routes = [r for r in backend.routes if r.startswith(MOUNTED_DIRS_ROOT)]
    assert routes == [first.route]


def test_mount_dir_disambiguates_same_basename(backend, tmp_path: Path) -> None:
    a = tmp_path / "a" / "shared"
    b = tmp_path / "b" / "shared"
    a.mkdir(parents=True)
    b.mkdir(parents=True)

    first = mount_dir(backend, a, workspace=backend.default.cwd)
    second = mount_dir(backend, b, workspace=backend.default.cwd)

    assert first.name == "shared"
    assert second.name == "shared-2"
    assert {first.route, second.route} <= set(backend.routes)


def test_mount_dir_resolves_relative_to_workspace(backend, tmp_path: Path) -> None:
    workspace = backend.default.cwd
    nested = Path(workspace) / "sub" / "child"
    nested.mkdir(parents=True)

    mount = mount_dir(backend, "sub/child", workspace=workspace)
    assert mount.path == nested.resolve()


def test_mount_dir_rejects_missing(backend, tmp_path: Path) -> None:
    with pytest.raises(MountError, match="no such directory"):
        mount_dir(backend, tmp_path / "ghost", workspace=backend.default.cwd)


def test_mount_dir_rejects_file(backend, tmp_path: Path) -> None:
    f = tmp_path / "file.txt"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(MountError, match="not a directory"):
        mount_dir(backend, f, workspace=backend.default.cwd)


def test_mount_dir_rejects_workspace_itself(backend) -> None:
    with pytest.raises(MountError, match="already mounted"):
        mount_dir(backend, backend.default.cwd, workspace=backend.default.cwd)


def test_mounted_dirs_lists_paths(backend, extra: Path) -> None:
    assert mounted_dirs(backend) == []
    mount = mount_dir(backend, extra, workspace=backend.default.cwd)
    listed = mounted_dirs(backend)
    assert len(listed) == 1
    assert listed[0].path == extra.resolve()
    assert listed[0].route == mount.route


def test_build_backend_mounts_extra_dirs(tmp_path: Path, extra: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    adapter = make_fake_adapter(tmp_path)
    backend = build_backend(adapter, workspace=workspace, mounted_dirs=[extra])
    assert f"{MOUNTED_DIRS_ROOT}data/" in backend.routes
