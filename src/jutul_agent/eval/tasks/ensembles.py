"""Ensemble suite: the parallel-sweep workflow through ``run_ensemble``.

One sample per simulator. The sweep itself is trivial arithmetic on
purpose. The mechanism, not the math, is what is graded. Each sample
runs inside its simulator's workspace env, because ``run_ensemble`` ships
in the JutulAgent runtime package that only exists there, and worker
processes inherit that env. The real check is the trace: ``run_ensemble``
must appear in code the agent actually executed, so a serial fallback or a
textual claim cannot pass.
"""

from __future__ import annotations

from inspect_ai import Task, task
from inspect_ai.dataset import Sample

from jutul_agent.eval.scorers import (
    julia_code_matches,
    no_interpreters_via_execute,
    numeric_answer,
    numeric_close,
    used_tools,
)
from jutul_agent.eval.solver import jutul_agent_solver, load_eval_credentials

load_eval_credentials()

_SIMULATORS = ("jutuldarcy", "battmo", "fimbul", "mocca")

# Exact values: sum of squares 1..n is n(n+1)(2n+1)/6, so the targets are
# 385, 338350, 333833500, 333383335000 — deterministic and cheap.
_PROMPT = (
    "For each n in [10, 100, 1000, 10000], compute the sum of the "
    "squares of the integers 1 through n. Run the four cases as a "
    "parallel ensemble across 2 workers, and report the four results "
    "in order."
)


@task
def ensembles() -> Task:
    samples = [
        Sample(
            id=f"ens-{sim}-parallel-sweep",
            input=_PROMPT,
            metadata={"needs_env": True, "simulator": sim},
        )
        for sim in _SIMULATORS
    ]
    return Task(
        dataset=samples,
        solver=jutul_agent_solver(),
        scorer=[
            numeric_close(385, 0.5),
            numeric_close(338_350, 0.5),
            numeric_close(333_833_500, 0.5),
            numeric_close(333_383_335_000, 0.5),
            # Plain Distributed (addprocs + pmap) is the skill-endorsed manual
            # path; the contract is "parallel across workers", not one helper.
            julia_code_matches(r"(run_ensemble|pmap)\s*\("),
            used_tools(["julia_eval"]),
            no_interpreters_via_execute(),
        ],
        # Generous like the other needs_env suites: the first run per machine
        # pays the golden-env build inside this budget.
        time_limit=2400,
        token_limit=1_000_000,
        message_limit=40,
    )


# The reference case ships as a workspace fixture so the task measures the
# parallel-ensemble workflow, not waterflood construction. JutulDarcy has no
# canned parameterised waterflood (unlike the other sims' shipped factories),
# and an agent-built case puts recovery in an arbitrary range where the
# porosity trend need not hold; with the physics pinned in the fixture the
# goldens are enforceable. Captured agent-free through the run_ensemble worker
# path: 0.6692 / 0.5884 / 0.5259 / 0.4762 for porosity 0.15 / 0.20 / 0.25 /
# 0.30 (recovery falls as a larger pore volume is swept by the same volume).
_WATERFLOOD_CASE = """\
# Reference waterflood case: run_waterflood_case(porosity) -> oil recovery
# factor after 3 years of injection at 1000 m^3/day.
using JutulDarcy, Jutul

function run_waterflood_case(porosity::Real)
    Darcy, bar, kg, meter, day = si_units(:darcy, :bar, :kilogram, :meter, :day)
    g = CartesianMesh((20, 20, 5), (500.0, 500.0, 20.0))
    domain = reservoir_domain(g; permeability = 0.2 * Darcy, porosity = porosity)
    inj = setup_vertical_well(domain, 1, 1, name = :Injector)
    prd = setup_vertical_well(domain, 20, 20, name = :Producer)
    sys = ImmiscibleSystem((AqueousPhase(), LiquidPhase());
        reference_densities = [1000.0, 850.0] .* kg / meter^3)
    model, parameters = setup_reservoir_model(domain, sys; wells = [inj, prd], extra_out = true)
    parameters[:Reservoir][:PhaseViscosities][1, :] .= 1e-3   # water 1 cP
    parameters[:Reservoir][:PhaseViscosities][2, :] .= 5e-3   # oil 5 cP
    state0 = setup_reservoir_state(model, Pressure = 150 * bar, Saturations = [0.0, 1.0])
    dt = fill(30.0 * day, 36)
    I_ctrl = InjectorControl(TotalRateTarget(1000.0 * meter^3 / day), [1.0, 0.0],
        density = 1000.0 * kg / meter^3)
    P_ctrl = ProducerControl(BottomHolePressureTarget(100 * bar))
    forces = setup_reservoir_forces(model,
        control = Dict(:Injector => I_ctrl, :Producer => P_ctrl))
    wd, states, t = simulate_reservoir(state0, model, dt;
        parameters = parameters, forces = forces, info_level = -1)
    pv = pore_volume(model, parameters)
    so = states[end][:Saturations][2, :]
    return (sum(pv) - sum(pv .* so)) / sum(pv)
end
"""


