from __future__ import annotations

from pathlib import Path

from jutul_agent.julia.backends.agentrepl.backend import (
    AgentREPLBackend,
    AgentREPLConfig,
    _looks_like_tool_error,
)


def test_make_params_sets_cwd_so_relative_includes_resolve(tmp_path: Path) -> None:
    # The REPL must run in the workspace so `include("candidate.jl")` and
    # `CSV.read("experiments/data.csv")` resolve against the files the agent wrote.
    backend = AgentREPLBackend(AgentREPLConfig(julia_project=tmp_path, cwd=tmp_path))
    params = backend._make_params()
    assert params.cwd == str(tmp_path)


def test_make_params_cwd_defaults_to_none() -> None:
    params = AgentREPLBackend(AgentREPLConfig())._make_params()
    assert params.cwd is None


def test_agentrepl_detects_julia_method_errors() -> None:
    text = (
        "julia> simulate_reservoir(state0, model, dt; parameters, forces)\n"
        "ERROR: MethodError: no method matching ^(::Tuple{Float64}, ::Int64)"
    )

    assert _looks_like_tool_error(text) is True


def test_agentrepl_allows_normal_eval_output() -> None:
    assert _looks_like_tool_error("julia> 1 + 1\n2") is False
