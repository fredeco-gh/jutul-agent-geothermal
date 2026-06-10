"""Renders the TUI against scripted v3-event stub agents."""

from __future__ import annotations

from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage
from textual.widgets import Footer

from _tui import submit_prompt, wait_until_ready
from fakes import (
    ScriptedV3Agent,
    interrupt_agent,
    streaming_agent,
    tool_call_events,
    v3_message_event,
    v3_tool_event,
    v3_values_event,
)
from jutul_agent.interfaces.tui import TUIApp
from jutul_agent.interfaces.tui.approval_menu import ApprovalMenu
from jutul_agent.interfaces.tui.prompt import PromptTextArea
from jutul_agent.interfaces.tui.widgets import (
    ApprovalBlock,
    MessageBlock,
    PromptGuide,
    ToolBlock,
    WelcomeBlock,
)
from jutul_agent.session import Session

_TRICKY_TOOL_NAME = "julia_eval"
_TRICKY_TOOL_ID = "call_Wadq4EXSvtuKOjcPsMw7lxy9"
_TRICKY_OUTPUT = (
    "[ToolMessage(content='2', name='julia_eval', "
    f"tool_call_id='{_TRICKY_TOOL_ID}', additional_kwargs={{}})]"
)
_TRICKY_ARGS = {"code": "[1, 2, 3] .+ 1"}


def _async_return(value):
    """An async function returning ``value`` regardless of arguments (for stubs)."""

    async def _fn(*args, **kwargs):
        return value

    return _fn


def _stub_agent() -> ScriptedV3Agent:
    return ScriptedV3Agent(
        tool_call_events(
            tool_name=_TRICKY_TOOL_NAME,
            tool_call_id=_TRICKY_TOOL_ID,
            args=_TRICKY_ARGS,
            output=_TRICKY_OUTPUT,
            final_text="Done. The answer is `[2, 3, 4]`.",
        )
    )


def _long_tool_agent() -> ScriptedV3Agent:
    # Must exceed the julia_eval preview budget (see tool_display.is_expandable).
    long_output = "\n".join(f"line {index}" for index in range(60))
    return ScriptedV3Agent(
        tool_call_events(
            tool_name="julia_eval",
            tool_call_id="call_long_1",
            args={"code": "println(1)"},
            output=long_output,
            final_text="Done.",
        )
    )


def _julia_delta_agent() -> ScriptedV3Agent:
    human = HumanMessage(content="run")
    final = AIMessage(content="Done.")
    return ScriptedV3Agent(
        [
            v3_tool_event(
                {
                    "event": "tool-started",
                    "tool_call_id": "call_delta_1",
                    "tool_name": "julia_eval",
                    "input": {"code": "run()"},
                }
            ),
            v3_tool_event(
                {
                    "event": "tool-output-delta",
                    "tool_call_id": "call_delta_1",
                    "delta": "progress\n",
                }
            ),
            v3_tool_event(
                {
                    "event": "tool-output-delta",
                    "tool_call_id": "call_delta_1",
                    "delta": "→ 42\n",
                }
            ),
            v3_tool_event(
                {
                    "event": "tool-finished",
                    "tool_call_id": "call_delta_1",
                    "output": "progress\n→ 42\n",
                }
            ),
            v3_values_event([human, final]),
        ]
    )


def _long_message_agent() -> ScriptedV3Agent:
    human = HumanMessage(content="hello")
    final = AIMessage(
        content=(
            "In JutulDarcy/Jutul-style reservoir simulation, a multi-segment "
            "well represents the wellbore as a connected network of segments "
            "instead of a single lumped connection."
        )
    )
    return ScriptedV3Agent(
        [
            v3_message_event(human),
            v3_message_event(final),
            v3_values_event([human, final]),
        ]
    )


async def test_chat_app_renders_brackety_tool_args_and_results(session: Session) -> None:
    app = TUIApp(agent=_stub_agent(), session=session)
    async with app.run_test() as pilot:
        await submit_prompt(pilot, "hello")


async def test_transcript_slash_command_writes_file(session: Session) -> None:
    app = TUIApp(agent=_stub_agent(), session=session)
    async with app.run_test() as pilot:
        await wait_until_ready(app)
        await pilot.press(*list("/transcript"))
        await pilot.press("enter")
        await wait_until_ready(app)

    target = session.output_dir / "transcript.html"
    assert target.exists()
    assert "<!doctype html>" in target.read_text(encoding="utf-8")


