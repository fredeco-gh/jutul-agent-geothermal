"""Contract tests for per-simulator plot_helpers_path wiring."""

from __future__ import annotations

from jutul_agent.simulators.battmo import BATTMO
from jutul_agent.simulators.fimbul import FIMBUL
from jutul_agent.simulators.jutuldarcy import JUTULDARCY
from jutul_agent.simulators.mocca import MOCCA


def test_battmo_and_mocca_have_no_plot_helpers() -> None:
    assert BATTMO.plot_helpers_path is None
    assert MOCCA.plot_helpers_path is None


def test_jutuldarcy_and_fimbul_plot_helpers_exist() -> None:
    for adapter in (JUTULDARCY, FIMBUL):
        path = adapter.plot_helpers_path
        assert path is not None
        assert path == adapter.julia_env_template_path / "plots.jl"
        assert path.is_file()
