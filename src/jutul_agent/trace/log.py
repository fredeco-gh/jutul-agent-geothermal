"""Per-session SQLite trace log.

Append-only event store at ``<state_dir>/trace.sqlite``. Renderers
(see ``core.transcript``) consume it to produce transcripts and other
artifacts.

Common event kinds include ``session_start``, ``session_end``,
``message_user``, ``message_assistant``, ``message_reasoning``,
``tool_call``, ``tool_result``, ``hitl_request``, ``hitl_response``,
and ``artifact``. An ``artifact`` payload looks like::

    {"path": "artifacts/plot-<id>.png", "mime": "image/png",
     "caption": "optional label", "tool_call_id": "<id or null>",
     "format": "png", "size_px": [800, 500], "dpi": null,
     "slot": null, "source_code": "<julia snippet>"}
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp    TEXT NOT NULL,
    kind         TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_kind_idx ON events(kind);
"""


@dataclass(frozen=True)
class Event:
    id: int
    timestamp: str
    kind: str
    payload: dict[str, Any]


class TraceLog:
    """Append-only event log for a single session."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)

    def append(self, kind: str, payload: dict[str, Any]) -> None:
        ts = datetime.now(UTC).isoformat()
        self._conn.execute(
            "INSERT INTO events (timestamp, kind, payload_json) VALUES (?, ?, ?)",
            (ts, kind, json.dumps(payload, default=str)),
        )

    def iter_events(self) -> list[Event]:
        rows = self._conn.execute(
            "SELECT id, timestamp, kind, payload_json FROM events ORDER BY id"
        ).fetchall()
        return [Event(id=r[0], timestamp=r[1], kind=r[2], payload=json.loads(r[3])) for r in rows]

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> TraceLog:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
