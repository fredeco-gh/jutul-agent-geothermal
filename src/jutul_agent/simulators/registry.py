"""Simulator registry: name → adapter."""

from __future__ import annotations

from jutul_agent.simulators.base import SimulatorAdapter
from jutul_agent.simulators.battmo import BATTMO
from jutul_agent.simulators.fimbul import FIMBUL
from jutul_agent.simulators.jutuldarcy import JUTULDARCY
from jutul_agent.simulators.mocca import MOCCA

_REGISTRY: dict[str, SimulatorAdapter] = {
    JUTULDARCY.name: JUTULDARCY,
    BATTMO.name: BATTMO,
    FIMBUL.name: FIMBUL,
    MOCCA.name: MOCCA,
}


def names() -> list[str]:
    return sorted(_REGISTRY)


def get(name: str) -> SimulatorAdapter:
    try:
        return _REGISTRY[name]
    except KeyError as exc:
        raise KeyError(f"unknown simulator {name!r}; known: {', '.join(names())}") from exc
