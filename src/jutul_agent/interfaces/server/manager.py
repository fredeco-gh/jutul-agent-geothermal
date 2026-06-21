"""Holds the running sessions and stands new ones up on request.

The manager maps a session id to its ``SessionHost``. New sessions are built by
a *host factory*, which defaults to standing up a real session from the
simulator registry. Tests inject a factory that returns a host wrapping fakes,
so the server can be exercised without a Julia kernel or a model.

Each live host holds a Julia kernel (a real OS process, hundreds of MB) and a
SQLite checkpointer open, so the registry is bounded: it keeps the most recently
created/resumed sessions and closes the rest (LRU). Without this, browsing back
through history — each resume stands up a fresh host — would accumulate kernels
until the server stops. A closed session stays fully resumable; only its live
kernel is reclaimed.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Any

from jutul_agent.interfaces.server.session_host import SessionHost

if TYPE_CHECKING:
    from jutul_agent.agent.capabilities import Capability

HostFactory = Callable[..., Awaitable[SessionHost]]

# How many live sessions (and so Julia kernels) to keep at once. A single user
# works in one session at a time; a few extra cover quickly flipping between
# recent chats. The oldest beyond this are closed (and stay resumable on disk).
DEFAULT_MAX_LIVE = 4


async def _default_host_factory(
    *,
    sim: str,
    model: str | None,
    approval_mode: str | None,
    workspace: Any | None,
    resume: bool,
    session_id: str | None,
    extensions: Sequence[Capability],
) -> SessionHost:
    """Build a real session host for a simulator named in the request."""
    from jutul_agent.simulators import registry

    adapter = registry.get(sim)
    return await SessionHost.start(
        simulator=adapter,
        model=model,
        approval_mode=approval_mode,
        workspace=workspace,
        resume=resume,
        session_id=session_id,
        extensions=extensions,
    )


class SessionManager:
    """Registry of running ``SessionHost``s, keyed by session id."""

    def __init__(
        self, *, host_factory: HostFactory | None = None, max_live: int = DEFAULT_MAX_LIVE
    ) -> None:
        self._host_factory = host_factory or _default_host_factory
        # Insertion order is recency: a (re)registered host moves to the end, so
        # the front is the least recently created/resumed and is evicted first.
        self._hosts: OrderedDict[str, SessionHost] = OrderedDict()
        self._lock = asyncio.Lock()
        self._max_live = max(1, max_live)

    async def create(
        self,
        *,
        sim: str,
        model: str | None = None,
        approval_mode: str | None = None,
        workspace: Any | None = None,
        extensions: Sequence[Capability] = (),
    ) -> SessionHost:
        host = await self._host_factory(
            sim=sim,
            model=model,
            approval_mode=approval_mode,
            workspace=workspace,
            resume=False,
            session_id=None,
            extensions=extensions,
        )
        await self._register(host)
        return host

    async def resume(
        self,
        session_id: str,
        *,
        sim: str,
        model: str | None = None,
        approval_mode: str | None = None,
        workspace: Any | None = None,
        extensions: Sequence[Capability] = (),
    ) -> SessionHost:
        host = await self._host_factory(
            sim=sim,
            model=model,
            approval_mode=approval_mode,
            workspace=workspace,
            resume=True,
            session_id=session_id,
            extensions=extensions,
        )
        await self._register(host)
        return host

    async def _register(self, host: SessionHost) -> None:
        """Add ``host`` as the most-recent session, then close any it displaces.

        A host already registered under this id (a re-resume) is replaced and the
        stale one closed, and anything beyond ``max_live`` is evicted oldest-first.
        Kernels are torn down outside the lock so a slow shutdown can't block other
        sessions; eviction never raises (a closed kernel stays resumable on disk).
        """
        to_close: list[SessionHost] = []
        async with self._lock:
            stale = self._hosts.pop(host.session_id, None)
            if stale is not None and stale is not host:
                to_close.append(stale)
            self._hosts[host.session_id] = host  # newest → most-recently-used end
            while len(self._hosts) > self._max_live:
                _sid, evicted = self._hosts.popitem(last=False)  # oldest
                to_close.append(evicted)
        for old in to_close:
            with contextlib.suppress(Exception):
                await old.aclose()

    def get(self, session_id: str) -> SessionHost | None:
        return self._hosts.get(session_id)

    def list_ids(self) -> list[str]:
        return list(self._hosts)

    async def close(self, session_id: str) -> bool:
        async with self._lock:
            host = self._hosts.pop(session_id, None)
        if host is None:
            return False
        await host.aclose()
        return True

    async def aclose(self) -> None:
        """Close every running session (used on server shutdown)."""
        for session_id in self.list_ids():
            await self.close(session_id)
