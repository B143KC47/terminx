"""UI-independent collection; session and network polling have different callers."""

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

from ..agents.base import RuntimeBinding, SessionInfo
from .events import EventJournal, apply_event, state_dir
from .integrations import atomic_write
from .live import LiveProcesses, is_rollout
from .logevents import JsonlTail, event_from_log
from .paths import configured_home
from .processes import normalize_path
from .usage import utcnow


def runtime_alive(binding):
    if not binding:
        return False
    try:
        import psutil

        return (
            abs(psutil.Process(binding.pid).create_time() - binding.created_at) < 0.01
        )
    except (psutil.Error, OSError):
        return False


class Monitor:
    def __init__(self, adapters, cfg, live_processes=None):
        self.adapters, self.cfg = adapters, cfg
        self.journal = EventJournal(state_dir(cfg))
        self.tail = JsonlTail()
        self.sessions = {}
        self.seq = 0
        self.last_discovery = 0
        self.errors = []
        self.last_prune = 0
        self.live_processes = (
            live_processes
            if live_processes is not None
            else LiveProcesses(a.name for a in adapters)
        )
        self.open_clis = []
        self.registrations = {}

    def merge(self, row):
        if row.key not in self.sessions:
            row.status = "unknown"
            self.sessions[row.key] = row
        else:
            old = self.sessions[row.key]
            for attr in (
                "source",
                "cwd",
                "model",
                "title",
                "resume_cmd",
                "activity_path",
                "context_percent",
            ):
                if getattr(row, attr):
                    setattr(old, attr, getattr(row, attr))
            if row.last_activity and (
                not old.last_activity or row.last_activity > old.last_activity
            ):
                old.last_activity = row.last_activity

    def discover_open_files(self):
        # An already-open Codex rollout remains discoverable beyond the history cutoff.
        codex = next((a for a in self.adapters if a.name == "codex"), None)
        if codex is None or not hasattr(codex, "session_from_file"):
            return
        for cli in self.open_clis:
            if cli.agent != "codex":
                continue
            for path in cli.files:
                if not is_rollout(path):
                    continue
                try:
                    row = codex.session_from_file(path)
                    if isinstance(row, SessionInfo):
                        self.merge(row)
                except (OSError, ValueError, TypeError):
                    self.errors.append("codex: unreadable open rollout")

    def associate_terminals(self):
        """One row per admitted interactive process; folders never establish identity."""
        associated = {}
        for cli in self.open_clis:
            identity = cli.pid, cli.created_at
            files = {normalize_path(p) for p in cli.files}
            candidates = [
                s
                for s in self.sessions.values()
                if s.agent == cli.agent and s.session_id
            ]
            registered = [
                s for s in candidates if self.registrations.get(s.key) == identity
            ]
            held = [
                s
                for s in candidates
                if s.activity_path and normalize_path(s.activity_path) in files
            ]
            # A unique passive registration can disambiguate other open subagent files.
            choices = (
                held if len(held) == 1 else registered if len(registered) == 1 else []
            )
            if len(choices) == 1:
                session = choices[0]
            else:
                source = f"terminal:{cli.pid}:{cli.created_at:.6f}"
                session = SessionInfo(
                    cli.agent,
                    cwd=cli.cwd,
                    source=source,
                    data_root=str(configured_home(cli.agent, self.cfg)),
                    status="unknown",
                )
                session = self.sessions.setdefault(session.key, session)
            if session.key in associated:
                # Two processes claiming one native session cannot be silently merged.
                source = f"terminal:{cli.pid}:{cli.created_at:.6f}"
                session = SessionInfo(
                    cli.agent,
                    cwd=cli.cwd,
                    source=source,
                    data_root=str(configured_home(cli.agent, self.cfg)),
                    status="unknown",
                    runtime=RuntimeBinding(
                        cli.pid, cli.created_at, console_hwnd=cli.console_hwnd
                    ),
                )
                self.sessions[session.key] = session
            old = session.runtime
            same = old and (old.pid, old.created_at) == identity
            session.runtime = RuntimeBinding(
                cli.pid,
                cli.created_at,
                old.wt_session if same else "",
                old.launch_id if same else "",
                cli.console_hwnd,
            )
            if old and not same and session.status == "exited":
                (
                    session.status,
                    session.status_at,
                    session.turn_id,
                    session.status_source,
                ) = "unknown", None, "", ""
            self.bind_launch(session, cli)
            associated[session.key] = identity
        return associated

    def bind_launch(self, session, cli):
        # Positive native file evidence can register a termiX launch without new hooks.
        if not session.session_id or session.runtime.launch_id:
            return
        directory = state_dir(self.cfg) / "launches"
        matches = []
        for path in directory.glob("*.json"):
            if not re.fullmatch(r"[a-f0-9]{32}", path.stem):
                continue
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                if record.get("agent") != cli.agent or normalize_path(
                    record.get("data_root", "")
                ) != normalize_path(session.data_root):
                    continue
                if (
                    record.get("session_id")
                    and record["session_id"] != session.session_id
                ):
                    continue
                if record.get("pid") not in {cli.pid, *cli.ancestors}:
                    continue
                if not runtime_alive(
                    RuntimeBinding(record["pid"], record.get("created_at", 0))
                ):
                    continue
                matches.append((path, record))
            except (OSError, ValueError, TypeError, AttributeError):
                continue
        if len(matches) == 1:
            path, record = matches[0]
            if not record.get("session_id"):
                record["session_id"] = session.session_id
                try:
                    atomic_write(path, json.dumps(record))
                except OSError:
                    self.errors.append("Terminal registration: write failed")
                    return
            session.runtime.launch_id = path.stem

    def scan(self):
        self.errors = []
        now = time.monotonic()
        if self.journal.path.exists() and now - self.last_prune > 3600:
            try:
                self.journal.prune()
                self.last_prune = now
            except Exception as exc:
                self.errors.append(f"Event journal: {type(exc).__name__}")
        if now - self.last_discovery >= max(1, self.cfg.get("refresh_sec", 3)):

            def discover(a):
                try:
                    return a.find_sessions(self.cfg), None
                except Exception as exc:
                    return [], f"{a.name}: {type(exc).__name__}"

            with ThreadPoolExecutor(max_workers=max(1, len(self.adapters))) as pool:
                results = list(pool.map(discover, self.adapters))
            for rows, error in results:
                if error:
                    self.errors.append(error)
                for row in rows:
                    self.merge(row)
            try:
                self.open_clis = self.live_processes.scan()
            except (OSError, ValueError, TypeError) as exc:
                self.open_clis = []
                self.errors.append(f"Terminal discovery: {type(exc).__name__}")
            self.discover_open_files()
            self.last_discovery = now
        for session in list(self.sessions.values()):
            if session.activity_path:
                rows, reset = self.tail.read(session.activity_path)
                if reset and session.status_source == "log":
                    session.status, session.status_at, session.turn_id = (
                        "unknown",
                        None,
                        "",
                    )
                for obj in rows:
                    try:
                        event = event_from_log(session, obj)
                        if event:
                            apply_event(session, event)
                    except (ValueError, TypeError, AttributeError, OverflowError):
                        error = f"{session.agent}: malformed log record"
                        if error not in self.errors:
                            self.errors.append(error)
        try:
            for seq, event in self.journal.read(self.seq):
                self.seq = seq
                key = event.agent, normalize_path(event.data_root), event.session_id
                if event.agent not in {a.name for a in self.adapters}:
                    self.seq = seq
                    continue
                s = self.sessions.setdefault(
                    key,
                    SessionInfo(
                        event.agent,
                        session_id=event.session_id,
                        data_root=event.data_root,
                        status="unknown",
                    ),
                )
                try:
                    apply_event(s, event)
                    if (
                        s.runtime
                        and event.data.get("pid")
                        and event.data.get("created_at")
                    ):
                        self.registrations[s.key] = s.runtime.pid, s.runtime.created_at
                except (ValueError, TypeError, AttributeError, OverflowError):
                    self.errors.append(f"{event.agent}: malformed event")
                    continue
                if not s.resume_cmd:
                    flag = {
                        "codex": "resume",
                        "claude": "--resume",
                        "kimi": "--session",
                        "grok": "--resume",
                        "opencode": "--session",
                    }[s.agent]
                    s.resume_cmd = [s.agent, flag, s.session_id]
                self.seq = seq
        except Exception as exc:
            self.errors.append(f"Event journal: {type(exc).__name__}")
        associated = self.associate_terminals()
        cutoff = time.time() - self.cfg.get("show_recent_hours", 24) * 3600
        for key, session in list(self.sessions.items()):
            if session.runtime:
                live = runtime_alive(session.runtime)
                session.presence = (
                    "live"
                    if live and key in associated
                    else "exited"
                    if not live
                    else "unverified"
                )
                session.pid = session.runtime.pid if live else None
                if not live:
                    session.status = "exited"
            else:
                session.presence = "unverified"
            if session.source.startswith("terminal:") and session.presence != "live":
                del self.sessions[key]
                continue
            if (
                session.presence != "live"
                and session.last_activity
                and session.last_activity.timestamp() < cutoff
            ):
                del self.sessions[key]
        # Copy snapshots: UI and collector threads never share mutable rows.
        rows = sorted(
            self.sessions.values(),
            key=lambda s: s.last_activity or utcnow(),
            reverse=True,
        )
        return deepcopy(rows), list(self.errors)


def collect_sessions(adapters, cfg):
    """Legacy adapter seam retained for third-party TUI adapters."""
    rows, errors = [], []
    for adapter in adapters:
        try:
            rows.extend(s for s in adapter.sessions(cfg) if s.status != "offline")
        except Exception as exc:
            errors.append(f"{adapter.name}: {type(exc).__name__}")
    return rows, errors
