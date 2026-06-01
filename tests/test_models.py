"""Tests for the model catalog (discovery) and provider metadata."""

from __future__ import annotations

from jutul_agent.agent.builder import DEFAULT_MODEL
from jutul_agent.agent.models import (
    PROVIDERS,
    discover_models,
    is_known_model,
    is_local,
    key_env_var,
    provider_info,
    provider_of,
)


def test_provider_of_handles_missing_prefix() -> None:
    assert provider_of("anthropic:claude-sonnet-4-6") == "anthropic"
    assert provider_of("bare-model-name") == ""


def test_key_env_var_and_local_flag() -> None:
    assert key_env_var("openai:gpt-5.5") == "OPENAI_API_KEY"
    assert key_env_var("anthropic:claude-opus-4-8") == "ANTHROPIC_API_KEY"
    assert key_env_var("google_genai:gemini-3-flash-preview") == "GOOGLE_API_KEY"
    assert key_env_var("ollama:llama4") is None
    assert key_env_var("madeup:model") is None
    assert is_local("ollama:llama4") is True
    assert is_local("openai:gpt-5.5") is False


def test_provider_info_unknown_returns_none() -> None:
    assert provider_info("madeup:model") is None
    assert provider_info("openai:gpt-5.5") is PROVIDERS["openai"]


def test_discovery_groups_real_models_by_provider() -> None:
    catalog = discover_models()
    # Bundled providers ship profiles, so each contributes models; Ollama has no
    # static profiles and is discovered from the daemon by the selector, not here.
    assert "openai" in catalog
    assert "anthropic" in catalog
    assert "ollama" not in catalog
    for provider, models in catalog.items():
        assert models, provider
        for model in models:
            assert model.provider == provider
            assert model.id.startswith(f"{provider}:")
            # The label is the bare model name (no provider prefix).
            assert ":" not in model.label


def test_discovery_includes_the_default_model() -> None:
    assert is_known_model(DEFAULT_MODEL)


def test_is_known_model_rejects_free_text() -> None:
    assert is_known_model("openai:gpt-5.4-mini")
    assert not is_known_model("openrouter:some/model")
    assert not is_known_model("anthropic:haiku")  # not a real id
