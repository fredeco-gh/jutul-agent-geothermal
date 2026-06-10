"""JutulDarcy suite: seed tasks for the reservoir-simulation workflows.

These instantiate the JutulDarcy workspace environment (``needs_env``), so
the first run on a cold depot takes minutes. Checks are structural
properties that must hold for any correct run; until golden references
captured from trusted baseline runs are added alongside.
"""

from __future__ import annotations

from inspect_ai import Task, task
from inspect_ai.dataset import Sample

from jutul_agent.eval.scorers import (
    no_interpreters_via_execute,
    no_repeated_identical_calls,
    numeric_answer,
    used_tools,
)
from jutul_agent.eval.solver import jutul_agent_solver, load_eval_credentials

load_eval_credentials()


@task
def jutuldarcy() -> Task:
    samples = [
        # Recall-and-run: a small simulation the skills cover directly.
        # The answer check is structural (a recovery factor is a fraction);
        # a golden value belongs here once captured on a trusted baseline.
        Sample(
            id="jd1-gravity-segregation",
            input=(
                "Using JutulDarcy, set up and run a small two-phase gravity "
                "segregation case (a vertical 1x1x20 column, water over gas). "
                "Report the final water saturation range across the column as "
                "two numbers between 0 and 1."
            ),
            metadata={"needs_env": True},
        ),
    ]
    return Task(
        dataset=samples,
        solver=jutul_agent_solver(simulator="jutuldarcy"),
        scorer=[
            # A saturation is a fraction; goldens replace this once captured.
            numeric_answer(0.0, 1.0, count=2),
            used_tools(["julia_eval"]),
            no_interpreters_via_execute(),
        ],
        time_limit=2400,
        token_limit=2_000_000,
        message_limit=80,
    )


@task
def jutuldarcy_rate_change() -> Task:
    # Compose-and-compare: run, change one knob, rerun, compare. Halving injection
    # lowers the final average pressure, so base-then-halved must decrease.
    # The unit in the prompt is bar while Jutul works in Pa: reporting an
    # unconverted value lands far outside the plausible range and fails.
    sample = Sample(
        id="jd3-halved-injection",
        input=(
            "Using JutulDarcy, set up a small two-phase water-injection case "
            "(a simple grid of your choice with one injector and one "
            "producer), run it, then rerun the same case with the injection "
            "rate halved. Report the average reservoir pressure at the end "
            "of each run, in bar: base case first, then halved."
        ),
        metadata={"needs_env": True},
    )
    return Task(
        dataset=[sample],
        solver=jutul_agent_solver(simulator="jutuldarcy"),
        scorer=[
            numeric_answer(1.0, 1000.0, count=2, order="decreasing"),
            used_tools(["julia_eval"]),
            no_interpreters_via_execute(),
            no_repeated_identical_calls(),
        ],
        time_limit=3000,
        token_limit=2_000_000,
        message_limit=100,
    )


TASKS = [jutuldarcy, jutuldarcy_rate_change]
