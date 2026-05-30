"""Mocca adapter."""

from __future__ import annotations

from pathlib import Path

from jutul_agent.simulators.base import SimulatorAdapter
from jutul_agent.simulators.warmup import warmup_script

MOCCA = SimulatorAdapter(
    name="mocca",
    display_name="Mocca",
    module_dir=Path(__file__).resolve().parent,
    package_imports=("Jutul", "Mocca"),
    primary_package="Mocca",
    warmup_code=warmup_script(
        packages=("Jutul", "Mocca", "CSV", "DataFrames", "Statistics", "Interpolations"),
    ),
    domain_hints=(
        "Mocca (MOdelling for Carbon Capture) simulates adsorption-based "
        "CO2 capture processes (pressure / temperature / vacuum swing "
        "adsorption) on the Jutul AD framework. Typical workflow: "
        "`Mocca.parse_input(json_filepath)` → `(constants, info)` → "
        "`Mocca.setup_mocca_case(constants, info)` → `(case, ts_config)` → "
        "`Mocca.simulate_process(case; timestep_selector_cfg=ts_config, "
        "output_substates=true)`. Built-in plotting: `Mocca.plot_outlet"
        "(case, states, timesteps)`. Examples are mounted under "
        "`/simulator/examples/` — `dcb_haghpanah_2013_co2_n2.jl` "
        "(direct column breakthrough), `cyclic_vsa_haghpanah_2013_co2_n2.jl` "
        "(4-stage VSA), `custom_setup_cyclic_vsa.jl`, plus `optimization.jl` "
        "and `history_matching.jl`. Reference JSON inputs ship beside the "
        'package at `joinpath(pkgdir(Mocca), "..", "models", "json")` '
        "(outside `/simulator/`; read via the REPL)."
    ),
)
