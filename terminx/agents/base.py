from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from ..core.processes import running_pids
from ..core.usage import UsageRecord, utcnow


@dataclass
class SessionInfo:
    agent: str
    cwd: str | None = None
    model: str | None = None
    provider: str | None = None
    branch: str | None = None
    last_activity: datetime | None = None
    source: str = ""
    pid: int | None = None
    status: str = "offline"
    detail: str = ""
    resume_cmd: list[str] | None = None


@dataclass
class QuotaWindow:
    label: str
    seconds: int
    used: int = 0
    limit: int | None = None
    used_percent: float | None = None
    reset_at: str | None = None
    countdown: str | None = None

    @property
    def pct(self) -> float | None:
        if self.used_percent is not None:
            return self.used_percent
        if self.limit:
            return self.used / self.limit * 100
        return None


@dataclass
class Quota:
    provider: str
    plan: str | None = None
    windows: list[QuotaWindow] = field(default_factory=list)


class AgentAdapter(ABC):
    name: str = ""
    process_names: list[str] = []
    primary_process: str | None = None

    @abstractmethod
    def find_sessions(self, cfg: dict) -> list[SessionInfo]:
        ...

    @abstractmethod
    def usage_records(self, since: datetime, cfg: dict) -> list[UsageRecord]:
        ...

    def quota(self, cfg: dict) -> Quota | None:
        return None

    def detect_status(self, s: SessionInfo, cfg: dict) -> SessionInfo:
        pids = running_pids(*self.process_names)
        if not pids:
            s.status = "offline"
            return s
        if s.cwd:
            pid = self.resolve_pid(s)
            if pid is None:
                s.status = "offline"
                s.detail = "no live process in dir"
                return s
            s.pid = pid
        else:
            s.pid = pids[0]
        now = utcnow()
        if s.last_activity is None:
            s.status = "running"
            return s
        age = (now - s.last_activity).total_seconds()
        if age <= cfg.get("working_threshold_sec", 60):
            s.status = "working"
        elif age <= cfg.get("blocked_threshold_sec", 600):
            s.status = "blocked"
            s.detail = f"waiting {int(age)}s"
        else:
            s.status = "idle"
            s.detail = f"idle {int(age)}s"
        return s

    def resolve_pid(self, s: SessionInfo) -> int | None:
        return None

    def sessions(self, cfg: dict) -> list[SessionInfo]:
        out = []
        for s in self.find_sessions(cfg):
            self.detect_status(s, cfg)
            out.append(s)
        return out

    @staticmethod
    def _merge_usage(a: UsageRecord, b: UsageRecord) -> UsageRecord:
        return UsageRecord(
            ts=b.ts,
            input_tokens=max(0, b.input_tokens - a.input_tokens),
            output_tokens=max(0, b.output_tokens - a.output_tokens),
            cache_read_tokens=max(0, b.cache_read_tokens - a.cache_read_tokens),
        )
