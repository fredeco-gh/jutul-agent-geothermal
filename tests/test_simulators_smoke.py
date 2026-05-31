"""Per-simulator smoke test: each env instantiates and its package loads.

This is the cheapest signal that an upstream change broke jutul-agent: if a
simulator (or Jutul underneath it) ships a breaking release, ``using <Sim>``
fails to precompile/load and this test goes red. It runs in the dedicated
``Simulators`` workflow (Linux matrix, one job per simulator), not in the
cross-OS lane — see ``.github/workflows/simulators.yml``.

Gating mirrors the other integration tests: a simulator runs only when its env
is instantiated, which we detect by the generated (gitignored) ``Manifest.toml``.
The CI job instantiates the matrix simulator's env first; locally, a simulator
participates once you've run ``Pkg.instantiate()`` on its env. Placeholder envs
that don't yet ship their package (e.g. VOCSim) skip automatically.
"""

from __future__ import annotations

import shutil

import pytest

from jutul_agent.julia.backends.agentrepl import AgentREPLBackend, AgentREPLConfig
from jutul_agent.simulators import registry
from jutul_agent.simulators.base import SimulatorAdapter
from jutul_agent.simulators.env_setup import project_has_package

pytestmark = pytest.mark.integration

_ADAPTERS = [registry.get(name) for name in registry.names()]


def _env_ready(adapter: SimulatorAdapter) -> bool:
    env = adapter.julia_env_template_path
    return (
        shutil.which("julia") is not None
        and (env / "Project.toml").exists()
        and (env / "Manifest.toml").exists()
    )


@pytest.mark.parametrize("adapter", _ADAPTERS, ids=[a.name for a in _ADAPTERS])
async def test_simulator_env_loads(adapter: SimulatorAdapter) -> None:
    env = adapter.julia_env_template_path
    if not _env_ready(adapter):
        pytest.skip(f"{adapter.name} env not instantiated (run `Pkg.instantiate()` on {env})")
    if not project_has_package(env, adapter.primary_package):
        pytest.skip(f"{adapter.name} is a placeholder: {adapter.primary_package} not in its env")

    config = AgentREPLConfig(julia_project=env)
    async with AgentREPLBackend(config) as julia:
        result = await julia.eval(f"using {adapter.primary_package}")
        assert result.error is None, f"{adapter.name}: {result.error}"
        loaded = await julia.eval(f"@isdefined({adapter.primary_package})")
        assert "true" in loaded.output, f"{adapter.name}: module not in scope ({loaded.output!r})"