async def test_chat_app_renders_approval_card_for_pending_interrupt(session: Session) -> None:
    app = TUIApp(agent=interrupt_agent(), session=session)
    async with app.run_test() as pilot:
        await submit_prompt(pilot, "approve")
        titles = [block.border_title for block in app.query(ApprovalBlock)]
        message_titles = [block.border_title for block in app.query(MessageBlock)]
        assert "Approval · execute" in titles
        assert "System" in message_titles


async def test_chat_app_approves_pending_interrupt(session: Session) -> None:
    agent = interrupt_agent()
    app = TUIApp(agent=agent, session=session)
    async with app.run_test() as pilot:
        await submit_prompt(pilot, "approve")
        await pilot.press(*list("/approve"))
        await pilot.press("enter")
        await wait_until_ready(app)

        titles = [block.border_title for block in app.query(MessageBlock)]
        assert "Assistant" in titles

    assert len(agent.resume_inputs) == 1
    assert agent.resume_inputs[0].resume == {"interrupt-1": {"decisions": [{"type": "approve"}]}}


async def test_chat_app_approves_pending_interrupt_with_y(session: Session) -> None:
    agent = interrupt_agent()
    app = TUIApp(agent=agent, session=session)
    async with app.run_test() as pilot:
        await submit_prompt(pilot, "approve")
        assert app.query_one("#approval-menu", ApprovalMenu).visible
        await pilot.press("y")
        await wait_until_ready(app)

    assert len(agent.resume_inputs) == 1
    assert agent.resume_inputs[0].resume == {"interrupt-1": {"decisions": [{"type": "approve"}]}}


async def test_chat_app_navigates_approval_menu_with_arrows(session: Session) -> None:
    agent = interrupt_agent()
    app = TUIApp(agent=agent, session=session)
    async with app.run_test() as pilot:
        await submit_prompt(pilot, "approve")
        menu = app.query_one("#approval-menu", ApprovalMenu)
        assert menu.visible
        assert len(menu._options) == 2
        await pilot.press("down", "enter")
        await wait_until_ready(app)

    assert len(agent.resume_inputs) == 1
    assert agent.resume_inputs[0].resume == {
        "interrupt-1": {"decisions": [{"type": "reject"}]},
    }


async def test_chat_app_rejects_pending_interrupt_with_reason(session: Session) -> None:
    agent = interrupt_agent()
    app = TUIApp(agent=agent, session=session)
    async with app.run_test() as pilot:
        await submit_prompt(pilot, "approve")
        for ch in "/reject use safer command":
            await pilot.press(ch if ch != " " else "space")
        await pilot.press("enter")
        await wait_until_ready(app)

    assert len(agent.resume_inputs) == 1
    assert agent.resume_inputs[0].resume == {
        "interrupt-1": {"decisions": [{"type": "reject", "message": "use safer command"}]}
    }


async def test_chat_app_blocks_plain_text_while_approval_pending(session: Session) -> None:
    agent = interrupt_agent()
    app = TUIApp(agent=agent, session=session)
    async with app.run_test() as pilot:
        await submit_prompt(pilot, "approve")
        await pilot.press(*list("continue"))
        await pilot.press("enter")
        await wait_until_ready(app)

    assert agent.resume_inputs == []


async def test_chat_app_hides_respond_for_reject_only_interrupt(session: Session) -> None:
    app = TUIApp(agent=interrupt_agent(allowed_decisions=["approve", "reject"]), session=session)

    async with app.run_test() as pilot:
        await submit_prompt(pilot, "approve")

    assert app._approval_help_lines() == ["/approve", "/reject [reason]"]


async def test_chat_app_renders_streamed_julia_output(session: Session) -> None:
    app = TUIApp(agent=_julia_delta_agent(), session=session)

    async with app.run_test() as pilot:
        await submit_prompt(pilot, "run")

        tool_blocks = list(app.query(ToolBlock))
        assert len(tool_blocks) == 1
        assert "progress" in tool_blocks[0]._output
        assert "→ 42" in tool_blocks[0]._output


