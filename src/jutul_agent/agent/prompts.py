"""Build the per-session system prompt.

Everything jutul-agent adds to the model's system prompt is assembled here,
deterministically from the ``SimulatorAdapter`` and the session's display
capability; Deep Agents appends its built-in BASE prompt after it. Each
behavioral rule is stated exactly once; the per-provider ``HarnessProfile``
registered in ``agent.builder`` carries no prompt text, only the
general-purpose-subagent disable.
"""

from __future__ import annotations

from jutul_agent.simulators.base import SimulatorAdapter


def assemble_session_prompt(adapter: SimulatorAdapter, *, open_windows: bool = True) -> str:
    sections = [
        f"Active simulator: {adapter.display_name} ({adapter.name}).",
        "Primary Julia packages: " + ", ".join(adapter.package_imports) + ".",
        _tool_guide(adapter),
        _ground_rules(),
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
    can show, steer it to ``julia_plot`` (which still renders a PNG) and away from
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

    ordered = dict.fromkeys((adapter.primary_package, *adapter.package_imports))
    return ", ".join(f"/packages/{pkg}/" for pkg in ordered)


def _tool_guide(adapter: SimulatorAdapter) -> str:
    primary = adapter.primary_package
    return (
        "You operate in the user's *workspace* (their current working "
        "directory). Two tool families:\n"
        "  - `julia_eval` and `julia_plot` run code in a persistent Julia "
        "REPL. State persists across calls. Use the REPL for probing APIs "
        "(`@doc`, `methods`, `names`, `fieldnames`, `pkgdir`), running "
        "simulations, and including workspace scripts.\n"
        "  - The stock file/shell tools (`read_file`, `write_file`, "
        "`edit_file`, `glob`, `grep`, `execute`) operate in the workspace. Use "
        "them to create real implementation files the user can inspect and "
        "edit. The installed source of every package the environment resolves "
        "— the simulator, what it builds on, and anything you `Pkg.add` — is "
        f"mounted read-only under `/packages/<Package>/` ({_package_mounts(adapter)}): "
        f"`read_file`, `glob`, and `grep` it to study examples "
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
        "Plots: build figures only with `julia_plot`, never `julia_eval` (that "
        "draws a figure nobody can see) — see the `plotting-basics` skill. Prefer "
        "the simulator's documented native plotters (the per-simulator skill names "
        "them); you may also build a `Figure` inline, and you don't need to return "
        "it or avoid `display`. Plotting runs on GLMakie like normal Julia: in an "
        "interactive session `julia_plot` opens a live window the user can "
        "rotate/zoom/step and also saves a PNG; headless runs just save the PNG. "
        "Give related plots a stable `slot` — the same slot refreshes one window "
        "in place, distinct slots get distinct windows, and "
        "`recapture_plot(slot=...)` / `close_plots(slot=...)` address that window. "
        "Pass `view=true` only when you need to see the result yourself (verify a "
        "fit, diagnose an anomaly), not for every plot. Don't repeat artifact "
        "paths in prose."
    )


def _ground_rules() -> str:
    """House rules that hold for every simulator and every provider.

    Each rule is stated here and nowhere else; the tool guide above only
    orients (what exists, where it is mounted).
    """

    return (
        "Ground rules:\n"
        "  - Paths: the workspace is the working directory everywhere. Refer to "
        "workspace files by plain relative path (`model.jl`, `experiments/foo.csv`) "
        "— the same path resolves in the file tools, in `execute`, and in "
        '`julia_eval` (`include("model.jl")`); the file\'s real absolute path also '
        "works in all of them. Don't prefix workspace files with `/` and don't "
        "invent a `/workspace/` folder — leading-slash paths are reserved for the "
        "mounts (`/packages/`, `/skills/`, `/dirs/`, ...).\n"
        "  - Julia runs only in the shared REPL: `julia_eval`, or `julia_plot` for "
        "figures. Never spawn `julia` (or `julia --project`, `julia -e`) through "
        "`execute` — a fresh process shares no state, pays a full precompile, "
        "and needs approval. Results that feed the task's conclusions "
        "(simulation outputs, quantities the user asked for) come from the "
        "session REPL, not recomputed elsewhere; `execute` covers ordinary "
        "shell work.\n"
        "  - When a tool or Julia call fails, read the full error output, diagnose "
        "the root cause (wrong path, missing package, API mismatch, stale REPL "
        "state), and retry with a concrete fix — never repeat the same failing "
        "call.\n"
        "  - Prefer evidence over memory: read the mounted source under "
        "`/packages/`, probe the REPL (`@doc`, `methods`, `names`), or consult the "
        "skills before guessing an API. If a package is missing, check what the "
        "workspace env already provides, use a stdlib alternative, or `Pkg.add` it "
        "when the task needs it.\n"
        "  - Folders the user adds to the session are mounted writable at "
        "`/dirs/<name>/` — read, grep, write, and edit them with the file tools; "
        "in `julia_eval` / `execute` use their real absolute paths instead."
    )
