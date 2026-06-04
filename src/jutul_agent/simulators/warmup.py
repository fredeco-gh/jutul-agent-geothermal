"""Builders for per-simulator REPL warm-up code.

Warm-up runs once in the background at session start, in the same persistent
Julia worker the agent uses, while the user is still reading the welcome card and
typing. Its job is to pay the compilation cost of the paths the agent hits first
so the first real julia_eval / julia_plot is fast.

A bare ``using <pkg>`` only compiles package load. It leaves the two slowest
first-call paths cold: the solver (``solve`` / ``simulate_reservoir``) and the
GLMakie render-and-save path behind julia_plot. So a good warm-up also runs a
tiny solve and saves a throwaway figure.

Order matters. Load all packages, including GLMakie, before the solve. Loading a
package adds methods that can invalidate already-compiled code; warming the solve
and only then loading GLMakie invalidates the solve's specializations, so the
agent's first real solve recompiles from scratch. Packages first, then solve,
then the plot save.

Every stage is wrapped in try/catch so an API drift in one stage (or a missing
optional package) never blocks the others, and the whole thing is best-effort:
run.py swallows failures and cancels the task on teardown.
"""

from __future__ import annotations

import textwrap

# Warm GLMakie's offscreen render+save, the expensive first-plot path for the
# native 3D plotters. A tiny Axis3 surface compiles the pipeline. Best-effort: if
# GLMakie isn't usable here (no GL, no xvfb) the try/catch swallows it.
_PLOT_SAVE = """try
    let
        GLMakie.activate!(visible = false)
        fig = Figure(size = (96, 96))
        ax = Axis3(fig[1, 1])
        surface!(ax, 1:4, 1:4, [Float64(i + j) for i in 1:4, j in 1:4])
        save(joinpath(tempdir(), "jutul_agent_gl_warmup.png"), fig)
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
    native_plot_block: str = "",
) -> str:
    """Assemble a best-effort warm-up script.

    Args:
        packages: Packages to ``using`` (primary package first). GLMakie is
            appended automatically when ``warm_plotting`` is set, before the solve
            so its method additions can't invalidate the warmed solve.
        solve_block: Optional Julia that runs the smallest possible solve, to
            compile the solver path. Wrapped in try/catch and a ``let`` so it
            cannot pollute the agent's global namespace.
        warm_plotting: Load GLMakie and warm its offscreen render+save path.
        native_plot_block: Optional simulator-specific Julia that calls a native
            3D plotter (e.g. ``plot_cell_data`` on a tiny domain) so its first-call
            compilation, the biggest interactive-plot cost, is paid during warm-up.
            Runs under GLMakie offscreen, wrapped in its own ``try``.
    """

    using_packages = list(packages)
    if warm_plotting:
        using_packages.append("GLMakie")

    stages = [_try("using " + ", ".join(using_packages))]
    if solve_block.strip():
        stages.append(_try("let\n" + textwrap.indent(solve_block.strip("\n"), "    ") + "\nend"))
    if warm_plotting:
        stages.append(_PLOT_SAVE)
        if native_plot_block.strip():
            stages.append(
                _try("let\n" + textwrap.indent(native_plot_block.strip("\n"), "    ") + "\nend")
            )
    return "\n".join(stages) + "\n"