async def test_chat_app_toggles_all_tool_output(session: Session) -> None:
    app = TUIApp(agent=_long_tool_agent(), session=session)

    async with app.run_test() as pilot:
        await submit_prompt(pilot, "hello")

        tool_blocks = list(app.query(ToolBlock))
        assert len(tool_blocks) == 1
        assert tool_blocks[0].expandable is True
        assert tool_blocks[0]._expanded is False

        await pilot.press("ctrl+o")
        await wait_until_ready(app)

        assert app._tools_expanded is True
        assert all(block._expanded for block in app.query(ToolBlock))

        await pilot.press("ctrl+o")
        await wait_until_ready(app)

        assert app._tools_expanded is False
        assert not any(block._expanded for block in app.query(ToolBlock))


async def test_tui_streams_into_single_assistant_block(session: Session) -> None:
    app = TUIApp(agent=streaming_agent(), session=session)

    async with app.run_test() as pilot:
        await submit_prompt(pilot, "hello")

        assistant_blocks = [
            block for block in app.query(MessageBlock) if block.border_title == "Assistant"
        ]
        assert len(assistant_blocks) == 1
        assert assistant_blocks[0]._content == "Hello world"
        assert assistant_blocks[0]._stream is None


async def test_tui_layout_survives_terminal_resize(session: Session) -> None:
    app = TUIApp(agent=_long_tool_agent(), session=session)

    async with app.run_test(size=(120, 28)) as pilot:
        await submit_prompt(pilot, "hello")

        for width, height in ((84, 18), (110, 24), (72, 20)):
            await pilot.resize_terminal(width, height)
            await wait_until_ready(app)

        assert app.query_one("#status").size.height > 0
        assert app.query_one("#log").size.height > 0
        assert app.query_one("#prompt", PromptTextArea).size.width > 0
        assert app._resize_timer is None

        await pilot.press("ctrl+o")
        await wait_until_ready(app)

        tool_blocks = list(app.query(ToolBlock))
        assert len(tool_blocks) == 1
        assert tool_blocks[0].expandable is True


async def test_tui_reflows_wrapped_blocks_after_terminal_resize(session: Session) -> None:
    app = TUIApp(agent=_long_message_agent(), session=session)

    async with app.run_test(size=(120, 28)) as pilot:
        await submit_prompt(pilot, "hello")

        await pilot.press(*list("/help"))
        await pilot.press("enter")
        await wait_until_ready(app)

        assistant = next(
            block for block in app.query(MessageBlock) if block.border_title == "Assistant"
        )
        system = [block for block in app.query(MessageBlock) if block.border_title == "System"][-1]
        initial_height = assistant.size.height

        await pilot.resize_terminal(64, 18)
        await wait_until_ready(app)

        assert app._resize_timer is None
        assert assistant.size.height >= initial_height
        assert system.region.y >= assistant.region.bottom


async def test_tui_starts_with_welcome_card(session: Session) -> None:
    app = TUIApp(agent=_stub_agent(), session=session, model_label="openai:gpt-5.4-mini")

    async with app.run_test():
        await wait_until_ready(app)
        welcome_cards = list(app.query(WelcomeBlock))
        assert len(welcome_cards) == 1
        assert welcome_cards[0].border_title == "Session"
        assert "/transcript" not in welcome_cards[0]._content
        assert "/approve" not in welcome_cards[0]._content
        # The model lives in the status bar (which stays live as it changes),
        # not the one-time welcome card.
        assert "openai:gpt-5.4-mini" not in welcome_cards[0]._content


async def test_ctrl_c_copies_selection_when_present(session: Session, monkeypatch) -> None:
    app = TUIApp(agent=_stub_agent(), session=session)
    async with app.run_test():
        await wait_until_ready(app)
        copied: list[str] = []
        monkeypatch.setattr(app, "copy_to_clipboard", copied.append)
        monkeypatch.setattr(app.screen, "get_selected_text", lambda: "agent said this")

        await app.action_interrupt()

        assert copied == ["agent said this"]
        assert app._quit_armed is False


async def test_ctrl_c_requires_two_presses_to_exit(session: Session, monkeypatch) -> None:
    app = TUIApp(agent=_stub_agent(), session=session)
    async with app.run_test():
        await wait_until_ready(app)
        monkeypatch.setattr(app.screen, "get_selected_text", lambda: None)
        exited: list[bool] = []
        monkeypatch.setattr(app, "exit", lambda *a, **k: exited.append(True))

        await app.action_interrupt()  # first press arms quit, does not exit
        assert app._quit_armed is True
        assert exited == []

        await app.action_interrupt()  # second press exits
        assert exited == [True]


