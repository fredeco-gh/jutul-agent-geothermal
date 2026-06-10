"""Tests for compact TUI tool summaries."""

from __future__ import annotations

from jutul_agent.interfaces.tui.tool_display import (
    compact_tool_summary,
    display_tool_body,
    strip_read_file_line_numbers,
)


def test_read_file_compact_summary() -> None:
    output = "     1\t# title\n     2\tbody"
    summary = compact_tool_summary(
        "read_file",
        {"file_path": "/skills/shared/julia-and-repl/SKILL.md"},
        output,
        is_error=False,
    )
    assert summary == "Read `skills/shared/julia-and-repl/SKILL.md` · 2 lines"


def test_read_file_compact_body_collapsed() -> None:
    output = "     1\t# title\n     2\tbody"
    body = display_tool_body(
        "read_file",
        {"file_path": "/experiments/candidate.jl"},
        output=output,
        expanded=False,
        is_error=False,
    )
    assert "Read `experiments/candidate.jl` · 2 lines" in body
    assert "Ctrl+O" not in body
    assert "content=" not in body


def test_strip_read_file_line_numbers() -> None:
    assert strip_read_file_line_numbers("     1\talpha\n     2\tbeta") == "alpha\nbeta"


def test_julia_eval_body_shows_code_then_output() -> None:
    body = display_tool_body(
        "julia_eval",
        {"code": "1 + 1"},
        output="2",
        expanded=False,
        is_error=False,
    )
    # Both the code the agent ran and the simulator output are visible; the
    # output isn't allowed to replace the code, and Jutul's iteration tables
    # would survive untouched if they were present.
    assert "**Code**" in body
    assert "1 + 1" in body
    assert "2" in body
    code_index = body.find("**Code**")
    output_index = body.find("output")
    assert code_index >= 0 and output_index > code_index


def test_julia_eval_running_state_shows_code() -> None:
    body = display_tool_body(
        "julia_eval",
        {"code": "simulate(model)"},
        output="",
        expanded=False,
        is_error=False,
    )
    assert "**Code**" in body
    assert "simulate(model)" in body
    assert "running" in body.lower()


def test_julia_eval_tail_truncation_keeps_return_value() -> None:
    lines = [f"progress line {i}" for i in range(60)]
    lines.extend(["→ 42", "[1.23s]"])
    output = "\n".join(lines)
    body = display_tool_body(
        "julia_eval",
        {"code": "run()"},
        output=output,
        expanded=False,
        is_error=False,
    )
    assert "output truncated above" in body
    assert "→ 42" in body
    assert "[1.23s]" in body
    assert "progress line 0" not in body


def test_julia_eval_preview_fits_jutul_timing_summary() -> None:
    """The simulation summary tables that follow a Jutul ``simulate(...)``
    call are ~30 lines. The collapsed preview must show all of them along
    with the trailing progress bar, return value, and elapsed marker so
    the user gets the real result without having to expand the card.
    """

    output = "\n".join(
        [
            "╭───────────────┬─────────┬───────────────┬─────────╮",
            "│ Iteration type │ Avg/step │ Avg/ministep │   Total │",
            "│                │ 18 steps │   21 ministeps │ (wasted)│",
            "├───────────────┼─────────┼───────────────┼─────────┤",
            "│ Newton         │  1.22222 │      1.04762 │ 22 (0)  │",
            "│ Linearization  │  2.38889 │      2.04762 │ 43 (0)  │",
            "│ Linear solver  │  2.66667 │      2.28571 │ 48 (0)  │",
            "│ Precond apply  │  5.33333 │      4.57143 │ 96 (0)  │",
            "╰───────────────┴─────────┴───────────────┴─────────╯",
            "",
            "╭──────────────┬─────────┬───────────┬────────╮",
            "│ Timing type  │    Each │  Relative │  Total │",
            "│              │      ms │         % │    s   │",
            "├──────────────┼─────────┼───────────┼────────┤",
            "│ Properties   │  0.3348 │   2.37 %  │ 0.1135 │",
            "│ Equations    │  2.8068 │  28.42 %  │ 1.3613 │",
            "│ Assembly     │  0.8855 │   8.97 %  │ 0.4295 │",
            "│ Linear solve │  0.4221 │   2.99 %  │ 0.1431 │",
            "│ Linear setup │  0.0000 │   0.00 %  │ 0.0000 │",
            "│ Precond apply│  0.0000 │   0.00 %  │ 0.0000 │",
            "│ Update       │  0.3636 │   2.57 %  │ 0.1233 │",
            "│ Convergence  │  2.7461 │  27.81 %  │ 1.3319 │",
            "│ Input/Output │  0.3804 │   1.16 %  │ 0.0555 │",
            "│ Other        │  3.6336 │  25.72 %  │ 1.2318 │",
            "│ Total        │ 14.1293 │ 100.00 %  │ 4.7898 │",
            "╰──────────────┴─────────┴───────────┴────────╯",
            "",
            "[stderr]",
            "Progress 100%|████████████████████████| Time: 0:00:05",
            "→ (145, (2.41708, 4.15396), (0.150268, 2.54521), 7048.44)",
            "[30.96s]",
        ]
    )
    body = display_tool_body(
        "julia_eval",
        {"code": 'include("candidate.jl"); run_candidate()'},
        output=output,
        expanded=False,
        is_error=False,
    )
    assert "Iteration type" in body
    assert "Timing type" in body
    assert "Total" in body
    assert "Progress 100%" in body
    assert "→ (145" in body
    assert "[30.96s]" in body


def test_task_delegate_summary() -> None:
    summary = compact_tool_summary(
        "task",
        {
            "subagent_type": "report",
            "description": "Write the calibration narrative markdown.",
        },
        "",
        is_error=False,
    )
    assert summary.startswith("Delegated → report ·")


def test_display_tool_body_handles_unparseable_todos() -> None:
    """write_todos output that isn't a todo list still renders as text, not None."""
    body = display_tool_body(
        "write_todos",
        {},
        output="Updated the plan.",
        expanded=False,
        is_error=False,
    )
    assert isinstance(body, str)
    assert "Updated the plan." in body
