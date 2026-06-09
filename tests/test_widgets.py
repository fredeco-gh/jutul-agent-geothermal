"""Pure-function tests for tool-rendering helpers in ``interfaces.widgets``."""

from __future__ import annotations

from jutul_agent.interfaces.tui.tool_display import display_tool_body
from jutul_agent.interfaces.tui.widgets import (
    ToolBlock,
    _render_request_preview,
    _render_tool_body,
    _render_tool_output,
)


def test_write_todos_preview_is_compact() -> None:
    preview = _render_request_preview(
        "write_todos",
        {
            "todos": [
                {"content": "Inspect the TUI event path", "status": "in_progress"},
                {"content": "Reduce startup noise", "status": "pending"},
            ]
        },
    )
    output = _render_tool_output(
        "write_todos",
        "Updated todo list to [{'content': 'Inspect the TUI event path', 'status': 'in_progress'}]",
        expanded=False,
    )

    assert "plan" in preview
    assert "[~] Inspect the TUI event path" in preview
    assert '"status"' not in output
    assert "plan updated" in output


def test_read_file_renders_compact_by_default() -> None:
    body = _render_tool_output(
        "read_file",
        "     1\t# title\n     2\tmore",
        expanded=False,
        args={"file_path": "candidate.jl"},
        is_error=False,
    )
    assert "Read `candidate.jl` · 2 lines" in body
    assert "content=" not in body


def test_julia_eval_running_body_shows_code_section() -> None:
    body = _render_tool_body(
        "julia_eval",
        {"code": "1 + 1"},
        output="",
        expanded=False,
        reject_reason=None,
        is_error=False,
    )
    assert "**Code**" in body
    assert "1 + 1" in body
    assert "running" in body.lower()
    assert 'julia_eval("' not in body


async def test_tool_block_append_output_then_set_result() -> None:
    block = ToolBlock("julia_eval", {"code": "run()"}, tool_call_id="call-1")

    class _FakeMarkdown:
        def __init__(self) -> None:
            self.body = ""

        async def update(self, body: str) -> None:
            self.body = body

        def refresh(self, *, layout: bool = False) -> None:
            return None

    block._body_widget = _FakeMarkdown()
    await block.append_output("progress\n")
    await block.append_output("→ 42\n")
    assert block._streamed == "progress\n→ 42\n"

    await block.set_result("progress\n→ 42\n", is_error=False)
    assert block._streamed == ""
    expected = display_tool_body(
        "julia_eval",
        {"code": "run()"},
        output="progress\n→ 42\n",
        expanded=False,
        is_error=False,
    )
    assert block._body_widget.body == expected


async def test_tool_block_collapses_carriage_return_progress() -> None:
    """Streamed deltas are rendered like a terminal: a progress bar that
    overwrites itself with carriage returns collapses to a single line instead
    of stacking, matching the kernel's final rendered output."""

    block = ToolBlock("julia_eval", {"code": "run()"}, tool_call_id="call-2")

    class _FakeMarkdown:
        def __init__(self) -> None:
            self.body = ""

        async def update(self, body: str) -> None:
            self.body = body

        def refresh(self, *, layout: bool = False) -> None:
            return None

    block._body_widget = _FakeMarkdown()
    # Three in-place updates of one bar, arriving as separate deltas.
    await block.append_output("Progress   0%|        |\r")
    await block.append_output("Progress  50%|####    |\r")
    await block.append_output("Progress 100%|########|\n")

    assert block._output == "Progress 100%|########|"
    assert block._output.count("Progress") == 1
