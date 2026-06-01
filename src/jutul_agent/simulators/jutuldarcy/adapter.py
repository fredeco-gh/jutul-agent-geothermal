"""JutulDarcy adapter."""

from __future__ import annotations

from pathlib import Path

from jutul_agent.simulators.base import SimulatorAdapter
from jutul_agent.simulators.warmup import warmup_script

JUTULDARCY = SimulatorAdapter(
    name="jutuldarcy",
    display_name="JutulDarcy",
    module_dir=Path(__file__).resolve().parent,
    package_imports=("Jutul", "JutulDarcy"),
    primary_package="JutulDarcy",
    warmup_code=warmup_script(
        packages=("Jutul", "JutulDarcy", "CSV", "DataFrames", "Statistics", "Interpolations"),
    ),
    domain_hints=(
        "JutulDarcy is a fully-differentiable porous-media reservoir simulator "
        "built on the Jutul framework. Core concepts: `CartesianMesh` or unstructured "
        "grid → `reservoir_domain(g; permeability, porosity)` → wells "
        "(`setup_vertical_well`, `setup_well`) → fluid system (`ImmiscibleSystem`, "
        "`BlackOilSystem`, `CompositionalSystem`) → `setup_reservoir_model(domain, "
        "sys; wells=...)` → initial state + controls + forces → `simulate_reservoir`. "
        "Units come from `si_units(:darcy, :bar, :day, ...)`. Examples are mounted "
        "at `/packages/JutulDarcy/examples/` — `wells_intro.jl`, "
        "`intro_example.jl`, `compositional_5components.jl`, `data_input_file.jl`."
    ),
)