async def test_ctrl_c_disarm_resets_after_window(session: Session, monkeypatch) -> None:
    app = TUIApp(agent=_stub_agent(), session=session)
    async with app.run_test():
        await wait_until_ready(app)
        monkeypatch.setattr(app.screen, "get_selected_text", lambda: None)

        await app.action_interrupt()
        assert app._quit_armed is True
        app._disarm_quit()
        assert app._quit_armed is False


async def test_ctrl_c_interrupts_running_turn(session: Session, monkeypatch) -> None:
    app = TUIApp(agent=_stub_agent(), session=session)
    async with app.run_test():
        await wait_until_ready(app)
        cancelled: list[bool] = []

        async def fake_cancel() -> None:
            cancelled.append(True)

        monkeypatch.setattr(app, "action_cancel_turn", fake_cancel)
        exited: list[bool] = []
        monkeypatch.setattr(app, "exit", lambda *a, **k: exited.append(True))
        app._busy = True

        await app.action_interrupt()  # while busy: interrupt, don't arm/exit

        assert cancelled == [True]
        assert exited == []
        assert app._quit_armed is False


async def test_copy_command_copies_last_assistant_message(session: Session, monkeypatch) -> None:
    app = TUIApp(agent=streaming_agent(), session=session)
    async with app.run_test() as pilot:
        await submit_prompt(pilot, "hello")
        await wait_until_ready(app)
        copied: list[str] = []
        monkeypatch.setattr(app, "copy_to_clipboard", copied.append)

        await pilot.press(*list("/copy"))
        await pilot.press("enter")
        await wait_until_ready(app)

        assert len(copied) == 1
        assert copied[0].strip()  # the assistant reply text, non-empty


async def test_warming_indicator_coexists_with_turn_status(session: Session) -> None:
    # The warm-up indicator must stay visible while a turn runs (it used to be
    # replaced by "thinking…" / the Ctrl+G hint), and it lives in the bottom bar.
    app = TUIApp(agent=_stub_agent(), session=session)
    async with app.run_test():
        await wait_until_ready(app)
        app._busy = True
        app._warming = True
        app._status_text = "thinking…"
        label = app._activity_label()
        assert "thinking" in label and "warming" in label

        app._warming = False
        assert "warming" not in app._activity_label()


async def test_streamed_normal_prose_is_shown(session: Session) -> None:
    app = TUIApp(agent=_stub_agent(), session=session)
    async with app.run_test():
        await wait_until_ready(app)
        for chunk in ["The cell uses ", "the chen_2020 set."]:
            await app._stream.append_prose(app._log, chunk)
        assert app._stream.prose is not None
        assert app._stream.prose._content == "The cell uses the chen_2020 set."


async def test_tui_does_not_mount_footer_shortcuts(session: Session) -> None:
    app = TUIApp(agent=_stub_agent(), session=session)

    async with app.run_test():
        await wait_until_ready(app)
        assert list(app.query(Footer)) == []


async def test_clear_command_restores_welcome_card(session: Session) -> None:
    app = TUIApp(agent=_stub_agent(), session=session)

    async with app.run_test() as pilot:
        await submit_prompt(pilot, "hello")
        await pilot.press(*list("/clear"))
        await pilot.press("enter")
        await wait_until_ready(app)
        assert len(list(app.query(WelcomeBlock))) == 1
        assert list(app.query(ToolBlock)) == []


async def test_tui_recalls_history_with_ctrl_up_and_down(session: Session) -> None:
    from fakes import echo_agent

    app = TUIApp(agent=echo_agent(), session=session)

    async with app.run_test() as pilot:
        await submit_prompt(pilot, "first")
        await submit_prompt(pilot, "second")

        await pilot.press(*list("draft"))
        prompt = app.query_one("#prompt", PromptTextArea)
        prompt.post_message(PromptTextArea.HistoryPrevious("draft"))
        await pilot.pause()

        guide = app.query_one("#prompt-guide", PromptGuide)
        assert prompt.value == "second"
        assert guide.message.startswith("History 2/2")

        prompt.post_message(PromptTextArea.HistoryPrevious(prompt.value))
        await pilot.pause()
        assert prompt.value == "first"

        prompt.post_message(PromptTextArea.HistoryNext())
        await pilot.pause()
        assert prompt.value == "second"

        prompt.post_message(PromptTextArea.HistoryNext())
        await pilot.pause()
        assert prompt.value == "draft"


