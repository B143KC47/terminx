import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..core.processes import running_pids_with_cwd, normalize_path
from ..core.usage import (
    UsageRecord,
    cached_json_parse,
    iter_json_lines,
    mtime_utc,
    parse_epoch_ms,
    parse_file_cached,
    read_tail,
    utcnow,
)
from .base import AgentAdapter, Quota, SessionInfo
from .quota import fetch_kimi_quota


def _read_state_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, json.JSONDecodeError):
        return None


class KimiAdapter(AgentAdapter):
    name = "kimi"
    process_names = ["kimi"]
    primary_process = "kimi"

    def resolve_pid(self, s: SessionInfo) -> int | None:
        if not s.cwd:
            return None
        procs = running_pids_with_cwd(["kimi", "kimi.exe"])
        target = normalize_path(s.cwd)
        for pid, cwd in procs.items():
            if normalize_path(cwd) == target:
                return pid
        return None

    def quota(self, cfg: dict) -> Quota | None:
        return fetch_kimi_quota(cfg)

    def _root(self, cfg: dict) -> Path:
        return Path(cfg.get("paths", {}).get("kimi", Path.home() / ".kimi-code"))

    def find_sessions(self, cfg: dict) -> list[SessionInfo]:
        root = self._root(cfg) / "sessions"
        if not root.exists():
            return []
        hours = cfg.get("show_recent_hours", 24)
        since = utcnow() - timedelta(hours=hours)
        rows: list[SessionInfo] = []
        for wd in root.iterdir():
            if not wd.is_dir() or not wd.name.startswith("wd_"):
                continue
            for sdir in wd.iterdir():
                if not sdir.is_dir():
                    continue
                state = sdir / "state.json"
                if not state.exists():
                    continue
                meta = cached_json_parse(state, _read_state_json)
                if not meta:
                    continue
                wire = sdir / "agents" / "main" / "wire.jsonl"
                last = mtime_utc(wire) if wire.exists() else mtime_utc(state)
                if last < since:
                    continue
                model = cached_json_parse(wire, self._read_model) if wire.exists() else None
                cwd = meta.get("workDir")
                title = (meta.get("title") or "")[:24]
                rows.append(
                    SessionInfo(
                        agent=self.name,
                        cwd=cwd,
                        model=model,
                        last_activity=last,
                        source=str(sdir),
                        detail=title,
                        resume_cmd=["kimi", "-c"],
                    )
                )
        rows.sort(key=lambda s: s.last_activity or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return rows[: cfg.get("max_rows_per_agent", 6)]

    @staticmethod
    def _read_model(wire: Path) -> str | None:
        model = None
        for line in read_tail(wire, 500_000):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") == "llm.request" and obj.get("model"):
                model = obj["model"]
        return model

    def usage_records(self, since: datetime, cfg: dict) -> list[UsageRecord]:
        root = self._root(cfg) / "sessions"
        if not root.exists():
            return []
        out: list[UsageRecord] = []
        for wd in root.iterdir():
            if not wd.is_dir() or not wd.name.startswith("wd_"):
                continue
            for sdir in wd.iterdir():
                if not sdir.is_dir():
                    continue
                wire = sdir / "agents" / "main" / "wire.jsonl"
                if wire.exists():
                    try:
                        if mtime_utc(wire) >= since - timedelta(minutes=5):
                            out.extend(parse_file_cached(wire, self._parse_usage_file))
                    except OSError:
                        continue
        return out

    @staticmethod
    def _parse_usage_file(f: Path) -> list[UsageRecord]:
        records: list[UsageRecord] = []
        for obj in iter_json_lines(f):
            if obj.get("type") != "usage.record":
                continue
            usage = obj.get("usage") or {}
            ts = parse_epoch_ms(obj.get("time") or 0)
            input_other = usage.get("inputOther", 0)
            cache_read = usage.get("inputCacheRead", 0)
            cache_create = usage.get("inputCacheCreation", 0)
            output = usage.get("output", 0)
            total = input_other + cache_read + cache_create + output
            if total <= 0:
                continue
            records.append(
                UsageRecord(
                    ts=ts,
                    input_tokens=input_other + cache_create,
                    output_tokens=output,
                    cache_read_tokens=cache_read,
                )
            )
        return records
