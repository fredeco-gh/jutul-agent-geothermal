"""Holds the running sessions and stands new ones up on request.

The manager maps a session id to its ``SessionHost``. New sessions are built by
a *host factory*, which defaults to standing up a real session from the
simulator registry. Tests inject a factory that returns a host wrapping fakes,
so the server can be exercised without a Julia kernel or a model.

Concurrency limits and idle eviction are layered on top of this in a later
step; for now it is a straightforward registry with a lock around mutation.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from jutul_agent.interfaces.server.session_host import SessionHost

HostFactory = Callable[..., Awaitable[SessionHost]]


async def _default_host_factory(
    *,
    sim: str,
    model: str | None,
    approval_mode: str | None,
    workspace: Any | None,
    resume: bool,
    session_id: str | None,
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
    )


class SessionManager:
    """Registry of running ``SessionHost``s, keyed by session id."""

    def __init__(self, *, host_factory: HostFactory | None = None) -> None:
        self._host_factory = host_factory or _default_host_factory
        self._hosts: dict[str, SessionHost] = {}
        self._lock = asyncio.Lock()

    async def create(
        self,
        *,
        sim: str,
        model: str | None = None,
        approval_mode: str | None = None,
        workspace: Any | None = None,
    ) -> SessionHost:
        host = await self._host_factory(
            sim=sim,
            model=model,
            approval_mode=approval_mode,
            workspace=workspace,
            resume=False,
            session_id=None,
        )
        async with self._lock:
            self._hosts[host.session_id] = host
        return host

    async def resume(
        self,
        session_id: str,
        *,
        sim: str,
        model: str | None = None,
        approval_mode: str | None = None,
        workspace: Any | None = None,
    ) -> SessionHost:
        host = await self._host_factory(
            sim=sim,
            model=model,
            approval_mode=approval_mode,
            workspace=workspace,
            resume=True,
            session_id=session_id,
        )
        async with self._lock:
            self._hosts[host.session_id] = host
        return host

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