async def test_tui_completes_slash_commands_with_tab(session: Session) -> None:
    from fakes import echo_agent

    app = TUIApp(agent=echo_agent(), session=session)

    async with app.run_test() as pilot:
        await pilot.press("/")
        await wait_until_ready(app)

        guide = app.query_one("#prompt-guide", PromptGuide)
        assert "/transcript" in guide.message

        await pilot.press("t")
        await pilot.press("r")
        await pilot.press("tab")
        await wait_until_ready(app)

        prompt = app.query_one("#prompt", PromptTextArea)
        assert prompt.value == "/transcript"


async def test_tui_completes_pending_response_command_with_hint(session: Session) -> None:
    app = TUIApp(agent=interrupt_agent(), session=session)

    async with app.run_test() as pilot:
        await submit_prompt(pilot, "approve")

        await pilot.press("/")
        await pilot.press("r")
        await pilot.press("e")
        await pilot.press("s")
        await pilot.press("tab")
        await wait_until_ready(app)

        prompt = app.query_one("#prompt", PromptTextArea)
        guide = app.query_one("#prompt-guide", PromptGuide)
        assert prompt.value == "/respond "
        assert "<message>" in guide.message


async def test_tui_renders_reasoning_from_v3_event_stream(session: Session) -> None:
    from fakes import reasoning_agent

    app = TUIApp(agent=reasoning_agent(), session=session)

    async with app.run_test() as pilot:
        await submit_prompt(pilot, "hello")

        reasoning_blocks = [
            block for block in app.query(MessageBlock) if block.border_title == "Reasoning"
        ]
        assistant_blocks = [
            block for block in app.query(MessageBlock) if block.border_title == "Assistant"
        ]

        assert len(reasoning_blocks) == 1
        assert reasoning_blocks[0]._content == "Checking simulator state."
        assert len(assistant_blocks) == 1
        assert assistant_blocks[0]._content == "Answer ready"


async def test_tui_prompt_stays_compact_with_long_multiline_draft(session: Session) -> None:
    app = TUIApp(agent=_stub_agent(), session=session)

    async with app.run_test(size=(100, 30)) as pilot:
        prompt = app.query_one("#prompt", PromptTextArea)
        log = app.query_one("#log")
        prompt.load_text("\n".join(f"line {index}" for index in range(1, 25)))
        await pilot.pause()

        assert log.size.height > prompt.size.height
        assert prompt.size.height <= 10


async def test_tui_multiline_submit_shows_user_message_immediately(session: Session) -> None:
    from fakes import echo_agent

    app = TUIApp(agent=echo_agent(), session=session)

    async with app.run_test(size=(100, 30)) as pilot:
        prompt = app.query_one("#prompt", PromptTextArea)
        prompt.load_text("line one\nline two")
        await pilot.press("enter")
        await pilot.pause()

        assert prompt.value == ""
        user_blocks = [block for block in app.query(MessageBlock) if block.border_title == "You"]
        assert len(user_blocks) == 1
        assert "line one" in user_blocks[0]._content

        await wait_until_ready(app)


async def test_add_dir_command_mounts_folder(session: Session, tmp_path: Path) -> None:
    from jutul_agent.agent.builder import build_backend
    from jutul_agent.agent.mounts import MOUNTED_DIRS_ROOT

    extra = tmp_path / "shared-data"
    extra.mkdir()
    backend = build_backend(session.simulator, workspace=tmp_path)
    app = TUIApp(agent=_stub_agent(), session=session, backend=backend)

    async with app.run_test() as pilot:
        await wait_until_ready(app)
        await app._handle_command(f"/add-dir {extra}")
        await pilot.pause()

        assert f"{MOUNTED_DIRS_ROOT}shared-data/" in backend.routes
        notes = [block for block in app.query(MessageBlock) if block.border_title == "System"]
        assert any("shared-data" in block._content for block in notes)


async def test_add_dir_command_reports_bad_path(session: Session, tmp_path: Path) -> None:
    from jutul_agent.agent.builder import build_backend

    backend = build_backend(session.simulator, workspace=tmp_path)
    app = TUIApp(agent=_stub_agent(), session=session, backend=backend)

    async with app.run_test() as pilot:
        await wait_until_ready(app)
        await app._handle_command(f"/add-dir {tmp_path / 'does-not-exist'}")
        await pilot.pause()

        notes = [block for block in app.query(MessageBlock) if block.border_title == "System"]
        assert any("could not add folder" in block._content for block in notes)


