"""Tests for TUI assistant prose filtering."""

from __future__ import annotations

from collections import deque

from jutul_agent.interfaces.tui.assistant_filter import filter_assistant_text


def test_filters_raw_todo_updates() -> None:
    text = "Updated todo list to [{'content': 'Inspect files', 'status': 'pending'}]"
    assert filter_assistant_text(text) is None


def test_filters_raw_todo_list_literal() -> None:
    text = "[{'content': 'do thing', 'status': 'pending'}]"
    assert filter_assistant_text(text) is None


def test_filters_duplicate_tool_output() -> None:
    tool_out = (
        "saved plot to jutul-agent/sessions/2024-01-01-abc12345/artifacts/"
        "cc_discharge_compare.png (format=png); slot=cc"
    )
    recent = deque([tool_out])
    assert filter_assistant_text(tool_out, recent_tool_outputs=recent) is None


def test_filters_line_numbered_skill_dump() -> None:
    # The agent pastes `read_file` output verbatim — line numbers + tabs defeat
    # the raw `^---\nname:` marker, so detection must normalize them away.
    text = "1\t---\n2\tname: battmo-overview\n3\tdescription: BattMo workflow\n4\t---"
    assert filter_assistant_text(text) is None


def test_filters_line_numbered_memory_dump() -> None:
    text = "1\t# Memory index\n2\t\n3\tThis file is the always-loaded index."
    assert filter_assistant_text(text) is None


def test_filters_space_numbered_skill_dump() -> None:
    # Some renders turn the read_file tab into spaces.
    text = "1  ---\n2  name: battmo-cycling\n3  description: protocols\n4  ---"
    assert filter_assistant_text(text) is None


def test_filters_fenced_skill_dump() -> None:
    text = "```\n---\nname: battmo-overview\ndescription: workflow\n---\n```"
    assert filter_assistant_text(text) is None


def test_keeps_unrelated_prose() -> None:
    recent = deque(["unrelated tool output line that is plenty long"])
    text = "Here is a short explanation of what I plan to do next."
    assert filter_assistant_text(text, recent_tool_outputs=recent) == text


def test_truncates_runaway_prose() -> None:
    text = "x" * 5000
    out = filter_assistant_text(text)
    assert out is not None
    assert "[assistant message truncated]" in out
    assert len(out) < 1500


def test_filters_skill_dump_with_frontmatter() -> None:
    text = "---\nname: investigation-loop\ndescription: stuff\n---\n\n# Investigation loop\n" + (
        "filler line\n" * 30
    )
    assert filter_assistant_text(text) is None


def test_filters_skill_dump_with_section_headers() -> None:
    text = (
        "# plotting-basics\n\n"
        "## When to use\n\n"
        "Use this skill when you need a quick comparison plot of\n"
        "observed data against a simulated curve.\n\n"
        "## Workflow\n\n"
        + ("Detailed step in the calibration workflow.\n" * 8)
        + "\n## Notes\n\n"
        + "Some extra material explaining caveats and edge cases.\n"
    )
    assert filter_assistant_text(text) is None


def test_filters_skill_dump_with_uncommon_sections() -> None:
    """The agent often dumps a skill with sections like Decision rule / Mental model
    that aren't in the original tight whitelist — those still need to be caught."""
    text = (
        "# JutulDarcy orientation\n\n"
        "## Mental model\n\n"
        "Five layers.\n\n"
        "## Decision rule\n\n"
        "Pick the smallest system.\n\n"
        "## Result inspection\n\n" + ("Read with `wd[:Producer][:bhp]`.\n" * 20)
    )
    assert filter_assistant_text(text) is None


def test_filters_memory_index_dump() -> None:
    text = (
        "# Memory index\n\n"
        "This file is the always-loaded index. Each entry below should be\n"
        "**one line** pointing to a sibling note file in this directory:\n\n"
        "- `<title>` — one-line hook (file: `<file.md>`)\n"
    )
    assert filter_assistant_text(text) is None


def test_keeps_short_prose_using_skill_phrases() -> None:
    text = "When to use this approach: run the baseline first, then iterate."
    assert filter_assistant_text(text) == text


def test_keeps_short_prose_with_one_section_header() -> None:
    """A short reply with a single ## heading is normal chat output."""
    text = (
        "Here is what I plan to do next.\n\n"
        "## Plan\n\n"
        "Run the baseline, capture rmse, then iterate."
    )
    assert filter_assistant_text(text) == text
