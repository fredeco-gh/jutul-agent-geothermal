"""Tests for runtime prompt helpers, Deep Agents assets, and simulator registry."""

from __future__ import annotations

from pathlib import Path

from deepagents.backends import CompositeBackend, FilesystemBackend, LocalShellBackend

from fakes import make_fake_adapter
from jutul_agent.agent.builder import build_backend, skill_sources
from jutul_agent.agent.prompts import assemble_session_prompt
from jutul_agent.paths import SHARED_SKILLS_DIR
from jutul_agent.simulators import registry
from jutul_agent.simulators.base import SimulatorAdapter


def test_registry_lists_known_simulators() -> None:
    assert "jutuldarcy" in registry.names()
    assert "battmo" in registry.names()
    assert "fimbul" in registry.names()
    assert "mocca" in registry.names()


def test_assemble_session_prompt_includes_runtime_context(tmp_path: Path) -> None:
    adapter = SimulatorAdapter(
        name="testsim",
        display_name="TestSim",
        module_dir=tmp_path,
        package_imports=("Jutul", "TestSim"),
        primary_package="TestSim",
        domain_hints="use the runtime and inspect installed packages",
    )

    prompt = assemble_session_prompt(adapter)

    assert "TestSim" in prompt
    assert "Jutul, TestSim" in prompt
    assert "inspect installed packages" in prompt
    assert "julia_eval" in prompt
    assert "write_file" in prompt
    assert "workspace" in prompt
    # Source mounts are named by package and lead with the primary.
    assert "/packages/TestSim/" in prompt
    # Retry guidance lives in HarnessProfile suffix, not the static prompt.
    assert "retry before responding" not in prompt


def test_build_backend_mounts_workspace_and_skills(tmp_path: Path) -> None:
    adapter = make_fake_adapter(tmp_path)

    backend = build_backend(adapter, workspace=tmp_path)

    assert isinstance(backend, CompositeBackend)
    assert isinstance(backend.default, LocalShellBackend)
    assert set(backend.routes) == {"/skills/shared/", "/skills/simulator/"}
    assert isinstance(backend.routes["/skills/shared/"], FilesystemBackend)
    assert isinstance(backend.routes["/skills/simulator/"], FilesystemBackend)
    assert skill_sources(adapter) == [
        ("/skills/shared/", "Built-in"),
        ("/skills/simulator/", adapter.display_name),
    ]


def test_repo_deepagents_skill_assets_exist() -> None:
    assert SHARED_SKILLS_DIR.joinpath("julia-and-repl", "SKILL.md").exists()
    assert SHARED_SKILLS_DIR.joinpath("workspace-and-source", "SKILL.md").exists()
    assert SHARED_SKILLS_DIR.joinpath("plotting-basics", "SKILL.md").exists()
    expected = [
        ("jutuldarcy", "jutuldarcy-overview"),
        ("jutuldarcy", "jutuldarcy-wells"),
        ("battmo", "battmo-overview"),
        ("battmo", "battmo-cycling"),
        ("fimbul", "fimbul-overview"),
        ("mocca", "mocca-overview"),
    ]
    for sim, skill in expected:
        assert registry.get(sim).skills_dir.joinpath(skill, "SKILL.md").exists()


def test_real_adapters_produce_nonempty_session_prompt() -> None:
    for name in registry.names():
        adapter = registry.get(name)
        prompt = assemble_session_prompt(adapter)
        assert adapter.display_name in prompt
        assert adapter.name in prompt


def test_every_simulator_has_env_template_and_overview_skill() -> None:
    for name in registry.names():
        adapter = registry.get(name)
        template = adapter.julia_env_template_path / "Project.toml"
        assert template.exists(), f"missing env template for {name}: {template}"
        overview = adapter.skills_dir / f"{name}-overview" / "SKILL.md"
        assert overview.exists(), f"missing overview skill for {name}: {overview}"

