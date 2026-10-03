import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..core.usage import (
    UsageRecord,
    cached_json_parse,
    iter_json_lines,
    mtime_utc,
    parse_file_cached,
    parse_ts,
    read_tail,
    utcnow,
)
from ..i18n import t
from .base import AgentAdapter, Quota, SessionInfo
from .quota import fetch_claude_quota

CACHE_READ_KEYS = (
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
    "cache_read_creation_input_tokens",
)


class ClaudeAdapter(AgentAdapter):
    name = "claude"
    process_names = ["claude"]
    primary_process = "claude"

    def _root(self, cfg: dict) -> Path:
        return Path(cfg.get("paths", {}).get("claude", Path.home() / ".claude"))

    def find_sessions(self, cfg: dict) -> list[SessionInfo]:
        root = self._root(cfg) / "projects"
        if not root.exists():
            return []
        hours = cfg.get("show_recent_hours", 24)
        since = utcnow() - timedelta(hours=hours)

        rows: list[SessionInfo] = []
        fallback_model = self._settings_model(cfg)
        for proj in root.iterdir():
            if not proj.is_dir():
                continue
            try:
                files = [p for p in proj.iterdir() if p.suffix == ".jsonl"]
            except OSError:
                continue
            if not files:
                continue
            for file in files:
                try:
                    last = mtime_utc(file)
                    if last < since:
                        continue
                    info = self._read_session(file, last, fallback_model)
                    if info:
                        info.data_root = str(self._root(cfg))
                        rows.append(info)
                except OSError:
                    continue
        rows.sort(
            key=lambda s: s.last_activity or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return rows

    @staticmethod
    def _settings_model(cfg: dict) -> str | None:
        settings = (
            Path(cfg.get("paths", {}).get("claude", Path.home() / ".claude"))
            / "settings.json"
        )
        if not settings.exists():
            return None
        try:
            data = json.loads(settings.read_text(encoding="utf-8", errors="ignore"))
            model = data.get("model") or (data.get("env") or {}).get("ANTHROPIC_MODEL")
            return model
        except (OSError, json.JSONDecodeError):
            return None

    def _read_session(
        self, f: Path, last: datetime, fallback_model: str | None = None
    ) -> SessionInfo | None:
        meta = cached_json_parse(f, self._read_session_tail)
        cwd = meta.get("cwd")
        if not cwd:
            return None
        model = meta.get("model")
        if not model or model == "<synthetic>":
            model = fallback_model or model
        detail = t("awaiting reply") if meta.get("waiting") else ""
        return SessionInfo(
            agent=self.name,
            cwd=cwd,
            model=model,
            last_activity=last,
            source=str(f),
            session_id=f.stem,
            activity_path=str(f),
            detail=detail,
            resume_cmd=["claude", "-r", f.stem],
        )

    @staticmethod
    def _read_session_tail(f: Path) -> dict:
        cwd: str | None = None
        model: str | None = None
        waiting = False
        for line in read_tail(f, 1_000_000):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            kind = obj.get("type")
            if isinstance(obj.get("cwd"), str):
                cwd = obj["cwd"]
            if kind == "assistant":
                msg = obj.get("message") if isinstance(obj.get("message"), dict) else {}
                if msg.get("model"):
                    model = msg["model"]
                waiting = False
            elif kind == "user" and not obj.get("isSidechain"):
                waiting = True
        return {"cwd": cwd, "model": model, "waiting": waiting}

    def quota(self, cfg: dict) -> Quota | None:
        return fetch_claude_quota(cfg)

    def usage_records(self, since: datetime, cfg: dict) -> list[UsageRecord]:
        root = self._root(cfg) / "projects"
        if not root.exists():
            return []
        out: list[UsageRecord] = []
        for proj in root.iterdir():
            if not proj.is_dir():
                continue
            for f in proj.glob("*.jsonl"):
                try:
                    if mtime_utc(f) >= since - timedelta(minutes=5):
                        out.extend(parse_file_cached(f, self._parse_usage_file))
                except OSError:
                    continue
        return out

    @staticmethod
    def _parse_usage_file(f: Path) -> list[UsageRecord]:
        records: list[UsageRecord] = []
        for obj in iter_json_lines(f):
            ts = parse_ts(obj.get("timestamp") or "")
            if obj.get("type") != "assistant":
                continue
            msg = obj.get("message") or {}
            usage = msg.get("usage") or {}
            if not usage:
                continue
            cache = 0
            for k in CACHE_READ_KEYS:
                cache += usage.get(k, 0)
            records.append(
                UsageRecord(
                    ts=ts or mtime_utc(f),
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                    cache_read_tokens=cache,
                )
            )
        return records
