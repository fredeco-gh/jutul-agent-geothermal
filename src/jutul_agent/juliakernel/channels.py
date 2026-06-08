"""The Python endpoint of the kernel wire protocol.

:class:`KernelChannels` owns the three channels to a running Julia server (the
loopback control socket plus the process's stdout/stderr pipes) and the framing
over them. Pump tasks drain the pipes, split each into per-eval segments at the
SENTINEL, stream live fragments to ``on_chunk``, and frame control results. A
read blocks until the next frame/segment arrives; if the pump feeding it exits
first it pushes ``_DEAD`` so the read raises instead of hanging forever.

The Julia counterpart is ``server.jl``; the two must agree on the SENTINEL bytes
and the ``OK``/``ERR``/``INT`` control framing.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import socket
from typing import IO, cast

from .result import OnChunk, OutputChunk

# Must byte-match the SENTINEL in server.jl.
_SENTINEL = b"\x1e\x1eJK-EVAL-DONE\x1e\x1e\n"
_STDERR_TAIL_CAP = 16 * 1024
_READ_SIZE = 64 * 1024
# Each result frame is one base64 ``readline`` line. A deep solver error prints
# enormous type signatures, well past asyncio's 64 KiB default (which would raise
# and look like the process died). The server caps payloads; this is the matching,
# generous transport ceiling.
_CTRL_LIMIT = 64 * 1024 * 1024

# Pushed onto a channel's queue when its pump exits, so a blocked reader wakes and
# learns the process is gone instead of hanging forever.
_DEAD = object()


class KernelChannels:
    """The control + stdout/stderr channels to a running Julia server."""

    def __init__(
        self,
        stdout_reader: asyncio.StreamReader,
        stderr_reader: asyncio.StreamReader,
        *,
        stderr_fh: IO[bytes] | None = None,
    ) -> None:
        self.closed = asyncio.Event()
        self.on_chunk: OnChunk | None = None
        self._ctrl_q: asyncio.Queue[object] = asyncio.Queue()
        self._seg_q: dict[str, asyncio.Queue[object]] = {
            "stdout": asyncio.Queue(),
            "stderr": asyncio.Queue(),
        }
        self._ctrl_writer: asyncio.StreamWriter | None = None
        self._stderr_tail = bytearray()
        self._stderr_fh = stderr_fh
        self._tasks = [
            asyncio.create_task(self._pump(stdout_reader, "stdout")),
            asyncio.create_task(self._pump(stderr_reader, "stderr")),
        ]

    async def attach_control(self, conn: socket.socket) -> None:
        """Open the control connection over ``conn`` and start pumping it."""
        reader, writer = await asyncio.open_connection(sock=conn, limit=_CTRL_LIMIT)
        self._ctrl_writer = writer
        self._tasks.append(asyncio.create_task(self._pump_control(reader)))

    @property
    def has_control(self) -> bool:
        return self._ctrl_writer is not None

    @property
    def stderr_tail(self) -> bytes:
        """The most recent stderr bytes, kept to diagnose a startup failure."""
        return bytes(self._stderr_tail)

    # ---- requests / reads --------------------------------------------------

    async def send(self, code: str) -> None:
        """Frame ``code`` and write it to the control channel."""
        assert self._ctrl_writer is not None
        self._ctrl_writer.write(base64.b64encode(code.encode("utf-8")) + b"\n")
        await self._ctrl_writer.drain()

    async def frame(self) -> tuple[str, str]:
        """The next control result, or raise if the channel closed first."""
        return cast("tuple[str, str]", await self._recv(self._ctrl_q))

    async def segment(self, name: str) -> str:
        """The next stdout/stderr segment, or raise if the channel closed first."""
        return cast("str", await self._recv(self._seg_q[name]))

    async def _recv(self, q: asyncio.Queue[object]) -> object:
        item = await q.get()
        if item is _DEAD:
            q.put_nowait(_DEAD)  # leave the channel poisoned for any later read
            raise RuntimeError("the Julia kernel exited unexpectedly")
        return item

    # ---- teardown ----------------------------------------------------------

    def close_control(self) -> None:
        """Close the control writer, giving the server a clean EOF exit."""
        if self._ctrl_writer is not None:
            with contextlib.suppress(Exception):
                self._ctrl_writer.close()

    async def aclose(self) -> None:
        """Stop every pump and close the control writer."""
        self.close_control()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    # ---- pumps -------------------------------------------------------------

    async def _pump(self, reader: asyncio.StreamReader, name: str) -> None:
        """Stream one output pipe live and split it into per-eval segments.

        Bytes accumulate in ``buf`` until a SENTINEL closes a segment, which is
        then decoded and queued for :meth:`segment`. Everything except a possible
        partial-sentinel tail is streamed to ``on_chunk`` as it arrives.
        ``scanned`` records how far ``buf`` has been searched, so a large
        sentinel-free output is scanned once rather than on every read.
        """
        seg_q = self._seg_q[name]
        is_stderr = name == "stderr"
        lookback = len(_SENTINEL) - 1
        buf = bytearray()
        streamed = 0  # bytes of buf already handed to on_chunk
        scanned = 0  # bytes of buf already searched for a SENTINEL
        try:
            while True:
                chunk = await reader.read(_READ_SIZE)
                if not chunk:
                    break
                if is_stderr:
                    self._note_stderr(chunk)
                buf += chunk
                # A SENTINEL can straddle a read boundary, so resume the search a
                # little before the bytes already scanned.
                search = max(scanned - lookback, 0)
                while (idx := buf.find(_SENTINEL, search)) != -1:
                    self._emit(name, buf[streamed:idx])
                    seg_q.put_nowait(buf[:idx].decode("utf-8", "replace"))
                    del buf[: idx + len(_SENTINEL)]
                    streamed = search = 0
                scanned = len(buf)
                # Stream everything except a possible partial-sentinel tail.
                safe_end = max(streamed, len(buf) - lookback)
                if safe_end > streamed:
                    self._emit(name, buf[streamed:safe_end])
                    streamed = safe_end
        finally:
            self._poison(seg_q)

    async def _pump_control(self, reader: asyncio.StreamReader) -> None:
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                self._ctrl_q.put_nowait(_parse_frame(line))
        finally:
            self._poison(self._ctrl_q)

    def _emit(self, name: str, raw: bytes | bytearray) -> None:
        cb = self.on_chunk
        if cb is None or not raw:
            return
        with contextlib.suppress(Exception):  # a bad sink must not wedge the pump
            cb(OutputChunk(text=raw.decode("utf-8", "replace"), stream=name))

    def _note_stderr(self, chunk: bytes) -> None:
        self._stderr_tail += chunk
        if len(self._stderr_tail) > _STDERR_TAIL_CAP:
            del self._stderr_tail[:-_STDERR_TAIL_CAP]
        if self._stderr_fh is not None:
            with contextlib.suppress(Exception):
                self._stderr_fh.write(chunk)
                self._stderr_fh.flush()

    def _poison(self, q: asyncio.Queue[object]) -> None:
        self.closed.set()
        q.put_nowait(_DEAD)


def _parse_frame(line: bytes) -> tuple[str, str]:
    s = line.decode("utf-8", "replace").rstrip("\r\n")
    if s.startswith("READY\t"):
        return ("READY", s[len("READY\t") :])  # token is plain, not base64
    if s == "INT":
        return ("INT", "")
    tag, _, rest = s.partition("\t")
    payload = base64.b64decode(rest).decode("utf-8", "replace") if rest else ""
    return (tag, payload)
