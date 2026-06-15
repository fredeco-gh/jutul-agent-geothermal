"""Plotting suite: a figure must actually exist, not just be described.

Needs the simulator environment (Makie) and a display, so the solver
instantiates the workspace env and starts a virtual display on headless
Linux. First run on a cold Julia depot is slow; later runs reuse the
shared precompile cache.
"""

from __future__ import annotations

from inspect_ai import Task, task
from inspect_ai.dataset import Sample

from jutul_agent.eval.scorers import (
    artifact_produced,
    no_interpreters_via_execute,
    reads_word,
    tool_call_matches,
    used_tools,
)
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


# A word rendered as scatter points: a 5-wide, 7-tall bitmap per letter, emitted
# as (x, y). The word is legible only once the points are plotted — the raw
# coordinates do not reveal it — so the task cannot be answered by reading the
# data, only by reading the agent's own plot. A self-contained bitmap font keeps
# the fixture deterministic, with no dependency on a system font that could
# render differently or drift.
_FONT = {
    "S": [".XXX.", "X...X", "X....", ".XXX.", "....X", "X...X", ".XXX."],
    "I": ["XXXXX", "..X..", "..X..", "..X..", "..X..", "..X..", "XXXXX"],
    "N": ["X...X", "XX..X", "X.X.X", "X.X.X", "X..XX", "X...X", "X...X"],
    "T": ["XXXXX", "..X..", "..X..", "..X..", "..X..", "..X..", "..X.."],
    "E": ["XXXXX", "X....", "X....", "XXXX.", "X....", "X....", "XXXXX"],
    "F": ["XXXXX", "X....", "X....", "XXXX.", "X....", "X....", "X...."],
}
_WORD = "SINTEF"


def _word_csv(word: str) -> str:
    """``x,y`` rows whose scatter spells ``word``.

    Each lit cell of the bitmap is filled with a small grid of points so the
    strokes read as solid letters in a scatter, not as ambiguous sparse dots
    (the top font row is plotted at the high y).
    """
    fill = 6  # points per cell edge: dense enough that the strokes stay solid
    # even when the agent plots with small markers
    gap = 3  # blank columns between letters, so neighbours stay separate
    yscale = 2  # taller letters -> a less extreme aspect, legible even when the
    # agent's plot is not perfectly aspect-corrected
    rows = ["x,y"]
    for i, char in enumerate(word):
        for r, line in enumerate(_FONT[char]):
            for c, cell in enumerate(line):
                if cell != "X":
                    continue
                for a in range(fill):
                    for b in range(fill * yscale):
                        rows.append(
                            f"{i * (5 + gap) + c + a / fill:.3f},{(6 - r) * yscale + b / fill:.3f}"
                        )
    return "\n".join(rows) + "\n"


_POINTS_CSV = _word_csv(_WORD)


@task
def plotting_vision() -> Task:
    # A genuine vision check: the points spell a word that is legible only in
    # the rendered scatter, not in the raw coordinates, so the agent has to plot
    # the data and read its own plot (view=true is scored from the trace) rather
    # than mine the answer out of the numbers.
    sample = Sample(
        id="x6-read-the-plot",
        input=(
            "The workspace file points.csv has columns x and y. The points are "
            "dense and span a region much wider than it is tall. Scatter-plot y "
            "against x with an equal aspect ratio, in a figure wide enough to "
            "show the full width clearly, using markers large enough that the "
            "letters read as solid shapes rather than sparse dots. Then look at "
            "your own plot: the points spell out a single word in block "
            "capitals. Report that word."
        ),
        metadata={
            "fixtures": {"points.csv": _POINTS_CSV},
            "needs_env": True,
            "needs_display": True,
        },
    )
    return Task(
        dataset=[sample],
        solver=jutul_agent_solver(),
        scorer=[
            reads_word(_WORD),
            tool_call_matches("julia_plot", r'"view":\s*true'),
            artifact_produced(".png"),
            no_interpreters_via_execute(),
        ],
        time_limit=1800,
        token_limit=2_000_000,
        message_limit=50,
    )


TASKS = [plotting, plotting_vision]
