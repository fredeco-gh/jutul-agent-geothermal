"""Tests for workspace config and bootstrap."""

from __future__ import annotations

from pathlib import Path

import pytest

from jutul_agent.workspace import (
    SimulatorConfig,
    WorkspaceConfig,
    auto_detect_simulator,
    bootstrap_julia_env,
    load_workspace_config,
    merge_simulator_config,
    resolve_julia_project,
    sync_julia_env_with_template,
    workspace_is_simulator_source,
    workspace_julia_env,
    write_workspace_config,
)


def test_load_and_write_workspace_config_round_trip(tmp_path: Path) -> None:
    config = WorkspaceConfig(
        simulator="jutuldarcy",
        simulators={"jutuldarcy": SimulatorConfig(source_path=tmp_path / "src")},
    )
    write_workspace_config(config, workspace=tmp_path)
    loaded = load_workspace_config(tmp_path)
    assert loaded.simulator == "jutuldarcy"
    assert loaded.simulator_config("jutuldarcy").source_path == (tmp_path / "src").resolve()


def test_auto_detect_from_deps(tmp_path: Path) -> None:
    (tmp_path / "Project.toml").write_text(
        '[deps]\nJutulDarcy = "uuid"\n',
        encoding="utf-8",
    )
    known = {"JutulDarcy": "jutuldarcy", "BattMo": "battmo"}
    assert auto_detect_simulator(known, tmp_path) == "jutuldarcy"


def test_auto_detect_from_project_name(tmp_path: Path) -> None:
    (tmp_path / "Project.toml").write_text(
        'name = "JutulDarcy"\n[deps]\n',
        encoding="utf-8",
    )
    known = {"JutulDarcy": "jutuldarcy"}
    assert auto_detect_simulator(known, tmp_path) == "jutuldarcy"


def test_workspace_is_simulator_source(tmp_path: Path) -> None:
    (tmp_path / "Project.toml").write_text('name = "Foo"\n', encoding="utf-8")
    assert workspace_is_simulator_source("Foo", tmp_path) is True
    assert workspace_is_simulator_source("Bar", tmp_path) is False


def test_bootstrap_julia_env_uses_root_project(tmp_path: Path) -> None:
    (tmp_path / "Project.toml").write_text("[deps]\n", encoding="utf-8")
    template = tmp_path / "doesnt-matter"
    project = bootstrap_julia_env(template, workspace=tmp_path)
    assert project == tmp_path.resolve()


def test_resolve_julia_project_prefers_julia_env_without_root_project(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    env = ws / ".jutul-agent" / "julia-env"
    env.mkdir(parents=True)
    (env / "Project.toml").write_text('[deps]\nAgentREPL = "uuid"\n', encoding="utf-8")

    assert resolve_julia_project(ws) == env


def test_bootstrap_julia_env_copies_template(tmp_path: Path) -> None:
    template = tmp_path / "template"
    template.mkdir()
    (template / "Project.toml").write_text("[deps]\n", encoding="utf-8")

    ws = tmp_path / "ws"
    ws.mkdir()
    project = bootstrap_julia_env(template, workspace=ws)
    assert project.name == "julia-env"
    assert (project / "Project.toml").exists()


def test_merge_simulator_config_updates_one_entry() -> None:
    base = WorkspaceConfig(simulators={"jutuldarcy": SimulatorConfig()})
    updated = merge_simulator_config(base, "jutuldarcy", source_path=Path("/tmp/src"))
    assert updated.simulator_config("jutuldarcy").source_path == Path("/tmp/src")
    assert base.simulator_config("jutuldarcy").source_path is None


@pytest.fixture
def _template_with_extra_deps(tmp_path: Path) -> Path:
    """Sim env template with three deps; workspace will be seeded with one."""
    template = tmp_path / "template"
    template.mkdir()
    (template / "Project.toml").write_text(
        '[deps]\n'
        'AgentREPL = "c6b0b931-bd15-49f6-a31f-cf7d80eb5e81"\n'
        'CSV = "336ed68f-0bac-5ca0-87d4-7b16caf5d00b"\n'
        'Interpolations = "a98d9a8b-a2ab-59e6-89dd-64a1c18fca59"\n',
        encoding="utf-8",
    )
    return template


def test_sync_adds_missing_deps_from_template(
    tmp_path: Path, _template_with_extra_deps: Path
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    env = workspace_julia_env(ws)
    env.mkdir(parents=True)
    (env / "Project.toml").write_text(
        '[deps]\nAgentREPL = "c6b0b931-bd15-49f6-a31f-cf7d80eb5e81"\n',
        encoding="utf-8",
    )

    added = sync_julia_env_with_template(_template_with_extra_deps, workspace=ws)
    assert sorted(added) == ["CSV", "Interpolations"]

    text = (env / "Project.toml").read_text(encoding="utf-8")
    assert 'CSV = "336ed68f-0bac-5ca0-87d4-7b16caf5d00b"' in text
    assert 'Interpolations = "a98d9a8b-a2ab-59e6-89dd-64a1c18fca59"' in text


def test_sync_is_noop_when_already_in_sync(
    tmp_path: Path, _template_with_extra_deps: Path
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    env = workspace_julia_env(ws)
    env.mkdir(parents=True)
    (env / "Project.toml").write_text(
        '[deps]\n'
        'AgentREPL = "c6b0b931-bd15-49f6-a31f-cf7d80eb5e81"\n'
        'CSV = "336ed68f-0bac-5ca0-87d4-7b16caf5d00b"\n'
        'Interpolations = "a98d9a8b-a2ab-59e6-89dd-64a1c18fca59"\n',
        encoding="utf-8",
    )

    assert sync_julia_env_with_template(_template_with_extra_deps, workspace=ws) == []


def test_sync_skipped_when_workspace_owns_project(
    tmp_path: Path, _template_with_extra_deps: Path
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "Project.toml").write_text("[deps]\n", encoding="utf-8")
    assert sync_julia_env_with_template(_template_with_extra_deps, workspace=ws) == []
