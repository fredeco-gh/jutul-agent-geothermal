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
