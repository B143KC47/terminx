import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from ..core.processes import running_pids_with_cwd
from ..core.usage import (
    UsageRecord,
    cached_json_parse,
    mtime_utc,
    parse_ts,
    read_head,
    read_tail,
    utcnow,
)
from .base import AgentAdapter, Quota, SessionInfo
from .quota import fetch_codex_quota


class CodexAdapter(AgentAdapter):
    name = "codex"
    process_names = ["codex", "codex-code-mode-host"]
    primary_process = "codex"

    def resolve_pid(self, s: SessionInfo) -> int | None:
        if not s.cwd:
            return None
        procs = running_pids_with_cwd(["codex", "codex.exe", "codex-code-mode-host", "codex-code-mode-host.exe"])
        target = s.cwd.lower().rstrip("\\/")
        for pid, cwd in procs.items():
            if cwd.lower().rstrip("\\/") == target:
                return pid
        return None

    def quota(self, cfg: dict) -> Quota | None:
        return fetch_codex_quota(cfg)

    def _root(self, cfg: dict) -> Path:
        return Path(cfg.get("paths", {}).get("codex", Path.home() / ".codex" / "sessions"))

    def _rollout_files(self, root: Path, since: datetime) -> list[Path]:
        out = []
        for year in root.iterdir():
            if not year.is_dir():
                continue
            for month in year.iterdir():
                if not month.is_dir():
                    continue
                for p in month.glob("*/rollout-*.jsonl"):
                    try:
                        if mtime_utc(p) >= since:
                            out.append(p)
                    except OSError:
                        continue
        return out

    def find_sessions(self, cfg: dict) -> list[SessionInfo]:
        root = self._root(cfg)
        if not root.exists():
            return []
        hours = cfg.get("show_recent_hours", 24)
        since = utcnow() - timedelta(hours=hours)
        files = self._rollout_files(root, since)
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        seen: dict[str, SessionInfo] = {}
        for f in files:
            meta = cached_json_parse(f, self._read_meta)
            if not meta:
                continue
            cwd = meta.get("cwd")
            if not cwd:
                continue
            key = str(cwd).lower()
            if key in seen:
                continue
            last = mtime_utc(f)
            seen[key] = SessionInfo(
                agent=self.name,
                cwd=cwd,
                model=meta.get("model"),
                last_activity=last,
                source=str(f),
                detail=meta.get("cli_version", "") or "",
                resume_cmd=["codex", "resume", _session_id(f.stem)],
            )
            if len(seen) >= cfg.get("max_rows_per_agent", 6):
                break
        return list(seen.values())

    @staticmethod
    def _read_meta(f: Path) -> dict:
        meta: dict = {}
        for line in read_head(f, 500_000):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = obj.get("type")
            payload = obj.get("payload") or {}
            if kind == "session_meta":
                if payload.get("cwd"):
                    meta["cwd"] = payload["cwd"]
                if payload.get("cli_version"):
                    meta["cli_version"] = payload["cli_version"]
            elif kind == "event_msg" and payload.get("type") == "thread_settings_applied":
                model = payload.get("thread_settings", {}).get("model")
                if model:
                    meta["model"] = model
            if meta.get("cwd") and meta.get("model"):
                break
        if not meta.get("model"):
            for line in read_tail(f, 500_000):
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payload = obj.get("payload") or {}
                if obj.get("type") == "event_msg" and payload.get("type") == "thread_settings_applied":
                    model = payload.get("thread_settings", {}).get("model")
                    if model:
                        meta["model"] = model
                        break
        return meta

    def usage_records(self, since: datetime, cfg: dict) -> list[UsageRecord]:
        root = self._root(cfg)
        if not root.exists():
            return []
        files = self._rollout_files(root, since - timedelta(minutes=5))
        out: list[UsageRecord] = []
        for f in files:
            rec = cached_json_parse(f, self._parse_usage_file)
            if rec:
                out.append(rec)
        return out

    @staticmethod
    def _parse_usage_file(f: Path) -> UsageRecord | None:
        first: tuple[int, int, int] | None = None
        last: tuple[int, int, int] | None = None
        last_ts: datetime | None = None
        for line in read_head(f, 512_000):
            snap = _extract_snapshot(line)
            if snap:
                first = snap
                break
        for line in read_tail(f, 1_500_000):
            snap = _extract_snapshot(line)
            if snap:
                last = snap
                ts = _line_ts(line)
                if ts:
                    last_ts = ts
        if first is None or last is None:
            return None
        if first == last:
            rec = UsageRecord(
                ts=last_ts or mtime_utc(f),
                input_tokens=first[0],
                output_tokens=first[1],
                cache_read_tokens=first[2],
            )
        else:
            rec = UsageRecord(
                ts=last_ts or mtime_utc(f),
                input_tokens=max(0, last[0] - first[0]),
                output_tokens=max(0, last[1] - first[1]),
                cache_read_tokens=max(0, last[2] - first[2]),
            )
        return rec if rec.total > 0 else None


_SNAP_RE = re.compile(
    r'"total_token_usage":\{"input_tokens":(\d+),"cached_input_tokens":(\d+),'
    r'"cache_write_input_tokens":\d+,"output_tokens":(\d+),"reasoning_output_tokens":(\d+),'
    r'"total_tokens":\d+\}'
)
_TS_RE = re.compile(r'"timestamp":"([\dT:.Z-]+)"')


def _session_id(stem: str) -> str:
    m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$", stem)
    return m.group(1) if m else stem


def _extract_snapshot(line: str) -> tuple[int, int, int] | None:
    m = _SNAP_RE.search(line)
    if not m:
        return None
    input_tok = int(m.group(1))
    cached = int(m.group(2))
    output = int(m.group(3)) + int(m.group(4))
    return input_tok, output, cached


def _line_ts(line: str) -> datetime | None:
    m = _TS_RE.search(line)
    return parse_ts(m.group(1)) if m else None