async def test_add_dir_command_lists_when_no_arg(session: Session, tmp_path: Path) -> None:
    from jutul_agent.agent.builder import build_backend
    from jutul_agent.agent.mounts import mount_dir

    extra = tmp_path / "alpha"
    extra.mkdir()
    backend = build_backend(session.simulator, workspace=tmp_path)
    mount_dir(backend, extra, workspace=tmp_path)
    app = TUIApp(agent=_stub_agent(), session=session, backend=backend)

    async with app.run_test() as pilot:
        await wait_until_ready(app)
        await app._handle_command("/add-dir")
        await pilot.pause()

        notes = [block for block in app.query(MessageBlock) if block.border_title == "System"]
        assert any(
            "Mounted folders" in block._content and "alpha" in block._content for block in notes
        )


async def test_model_command_opens_selector(session: Session) -> None:
    from jutul_agent.interfaces.tui.model_menu import ModelMenu

    app = TUIApp(agent=_stub_agent(), session=session, model_label="openai:gpt-5.4-mini")
    async with app.run_test() as pilot:
        await wait_until_ready(app)
        await app._handle_command("/model")
        await pilot.pause()
        assert isinstance(app.screen, ModelMenu)


async def test_model_switch_rebuilds_and_persists_to_workspace(
    session: Session, tmp_path: Path, monkeypatch
) -> None:
    from jutul_agent import ollama_client
    from jutul_agent.agent.builder import build_backend
    from jutul_agent.workspace import load_workspace_config

    # Local model is reachable + already pulled, so the switch is deterministic.
    monkeypatch.setattr(ollama_client, "is_reachable", _async_return(True))
    monkeypatch.setattr(ollama_client, "is_installed", _async_return(True))
    monkeypatch.setattr(ollama_client, "supports_tools", _async_return(True))

    calls: list[tuple[str, list]] = []

    def factory(model_id: str, dirs):
        calls.append((model_id, list(dirs)))
        return _stub_agent(), build_backend(session.simulator, workspace=tmp_path)

    app = TUIApp(
        agent=_stub_agent(),
        session=session,
        backend=build_backend(session.simulator, workspace=tmp_path),
        model_label="openai:gpt-5.4-mini",
        agent_factory=factory,
    )
    async with app.run_test() as pilot:
        await wait_until_ready(app)
        # Local model: no API key needed, so the switch is deterministic.
        await app._handle_command("/model ollama:llama3.1")
        await pilot.pause()

        assert calls and calls[0][0] == "ollama:llama3.1"
        assert app._model_label == "ollama:llama3.1"
        notes = [block for block in app.query(MessageBlock) if block.border_title == "System"]
        assert any("model changed to" in block._content for block in notes)

    assert load_workspace_config(tmp_path).model == "ollama:llama3.1"


async def test_cloud_ollama_switch_skips_pull(
    session: Session, tmp_path: Path, monkeypatch
) -> None:
    from jutul_agent import ollama_client
    from jutul_agent.agent.builder import build_backend
    from jutul_agent.interfaces.tui.model_menu import OllamaPullModal

    monkeypatch.setattr(ollama_client, "is_reachable", _async_return(True))

    async def _must_not_check(name):
        raise AssertionError("is_installed must not be called for a cloud model")

    monkeypatch.setattr(ollama_client, "is_installed", _must_not_check)

    calls: list[str] = []

    def factory(model_id: str, dirs):
        calls.append(model_id)
        return _stub_agent(), build_backend(session.simulator, workspace=tmp_path)

    app = TUIApp(
        agent=_stub_agent(),
        session=session,
        backend=build_backend(session.simulator, workspace=tmp_path),
        model_label="openai:gpt-5.4-mini",
        agent_factory=factory,
    )
    async with app.run_test() as pilot:
        await wait_until_ready(app)
        await app._handle_command("/model ollama:glm-5.1:cloud")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert calls == ["ollama:glm-5.1:cloud"]  # switched, no pull
        assert app._model_label == "ollama:glm-5.1:cloud"
        assert not isinstance(app.screen, OllamaPullModal)


