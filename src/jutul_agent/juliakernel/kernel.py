"""A supervised, persistent Julia runtime with live output and interrupt.

``JuliaKernel`` owns one Julia subprocess and talks to it over three channels:
the process's **stdout** and **stderr** pipes (raw user output, streamed live as
it is produced) and a loopback-TCP **control** channel carrying length-framed
requests and authoritative ``OK``/``ERR``/``INT`` results. Evaluation runs
*in-process* in that Julia process, so a ``Distributed`` worker pool launched
from user code uses it the normal way (the process is the cluster master). The
kernel is the supervisor: it spawns, interrupts (SIGINT), and respawns the
process, so a reset never takes the surrounding Python session down with it.

The channel plumbing (draining the pipes, splitting them into per-eval segments,
framing control results) lives in :class:`KernelChannels`; ``JuliaKernel`` itself
supervises the process and drives the eval protocol. The package depends only on
the standard library.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import secrets
import signal
import socket
from pathlib import Path
from typing import IO, Self

from .channels import KernelChannels
from .config import KernelConfig
from .result import EvalResult, OnChunk
from .text import render_terminal_output

_SERVER_JL = Path(__file__).resolve().parent / "server.jl"
_MAX_ERROR_LINES = 80  # cap a Julia backtrace so it can't flood the agent's context


class JuliaStartupError(RuntimeError):
    """The Julia process died or never connected before the kernel was ready.

    Carries the diagnostic context a bare transport error throws away: which
    Julia and project were used, the tail of Julia's own stderr (the actual
    error, usually a package-load failure), and where the full log lives.
    """

    def __init__(
        self,
        summary: str,
        *,
        julia_executable: str,
        julia_project: Path | None,
        stderr_tail: str = "",
        log_file: Path | None = None,
    ) -> None:
        self.summary = summary
        self.julia_executable = julia_executable
        self.julia_project = julia_project
        self.stderr_tail = stderr_tail
        self.log_file = log_file
        super().__init__(self.format())

    def format(self) -> str:
        lines = [
            f"Julia failed to start before the kernel was ready: {self.summary}",
            f"  julia:         {self.julia_executable}",
            f"  julia project: {self.julia_project if self.julia_project else '(default)'}",
        ]
        if self.stderr_tail.strip():
            lines.append("  Julia said:")
            lines.extend(f"    {line}" for line in self.stderr_tail.strip().splitlines()[-40:])
        if self.log_file is not None:
            lines.append(f"  full log:      {self.log_file}")
        return "\n".join(lines)


class JuliaKernel:
    """A ``JuliaSession``-compatible persistent Julia runtime."""

    def __init__(self, config: KernelConfig | None = None) -> None:
        self._config = config or KernelConfig()
        self._proc: asyncio.subprocess.Process | None = None
        self._listener: socket.socket | None = None
        self._channels: KernelChannels | None = None
        self._watch_task: asyncio.Task[None] | None = None
        self._stderr_fh: IO[bytes] | None = None
        self._token = ""
        self._lock = asyncio.Lock()

    # ---- lifecycle ---------------------------------------------------------

    async def __aenter__(self) -> Self:
        await self._spawn()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._teardown(graceful=True)

    @property
    def running(self) -> bool:
        return (
            self._proc is not None
            and self._proc.returncode is None
            and self._channels is not None
            and not self._channels.closed.is_set()
        )

    async def reset(self) -> EvalResult:
        """Respawn a fresh Julia process (cooperative; never raises)."""
        with contextlib.suppress(BaseException):
            await self._teardown(graceful=True)
        await self._spawn()
        return EvalResult(output="Julia restarted with a fresh session.")

    async def restart(self) -> None:
        """Force the process down (SIGKILL) and respawn, ignoring responsiveness."""
        await self._teardown(graceful=False)
        await self._spawn()

    async def interrupt(self) -> None:
        """Send SIGINT to the running eval (best-effort; the process survives)."""
        proc = self._proc
        if proc is None or proc.returncode is not None:
            return
        with contextlib.suppress(ProcessLookupError, OSError, NotImplementedError):
            proc.send_signal(signal.SIGINT)

    # ---- evaluation --------------------------------------------------------

    async def eval(self, code: str, on_chunk: OnChunk | None = None) -> EvalResult:
        """Evaluate ``code`` in the persistent session.

        ``on_chunk`` (optional) receives :class:`OutputChunk` fragments live as
        the eval produces them; the returned :class:`EvalResult` carries the full
        cleaned output plus the structured value/error.
        """
        if self._proc is None:
            raise RuntimeError("JuliaKernel must be used inside an `async with` block")
        if not self.running:
            raise RuntimeError("the Julia kernel is not running")
        channels = self._channels
        assert channels is not None
        async with self._lock:
            channels.on_chunk = on_chunk
            try:
                await channels.send(code)
                frame = await channels.frame()
                out_raw = await channels.segment("stdout")
                err_raw = await channels.segment("stderr")
            finally:
                channels.on_chunk = None
        return self._build_result(frame, out_raw, err_raw)

    def _build_result(self, frame: tuple[str, str], out_raw: str, err_raw: str) -> EvalResult:
        tag, payload = frame
        out = render_terminal_output(out_raw)
        err = render_terminal_output(err_raw)
        # REPL-style text the user code produced, whatever the outcome: stdout, then
        # stderr under a heading. On OK this gets the value's repr appended; on an
        # error or interrupt it is the output printed before the eval stopped, kept
        # so the caller can surface it next to the error.
        parts: list[str] = []
        if out.strip():
            parts.append(out.rstrip("\n"))
        if err.strip():
            parts.append("[stderr]\n" + err.rstrip("\n"))
        if tag == "INT":
            return EvalResult(
                output="\n".join(parts),
                error="InterruptException: evaluation was interrupted",
                stdout=out,
                stderr=err,
                interrupted=True,
            )
        if tag == "ERR":
            return EvalResult(
                output="\n".join(parts), error=_truncate(payload), stdout=out, stderr=err
            )
        # OK — append the value's repr.
        if payload:
            parts.append(payload)
        return EvalResult(
            output="\n".join(parts),
            value_repr=payload or None,
            stdout=out,
            stderr=err,
        )

    # ---- spawn / teardown --------------------------------------------------

    async def _spawn(self) -> None:
        loop = asyncio.get_running_loop()

        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(1)
        self._listener.setblocking(False)
        port = self._listener.getsockname()[1]
        self._token = secrets.token_hex(16)

        if self._config.stderr_file is not None:
            self._config.stderr_file.parent.mkdir(parents=True, exist_ok=True)
            self._stderr_fh = open(self._config.stderr_file, "wb")  # noqa: SIM115

        command, args, env = self._build_launch(port)
        try:
            self._proc = await asyncio.create_subprocess_exec(
                command,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._config.cwd) if self._config.cwd is not None else None,
                env=env,
                start_new_session=True,  # own process group: our SIGINT hits only Julia
            )
        except FileNotFoundError as exc:
            await self._teardown(graceful=False)  # close the listener / stderr log we opened
            raise JuliaStartupError(
                f"`{command}` is not on PATH",
                julia_executable=self._config.julia_executable,
                julia_project=self._config.julia_project,
            ) from exc

        assert self._proc.stdout is not None and self._proc.stderr is not None
        self._channels = KernelChannels(
            self._proc.stdout, self._proc.stderr, stderr_fh=self._stderr_fh
        )
        self._watch_task = asyncio.create_task(self._watch_proc(self._proc, self._channels))

        try:
            conn = await self._accept_control(loop, port)
            await self._channels.attach_control(conn)
            await self._await_ready()
            # Drain the startup-preamble segment the server emits after READY.
            await self._channels.segment("stdout")
            await self._channels.segment("stderr")
        except JuliaStartupError:
            await self._teardown(graceful=False)
            raise
        except BaseException as exc:
            tail = self._channels.stderr_tail.decode("utf-8", "replace") if self._channels else ""
            await self._teardown(graceful=False)
            raise JuliaStartupError(
                "the Julia process exited before it was ready (see Julia output below)",
                julia_executable=self._config.julia_executable,
                julia_project=self._config.julia_project,
                stderr_tail=tail,
                log_file=self._config.stderr_file,
            ) from exc

    async def _accept_control(self, loop: asyncio.AbstractEventLoop, port: int) -> socket.socket:
        assert self._listener is not None and self._channels is not None
        accept = asyncio.ensure_future(loop.sock_accept(self._listener))
        dead = asyncio.ensure_future(self._channels.closed.wait())
        done, _ = await asyncio.wait(
            {accept, dead},
            timeout=self._config.startup_timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if accept not in done:
            accept.cancel()
            dead.cancel()
            why = (
                "the Julia process exited"
                if self._channels.closed.is_set()
                else "timed out connecting"
            )
            raise JuliaStartupError(
                f"{why} before the control channel came up",
                julia_executable=self._config.julia_executable,
                julia_project=self._config.julia_project,
                stderr_tail=self._channels.stderr_tail.decode("utf-8", "replace"),
                log_file=self._config.stderr_file,
            )
        dead.cancel()
        conn, _ = accept.result()
        return conn

    async def _await_ready(self) -> None:
        assert self._channels is not None
        tag, payload = await self._channels.frame()
        if tag != "READY" or payload != self._token:
            raise JuliaStartupError(
                "the control handshake failed (token mismatch)",
                julia_executable=self._config.julia_executable,
                julia_project=self._config.julia_project,
            )

    async def _watch_proc(self, proc: asyncio.subprocess.Process, channels: KernelChannels) -> None:
        with contextlib.suppress(Exception):
            await proc.wait()
        channels.closed.set()

    async def _teardown(self, *, graceful: bool) -> None:
        proc = self._proc
        if proc is not None and proc.returncode is None:
            if graceful and self._channels is not None and self._channels.has_control:
                self._channels.close_control()  # clean EOF exit for the server
                with contextlib.suppress(TimeoutError, Exception):
                    await asyncio.wait_for(proc.wait(), timeout=5)
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError, OSError):
                    proc.kill()
                with contextlib.suppress(Exception):
                    await proc.wait()
        if self._watch_task is not None:
            self._watch_task.cancel()
            with contextlib.suppress(BaseException):
                await self._watch_task
            self._watch_task = None
        if self._channels is not None:
            await self._channels.aclose()
            self._channels = None
        if self._listener is not None:
            with contextlib.suppress(Exception):
                self._listener.close()
            self._listener = None
        if self._stderr_fh is not None:
            with contextlib.suppress(Exception):
                self._stderr_fh.close()
            self._stderr_fh = None
        self._proc = None
        self._token = ""

    def _build_launch(self, port: int) -> tuple[str, list[str], dict[str, str]]:
        cfg = self._config
        args: list[str] = []
        if cfg.julia_project is not None:
            args.append(f"--project={cfg.julia_project}")
        if cfg.sysimage is not None:
            args.append(f"--sysimage={cfg.sysimage}")
        if cfg.threads is not None:
            args.append(f"--threads={cfg.threads}")
        args.extend(cfg.extra_args)
        args.extend([str(_SERVER_JL), str(port)])

        env = dict(os.environ)
        if cfg.env:
            env.update(cfg.env)
        env["JK_TOKEN"] = self._token

        return cfg.julia_executable, args, env


def _truncate(text: str) -> str:
    lines = text.splitlines()
    if len(lines) <= _MAX_ERROR_LINES:
        return text
    kept = lines[:_MAX_ERROR_LINES]
    kept.append(f"… ({len(lines) - _MAX_ERROR_LINES} more lines of backtrace omitted)")
    return "\n".join(kept)
