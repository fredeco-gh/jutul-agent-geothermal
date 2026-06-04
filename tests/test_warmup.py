"""Tests for the background Julia warmup task and ``JuliaSession.reset``."""

from __future__ import annotations

import asyncio

import pytest

from fakes import FakeJulia
from jutul_agent.interfaces.cli.run import _start_warmup
from jutul_agent.julia.session import EvalResult


async def test_start_warmup_returns_none_for_empty_code() -> None:
    julia = FakeJulia()
    assert _start_warmup(julia, "") is None
    assert _start_warmup(julia, "   \n   ") is None
    assert julia.calls == []


async def test_start_warmup_runs_warmup_code_in_background() -> None:
    julia = FakeJulia()
    task = _start_warmup(julia, "using BattMo")
    assert task is not None
    await task
    assert julia.calls == ["using BattMo"]


async def test_start_warmup_swallows_errors_so_startup_does_not_break() -> None:
    def boom(_code: str) -> EvalResult:
        raise RuntimeError("simulated env-load failure")

    julia = FakeJulia(eval_handler=boom)
    task = _start_warmup(julia, "using BrokenPackage")
    assert task is not None
    # The task should finish without re-raising — startup must not block on
    # a broken simulator env.
    await task


async def test_start_warmup_can_be_cancelled_during_shutdown() -> None:
    started = asyncio.Event()

    async def slow(_code: str) -> EvalResult:
        started.set()
        await asyncio.sleep(60)
        return EvalResult(output="never")

    julia = FakeJulia(eval_handler=slow)
    task = _start_warmup(julia, "using SlowPackage")
    assert task is not None
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_fake_julia_reset_counts_invocations() -> None:
    julia = FakeJulia()
    assert julia.reset_count == 0
    result = await julia.reset()
    assert result.output == "reset"
    await julia.reset()
    assert julia.reset_count == 2


async def test_all_real_adapters_warm_their_primary_package() -> None:
    """Every adapter except placeholders should ``using <primary>`` on startup."""

    from jutul_agent.simulators import registry

    for name in registry.names():
        adapter = registry.get(name)
        if name == "vocsim":  # placeholder while VOCSim.jl is unreleased
            continue
        assert adapter.warmup_code, f"adapter {name!r} has no warmup_code"
        assert adapter.primary_package in adapter.warmup_code, (
            f"adapter {name!r} warmup_code does not load primary package "
            f"{adapter.primary_package!r}"
        )


async def test_all_real_adapters_warm_the_plotting_path() -> None:
    """Warm-up must compile the GLMakie save path so the first plot is fast."""

    from jutul_agent.simulators import registry

    for name in registry.names():
        if name == "vocsim":
            continue
        adapter = registry.get(name)
        assert "GLMakie.activate!(visible = false)" in adapter.warmup_code, (
            f"adapter {name!r} does not warm the plotting path"
        )


def test_warmup_loads_glmakie_before_solving() -> None:
    """GLMakie must load before the solve.

    Loading a package after warming the solve invalidates the solve's compiled
    code, so the agent's first real solve recompiles from scratch. GLMakie
    therefore has to be in the up-front `using`.
    """
    from jutul_agent.simulators.warmup import warmup_script

    script = warmup_script(packages=("BattMo",), solve_block="solve(sim)")
    assert "GLMakie" in script.split("solve(", 1)[0], (
        "GLMakie must be loaded before the warm-up solve to avoid invalidation"
    )


def test_warmup_script_stages_are_independent_try_blocks() -> None:
    """A failure in one stage (missing pkg, API drift) must not abort the rest."""

    from jutul_agent.simulators.warmup import warmup_script

    script = warmup_script(packages=("Foo",), solve_block="error_here()")
    # using(Foo, GLMakie), solve, GLMakie save: each its own try/catch so one
    # failure can't abort the rest.
    assert script.count("try") == 3
    assert script.count("catch") == 3
    assert "using Foo, GLMakie" in script
    assert "error_here()" in script
    assert "GLMakie.activate!(visible = false)" in script

    # Opting out of plotting drops the GLMakie stages (down to the solve only).
    no_plot = warmup_script(packages=("Foo",), solve_block="x()", warm_plotting=False)
    assert no_plot.count("try") == 2
    assert "GLMakie" not in no_plot


def test_battmo_warmup_runs_a_real_solve() -> None:
    from jutul_agent.simulators.battmo import BATTMO

    assert "Simulation(" in BATTMO.warmup_code
    assert "solve(" in BATTMO.warmup_code
