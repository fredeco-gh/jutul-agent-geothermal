"""Tests for the Ollama client wrapper (no real server required)."""

from __future__ import annotations

import pytest

from jutul_agent import ollama_client
from jutul_agent.ollama_client import _matches, host, model_name


class _Model:
    def __init__(self, name: str) -> None:
        self.model = name


class _ListResp:
    def __init__(self, names: list[str]) -> None:
        self.models = [_Model(n) for n in names]


def _fake_client(*, names=None, list_error=None, pull_chunks=None):
    class _Chunk:
        def __init__(self, status, total=None, completed=None):
            self.status, self.total, self.completed = status, total, completed

    class _Client:
        async def list(self):
            if list_error is not None:
                raise list_error
            return _ListResp(names or [])

        async def pull(self, name, stream=False):
            async def _gen():
                for status, total, completed in pull_chunks or []:
                    yield _Chunk(status, total, completed)

            return _gen()

    return _Client()


def test_model_name_strips_provider_prefix() -> None:
    assert model_name("ollama:llama3.1") == "llama3.1"
    assert model_name("llama3.1") == "llama3.1"


def test_matches_handles_latest_tag() -> None:
    assert _matches("llama3.1:latest", "llama3.1")
    assert _matches("llama3.1", "llama3.1")
    assert not _matches("qwen2.5:latest", "llama3.1")


def test_host_defaults_and_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    assert host() == "http://localhost:11434"
    monkeypatch.setenv("OLLAMA_HOST", "http://box:1234")
    assert host() == "http://box:1234"


async def test_is_reachable_true_and_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ollama_client, "_client", lambda: _fake_client(names=[]))
    assert await ollama_client.is_reachable() is True

    monkeypatch.setattr(
        ollama_client, "_client", lambda: _fake_client(list_error=ConnectionError("down"))
    )
    assert await ollama_client.is_reachable() is False


async def test_installed_models_and_is_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ollama_client,
        "_client",
        lambda: _fake_client(names=["llama3.1:latest", "qwen2.5:latest"]),
    )
    assert set(await ollama_client.installed_models()) == {"llama3.1:latest", "qwen2.5:latest"}
    assert await ollama_client.is_installed("llama3.1") is True
    assert await ollama_client.is_installed("mistral") is False


async def test_installed_models_empty_when_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ollama_client, "_client", lambda: _fake_client(list_error=ConnectionError("down"))
    )
    assert await ollama_client.installed_models() == []
    assert await ollama_client.is_installed("llama3.1") is False


async def test_pull_yields_progress_with_fraction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ollama_client,
        "_client",
        lambda: _fake_client(pull_chunks=[("pulling", 100, 50), ("success", None, None)]),
    )
    progress = [p async for p in ollama_client.pull("llama3.1")]
    assert progress[0].status == "pulling"
    assert progress[0].fraction == 0.5
    assert progress[1].status == "success"
    assert progress[1].fraction is None
