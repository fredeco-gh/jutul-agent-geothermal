"""Calibration suite: an iterative investigation, graded on the recorded process.

No simulator environment is needed: the agent fits a two-parameter model
to workspace data through the Julia session. The scorers read the
``attempt`` events in the trace, so a correct answer with an unrecorded
process still fails.
"""

from __future__ import annotations

from inspect_ai import Task, task
from inspect_ai.dataset import Sample

from jutul_agent.eval.scorers import (
    investigation_recorded,
    no_interpreters_via_execute,
    numeric_close,
    used_tools,
)
from jutul_agent.eval.solver import jutul_agent_solver, load_eval_credentials

load_eval_credentials()

# Generated from y = 2.5 * exp(-0.7 t) plus Gaussian noise (sigma 0.01,
# fixed seed); least squares on these exact points recovers a = 2.4975,
# b = 0.6983 with rmse 0.0063.
_DATA = """t,y
0.0,2.49856
0.1,2.32926
0.2,2.17228
0.3,2.03348
0.4,1.88818
0.5,1.74675
0.6,1.64594
0.7,1.52889
0.8,1.42585
0.9,1.33264
1.0,1.24379
1.1,1.16917
1.2,1.08584
1.3,1.00742
1.4,0.93089
1.5,0.8647
1.6,0.81816
1.7,0.77366
1.8,0.70955
1.9,0.66013
2.0,0.62181
"""


@task
def calibration() -> Task:
    sample = Sample(
        id="cal1-exp-decay-fit",
        input=(
            "The workspace file data.csv holds measurements with columns t "
            "and y, generated from y = a*exp(-b*t) plus a little noise. "
            "Calibrate a and b against the data, iterating in the Julia "
            "session until the fit is good; for this data a good fit "
            "reaches an rmse below 0.01. Record every configuration you "
            "actually evaluate with the record_attempt tool, including an "
            "rmse metric, linking follow-up attempts to their parent, and "
            "finish with write_report. Then report the calibrated a and b."
        ),
        metadata={"fixtures": {"data.csv": _DATA}},
    )
    return Task(
        dataset=[sample],
        solver=jutul_agent_solver(),
        scorer=[
            numeric_close(2.50, 0.05),
            numeric_close(0.70, 0.03),
            investigation_recorded(min_attempts=3, metric="rmse"),
            used_tools(["julia_eval", "record_attempt", "write_report"]),
            no_interpreters_via_execute(),
        ],
        time_limit=1200,
        token_limit=500_000,
        message_limit=60,
    )
