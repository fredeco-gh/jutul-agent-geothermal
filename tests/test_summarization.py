"""Tests for auto-compaction wiring and the manual /compact path."""

from __future__ import annotations

from pathlib import Path

from langchain_core.messages import HumanMessage

from fakes import FakeJulia, make_fake_adapter, make_scripted_model, scripted_final
from jutul_agent.agent.builder import build_agent
from jutul_agent.agent.summarization import (
    TraceSummarizationMiddleware,
    build_summarization_middleware,
    compact_thread,
)
from jutul_agent.agent.turns import TurnRunner
from jutul_agent.session import Session
from jutul_agent.trace import TraceLog


def test_middleware_uses_fraction_trigger_with_profile(monkeypatch) -> None:
    from langchain_openai import ChatOpenAI

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    middleware = build_summarization_middleware(
        ChatOpenAI(model="gpt-5.4-mini"), model_id="openai:gpt-5.4-mini"
    )
    assert middleware.trigger == ("fraction", 0.8)


def test_middleware_falls_back_to_window_tokens(monkeypatch) -> None:
    from jutul_agent import models

    monkeypatch.setattr(models, "context_window", lambda model_id: 50_000)
    middleware = build_summarization_middleware(
        make_scripted_model([scripted_final("x")]), model_id="ollama:qwen3.6:27b"
    )
    assert middleware.trigger == ("tokens", 40_000)

    monkeypatch.setattr(models, "context_window", lambda model_id: None)
    middleware = build_summarization_middleware(
        make_scripted_model([scripted_final("x")]), model_id="ollama:unknown"
    )
    assert middleware.trigger == ("tokens", 100_000)


async def test_trace_middleware_records_compaction(tmp_path: Path) -> None:
    trace = TraceLog(tmp_path / "trace.sqlite")
    middleware = TraceSummarizationMiddleware(
        trace,
        model=make_scripted_model([scripted_final("SUMMARY of the early work")]),
        trigger=("messages", 3),
        keep=("messages", 2),
    )
    state = {"messages": [HumanMessage(content=f"message {i}") for i in range(4)]}
    update = await middleware.abefore_model(state, None)

    assert update is not None
    events = [e for e in trace.iter_events() if e.kind == "context_compaction"]
    assert len(events) == 1
    assert events[0].payload["messages_before"] == 4
    assert events[0].payload["messages_after"] == len(update["messages"]) - 1
    trace.close()


async def test_compact_thread_round_trip(tmp_path: Path) -> None:
    """/compact rewrites the checkpointed thread: summary + recent turns."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    adapter = make_fake_adapter(tmp_path)
    session = Session.create(julia=FakeJulia(), state_root=tmp_path, simulator=adapter)
    finals = [scripted_final(f"answer {i}") for i in range(6)]
    ckpt = session.state_dir / "checkpoints.sqlite"
    async with AsyncSqliteSaver.from_conn_string(str(ckpt)) as saver:
        agent, _ = build_agent(session, model=make_scripted_model(finals), checkpointer=saver)
        runner = TurnRunner(agent, thread_id=session.session_id, trace=session.trace)
        for i in range(6):
            await runner.run_prompt(f"question {i}")

        result = await compact_thread(
            agent,
            thread_id=session.session_id,
            model=make_scripted_model([scripted_final("SUMMARY of earlier work")]),
            trace=session.trace,
        )
        assert result is not None
        assert result.messages_before == 12
        assert result.messages_after < result.messages_before

        state = await agent.aget_state({"configurable": {"thread_id": session.session_id}})
        contents = [str(getattr(m, "content", "")) for m in state.values["messages"]]
        assert len(contents) == result.messages_after
        assert any("SUMMARY of earlier work" in c for c in contents)
        assert any("question 5" in c for c in contents)  # newest turns survive

    events = [e for e in session.trace.iter_events() if e.kind == "context_compaction"]
    assert len(events) == 1 and events[0].payload.get("manual") is True
    session.finalize()


async def test_compact_thread_skips_short_threads(tmp_path: Path) -> None:
    class _NoState:
        pass

    assert (
        await compact_thread(_NoState(), thread_id="t", model=None, trace=None)
    ) is None
