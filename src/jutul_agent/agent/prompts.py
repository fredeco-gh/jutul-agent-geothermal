"""Build the per-session system prompt.

The system prompt is split across three layers:

- This module emits the **simulator-bound** prefix (active simulator,
  primary packages, the tool guide, and any simulator-specific hints).
  Everything here is deterministic from the ``SimulatorAdapter``.
- Deep Agents inserts its built-in **BASE** prompt next.
- ``agent/builder.register_provider_profiles`` appends a provider-specific
  ``system_prompt_suffix`` (closest to the conversation). Model-tuning
  guidance (e.g. retry-on-error, prefer-tool-use nudges) lives there, not
  here.
"""

from __future__ import annotations

from jutul_agent.simulators.base import SimulatorAdapter


def assemble_session_prompt(adapter: SimulatorAdapter, *, open_windows: bool = True) -> str:
    sections = [
        f"Active simulator: {adapter.display_name} ({adapter.name}).",
        "Primary Julia packages: " + ", ".join(adapter.package_imports) + ".",
        _tool_guide(adapter),
        _display_note(open_windows),
    ]
    hints = adapter.domain_hints.strip()
    if hints:
        sections.append("Simulator hints:\n" + hints)
    return "\n\n".join(sections) + "\n"


def _display_note(open_windows: bool) -> str:
    """Tell the agent, for *this* session, whether a live plot window can appear.

    Without it the agent can't know it's headless and will wrongly tell the user a
    window opened (e.g. after a native ``plot_well_results`` call). When no window
    can show, steer it to ``julia_plot`` — which still renders a PNG — and away from
    claiming interactivity the user can't see.
    """

    if open_windows:
        return (
            "Display: live plot windows are available this session. `julia_plot` "
            "opens an interactive Makie window the user can rotate/zoom/step, and "
            "also saves a PNG."
        )
    return (
        "Display: this session is HEADLESS — no on-screen window can appear. "
        "`julia_plot` still renders and saves a PNG (the user sees it in the "
        "transcript/report), so use it for every figure. Native interactive viewers "
        "(`plot_well_results`, `plot_reservoir`, `plot_cell_data`, …) called in "
        "`julia_eval` draw to an offscreen virtual display the user cannot see — "
        "wrap such results in `julia_plot` instead. Never tell the user a window "
        "opened or that they can rotate/zoom/interact with a plot; they can't."
    )


def _package_mounts(adapter: SimulatorAdapter) -> str:
    """The ``/packages/<Package>/`` routes the agent can browse, named explicitly.

    Lists every package in ``package_imports`` (when its source resolves it is
    mounted read-only), leading with the primary so the agent knows where the
    simulator's own examples live.
    """

    ordered = [adapter.primary_package, *adapter.package_imports]
    seen: list[str] = []
    for pkg in ordered:
        if pkg in adapter.package_imports and pkg not in seen:
            seen.append(pkg)
    return ", ".join(f"/packages/{pkg}/" for pkg in seen)


def _tool_guide(adapter: SimulatorAdapter) -> str:
    primary = adapter.primary_package
    return (
        "You operate in the user's *workspace* (their current working "
        "directory). Two tool families:\n"
        "  - `julia_eval` and `julia_plot` run code in a persistent Julia "
        "REPL. State persists across calls. Use the REPL for probing APIs "
        "(`@doc`, `methods`, `fieldnames`, `pkgdir`), running simulations, "
        "and including workspace scripts.\n"
        "  - Use `julia_plot` whenever a plot would help the user (see the "
        "`plotting-basics` skill). Prefer the simulator's native plotters (named "
        "in the per-simulator skill); they render on GLMakie and are captured to "
        "an image automatically. You may also build a `Figure` inline. You do "
        "*not* need to return a `Figure` or avoid `display`. Pass `view=true` only "
        "when you need to see the result yourself (verify a fit, diagnose an "
        "anomaly), not for every plot. Plotting runs on GLMakie like normal Julia: "
        "in an interactive session `julia_plot` opens a live window the user can "
        "rotate/zoom/step and also saves a PNG; headless runs just save the PNG.\n"
        "  - The stock file/shell tools (`read_file`, `write_file`, "
        "`edit_file`, `glob`, `grep`, `execute`) operate in the workspace. Use "
        "them to create real implementation files the user can inspect and "
        "edit. The simulator and the Julia packages it builds on are mounted "
        f"read-only under `/packages/<Package>/` ({_package_mounts(adapter)}) — "
        f"`read_file`, `glob`, and `grep` them to study examples "
        f"(`/packages/{primary}/examples/`), documentation "
        f"(`/packages/{primary}/docs/`), and source (`/packages/{primary}/src/`) "
        "with the same tools (see the `workspace-and-source` skill).\n"
        "Two ways to run Julia, one shared REPL:\n"
        '    1. Direct — `julia_eval("<code>")` for probes, quick computations, '
        "and building/solving inline.\n"
        "    2. From a file — for a real implementation the user can keep, "
        "`write_file` a `.jl` file in the workspace, then run it in the same REPL "
        "with `julia_eval('include(\"candidate.jl\")')`. Edit the file with "
        "`edit_file` and re-`include` to re-run — the REPL keeps state, so loaded "
        "packages and earlier results survive across calls.\n"
        "Decision rule: real implementations → write a `.jl` file and `include` it; "
        "quick probes → `julia_eval` directly.\n"
        "Julia rule: always run Julia code with `julia_eval` (or `julia_plot` "
        "for figures). Never use `execute` to spawn `julia`, `julia --project`, "
        "or any shell pipeline that runs Julia — those start a fresh process "
        "with no shared state, cost a full precompile, and need approval. "
        "`execute` is for non-Julia shell work (grep, find, ls, git, etc.).\n"
        "Path rule: the workspace *is* the working directory — use plain "
        "relative paths for files in it (e.g. `paths.jl`), the same across file "
        "tools, `julia_eval`, and `execute`; don't prefix them with `/` or "
        "`/workspace/`. Leading-slash paths are only the read-only mounts "
        "(`/packages/`, `/skills/`, ...). "
        "Plots: build figures only via `julia_plot`, never `julia_eval` (that "
        "saves nothing the user can see). By default `julia_plot` opens a live "
        "Makie window for the user (interactive sessions) — give related plots a "
        "`slot` so the same slot refreshes one window and distinct slots are "
        "separate windows. Use `recapture_plot(slot=...)` to snapshot a window the "
        "user rotated, and `close_plots(slot=...)` to close one. Don't repeat "
        "artifact paths in prose."
    )
