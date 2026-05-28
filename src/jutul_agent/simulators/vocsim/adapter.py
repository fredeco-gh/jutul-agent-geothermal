"""VOCSim adapter (placeholder — upstream package not yet released)."""

from __future__ import annotations

from pathlib import Path

from jutul_agent.simulators.base import SimulatorAdapter

VOCSIM = SimulatorAdapter(
    name="vocsim",
    display_name="VOCSim",
    module_dir=Path(__file__).resolve().parent,
    # `primary_package` points at the unreleased VOCSim package so auto-detect
    # only matches once it ships; `package_imports` lists what the agent is
    # actually safe to ``using`` today.
    package_imports=("Jutul",),
    primary_package="VOCSim",
    domain_hints=(
        "VOCSim is a Jutul-based simulator for methane and volatile "
        "organic-compound emissions during hydrocarbon storage and handling "
        "(VOCSimPRO project). The Julia package is not yet released, so the "
        "workspace env ships only Jutul; use this entry point to scaffold "
        "workspaces and exercise the generic Jutul surface until specialised "
        "workflows can be added."
    ),
)
