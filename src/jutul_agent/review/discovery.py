"""Find sessions to review across every workspace on this machine.

The session store is per-workspace (``$STATE_HOME/workspaces/<hash>/sessions/``),
but mining is a cross-cutting, developer-facing job: "review everything I've run
lately, wherever I ran it". This module walks all workspaces, lists every recorded
session, marks which have already been reviewed (their id appears in the findings
log), and renders any session's trace by path — independent of which workspace is
currently active.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from jutul_agent.paths import state_home
from jutul_agent.session import _started_from_id, read_session_title


@dataclass(frozen=True)
class DiscoveredSession:
    """One recorded session found on disk, anywhere on the machine."""

    session_id: str
    trace_path: Path
    workspace: str  # the workspace-hash directory the session lives under
    title: str | None
    started: datetime
    reviewed: bool

    @property
    def state_dir(self) -> Path:
        return self.trace_path.parent


def workspaces_root() -> Path:
    return state_home() / "workspaces"


def eval_sessions_state_root(simulator: str) -> Path:
    """A stable, discoverable home for an eval run's sessions.

    The eval harness otherwise drops each session in a temp dir that is cleaned up,
    so eval runs — where a golden answer is known and silent failures are most worth
    catching — can't be reviewed. Pointing the eval session's ``state_root`` here puts
    its trace under ``workspaces/eval-<sim>/sessions/``, which ``discover_sessions``
    finds like any other session; the workspace name marks it as an eval run.
    """
    return workspaces_root() / f"eval-{simulator}"


def _first_event_payload(trace_path: Path, kind: str) -> dict | None:
    """The payload of the earliest event of ``kind`` in a trace, read cheaply."""
    import json
    import sqlite3

    try:
        con = sqlite3.connect(f"file:{trace_path}?mode=ro", uri=True)
        try:
            row = con.execute(
                "SELECT payload_json FROM events WHERE kind=? ORDER BY id LIMIT 1", (kind,)
            ).fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return None
    if not row:
        return None
    try:
        payload = json.loads(row[0])
        return payload if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        return None


def session_simulator(trace_path: Path) -> str | None:
    """The simulator a session ran, read from its ``session_start`` event."""
    payload = _first_event_payload(trace_path, "session_start")
    return (payload or {}).get("simulator") or None


def session_ground_truth(trace_path: Path) -> str | None:
    """The expected answer recorded for an eval session, if any (``eval_target``)."""
    payload = _first_event_payload(trace_path, "eval_target")
    return (payload or {}).get("expected") or None


def session_eval_result(trace_path: Path) -> dict | None:
    """The eval verdict linked onto a session (``eval_result``): passed, task, scores."""
    return _first_event_payload(trace_path, "eval_result")


def eval_review_context(trace_path: Path) -> str | None:
    """A one-line ground-truth note for the reviewer: expected answer and verdict."""
    expected = session_ground_truth(trace_path)
    result = session_eval_result(trace_path)
    parts = []
    if expected:
        parts.append(f"expected {expected}")
    if result is not None:
        parts.append("the eval graded this run as " + ("PASS" if result.get("passed") else "FAIL"))
    return "; ".join(parts) or None


def reviewed_session_ids() -> set[str]:
    """Ids of every session that already has at least one logged review."""
    from jutul_agent.review.findings import load_reports

    return {r.session_id for r in load_reports() if r.session_id}


def discover_sessions(
    *, pending_only: bool = False, limit: int | None = None
) -> list[DiscoveredSession]:
    """Every session across all workspaces, newest first.

    ``pending_only`` drops sessions that already have a logged review; ``limit``
    caps the result after sorting, so it always keeps the most recent.
    """
    reviewed = reviewed_session_ids()
    root = workspaces_root()
    found: list[DiscoveredSession] = []
    if root.is_dir():
        for ws in root.iterdir():
            sessions = ws / "sessions"
            if not sessions.is_dir():
                continue
            for entry in sessions.iterdir():
                trace = entry / "trace.sqlite"
                if not entry.is_dir() or not trace.exists():
                    continue
                started = _started_from_id(entry.name)
                if started is None:
                    started = datetime.fromtimestamp(entry.stat().st_mtime)
                found.append(
                    DiscoveredSession(
                        session_id=entry.name,
                        trace_path=trace,
                        workspace=ws.name,
                        title=read_session_title(entry),
                        started=started,
                        reviewed=entry.name in reviewed,
                    )
                )
    found.sort(key=lambda s: s.started, reverse=True)
    if pending_only:
        found = [s for s in found if not s.reviewed]
    return found[:limit] if limit is not None else found


def find_session(arg: str) -> DiscoveredSession | None:
    """Resolve an exact id or unique prefix to a session in any workspace."""
    arg = arg.strip()
    if not arg:
        return None
    sessions = discover_sessions()
    exact = next((s for s in sessions if s.session_id == arg), None)
    if exact is not None:
        return exact
    matches = [s for s in sessions if s.session_id.startswith(arg)]
    return matches[0] if len(matches) == 1 else None


def render_trace(trace_path: Path) -> str:
    """Markdown of a session's whole trace, read from its database by path."""
    from jutul_agent.trace import TraceLog
    from jutul_agent.transcript import render_markdown

    return render_markdown(TraceLog(trace_path).iter_events())


def render_trace_html(trace_path: Path) -> str:
    """Self-contained HTML of a session's trace, read by path."""
    from jutul_agent.trace import TraceLog
    from jutul_agent.transcript import render_html

    return render_html(TraceLog(trace_path).iter_events())