async def test_model_switch_preserves_mounted_dirs(
    session: Session, tmp_path: Path, monkeypatch
) -> None:
    from jutul_agent import ollama_client
    from jutul_agent.agent.builder import build_backend
    from jutul_agent.agent.mounts import mount_dir

    monkeypatch.setattr(ollama_client, "is_reachable", _async_return(True))
    monkeypatch.setattr(ollama_client, "is_installed", _async_return(True))
    monkeypatch.setattr(ollama_client, "supports_tools", _async_return(True))

    extra = tmp_path / "data"
    extra.mkdir()
    backend0 = build_backend(session.simulator, workspace=tmp_path)
    mount_dir(backend0, extra, workspace=tmp_path)

    calls: list[list[str]] = []

    def factory(model_id: str, dirs):
        calls.append([str(d) for d in dirs])
        return _stub_agent(), build_backend(session.simulator, workspace=tmp_path)

    app = TUIApp(
        agent=_stub_agent(),
        session=session,
        backend=backend0,
        model_label="openai:gpt-5.4-mini",
        agent_factory=factory,
    )
    async with app.run_test() as pilot:
        await wait_until_ready(app)
        await app._handle_command("/model ollama:qwen2.5")
        await pilot.pause()

    assert calls and str(extra.resolve()) in calls[0]


async def test_model_switch_without_key_opens_api_key_modal(session: Session, monkeypatch) -> None:
    from jutul_agent.interfaces.tui.model_menu import ApiKeyModal

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    calls: list[str] = []

    def factory(model_id: str, dirs):
        calls.append(model_id)
        return _stub_agent(), None

    app = TUIApp(
        agent=_stub_agent(),
        session=session,
        model_label="openai:gpt-5.4-mini",
        agent_factory=factory,
    )
    async with app.run_test() as pilot:
        await wait_until_ready(app)
        await app._handle_command("/model anthropic:claude-sonnet-4-6")
        await pilot.pause()

        assert isinstance(app.screen, ApiKeyModal)
        assert calls == []  # not rebuilt until a key is provided


async def test_api_key_modal_stores_key_and_switches(
    session: Session, tmp_path: Path, monkeypatch
) -> None:
    from textual.widgets import Input

    from jutul_agent.agent.builder import build_backend
    from jutul_agent.credentials import user_env_path
    from jutul_agent.interfaces.tui.model_menu import ApiKeyModal

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    calls: list[str] = []

    def factory(model_id: str, dirs):
        calls.append(model_id)
        return _stub_agent(), build_backend(session.simulator, workspace=tmp_path)

    app = TUIApp(
        agent=_stub_agent(),
        session=session,
        backend=build_backend(session.simulator, workspace=tmp_path),
        model_label="openai:gpt-5.4-mini",
        agent_factory=factory,
    )
    async with app.run_test() as pilot:
        await wait_until_ready(app)
        await app._handle_command("/model anthropic:claude-sonnet-4-6")
        await pilot.pause()
        assert isinstance(app.screen, ApiKeyModal)

        app.screen.query_one("#api-key-input", Input).value = "sk-secret"
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert calls == ["anthropic:claude-sonnet-4-6"]
        assert app._model_label == "anthropic:claude-sonnet-4-6"

    # Stored to the global secrets file and the process env.
    assert "ANTHROPIC_API_KEY" in user_env_path().read_text(encoding="utf-8")


async def test_local_model_without_tools_is_refused(session: Session, monkeypatch) -> None:
    from jutul_agent import ollama_client

    monkeypatch.setattr(ollama_client, "is_reachable", _async_return(True))
    monkeypatch.setattr(ollama_client, "is_installed", _async_return(True))
    # Daemon too old for the model's template → reports no `tools` capability.
    monkeypatch.setattr(ollama_client, "supports_tools", _async_return(False))
    calls: list[str] = []

    app = TUIApp(
        agent=_stub_agent(),
        session=session,
        model_label="openai:gpt-5.4-mini",
        agent_factory=lambda model_id, dirs: (calls.append(model_id), (_stub_agent(), None))[1],
    )
    async with app.run_test() as pilot:
        await wait_until_ready(app)
        await app._handle_command("/model ollama:qwen3.6:27b")
        await pilot.pause()

        assert calls == []  # not switched
        assert app._model_label == "openai:gpt-5.4-mini"
        notes = [block for block in app.query(MessageBlock) if block.border_title == "System"]
        assert any("doesn't support tool calling" in block._content for block in notes)


