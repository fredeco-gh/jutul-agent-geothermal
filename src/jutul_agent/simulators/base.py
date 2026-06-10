"""Simulator adapter dataclass.

Each supported simulator (JutulDarcy, BattMo, …) ships an adapter that
declares which Julia packages the agent should know about, where its
skill markdown lives, and short orientation hints for the system prompt.
The adapter does not know about workspace paths; those are resolved at
run time via ``jutul_agent.workspace``.

Layout convention: each simulator owns one folder under
``src/jutul_agent/simulators/<name>/`` containing ``adapter.py``,
``julia_env/`` (Project.toml), and ``skills/`` (one sub-directory per skill).
The adapter passes its own ``module_dir`` so ``julia_env_template_path`` and
``skills_dir`` can be derived without reaching into package-wide constants.
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
    # Name of this env's per-simulator warm-up package (e.g.
    # ``"JutulAgentJutulDarcy"``). Loaded in the background at session start so its
    # precompiled, GLMakie-aware solver is resident; its solve/plot bake is what
    # makes the agent's first call fast. Empty disables the warm-up.
    warm_package: str = ""
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
