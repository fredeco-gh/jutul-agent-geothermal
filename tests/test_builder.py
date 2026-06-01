"""Tests for agent builder helpers."""

from __future__ import annotations

import pytest

from jutul_agent.agent.builder import DEFAULT_MODEL, MODEL_ENV_VAR, resolve_model


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


def test_resolve_model_user_beats_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(MODEL_ENV_VAR, "openai:env")
    assert resolve_model(None, user_model="openai:user") == "openai:user"
