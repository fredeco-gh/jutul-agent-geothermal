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
