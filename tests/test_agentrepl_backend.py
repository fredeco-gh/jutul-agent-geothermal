from __future__ import annotations

from jutul_agent.julia.backends.agentrepl.backend import _looks_like_tool_error


def test_agentrepl_detects_julia_method_errors() -> None:
    text = (
        "julia> simulate_reservoir(state0, model, dt; parameters, forces)\n"
        "ERROR: MethodError: no method matching ^(::Tuple{Float64}, ::Int64)"
    )

    assert _looks_like_tool_error(text) is True


def test_agentrepl_allows_normal_eval_output() -> None:
    assert _looks_like_tool_error("julia> 1 + 1\n2") is False