async def test_local_model_switch_notes_when_ollama_unreachable(
    session: Session, monkeypatch
) -> None:
    from jutul_agent import ollama_client

    monkeypatch.setattr(ollama_client, "is_reachable", _async_return(False))
    calls: list[str] = []

    app = TUIApp(
        agent=_stub_agent(),
        session=session,
        model_label="openai:gpt-5.4-mini",
        agent_factory=lambda model_id, dirs: (calls.append(model_id), (_stub_agent(), None))[1],
    )
    async with app.run_test() as pilot:
        await wait_until_ready(app)
        await app._handle_command("/model ollama:llama3.1")
        await pilot.pause()

        assert calls == []
        assert app._model_label == "openai:gpt-5.4-mini"
        notes = [block for block in app.query(MessageBlock) if block.border_title == "System"]
        assert any("Ollama isn't reachable" in block._content for block in notes)


async def test_local_model_switch_pulls_then_switches(
    session: Session, tmp_path: Path, monkeypatch
) -> None:
    from jutul_agent import ollama_client
    from jutul_agent.agent.builder import build_backend
    from jutul_agent.ollama_client import PullProgress

    monkeypatch.setattr(ollama_client, "is_reachable", _async_return(True))
    monkeypatch.setattr(ollama_client, "is_installed", _async_return(False))
    monkeypatch.setattr(ollama_client, "supports_tools", _async_return(True))

    async def fake_pull(name):
        yield PullProgress(status="pulling", fraction=0.5)
        yield PullProgress(status="success", fraction=1.0)

    monkeypatch.setattr(ollama_client, "pull", fake_pull)

    calls: list[str] = []

    def factory(model_id: str, dirs):
        calls.append(model_id)
        return _stub_agent(), build_backend(session.simulator, workspace=tmp_path)

    app = TUIApp(
        agent=_stub_agent(),
        session=session,
        backend=build_backend(session.simulator, workspace=tmp_path),
        model_label="openai:gpt-5.4-mini",
        agent_factory=factory,
    )
    async with app.run_test() as pilot:
        await wait_until_ready(app)
        await app._handle_command("/model ollama:llama3.1")
        await pilot.pause()  # mount the pull modal + start the pull worker
        await app.workers.wait_for_complete()  # pull completes → dismiss(True)
        await pilot.pause()  # dismiss callback → _apply_model worker
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert calls == ["ollama:llama3.1"]
        assert app._model_label == "ollama:llama3.1"


async def test_model_switch_refused_while_busy(session: Session) -> None:
    app = TUIApp(
        agent=_stub_agent(),
        session=session,
        model_label="openai:gpt-5.4-mini",
        agent_factory=lambda model_id, dirs: (_stub_agent(), None),
    )
    async with app.run_test() as pilot:
        await wait_until_ready(app)
        app._busy = True
        await app._handle_command("/model ollama:llama3.1")
        await pilot.pause()

    assert app._model_label == "openai:gpt-5.4-mini"


async def test_message_block_streams_before_mount_completes() -> None:
    from textual.app import App
    from textual.containers import VerticalScroll

    from jutul_agent.interfaces.tui.widgets import MessageBlock

    class _Host(App[None]):
        def compose(self):
            yield VerticalScroll(id="log")

    app = _Host()
    async with app.run_test() as _pilot:
        log = app.query_one("#log", VerticalScroll)
        block = MessageBlock("Assistant", "assistant", "", markdown=True)
        await log.mount(block)
        await block.append_content("Hello")
        await block.stop_stream()
        assert block._content == "Hello"


async def test_assistant_stream_survives_flush_during_append() -> None:
    from textual.app import App
    from textual.containers import VerticalScroll

    from jutul_agent.interfaces.tui.app import _AssistantStream
    from jutul_agent.interfaces.tui.widgets import MessageBlock

    class _Host(App[None]):
        def compose(self):
            yield VerticalScroll(id="log")

    app = _Host()
    async with app.run_test() as _pilot:
        log = app.query_one("#log", VerticalScroll)
        stream = _AssistantStream()
        block = MessageBlock("Assistant", "assistant", "", markdown=True)
        stream.prose = block
        await log.mount(block)
        stream.prose = None
        await block.append_content("Hello")
        assert block._content == "Hello"


def test_every_command_spec_has_a_handler() -> None:
    """Declaring a spec in commands.py requires the matching TUIApp method."""
    from jutul_agent.interfaces.tui.commands import ALL_COMMANDS

    for spec in ALL_COMMANDS:
        handler = getattr(TUIApp, spec.handler_attr, None)
        assert callable(handler), f"{spec.name} has no handler {spec.handler_attr}"
