from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..core.processes import running_pids_with_cwd, normalize_path
from ..core.usage import cached_json_parse, parse_ts, utcnow
from ..i18n import t
from .base import AgentAdapter, SessionInfo


def _kv(line: str) -> dict[str, str]:
    import json

    out: dict[str, str] = {}
    for tok in line.split():
        if "=" in tok:
            k, _, v = tok.partition("=")
            if v.startswith('"'):
                try:
                    v = json.loads(v)
                except Exception:
                    v = v.strip('"')
            out[k] = v
    return out


class OpenCodeAdapter(AgentAdapter):
    name = "opencode"
    process_names = ["opencode"]
    primary_process = "opencode"

    def resolve_pid(self, s: SessionInfo) -> int | None:
        if not s.cwd:
            return None
        procs = running_pids_with_cwd(["opencode", "opencode.exe"])
        target = normalize_path(s.cwd)
        for pid, cwd in procs.items():
            if normalize_path(cwd) == target:
                return pid
        return None

    def _root(self, cfg: dict) -> Path:
        return Path(cfg.get("paths", {}).get("opencode", Path.home() / ".local/share/opencode"))

    def _log_path(self, cfg: dict) -> Path:
        return self._root(cfg) / "log" / "opencode.log"

    def _parse_log(self, path: Path) -> dict[str, dict]:
        sessions: dict[str, dict] = {}
        try:
            with open(path, "rb") as fh:
                fh.seek(0, 2)
                size = fh.tell()
                start = max(0, size - 2_000_000)
                fh.seek(start)
                text = fh.read().decode("utf-8", errors="ignore")
            lines = text.splitlines()[-4000:]
        except OSError:
            return sessions
        for line in lines:
            kv = _kv(line)
            ts = parse_ts(kv.get("timestamp") or "")
            msg = kv.get("message")
            sid = kv.get("session.id")
            if not sid and msg == "created":
                cand = kv.get("id") or ""
                if cand.startswith("ses_"):
                    sid = cand
            if not sid:
                continue
            entry = sessions.setdefault(
                sid, {"id": sid, "directory": None, "last_seen": ts, "asking": None}
            )
            if msg == "created" and kv.get("directory") and not entry["directory"]:
                entry["directory"] = kv["directory"]
            elif msg == "stream":
                if kv.get("providerID"):
                    entry["provider"] = kv["providerID"]
                if kv.get("modelID"):
                    entry["model"] = kv["modelID"]
            elif msg == "asking":
                entry["asking"] = ts
            if ts and (entry["last_seen"] is None or ts > entry["last_seen"]):
                entry["last_seen"] = ts
        return sessions

    def find_sessions(self, cfg: dict) -> list[SessionInfo]:
        log = self._log_path(cfg)
        if not log.exists():
            return []
        sessions = cached_json_parse(log, self._parse_log)
        if sessions is None:
            sessions = {}
        hours = cfg.get("show_recent_hours", 24)
        since = utcnow() - timedelta(hours=hours)
        rows: list[SessionInfo] = []
        for entry in sessions.values():
            last = entry.get("last_seen")
            if last and last < since:
                continue
            detail = t("permission prompt") if entry.get("asking") else ""
            rows.append(
                SessionInfo(
                    agent=self.name,
                    cwd=entry.get("directory"),
                    model=entry.get("model"),
                    provider=entry.get("provider"),
                    last_activity=last,
                    source=entry.get("id", ""),
                    detail=detail,
                    resume_cmd=["opencode", "--session", entry.get("id", "")],
                )
            )
        rows.sort(key=lambda s: s.last_activity or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return rows[: cfg.get("max_rows_per_agent", 6)]

    def usage_records(self, since: datetime, cfg: dict) -> list:
        return []
