"""Tests for the JuliaKernel backend.

The integration tests need only ``julia`` on PATH — the kernel runs against base
Julia, no instantiated env required (a strict improvement over the old backend,
which needed a built env to test at all).
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from jutul_agent.juliakernel import JuliaKernel, KernelConfig, OutputChunk
from jutul_agent.juliakernel.channels import _SENTINEL, KernelChannels, _parse_frame
from jutul_agent.juliakernel.kernel import JuliaStartupError

_HAS_JULIA = shutil.which("julia") is not None
needs_julia = pytest.mark.skipif(not _HAS_JULIA, reason="requires `julia` on PATH")


# ---- unit tests (no Julia) -------------------------------------------------


def test_build_launch_assembles_flags(tmp_path: Path) -> None:
    kernel = JuliaKernel(
        KernelConfig(
            julia_executable="julia",
            julia_project=tmp_path / "env",
            sysimage=tmp_path / "sys.so",
            threads="auto",
            env={"DISPLAY": ":7"},
        )
    )
    command, args, env = kernel._build_launch(54321)
    # Julia is launched directly (no xvfb-run wrapper); a display arrives via DISPLAY.
    assert command == "julia"
    assert f"--project={tmp_path / 'env'}" in args
    assert f"--sysimage={tmp_path / 'sys.so'}" in args
    assert "--threads=auto" in args
    assert "54321" in args
    assert any(a.endswith("server.jl") for a in args)
    assert env["DISPLAY"] == ":7"
    assert "JK_TOKEN" in env


def test_parse_frame_handles_every_tag() -> None:
    import base64

    assert _parse_frame(b"READY\tdeadbeef\n") == ("READY", "deadbeef")
    assert _parse_frame(b"INT\n") == ("INT", "")
    ok = b"OK\t" + base64.b64encode(b"2") + b"\n"
    assert _parse_frame(ok) == ("OK", "2")
    err = b"ERR\t" + base64.b64encode(b"DomainError") + b"\n"
    assert _parse_frame(err) == ("ERR", "DomainError")


async def test_startup_error_for_missing_julia() -> None:
    kernel = JuliaKernel(KernelConfig(julia_executable="definitely-not-julia-zzz"))
    with pytest.raises(JuliaStartupError):
        await kernel.__aenter__()
    # _spawn tore down what it opened before raising (no leaked listener socket).
    assert kernel._listener is None


async def test_channels_split_a_segment_across_two_reads() -> None:
    """A SENTINEL straddling a read boundary still closes the segment cleanly.

    Drives KernelChannels with bare StreamReaders (no Julia): the parser must
    reassemble the sentinel from two reads and stream the pre-sentinel bytes.
    """
    out, err = asyncio.StreamReader(), asyncio.StreamReader()
    channels = KernelChannels(out, err)
    streamed: list[str] = []
    channels.on_chunk = lambda chunk: streamed.append(chunk.text)

    data = b"hello world" + _SENTINEL + b"leftover"
    mid = len(b"hello world") + 3  # split inside the SENTINEL
    out.feed_data(data[:mid])
    out.feed_data(data[mid:])

    assert await channels.segment("stdout") == "hello world"
    assert "".join(streamed) == "hello world"  # streamed, not the held-back tail
    out.feed_eof()
    err.feed_eof()
    await channels.aclose()


async def test_channels_segment_raises_when_the_pipe_closes() -> None:
    """A read blocked on a dead channel wakes with an error instead of hanging."""
    out, err = asyncio.StreamReader(), asyncio.StreamReader()
    channels = KernelChannels(out, err)
    out.feed_eof()
    err.feed_eof()
    with pytest.raises(RuntimeError):
        await channels.segment("stdout")
    await channels.aclose()


# ---- integration tests (need Julia) ----------------------------------------


@pytest.mark.integration
@needs_julia
async def test_relative_include_resolves_in_workspace(tmp_path: Path) -> None:
    # A file written to the workspace must be `include`-able by its relative name;
    # without the rewrite, Julia resolves it next to the kernel's own source file.
    (tmp_path / "snippet.jl").write_text('println("loaded snippet")\n')
    async with JuliaKernel(KernelConfig(cwd=tmp_path)) as k:
        r = await k.eval('include("snippet.jl")')
        assert r.error is None, r.error
        assert "loaded snippet" in r.output


@pytest.mark.integration
@needs_julia
async def test_eval_persistence_streaming_and_error() -> None:
    async with JuliaKernel(KernelConfig()) as k:
        r = await k.eval("1 + 1")
        assert r.error is None
        assert r.output == "2"
        assert r.value_repr == "2"

        assert (await k.eval("x = 41; x + 1")).output == "42"  # state persists

        r = await k.eval('println("hello"); nothing')
        assert r.error is None
        assert r.output == "hello"  # no "nothing" noise

        r = await k.eval("sqrt(-1)")
        assert r.error is not None
        assert "DomainError" in r.error

        chunks: list[OutputChunk] = []
        r = await k.eval(
            'for i in 1:4; println("tick $i"); flush(stdout); sleep(0.15); end',
            on_chunk=chunks.append,
        )
        assert chunks, "expected live output chunks"
        assert any("tick" in c.text for c in chunks if c.stream == "stdout")
        assert r.output == "tick 1\ntick 2\ntick 3\ntick 4"


@pytest.mark.integration
@needs_julia
async def test_huge_error_frame_does_not_kill_session() -> None:
    """A giant error payload comes back as a normal error, not a false death.

    A deep error's base64 frame can exceed asyncio's 64 KiB readline default, which
    would look like the process died. The kernel raises the transport limit and caps
    the payload server-side, so the error returns bounded and the session survives.
    """
    async with JuliaKernel(KernelConfig()) as k:
        r = await k.eval('error("X" ^ 200_000)')
        assert r.error is not None
        assert k.running, "the session must survive a huge error frame"
        assert "output truncated" in r.error  # server-side cap kept the frame small
        assert len(r.error) < 80 * 1024
        assert (await k.eval("6 * 7")).output == "42"  # still usable, no reset needed


@pytest.mark.integration
@needs_julia
async def test_error_stacktrace_is_compact() -> None:
    """Errors use Julia's own REPL backtrace with the type limiter.

    ``format_error`` passes the ``:stacktrace_types_limited`` IOContext key, so a
    frame's huge specialized argument types collapse to ``{…}`` while the call chain
    and small types are kept.
    """
    async with JuliaKernel(KernelConfig()) as k:
        # A nested call so there are real frames with argument types.
        r = await k.eval("f(x) = sqrt(x); g(x) = f(x); g(-1.0)")
        assert r.error is not None
        assert "DomainError" in r.error
        assert "Stacktrace:" in r.error
        assert " @ " in r.error  # frames carry `@ file:line`
        assert len(r.error) < 8 * 1024  # compact, not a type-signature dump


@pytest.mark.integration
@needs_julia
async def test_error_keeps_output_printed_before_the_throw() -> None:
    """Output the user code printed before it threw is kept, not discarded."""
    async with JuliaKernel(KernelConfig()) as k:
        r = await k.eval('println("progress: step 1"); error("boom")')
        assert r.error is not None
        assert "boom" in r.error
        # The breadcrumb the agent needs survives in both the assembled output
        # and the structured stdout.
        assert "progress: step 1" in r.output
        assert "progress: step 1" in r.stdout


@pytest.mark.integration
@needs_julia
async def test_undisplayable_value_reports_its_type() -> None:
    """A value whose show/string both throw yields its type, not '<unprintable value>'."""
    async with JuliaKernel(KernelConfig()) as k:
        await k.eval(
            "struct _Unshowable end\n"
            'Base.show(io::IO, ::MIME"text/plain", ::_Unshowable) = error("no")\n'
            'Base.show(io::IO, ::_Unshowable) = error("no")'
        )
        r = await k.eval("_Unshowable()")
        assert r.error is None
        assert "_Unshowable" in r.output
        assert "cannot be displayed" in r.output


@pytest.mark.integration
@needs_julia
async def test_interrupt_survives_and_recovers() -> None:
    async with JuliaKernel(KernelConfig()) as k:
        task = asyncio.create_task(
            k.eval("for i in 1:200; println(i); flush(stdout); sleep(0.05); end")
        )
        await asyncio.sleep(1.0)
        await k.interrupt()
        r = await task
        assert r.interrupted
        assert k.running  # the server survived the interrupt
        assert (await k.eval("21 * 2")).output == "42"  # and still works


@pytest.mark.integration
@needs_julia
async def test_cancelled_eval_interrupts_and_preserves_state() -> None:
    """Cancelling a running eval interrupts it and keeps the session + state alive.

    Instead of restarting Julia (losing packages and variables), the kernel SIGINTs
    the eval and drains its result frame, so the process stays in protocol sync.
    """
    async with JuliaKernel(KernelConfig()) as k:
        await k.eval("kept = 123")  # state that must survive the cancel
        task = asyncio.create_task(k.eval("for i in 1:1000; sleep(0.1); end; 1"))
        await asyncio.sleep(1.0)  # let it enter the loop
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert k.running, "the session must survive a cancelled eval"
        assert k.cancel_preserved_state, "state should be preserved, not restarted"
        # No protocol desync (results align with their code) and state is intact.
        assert (await k.eval("kept + 1")).output == "124"
        assert (await k.eval("2 + 2")).output == "4"


@pytest.mark.integration
@needs_julia
async def test_reset_and_restart_clear_state() -> None:
    async with JuliaKernel(KernelConfig()) as k:
        await k.eval("y = 7")
        await k.reset()
        assert (await k.eval("@isdefined(y)")).output == "false"

        await k.eval("z = 9")
        await k.restart()
        assert k.running
        assert (await k.eval("@isdefined(z)")).output == "false"


@pytest.mark.integration
@needs_julia
async def test_killed_process_surfaces_as_error_not_a_hang() -> None:
    """If the process dies mid-eval, the blocked read wakes with a clean error.

    The pump feeding a channel pushes a poison marker when it exits, so a read
    waiting on the dead channel raises instead of hanging forever.
    """
    async with JuliaKernel(KernelConfig()) as k:
        task = asyncio.create_task(k.eval("sleep(60)"))
        await asyncio.sleep(0.5)
        assert k._proc is not None
        k._proc.kill()  # hard kill mid-eval, not a survivable SIGINT
        with pytest.raises(RuntimeError):
            await task
        assert not k.running
