"""Simulator registry: discovers adapters from the simulator packages.

Each simulator is a subpackage under ``jutul_agent.simulators`` with an
``adapter.py`` that defines a module-level :class:`SimulatorAdapter`. The
registry imports each subpackage and collects those adapters, so adding a
simulator is just adding its folder; this file does not need editing.
"""

from __future__ import annotations

import importlib
import pkgutil
from functools import cache

from jutul_agent.simulators.base import SimulatorAdapter

# Subpackages under ``simulators`` that are not simulators themselves.
_NOT_SIMULATORS = frozenset({"shared_skills"})


def _adapter_in(module: object) -> SimulatorAdapter | None:
    return next(
        (value for value in vars(module).values() if isinstance(value, SimulatorAdapter)),
        None,
    )


@cache
def _registry() -> dict[str, SimulatorAdapter]:
    """Import every simulator subpackage and collect its adapter (cached)."""
    import jutul_agent.simulators as simulators_pkg

    found: dict[str, SimulatorAdapter] = {}
    for info in pkgutil.iter_modules(simulators_pkg.__path__):
        if not info.ispkg or info.name.startswith("_") or info.name in _NOT_SIMULATORS:
            continue
        qualified = f"{simulators_pkg.__name__}.{info.name}"
        module = importlib.import_module(qualified)
        # Prefer the adapter the subpackage exports; fall back to its adapter.py
        # so a folder with only an adapter.py is enough.
        adapter = _adapter_in(module)
        if adapter is None:
            try:
                adapter = _adapter_in(importlib.import_module(f"{qualified}.adapter"))
            except ModuleNotFoundError:
                adapter = None
        if adapter is not None:
            found[adapter.name] = adapter
    return found


def names() -> list[str]:
    return sorted(_registry())


def get(name: str) -> SimulatorAdapter:
    try:
        return _registry()[name]
    except KeyError as exc:
        raise KeyError(f"unknown simulator {name!r}; known: {', '.join(names())}") from exc
