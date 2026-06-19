"""The simulator registry auto-discovers adapters from the package folders."""

from __future__ import annotations

import pytest

from jutul_agent.simulators import registry
from jutul_agent.simulators.base import SimulatorAdapter


def test_known_simulators_are_discovered() -> None:
    names = registry.names()
    for expected in ("jutuldarcy", "battmo", "fimbul", "mocca"):
        assert expected in names


def test_get_returns_the_adapter() -> None:
    adapter = registry.get("jutuldarcy")
    assert isinstance(adapter, SimulatorAdapter)
    assert adapter.name == "jutuldarcy"


def test_names_are_sorted() -> None:
    assert registry.names() == sorted(registry.names())


def test_unknown_simulator_raises() -> None:
    with pytest.raises(KeyError):
        registry.get("does-not-exist")
