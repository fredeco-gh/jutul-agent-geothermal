"""Tests for AgentREPL text helpers — ANSI stripping and terminal emulation."""

from __future__ import annotations

from jutul_agent.julia.backends.agentrepl import (
    render_terminal_output,
    strip_ansi,
    strip_julia_repl_echo,
)


def test_strip_ansi_removes_csi_and_color_codes() -> None:
    raw = "\x1b[32mhello\x1b[0m \x1b[1;31mworld\x1b[0m"
    assert strip_ansi(raw) == "hello world"


def test_render_terminal_output_passes_plain_text_through() -> None:
    assert render_terminal_output("a\nb\nc") == "a\nb\nc"


def test_render_terminal_output_collapses_carriage_return_overwrite() -> None:
    # Single-line progress bar that overwrites itself via \r.
    raw = "\rProgress  10%|##|\rProgress  50%|####|\rProgress 100%|######|"
    assert render_terminal_output(raw) == "Progress 100%|######|"


def test_render_terminal_output_handles_cursor_up_and_erase_line() -> None:
    # Three-line progress block, then cursor-up twice + erase-line to
    # overwrite the previous block with a fresh one — exactly what
    # ProgressMeter.jl emits.
    raw = (
        "Progress  10%|####      | ETA: 0:00:10\x1b[K\n"
        "   Solving step 17/100\x1b[K\n"
        "     Stats: 30 iterations\x1b[K"
        "\x1b[A\r\x1b[K\x1b[A\r\x1b[K"
        "Progress 100%|##########| Time: 0:00:01\x1b[K\n"
        "   Solving step 100/100\x1b[K\n"
        "     Stats: 200 iterations\x1b[K"
    )
    out = render_terminal_output(raw)
    assert out == (
        "Progress 100%|##########| Time: 0:00:01\n"
        "   Solving step 100/100\n"
        "     Stats: 200 iterations"
    )


def test_render_terminal_output_preserves_static_tables_before_progress() -> None:
    raw = "│ Newton │ 2.32 │\n│ Total  │ 14.18 │\n\n\rProgress  50%|####|\rProgress 100%|########|"
    out = render_terminal_output(raw)
    assert "│ Newton │ 2.32 │" in out
    assert "│ Total  │ 14.18 │" in out
    assert "Progress 100%|########|" in out
    assert "50%" not in out


def test_render_terminal_output_ignores_sgr_color_codes() -> None:
    raw = "\x1b[1;32mok\x1b[0m\n\x1b[31merror\x1b[0m"
    assert render_terminal_output(raw) == "ok\nerror"


def test_render_terminal_output_handles_backspace_and_tab() -> None:
    assert render_terminal_output("foox\bbar") == "foobar"
    # Tab moves to next 8-col stop.
    assert render_terminal_output("ab\tcd") == "ab      cd"


def test_strip_julia_repl_echo_drops_leading_julia_block() -> None:
    text = "julia> using CSV\n\nloaded\n"
    assert strip_julia_repl_echo(text) == "loaded"


def test_strip_julia_repl_echo_leaves_non_echo_text_alone() -> None:
    text = "just some output\n"
    assert strip_julia_repl_echo(text) == text
