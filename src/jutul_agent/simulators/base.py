"""Simulator adapter dataclass.

Each supported simulator (JutulDarcy, BattMo, …) ships an adapter that
declares which Julia packages the agent should know about, where its
skill markdown lives, and short orientation hints for the system prompt.
The adapter does not know about workspace paths — those are resolved at
run time via ``jutul_agent.workspace``.

Layout convention: each simulator owns one folder under
``src/jutul_agent/simulators/<name>/`` containing ``adapter.py``,
``julia_env/`` (Project.toml + optional plots.jl), and ``skills/`` (one
sub-directory per skill). The adapter passes its own ``module_dir`` so
``julia_env_template_path``, ``skills_dir`` and ``plot_helpers_path`` can
be derived without reaching into package-wide constants.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from jutul_agent.session import Session


@dataclass(frozen=True)
class SimulatorAdapter:
    """Per-simulator metadata consumed by the agent and the env bootstrap."""

    name: str
    display_name: str
    module_dir: Path
    package_imports: tuple[str, ...]
    primary_package: str
    domain_hints: str
    # Background eval that pays the simulator's heavy precompile cost while
    # the user is reading the welcome card. Empty disables.
    warmup_code: str = ""
    # Each factory takes the Session and returns a deepagents ``SubAgent``
    # spec dict so a simulator can contribute named subagents on top of
    # the default set.
    subagent_factories: tuple[Callable[[Session], dict[str, Any]], ...] = field(
        default_factory=tuple
    )

    @property
    def julia_env_template_path(self) -> Path:
        return self.module_dir / "julia_env"

    @property
    def skills_dir(self) -> Path:
        return self.module_dir / "skills"

    @property
    def plot_helpers_path(self) -> Path | None:
        candidate = self.julia_env_template_path / "plots.jl"
        return candidate if candidate.is_file() else None
