"""Tests for session-prompt assembly."""

from __future__ import annotations

from pathlib import Path

from jutul_agent.agent.prompts import assemble_session_prompt
from jutul_agent.simulators.base import SimulatorAdapter


def _adapter(tmp_path: Path) -> SimulatorAdapter:
    return SimulatorAdapter(
        name="test",
        display_name="Test",
        module_dir=tmp_path,
        package_imports=("Foo",),
        primary_package="Foo",
        domain_hints="",
    )


def test_prompt_is_native_first(tmp_path: Path) -> None:
    p = assemble_session_prompt(_adapter(tmp_path))
    assert "native plotters" in p
    assert "view=true" in p
    # The old return-a-Figure contract is gone.
    assert "must return a Makie" not in p
    assert "Code must return" not in p
    # The general prompt stays simulator-agnostic: no hardcoded plotter names.
    assert "plot_reservoir" not in p
    assert "plot_well_results" not in p


def test_prompt_describes_glmakie_window_behavior(tmp_path: Path) -> None:
    p = assemble_session_prompt(_adapter(tmp_path))
    assert "GLMakie" in p
    assert "live window" in p
