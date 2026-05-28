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


def assemble_session_prompt(adapter: SimulatorAdapter) -> str:
    sections = [
        f"Active simulator: {adapter.display_name} ({adapter.name}).",
        "Primary Julia packages: " + ", ".join(adapter.package_imports) + ".",
        _tool_guide(),
    ]
    hints = adapter.domain_hints.strip()
    if hints:
        sections.append("Simulator hints:\n" + hints)
    return "\n\n".join(sections) + "\n"


def _tool_guide() -> str:
    return (
        "You operate in the user's *workspace* (their current working "
        "directory). Two tool families:\n"
        "  - `julia_eval` and `julia_plot` run code in a persistent Julia "
        "REPL. State persists across calls. Use the REPL for probing APIs "
        "(`@doc`, `methods`, `fieldnames`, `pkgdir`), running simulations, "
        "and including workspace scripts.\n"
        "  - Use `julia_plot` whenever a plot would help the user (see the "
        "`plotting-basics` skill). Code must return a Makie `Figure`. Do "
        "not call `display(fig)` or open windows unless the user explicitly "
        "asks for an interactive viewer.\n"
        "  - The stock file/shell tools (`read_file`, `write_file`, "
        "`edit_file`, `execute`) operate in the workspace. Use them to "
        "create real implementation files the user can inspect and edit, "
        "and to grep installed simulator source via shell idioms "
        "(see the `workspace-and-source` skill).\n"
        "Decision rule: real implementations → write a file the user can "
        "edit; quick probes → REPL.\n"
        "Julia rule: always run Julia code with `julia_eval` (or `julia_plot` "
        "for figures). Never use `execute` to spawn `julia`, `julia --project`, "
        "or any shell pipeline that runs Julia — those start a fresh process "
        "with no shared state, cost a full precompile, and need approval. "
        "`execute` is for non-Julia shell work (grep, find, ls, git, etc.).\n"
        "Path rule: file tools may show virtual paths with a leading slash; "
        "Julia and shell code must use workspace-relative paths without it. "
        "Saved artifacts (plots, reports) auto-open in the user's default app "
        "and are visible in the tool card above your reply — don't repeat "
        "their paths in prose."
    )
