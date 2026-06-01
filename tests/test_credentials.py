"""Tests for user-global credential storage and provider checks."""

from __future__ import annotations

import os
import sys

import pytest

from jutul_agent.credentials import (
    load_user_credentials,
    missing_credential,
    store_credential,
    user_env_path,
)
from jutul_agent.paths import state_home

# The autouse ``_reset_workspace_overrides`` fixture isolates state_home per
# test, so ``user_env_path()`` points at a fresh tmp dir.

_VAR = "JUTUL_AGENT_TEST_KEY"


@pytest.fixture(autouse=True)
def _clean_test_var() -> None:
    # store_credential mutates os.environ directly, so clean up around each test.
    os.environ.pop(_VAR, None)
    yield
    os.environ.pop(_VAR, None)


def test_user_env_path_under_state_home() -> None:
    assert user_env_path() == state_home() / ".env"


def test_store_credential_writes_file_and_sets_env() -> None:
    path = store_credential(_VAR, "secret-value")
    assert path == user_env_path()
    assert os.environ[_VAR] == "secret-value"
    assert _VAR in path.read_text(encoding="utf-8")
    assert "secret-value" in path.read_text(encoding="utf-8")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file mode")
def test_store_credential_locks_file_mode() -> None:
    path = store_credential(_VAR, "secret-value")
    assert (path.stat().st_mode & 0o777) == 0o600


def test_missing_credential_present_absent_and_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert missing_credential("openai:gpt-5.4") == "OPENAI_API_KEY"
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    assert missing_credential("openai:gpt-5.4") is None
    # Local providers need no key; unknown providers have none either.
    assert missing_credential("ollama:llama3.1") is None
    assert missing_credential("madeup:model") is None


def test_load_user_credentials_does_not_override_existing(monkeypatch: pytest.MonkeyPatch) -> None:
    path = user_env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'{_VAR}="from-file"\nJUTUL_AGENT_TEST_OTHER="loaded"\n', encoding="utf-8")

    monkeypatch.setenv(_VAR, "from-shell")
    load_user_credentials()
    # Shell value wins; a var only in the file is loaded.
    assert os.environ[_VAR] == "from-shell"
    assert os.environ.get("JUTUL_AGENT_TEST_OTHER") == "loaded"
    os.environ.pop("JUTUL_AGENT_TEST_OTHER", None)
