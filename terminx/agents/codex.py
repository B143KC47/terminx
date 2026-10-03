import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

from ..core.paths import provider_home
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

    def quota(self, cfg: dict) -> Quota | None:
        return fetch_codex_quota(cfg)

    def _root(self, cfg: dict) -> Path:
        path = Path(cfg.get("paths", {}).get("codex") or provider_home("codex"))
        return path / "sessions" if (path / "sessions").is_dir() else path

    def _rollout_files(self, root: Path, since: datetime) -> list[Path]:
        out: list[tuple[float, Path]] = []
        since_ts = since.timestamp()

        def entries(path) -> list[os.DirEntry]:
            try:
                with os.scandir(path) as iterator:
                    return list(iterator)
            except OSError:
                return []

        for year in entries(root):
            if not year.is_dir():
                continue
            for month in entries(year.path):
                if not month.is_dir():
                    continue
                for day in entries(month.path):
                    if not day.is_dir():
                        continue
                    for entry in entries(day.path):
                        if not (
                            entry.is_file()
                            and entry.name.startswith("rollout-")
                            and entry.name.endswith(".jsonl")
                        ):
                            continue
                        try:
                            modified = entry.stat().st_mtime
                        except OSError:
                            continue
                        if modified >= since_ts:
                            out.append((modified, Path(entry.path)))
        out.sort(key=lambda item: item[0], reverse=True)
        return [path for _, path in out]

    def find_sessions(self, cfg: dict) -> list[SessionInfo]:
        root = self._root(cfg)
        if not root.exists():
            return []
        hours = cfg.get("show_recent_hours", 24)
        since = utcnow() - timedelta(hours=hours)
        files = self._rollout_files(root, since)

        seen: dict[str, SessionInfo] = {}
        for f in files:
            session = self.session_from_file(f, root)
            if not session:
                continue
            key = session.session_id
            if key in seen:
                continue
            seen[key] = session
        return list(seen.values())

    def session_from_file(self, file, root=None):
        file = Path(file)
        meta = cached_json_parse(file, self._read_meta)
        if (
            not meta
            or not meta.get("cwd")
            or meta.get("thread_source") not in {None, "cli"}
        ):
            return None
        if root is None:
            root = next((p for p in file.parents if p.name == "sessions"), file.parent)
        sid = meta.get("id") or _session_id(file.stem)
        return SessionInfo(
            self.name,
            cwd=meta["cwd"],
            model=meta.get("model"),
            last_activity=mtime_utc(file),
            source=str(file),
            session_id=sid,
            data_root=str(root.parent if root.name == "sessions" else root),
            activity_path=str(file),
            parent_id=meta.get("parent_id"),
            detail=meta.get("cli_version") or "",
            resume_cmd=["codex", "resume", sid],
        )

    @staticmethod
    def _read_meta(f: Path) -> dict:
        meta: dict = {}
        for line in read_head(f, 500_000):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict) or not isinstance(
                obj.get("payload", {}), dict
            ):
                continue
            kind = obj.get("type")
            payload = obj.get("payload") or {}
            if kind == "session_meta":
                meta["id"] = payload.get("id")
                source = payload.get("source")
                meta["thread_source"] = (
                    source
                    if isinstance(source, str)
                    else "subagent"
                    if source
                    else None
                )
                meta["parent_id"] = payload.get("forked_from_id") or payload.get(
                    "parent_id"
                )
                if payload.get("cwd"):
                    meta["cwd"] = payload["cwd"]
                if payload.get("cli_version"):
                    meta["cli_version"] = payload["cli_version"]
            elif (
                kind == "event_msg" and payload.get("type") == "thread_settings_applied"
            ):
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
                if not isinstance(obj, dict) or not isinstance(
                    obj.get("payload", {}), dict
                ):
                    continue
                payload = obj.get("payload") or {}
                if (
                    obj.get("type") == "event_msg"
                    and payload.get("type") == "thread_settings_applied"
                ):
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
    m = re.search(
        r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$", stem
    )
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
