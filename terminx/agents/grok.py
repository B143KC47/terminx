"""Grok Build's on-disk session index (never read prompts for discovery)."""

import json
from datetime import timedelta
from pathlib import Path
from urllib.parse import unquote

from ..core.usage import cached_json_parse, mtime_utc, utcnow
from .base import AgentAdapter, SessionInfo


class GrokAdapter(AgentAdapter):
    name = "grok"
    process_names = ["grok"]

    def _root(self, cfg):
        return Path(cfg.get("paths", {}).get("grok", Path.home() / ".grok"))

    def find_sessions(self, cfg):
        root = self._root(cfg)
        since = utcnow() - timedelta(hours=cfg.get("show_recent_hours", 24))
        rows = []
        for file in (root / "sessions").glob("*/*/summary.json"):
            try:
                activity = file.parent / "updates.jsonl"
                last = mtime_utc(activity if activity.exists() else file)
                if last < since:
                    continue
                meta = cached_json_parse(file, _read_summary)
                if not isinstance(meta, dict):
                    continue
                info = meta.get("info") if isinstance(meta.get("info"), dict) else {}
                cwd = (
                    info.get("cwd")
                    or info.get("working_directory")
                    or info.get("workingDirectory")
                )
                if not cwd:
                    cwd_file = file.parent.parent / ".cwd"
                    cwd = (
                        cwd_file.read_text(encoding="utf-8").strip()
                        if cwd_file.exists()
                        else unquote(file.parent.parent.name)
                    )
                sid = file.parent.name
                context = None
                signals_file = file.parent / "signals.json"
                if signals_file.exists():
                    try:
                        signals = cached_json_parse(signals_file, _read_summary)
                        used, total = (
                            signals.get("contextTokensUsed"),
                            signals.get("contextWindowTokens"),
                        )
                        if (
                            isinstance(used, (int, float))
                            and isinstance(total, (int, float))
                            and total > 0
                            and used >= 0
                        ):
                            context = used / total * 100
                    except (ValueError, TypeError, AttributeError, OSError):
                        pass
                rows.append(
                    SessionInfo(
                        agent=self.name,
                        session_id=sid,
                        data_root=str(root),
                        cwd=cwd,
                        title=meta.get("generated_title") or "",
                        model=meta.get("current_model_id"),
                        source=str(file),
                        activity_path=str(activity),
                        last_activity=last,
                        context_percent=context,
                        resume_cmd=["grok", "--resume", sid],
                    )
                )
            except (OSError, ValueError, TypeError):
                continue
        return sorted(rows, key=lambda s: s.last_activity, reverse=True)

    def usage_records(self, since, cfg):
        return []


def _read_summary(path):
    return json.loads(path.read_text(encoding="utf-8"))
