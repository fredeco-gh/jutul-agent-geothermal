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
    warmup_code=warmup_script(
        packages=(
            "Jutul",
            "JutulDarcy",
            "Fimbul",
            "CSV",
            "DataFrames",
            "Statistics",
            "Interpolations",
        ),
        native_plot_block=(
            "g = CartesianMesh((2, 2, 1), (1.0, 1.0, 1.0))\n"
            "dom = reservoir_domain(g, permeability = 1e-13, porosity = 0.2)\n"
            "fig, ax, plt = plot_cell_data(physical_representation(dom), dom[:porosity])\n"
            'save(joinpath(tempdir(), "jutul_agent_native_warmup.png"), fig)'
        ),
    ),
    domain_hints=(
        "Fimbul is a geothermal reservoir simulator built on top of JutulDarcy. "
        "It augments Darcy flow with an energy-conservation equation, "
        "transporting heat by advection and conduction. Typical workflow: a "
        "case factory (e.g. `egg_geothermal_doublet()`, `doublet_demo()`, "
        "`ates_demo()`) returns a `JutulCase` → `simulate_reservoir(case)` → "
        "inspect states (key field is `:Temperature`). Examples are mounted "
        "under `/packages/Fimbul/examples/` in three groups: "
        "`analytical/`, `production/` (doublet, EGS, AGS, coaxial BHE), and "
        "`storage/` (ATES, BTES, FTES, HTATES). Most workflows reuse "
        "JutulDarcy's grid + well constructors; its source is mounted at "
        "`/packages/JutulDarcy/` and the JutulDarcy skills/overview cover those "
        "primitives."
    ),
)
