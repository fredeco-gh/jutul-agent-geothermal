"""Model catalog and provider metadata.

The in-app selector is built by *discovery*: ``discover_models()`` reads the
tool-calling models each installed provider package ships in its bundled
``data/_profiles.py`` (the same metadata LangChain uses), so new models appear
when the provider package updates — no hardcoded list to maintain. Ollama has
no static profiles and is discovered from the daemon by the selector. Any
``provider:model`` string ``init_chat_model`` accepts also works via free-text.

``PROVIDERS`` holds the per-provider API-key variable and the pip package that
supplies the LangChain integration.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProviderInfo:
    name: str
    label: str
    package: str
    key_env_var: str | None = None
    local: bool = False


@dataclass(frozen=True)
class ModelInfo:
    id: str
    label: str
    note: str = ""

    @property
    def provider(self) -> str:
        return provider_of(self.id)


PROVIDERS: dict[str, ProviderInfo] = {
    "openai": ProviderInfo("openai", "OpenAI", "langchain-openai", "OPENAI_API_KEY"),
    "anthropic": ProviderInfo("anthropic", "Anthropic", "langchain-anthropic", "ANTHROPIC_API_KEY"),
    "google_genai": ProviderInfo(
        "google_genai", "Google", "langchain-google-genai", "GOOGLE_API_KEY"
    ),
    "ollama": ProviderInfo("ollama", "Ollama (local)", "langchain-ollama", local=True),
}


def provider_of(model_id: str) -> str:
    prefix, sep, _ = model_id.partition(":")
    return prefix if sep else ""


def provider_info(model_id: str) -> ProviderInfo | None:
    return PROVIDERS.get(provider_of(model_id))


def key_env_var(model_id: str) -> str | None:
    info = provider_info(model_id)
    return info.key_env_var if info is not None else None


def is_local(model_id: str) -> bool:
    info = provider_info(model_id)
    return bool(info and info.local)


def is_ollama_cloud(model_id: str) -> bool:
    """Ollama-hosted (``:cloud``) models run remotely — no local pull needed."""
    return provider_of(model_id) == "ollama" and model_id.endswith(":cloud")


# Ollama ships no profile data, so unlike the cloud providers it has no
# discoverable catalog — a short hand-maintained list is the only way to offer
# browse-and-pull. This is the one curated list we keep; edit it as the local
# landscape moves. Local tags are pulled on first use; cloud models are hosted
# by Ollama (`ollama signin`) and switch directly.
#
# Qwen3.6 is the current sweet spot for local agentic coding (Apache 2.0): the
# 27B dense leads its size class on agentic-coding benchmarks (~17 GB at Q4),
# and the 35B-A3B MoE (~3B active) decodes far faster with long context, good
# for batched eval rollouts. NB: all open-weight models are Python-centric, so
# Julia/JutulDarcy tool-use is their weak axis — validate on real tasks.
RECOMMENDED_OLLAMA_LOCAL: tuple[str, ...] = (
    "qwen3.6:27b",
    "qwen3.6:35b-a3b",
)
# Frontier-tier models hosted by Ollama (mirrors deepagents-code's set); far
# better at tool use than small local models.
OLLAMA_CLOUD: tuple[str, ...] = (
    "deepseek-v4-flash:cloud",
    "glm-5.1:cloud",
    "kimi-k2.6:cloud",
    "minimax-m2.7:cloud",
)


@lru_cache(maxsize=1)
def discover_models() -> dict[str, list[ModelInfo]]:
    """Tool-calling models from installed provider packages, grouped by provider.

    Each non-local provider's ``data/_profiles.py`` is read and filtered to
    models that support tool calling and text I/O. Providers are ordered as in
    ``PROVIDERS``; models within a provider are sorted newest-ish first (reverse
    name order, which tracks the version-in-name scheme of the major providers).
    Cached for the process; call ``discover_models.cache_clear()`` to refresh.
    """
    grouped: dict[str, list[ModelInfo]] = {}
    for name, info in PROVIDERS.items():
        if info.local:
            continue  # Ollama ships no profiles; the selector probes the daemon.
        names = sorted(
            (m for m, profile in _load_profiles(info.package).items() if _is_chat_capable(profile)),
            reverse=True,
        )
        if names:
            grouped[name] = [ModelInfo(f"{name}:{m}", m) for m in names]
    return grouped


def is_known_model(model_id: str) -> bool:
    """Whether ``model_id`` is in the discovered catalog (vs free-text)."""
    return any(m.id == model_id for m in discover_models().get(provider_of(model_id), ()))


def _is_chat_capable(profile: dict[str, Any]) -> bool:
    return (
        bool(profile.get("tool_calling"))
        and profile.get("text_inputs", True) is not False
        and profile.get("text_outputs", True) is not False
    )


def _load_profiles(dist_name: str) -> dict[str, Any]:
    """Load ``_PROFILES`` from a provider package's ``data/_profiles.py``.

    Best-effort: a missing package or unreadable module yields an empty dict so
    discovery degrades to "that provider contributes nothing" rather than failing.
    """
    module_root = dist_name.replace("-", "_")
    spec = importlib.util.find_spec(module_root)
    if spec is None:
        return {}
    if spec.origin:
        base = Path(spec.origin).parent
    elif spec.submodule_search_locations:
        base = Path(next(iter(spec.submodule_search_locations)))
    else:
        return {}
    path = base / "data" / "_profiles.py"
    if not path.exists():
        return {}
    file_spec = importlib.util.spec_from_file_location(f"{module_root}.data._profiles", path)
    if file_spec is None or file_spec.loader is None:
        return {}
    module = importlib.util.module_from_spec(file_spec)
    try:
        file_spec.loader.exec_module(module)
    except Exception:
        return {}
    return getattr(module, "_PROFILES", {}) or {}
