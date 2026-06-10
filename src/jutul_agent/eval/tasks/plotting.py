"""Plotting suite: a figure must actually exist, not just be described.

Needs the simulator environment (Makie) and a display, so the solver
instantiates the workspace env and starts a virtual display on headless
Linux. First run on a cold Julia depot is slow; later runs reuse the
shared precompile cache.
"""

from __future__ import annotations

from inspect_ai import Task, task
from inspect_ai.dataset import Sample

from jutul_agent.eval.scorers import artifact_produced, used_tools
from jutul_agent.eval.solver import jutul_agent_solver, load_eval_credentials

load_eval_credentials()


@task
def plotting() -> Task:
    sample = Sample(
        id="x5-headless-plot",
        input=(
            "Plot sin(x) for x in [0, 2pi] and save it as a PNG in the "
            "workspace. Reply with the file path."
        ),
        metadata={"needs_env": True, "needs_display": True},
    )
    return Task(
        dataset=[sample],
        solver=jutul_agent_solver(),
        scorer=[used_tools(["julia_plot"]), artifact_produced(".png")],
        time_limit=1800,
        token_limit=2_000_000,
        message_limit=50,
    )
