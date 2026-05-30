"""Tests for workspace-scoped agent memory."""

from __future__ import annotations

from pathlib import Path

from deepagents.backends import FilesystemBackend

from fakes import make_fake_adapter
from jutul_agent.agent.builder import build_backend
from jutul_agent.agent.memory import (
    MEMORY_INDEX_FILENAME,
    MEMORY_ROUTE,
    ensure_memory_dir,
    make_remember_tool,
)
from jutul_agent.paths import workspace_memory_dir, workspace_state_dir


def test_workspace_memory_dir_is_under_workspace_state(tmp_path: Path, monkeypatch) -> None:
    from jutul_agent.paths import set_state_home, set_workspace_root

    set_workspace_root(tmp_path)
    set_state_home(tmp_path / "state")

    memory_dir = workspace_memory_dir()
    assert memory_dir == workspace_state_dir() / "memory"
    assert "workspaces" in memory_dir.parts


def test_ensure_memory_dir_seeds_index_once(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    ensure_memory_dir(memory_dir)
    index = memory_dir / MEMORY_INDEX_FILENAME
    assert index.exists()
    first = index.read_text(encoding="utf-8")
    assert "Memory index" in first

    index.write_text("# customized\n", encoding="utf-8")
    ensure_memory_dir(memory_dir)
    assert index.read_text(encoding="utf-8") == "# customized\n"


def test_build_backend_mounts_memory_route(tmp_path: Path) -> None:
    adapter = make_fake_adapter(tmp_path)
    memory_dir = ensure_memory_dir(tmp_path / "memory")

    backend = build_backend(adapter, workspace=tmp_path, memory_dir=memory_dir)

    assert MEMORY_ROUTE in backend.routes
    route_backend = backend.routes[MEMORY_ROUTE]
    assert isinstance(route_backend, FilesystemBackend)
    assert route_backend.cwd == memory_dir.resolve()


async def test_remember_writes_note_and_indexes_it(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    remember = make_remember_tool(memory_dir)

    result = await remember.ainvoke(
        {
            "content": "The user is Jakob at SINTEF; focus is BattMo battery sims.",
            "title": "User role",
            "kind": "user",
        }
    )

    note = memory_dir / "user-role.md"
    assert note.exists()
    note_text = note.read_text(encoding="utf-8")
    assert "type: user" in note_text
    assert "SINTEF" in note_text

    index = (memory_dir / MEMORY_INDEX_FILENAME).read_text(encoding="utf-8")
    assert "(file: `user-role.md`)" in index
    assert "user-role.md" in result


async def test_remember_updates_existing_note_without_duplicating_index(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    remember = make_remember_tool(memory_dir)

    await remember.ainvoke({"content": "first version", "title": "Quirk X"})
    await remember.ainvoke({"content": "second version", "title": "Quirk X"})

    note_text = (memory_dir / "quirk-x.md").read_text(encoding="utf-8")
    assert "second version" in note_text
    assert "first version" not in note_text

    index = (memory_dir / MEMORY_INDEX_FILENAME).read_text(encoding="utf-8")
    assert index.count("(file: `quirk-x.md`)") == 1


async def test_remember_falls_back_to_project_for_unknown_kind(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    remember = make_remember_tool(memory_dir)

    await remember.ainvoke({"content": "fact", "title": "Thing", "kind": "nonsense"})
    assert "type: project" in (memory_dir / "thing.md").read_text(encoding="utf-8")
