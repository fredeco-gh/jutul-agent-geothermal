"""Tests for agent builder helpers."""

from __future__ import annotations

import pytest

from jutul_agent.agent.builder import (
    DEFAULT_MODEL,
    MODEL_ENV_VAR,
    _ollama_ctx_budget,
    _ollama_num_ctx,
    register_provider_profiles,
    resolve_model,
)


def test_resolve_model_prefers_explicit() -> None:
    assert resolve_model("anthropic:claude-test") == "anthropic:claude-test"


def test_resolve_model_uses_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(MODEL_ENV_VAR, "openai:gpt-custom")
    assert resolve_model(None) == "openai:gpt-custom"


def test_resolve_model_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(MODEL_ENV_VAR, raising=False)
    assert resolve_model(None) == DEFAULT_MODEL


def test_resolve_model_explicit_beats_config_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(MODEL_ENV_VAR, "openai:env")
    assert (
        resolve_model("anthropic:cli", workspace_model="x:ws", user_model="x:user")
        == "anthropic:cli"
    )


def test_resolve_model_workspace_beats_user_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(MODEL_ENV_VAR, "openai:env")
    resolved = resolve_model(None, workspace_model="anthropic:ws", user_model="x:user")
    assert resolved == "anthropic:ws"


def test_ollama_ctx_budget_default_and_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JUTUL_AGENT_OLLAMA_NUM_CTX", raising=False)
    assert _ollama_ctx_budget() == 65536
    monkeypatch.setenv("JUTUL_AGENT_OLLAMA_NUM_CTX", "16384")
    assert _ollama_ctx_budget() == 16384
    monkeypatch.setenv("JUTUL_AGENT_OLLAMA_NUM_CTX", "not-an-int")
    assert _ollama_ctx_budget() == 65536  # bad value falls back to the default


def test_ollama_num_ctx_clamps_model_context_to_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    from jutul_agent import ollama_client

    monkeypatch.delenv("JUTUL_AGENT_OLLAMA_NUM_CTX", raising=False)  # budget = 65536
    # A big-context model is capped at the budget...
    monkeypatch.setattr(ollama_client, "context_window", lambda name: 262144)
    assert _ollama_num_ctx("ollama:qwen3.6:27b") == 65536
    # ...a small model keeps its own (smaller) max, not an inflated value...
    monkeypatch.setattr(ollama_client, "context_window", lambda name: 8192)
    assert _ollama_num_ctx("ollama:tiny") == 8192
    # ...and when the daemon can't report, fall back to the budget.
    monkeypatch.setattr(ollama_client, "context_window", lambda name: None)
    assert _ollama_num_ctx("ollama:mystery") == 65536


def test_resolve_model_for_agent_handles_ollama_and_cloud(monkeypatch: pytest.MonkeyPatch) -> None:
    from deepagents.profiles.harness.harness_profiles import _harness_profile_for_model
    from langchain_core.language_models import BaseChatModel

    from jutul_agent import ollama_client
    from jutul_agent.agent.builder import _resolve_model_for_agent

    register_provider_profiles()
    monkeypatch.delenv("JUTUL_AGENT_OLLAMA_NUM_CTX", raising=False)
    monkeypatch.setattr(ollama_client, "context_window", lambda name: 262144)
    # Cloud stays a spec string so deepagents resolves it + applies its profiles.
    assert _resolve_model_for_agent("openai:gpt-5.4-mini") == "openai:gpt-5.4-mini"
    # A version-tagged Ollama id (>1 colon) becomes a built instance whose context
    # is sized from the model and capped at the budget, and; crucially; our
    # harness profile now resolves for it (it does NOT for such a spec as a string).
    model = _resolve_model_for_agent("ollama:qwen3.6:27b")
    assert isinstance(model, BaseChatModel)
    assert getattr(model, "num_ctx", None) == 65536  # min(262144, budget)
    profile = _harness_profile_for_model(model, None)
    assert not profile.system_prompt_suffix  # all prompt text lives in agent.prompts
    assert profile.general_purpose_subagent.enabled is False


def test_resolve_model_user_beats_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(MODEL_ENV_VAR, "openai:env")
    assert resolve_model(None, user_model="openai:user") == "openai:user"
