"""Integration test: real agent + Textual TUI, driven by a scripted LLM."""

from __future__ import annotations

from textual.widgets import Markdown

from _tui import submit_prompt
from fakes import make_scripted_model, scripted_final, scripted_tool_call
from jutul_agent.agent.builder import build_agent
from jutul_agent.interfaces.tui import TUIApp
from jutul_agent.interfaces.tui.widgets import MessageBlock, ToolBlock
from jutul_agent.session import Session
from jutul_agent.trace import TraceLog


async def test_multi_tool_turn_renders_full_block_sequence(
    session_with_pkg: tuple[Session, object],
) -> None:
    session, julia = session_with_pkg

    model = make_scripted_model(
        [
            scripted_tool_call(
                tool_name="julia_eval",
                args={"code": "2 + 2"},
                tool_call_id="call_eval_1",
                content="Let me compute that.",
            ),
            scripted_tool_call(
                tool_name="julia_eval",
                args={"code": "print(pkgdir(FakePkg))"},
                tool_call_id="call_eval_2",
            ),
            scripted_final("Result is 4 and FakePkg lives at the printed path."),
        ]
    )

    agent = build_agent(session, model=model)
    app = TUIApp(agent=agent, session=session, model_label="fake:script")

    async with app.run_test() as pilot:
        await submit_prompt(pilot, "compute")

        blocks = list(app.query(MessageBlock))
        titles = [b.border_title for b in blocks]
        tool_blocks = list(app.query(ToolBlock))
        markdown_count = len(list(app.query(Markdown)))

    assert "Session" in titles
    assert "You" in titles
    assert "Assistant" in titles
    assert [block.border_title for block in tool_blocks] == [
        "Julia · run",
        "Julia · run",
    ]
    assert markdown_count >= 4
    assert "2 + 2" in julia.calls

    session.finalize()
    trace_text = _trace_payloads_concat(session)
    assert "2 + 2" in trace_text
    assert "pkgdir(FakePkg)" in trace_text


def _trace_payloads_concat(session: Session) -> str:
    log = TraceLog(session.state_dir / "trace.sqlite")
    try:
        return "\n".join(repr(e.payload) for e in log.iter_events())
    finally:
        log.close()


async def test_status_revert_to_ready_after_turn(
    session_with_pkg: tuple[Session, object],
) -> None:
    session, _ = session_with_pkg

    model = make_scripted_model([scripted_final("hello back")])
    agent = build_agent(session, model=model)
    app = TUIApp(agent=agent, session=session)

    async with app.run_test() as pilot:
        await submit_prompt(pilot, "hi")

        prompt_input = app.query_one("#prompt")
        assert prompt_input.disabled is False  # type: ignore[attr-defined]

    session.finalize()
