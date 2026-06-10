"""User-global API-key storage and provider-credential checks.

Keys live in a global ``.env`` file at ``state_home()/.env``, loaded on startup
alongside any repo or workspace ``.env``. Shell environment and a project
``.env`` take precedence; this file is the fallback filled in when the user
enters a key interactively (at ``init`` or in the selector). Keys are kept out
of ``config.toml`` so that file stays safe to share.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

from dotenv import load_dotenv, set_key

from jutul_agent.models import key_env_var
from jutul_agent.paths import state_home


def user_env_path() -> Path:
    """Global secrets file at the root of the jutul-agent home."""
    return state_home() / ".env"


def load_user_credentials() -> None:
    """Load the global ``.env`` without overriding existing variables."""
    path = user_env_path()
    if path.exists():
        load_dotenv(path, override=False)


def missing_credential(model_id: str) -> str | None:
    """Env var the model's provider needs but that isn't set, else ``None``.

    ``None`` when the provider needs no key (local models like Ollama) or the
    key is already present in the environment.
    """
    env_var = key_env_var(model_id)
    if env_var is None or os.environ.get(env_var):
        return None
    return env_var


def store_credential(env_var: str, value: str) -> Path:
    """Persist ``env_var`` to the global ``.env`` and set it in the environment.

    Returns the file path. ``os.environ`` is updated so the key works without a
    restart.
    """
    value = value.strip()
    path = user_env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    # Restrict to the owner on POSIX; a no-op on Windows.
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)
    set_key(str(path), env_var, value)
    os.environ[env_var] = value
    return path
