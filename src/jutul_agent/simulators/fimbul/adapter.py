"""Fimbul adapter."""

from __future__ import annotations

from pathlib import Path

from jutul_agent.simulators.base import SimulatorAdapter
from jutul_agent.simulators.warmup import warmup_script

FIMBUL = SimulatorAdapter(
    name="fimbul",
    display_name="Fimbul",
    module_dir=Path(__file__).resolve().parent,
    package_imports=("Jutul", "JutulDarcy", "Fimbul"),
    primary_package="Fimbul",
    warmup_code="using Jutul, JutulDarcy, Fimbul, CSV, DataFrames, Statistics, Interpolations",
    domain_hints=(
        "Fimbul is a geothermal reservoir simulator built on top of JutulDarcy. "
        "It augments Darcy flow with an energy-conservation equation, "
        "transporting heat by advection and conduction. Typical workflow: a "
        "case factory (e.g. `egg_geothermal_doublet()`, `doublet_demo()`, "
        "`ates_demo()`) returns a `JutulCase` → `simulate_reservoir(case)` → "
        "inspect states (key field is `:Temperature`). Examples on disk live "
        'under `joinpath(pkgdir(Fimbul), "examples")` in three groups: '
        "`analytical/`, `production/` (doublet, EGS, AGS, coaxial BHE), and "
        "`storage/` (ATES, BTES, FTES, HTATES). Most workflows reuse "
        "JutulDarcy's grid + well constructors; consult the JutulDarcy "
        "skills/overview for those primitives."
    ),
)
