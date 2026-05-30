"""Builders for per-simulator REPL warm-up code.

Warm-up runs once in the background at session start, in the same persistent
Julia worker the agent uses, while the user is still reading the welcome card
and typing. Its job is to pay the *compilation* cost of the paths the agent
hits first so the first real ``julia_eval`` / ``julia_plot`` is fast.

A bare ``using <pkg>`` only compiles package load — it leaves the two slowest
first-call paths cold: the solver (``solve`` / ``simulate_reservoir``) and the
Makie render-and-save path behind ``julia_plot``. So a good warm-up also runs a
tiny solve and saves a throwaway CairoMakie figure.

**Order matters.** Load *all* packages — including CairoMakie — *before* the
solve. Loading a package adds methods that can invalidate already-compiled
code; warming the solve and only then ``using CairoMakie`` invalidates the
solve's specializations, so the agent's first real solve recompiles from
scratch (measured: 35 s vs 0.6 s). Packages first, then solve, then the plot
save (CairoMakie is already loaded by then).

Every stage is wrapped in ``try/catch`` so an API drift in one stage (or a
missing optional package) never blocks the others, and the whole thing is
best-effort — ``run.py`` swallows failures and cancels the task on teardown.
"""

from __future__ import annotations

import textwrap

# Figure + save only — CairoMakie is loaded up front with the other packages so
# it can't invalidate the warmed solve. Compiling this save path is the single
# biggest first-plot cost and is identical across simulators.
_PLOT_SAVE = """try
    let
        fig = Figure(size = (96, 96))
        lines!(Axis(fig[1, 1]), 1:3, [1.0, 2.0, 1.5])
        CairoMakie.save(joinpath(tempdir(), "jutul_agent_warmup.png"), fig)
    end
catch
end"""


def _try(block: str) -> str:
    return "try\n" + textwrap.indent(block.strip("\n"), "    ") + "\ncatch\nend"


def warmup_script(
    *,
    packages: tuple[str, ...],
    solve_block: str = "",
    warm_plotting: bool = True,
) -> str:
    """Assemble a best-effort warm-up script.

    Args:
        packages: Packages to ``using`` (primary package first). CairoMakie is
            appended automatically when ``warm_plotting`` is set.
        solve_block: Optional Julia that runs the smallest possible solve, to
            compile the solver path. Wrapped in ``try/catch`` and a ``let`` so
            it cannot pollute the agent's global namespace.
        warm_plotting: Load CairoMakie (before the solve) and warm the figure
            save path.
    """

    using_packages = list(packages)
    if warm_plotting:
        # Load CairoMakie *with* the rest, before the solve, so its method
        # additions don't invalidate the solve's compiled code afterwards.
        using_packages.append("CairoMakie")

    stages = [_try("using " + ", ".join(using_packages))]
    if solve_block.strip():
        stages.append(_try("let\n" + textwrap.indent(solve_block.strip("\n"), "    ") + "\nend"))
    if warm_plotting:
        stages.append(_PLOT_SAVE)
    return "\n".join(stages) + "\n"
