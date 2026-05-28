"""The Session object: unit of work for one jutul-agent invocation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path

from jutul_agent.agent.memory import create_ephemeral_memory_dir, remove_ephemeral_memory_dir
from jutul_agent.julia.session import JuliaSession
from jutul_agent.paths import session_output_dir, workspace_state_dir
from jutul_agent.simulators.base import SimulatorAdapter
from jutul_agent.trace import TraceLog


def sessions_root(state_root: Path | None = None) -> Path:
    """Where session subdirectories live.

    Defaults to ``$STATE_HOME/workspaces/<hash>/sessions/`` via
    ``workspace_state_dir()``. Tests can pass an explicit ``state_root``
    that holds ``sessions/`` directly.
    """
    base = state_root if state_root is not None else workspace_state_dir()
    return base / "sessions"


def session_dir(session_id: str, *, state_root: Path | None = None) -> Path:
    return sessions_root(state_root) / session_id


def last_session_path(state_root: Path | None = None) -> Path:
    base = state_root if state_root is not None else workspace_state_dir()
    return base / "last-session"


def read_last_session(state_root: Path | None = None) -> str | None:
    p = last_session_path(state_root)
    if not p.exists():
        return None
    sid = p.read_text(encoding="utf-8").strip()
    return sid or None


def write_last_session(session_id: str, *, state_root: Path | None = None) -> None:
    p = last_session_path(state_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(session_id, encoding="utf-8")


def _ensure_jutul_agent_gitignore(output_dir: Path) -> None:
    """Drop a ``.gitignore`` at the root of ``<workspace>/jutul-agent/`` so
    generated sessions, transcripts, and reports stay out of the user's repo.

    ``output_dir`` is ``<workspace>/jutul-agent/sessions/<date>-<sid>/``; the
    gitignore goes two levels up at ``<workspace>/jutul-agent/.gitignore``.
    """
    root = output_dir.parent.parent
    gitignore = root / ".gitignore"
    if gitignore.exists():
        return
    gitignore.write_text("*\n", encoding="utf-8")


@dataclass
class Session:
    """A live jutul-agent session. Construct via ``Session.create``.

    Direct construction is supported for tests that want to wire a Session
    around a pre-built trace, but production code should always go through
    ``create`` so the on-disk layout and the ``session_start`` lifecycle
    event are guaranteed.
    """

    julia: JuliaSession
    state_dir: Path
    output_dir: Path
    trace: TraceLog
    simulator: SimulatorAdapter
    session_id: str
    ephemeral_memory: bool = False
    _ephemeral_memory_dir: Path | None = field(default=None, repr=False)

    @classmethod
    def create(
        cls,
        *,
        julia: JuliaSession,
        simulator: SimulatorAdapter,
        session_id: str | None = None,
        state_root: Path | None = None,
        ephemeral_memory: bool = False,
    ) -> Session:
        sid = session_id or str(uuid.uuid4())
        dir_ = session_dir(sid, state_root=state_root)
        dir_.mkdir(parents=True, exist_ok=True)

        out_dir = session_output_dir(sid)
        try:
            (out_dir / "artifacts").mkdir(parents=True, exist_ok=True)
            _ensure_jutul_agent_gitignore(out_dir)
        except OSError:
            out_dir = dir_  # fall back to state_dir if workspace is not writable

        trace = TraceLog(dir_ / "trace.sqlite")
        trace.append(
            "session_start",
            {"session_id": sid, "simulator": simulator.name},
        )
        ephemeral_dir = create_ephemeral_memory_dir() if ephemeral_memory else None
        return cls(
            julia=julia,
            state_dir=dir_,
            output_dir=out_dir,
            trace=trace,
            simulator=simulator,
            session_id=sid,
            ephemeral_memory=ephemeral_memory,
            _ephemeral_memory_dir=ephemeral_dir,
        )

    def memory_dir(self, *, workspace_memory: Path) -> Path:
        """Resolved memory directory for this session."""
        if self.ephemeral_memory and self._ephemeral_memory_dir is not None:
            return self._ephemeral_memory_dir
        return workspace_memory

    def finalize(self) -> None:
        self.trace.append("session_end", {"session_id": self.session_id})
        self.trace.close()
        if self.ephemeral_memory:
            remove_ephemeral_memory_dir(self._ephemeral_memory_dir)
            self._ephemeral_memory_dir = None
