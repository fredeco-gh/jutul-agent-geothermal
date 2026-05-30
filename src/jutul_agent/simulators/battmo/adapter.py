"""BattMo adapter."""

from __future__ import annotations

from pathlib import Path

from jutul_agent.simulators.base import SimulatorAdapter
from jutul_agent.simulators.warmup import warmup_script

# Smallest meaningful BattMo run: the shipped default cell + a constant-current
# discharge. Mirrors the battmo-overview skill so warm-up compiles exactly the
# methods the agent reaches for first.
_BATTMO_SOLVE = """
cell = load_cell_parameters(; from_default_set = "chen_2020")
protocol = load_cycling_protocol(; from_default_set = "cc_discharge")
sim = Simulation(LithiumIonBattery(), cell, protocol)
solve(sim; info_level = -1)
"""

BATTMO = SimulatorAdapter(
    name="battmo",
    display_name="BattMo",
    module_dir=Path(__file__).resolve().parent,
    package_imports=("Jutul", "BattMo"),
    primary_package="BattMo",
    warmup_code=warmup_script(
        packages=("BattMo", "CSV", "DataFrames", "Statistics", "Interpolations"),
        solve_block=_BATTMO_SOLVE,
    ),
    domain_hints=(
        "BattMo is a Jutul-framework battery simulator (lithium-ion and other "
        "chemistries, coupled electrochemistry / transport / optionally thermal). "
        "Workflow: `load_cell_parameters(; from_default_set=...)` → "
        "`load_cycling_protocol(; from_default_set=...)` → `LithiumIonBattery()` "
        "→ `Simulation(model, cell_parameters, cycling_protocol)` → `solve(sim)`. "
        "Beginner walkthroughs live in `examples/beginner_tutorials/` "
        "(numbered 1-11)."
    ),
)