@task
def ensembles_jutuldarcy() -> Task:
    sample = Sample(
        id="ens-jd-porosity-sweep",
        input=(
            "The workspace file waterflood_case.jl defines "
            "run_waterflood_case(porosity), which runs a fixed reference "
            "waterflood and returns its oil recovery factor. Using that "
            "function, run porosity = 0.15, 0.20, 0.25, 0.30 as a parallel "
            "ensemble across 4 workers, and report the four recovery factors "
            "in order of increasing porosity."
        ),
        metadata={
            "fixtures": {"waterflood_case.jl": _WATERFLOOD_CASE},
            "needs_env": True,
            "simulator": "jutuldarcy",
        },
    )
    return Task(
        dataset=[sample],
        solver=jutul_agent_solver(),
        scorer=[
            numeric_close(0.6692, 0.01),
            numeric_close(0.5884, 0.01),
            numeric_close(0.5259, 0.01),
            numeric_close(0.4762, 0.01),
            numeric_answer(0.0, 1.0, count=4, order="decreasing"),
            julia_code_matches(r"(run_ensemble|pmap)\s*\("),
            used_tools(["julia_eval"]),
            no_interpreters_via_execute(),
        ],
        time_limit=2400,
        token_limit=1_000_000,
        message_limit=60,
    )


@task
def ensembles_battmo() -> Task:
    # Same workflow on the battery side, kept structural: higher discharge
    # rate delivers less capacity, so the three values must decrease.
    sample = Sample(
        id="ens-bm-crate-sweep",
        input=(
            "Using BattMo, run constant-current discharges of the chen_2020 "
            "cell at C-rates 0.5, 1, and 2 (the protocol's DRate), as a "
            "parallel ensemble across 3 workers, each case returning only "
            "its discharged capacity in Ah. Report the three capacities in "
            "that order."
        ),
        metadata={"needs_env": True, "simulator": "battmo"},
    )
    return Task(
        dataset=[sample],
        solver=jutul_agent_solver(),
        scorer=[
            numeric_answer(0.0, 10.0, count=3, order="decreasing"),
            julia_code_matches(r"(run_ensemble|pmap)\s*\("),
            used_tools(["julia_eval"]),
            no_interpreters_via_execute(),
        ],
        time_limit=3000,
        token_limit=2_000_000,
        message_limit=100,
    )


@task
def ensembles_fimbul() -> Task:
    # The doublet is Fimbul's shipped geothermal_doublet factory, so the agent
    # drives it directly. Goldens captured agent-free from that same factory
    # call (num_years=100): produced-water temperature warms as the reinjection
    # temperature rises and the cold front reaches the producer.
    sample = Sample(
        id="ens-fb-injtemp-sweep",
        input=(
            "Using Fimbul, run its standard geothermal doublet — the "
            "geothermal_doublet factory — for 100 years, reinjecting at 10, "
            "20, 30, and 40 deg C (geothermal_doublet's temperature_inj is in "
            "SI, so convert from Celsius). Run the four cases as a parallel "
            "ensemble across 4 workers, and report the produced-water "
            "temperature (deg C) at the end of each, in order of increasing "
            "injection temperature."
        ),
        metadata={"needs_env": True, "simulator": "fimbul"},
    )
    return Task(
        dataset=[sample],
        solver=jutul_agent_solver(),
        scorer=[
            numeric_close(67.223, 0.5),
            numeric_close(67.908, 0.5),
            numeric_close(69.104, 0.5),
            numeric_close(70.81, 0.5),
            numeric_answer(1.0, 250.0, count=4, order="increasing"),
            julia_code_matches(r"(run_ensemble|pmap)\s*\("),
            used_tools(["julia_eval"]),
            no_interpreters_via_execute(),
        ],
        time_limit=3000,
        token_limit=1_500_000,
        message_limit=80,
    )


@task
def ensembles_mocca() -> Task:
    # CO2-capture side. No captured reference for how the feed-end mole
    # fraction moves with cycle count, so the answer check is plausibility
    # (mole fractions) and the substance is the parallel trace check.
    sample = Sample(
        id="ens-mc-cycles-sweep",
        input=(
            "Using Mocca, run the cyclic VSA CO2-capture example that ships "
            "with the package (the Haghpanah setup) for 1, 2, and 3 cycles, "
            "as a parallel ensemble across 3 workers, each case returning "
            "only the CO2 gas mole fraction at the feed end of the column "
            "in its final state. Report the three mole fractions in order "
            "of increasing cycle count."
        ),
        metadata={"needs_env": True, "simulator": "mocca"},
    )
    return Task(
        dataset=[sample],
        solver=jutul_agent_solver(),
        scorer=[
            numeric_answer(0.0, 1.0, count=3),
            julia_code_matches(r"(run_ensemble|pmap)\s*\("),
            used_tools(["julia_eval"]),
            no_interpreters_via_execute(),
        ],
        time_limit=3000,
        token_limit=2_000_000,
        message_limit=100,
    )


TASKS = [
    ensembles,
    ensembles_jutuldarcy,
    ensembles_battmo,
    ensembles_fimbul,
    ensembles_mocca,
]
