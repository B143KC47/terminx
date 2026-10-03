"""Small, local, metadata-only event journal shared by hooks and both UIs."""

import json
import math
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path


def state_dir(cfg=None):
    return Path(
        (cfg or {}).get("state_dir")
        or os.environ.get("TERMINX_STATE_DIR")
        or Path.home() / ".config" / "terminx"
    )


@dataclass
class SessionEvent:
    agent: str
    session_id: str
    data_root: str
    kind: str
    at: float
    source: str = "hook"
    turn_id: str = ""
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    data: dict = field(default_factory=dict)


class EventJournal:
    def __init__(self, directory=None):
        self.path = Path(directory or state_dir()) / "events.sqlite3"

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=0.2)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute(
            "CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, id TEXT UNIQUE, at REAL, body TEXT)"
        )
        try:
            with db:
                yield db
        finally:
            db.close()

    def append(self, event):
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO events(id,at,body) VALUES (?,?,?)",
                (
                    event.event_id,
                    event.at,
                    json.dumps(asdict(event), ensure_ascii=False),
                ),
            )

    def read(self, after=0):
        if not self.path.exists():
            return []
        with self.connect() as db:
            rows = db.execute(
                "SELECT seq,body FROM events WHERE seq>? ORDER BY seq LIMIT 10000",
                (after,),
            ).fetchall()
        out = []
        for seq, body in rows:
            try:
                out.append((seq, SessionEvent(**json.loads(body))))
            except (TypeError, ValueError):
                continue
        return out

    def prune(self):
        with self.connect() as db:
            db.execute("DELETE FROM events WHERE at<?", (time.time() - 7 * 86400,))


ATTENTION = {"waiting_approval", "waiting_input", "error"}
ACTIVE = {"processing", "outputting", "tool_running"}
LABELS = {
    "unknown": "Unknown",
    "processing": "Processing",
    "outputting": "Outputting",
    "tool_running": "Running tool",
    "waiting_approval": "Waiting for approval",
    "waiting_input": "Waiting for answer",
    "ready": "Ready for instructions",
    "completed": "Turn ended · ready",
    "interrupted": "Interrupted",
    "paused": "Paused",
    "exited": "Exited",
    "error": "Error",
    "offline": "Offline",
    "working": "Processing",
    "blocked": "Waiting for approval",
    "running": "Processing",
    "idle": "Ready for instructions",
}


def apply_event(session, event):
    """Never let an old turn, Stop candidate, or heartbeat finish a new turn."""
    from datetime import datetime, timezone

    from ..agents.base import RuntimeBinding

    previous = session.status_at.timestamp() if session.status_at else 0
    if (
        not isinstance(event.at, (int, float))
        or not math.isfinite(event.at)
        or event.at <= 0
        or event.at > time.time() + 30
    ):
        return False
    data = event.data
    if not isinstance(data, dict):
        return False
    if (
        session.runtime
        and data.get("created_at")
        and data["created_at"] < session.runtime.created_at
    ):
        return False  # A delayed hook from an earlier runtime cannot end a resumed session.
    if (
        data.get("pid")
        and data.get("created_at")
        and (not session.runtime or data["created_at"] >= session.runtime.created_at)
    ):
        session.runtime = RuntimeBinding(
            pid=int(data["pid"]),
            created_at=float(data["created_at"]),
            wt_session=str(data.get("wt_session") or ""),
            launch_id=str(data.get("launch_id") or ""),
            console_hwnd=int(data.get("console_hwnd") or 0),
        )
    # Compare both times at datetime precision. Float-to-datetime rounding can
    # otherwise reject the next record with the same native timestamp.
    if datetime.fromtimestamp(event.at, timezone.utc).timestamp() < previous:
        return False
    for attr in ("cwd", "title", "model", "parent_id", "activity_path"):
        if data.get(attr):
            setattr(session, attr, data[attr])
    for attr in ("input_tokens", "output_tokens", "context_percent"):
        if isinstance(data.get(attr), (int, float)):
            setattr(session, attr, data[attr])
    kind = event.kind
    if kind in {"heartbeat", "usage", "stop_candidate", "queued"}:
        return True
    if event.turn_id and session.turn_id and event.turn_id != session.turn_id:
        if kind not in {"processing", "turn_started", "outputting"}:
            return False
    mapping = {
        "session_started": "ready",
        "turn_started": "processing",
        "tool_finished": "processing",
    }
    status = mapping.get(kind, kind)
    if status not in LABELS:
        return False
    session.status = status
    session.status_at = datetime.fromtimestamp(event.at, timezone.utc)
    session.last_activity = session.status_at
    session.status_source = event.source
    if event.turn_id:
        session.turn_id = event.turn_id
    session.detail = ""
    return True
