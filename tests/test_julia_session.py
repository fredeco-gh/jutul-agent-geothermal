"""Integration tests for the AgentREPL.jl-backed JuliaSession.

The MCP SDK's anyio cancel scopes require the same task to enter and exit
``stdio_client`` / ``ClientSession``. Async pytest fixtures that yield a
backend can split that across tasks. To keep the tests robust we inline
``async with`` inside the test rather than relying on a fixture.
"""

from __future__ import annotations

import shutil

import pytest

from jutul_agent.julia.backends.agentrepl import AgentREPLBackend, AgentREPLConfig
from jutul_agent.paths import PACKAGE_ROOT

AGENTREPL_ENV = PACKAGE_ROOT / "julia" / "agentrepl_env"


def _julia_available() -> bool:
    return shutil.which("julia") is not None and (AGENTREPL_ENV / "Project.toml").exists()


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _julia_available(),
        reason=(
            "Julia and the AgentREPL.jl env under "
            "src/jutul_agent/julia/agentrepl_env are required"
        ),
    ),
]


def _config() -> AgentREPLConfig:
    return AgentREPLConfig(julia_project=AGENTREPL_ENV)


async def test_agentrepl_eval_persistence_and_reset() -> None:
    async with AgentREPLBackend(_config()) as repl:
        result = await repl.eval("1 + 1")
        assert result.error is None, result.error
        assert "2" in result.output

        set_result = await repl.eval("x = 42")
        assert set_result.error is None, set_result.error
        get_result = await repl.eval("x")
        assert get_result.error is None, get_result.error
        assert "42" in get_result.output

        await repl.eval("y = 7")
        await repl.reset()
        reset_result = await repl.eval("y")
        haystack = (reset_result.output or "") + (reset_result.error or "")
        assert "UndefVar" in haystack
