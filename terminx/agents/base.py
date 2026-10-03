from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from ..core.processes import normalize_path, running_pids, running_pids_with_cwd
from ..core.usage import UsageRecord


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
    session_id: str = ""
    data_root: str = ""
    title: str = ""
    parent_id: str | None = None
    status_source: str = ""
    status_at: datetime | None = None
    turn_id: str = ""
    runtime: "RuntimeBinding | None" = None
    activity_path: str = ""
    presence: str = "unverified"
    input_tokens: int | None = None
    output_tokens: int | None = None
    context_percent: float | None = None

    @property
    def key(self) -> tuple[str, str, str]:
        return (
            self.agent,
            normalize_path(self.data_root),
            self.session_id or self.source,
        )


@dataclass
class RuntimeBinding:
    pid: int
    created_at: float
    wt_session: str = ""
    launch_id: str = ""
    console_hwnd: int = 0


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
    source: str = ""
    account_id: str = ""
    fetched_at: datetime | None = None
    availability: str = "ok"
    reason: str = ""
    official_url: str = ""
    limited: bool = False


class AgentAdapter(ABC):
    name: str = ""
    process_names: list[str] = []
    primary_process: str | None = None

    @abstractmethod
    def find_sessions(self, cfg: dict) -> list[SessionInfo]: ...

    @abstractmethod
    def usage_records(self, since: datetime, cfg: dict) -> list[UsageRecord]: ...

    def quota(self, cfg: dict) -> Quota | None:
        return None

    def detect_status(
        self,
        s: SessionInfo,
        cfg: dict,
        pids: list[int] | None = None,
        pids_by_cwd: dict[str, int] | None = None,
    ) -> SessionInfo:
        if pids is None:
            pids = running_pids(*self.process_names)
        if not pids:
            s.status = "offline"
            return s
        if s.cwd:
            if pids_by_cwd is None:
                pid = self.resolve_pid(s)
            else:
                pid = pids_by_cwd.get(normalize_path(s.cwd))
            if pid is None:
                s.status = "offline"
                s.detail = "no live process in dir"
                return s
            s.pid = pid
        else:
            s.pid = pids[0]
        # Directory matches are candidates, never proof of a live session.
        s.pid = None
        s.status = "unknown"
        s.detail = "Runtime association unverified"
        return s

    def resolve_pid(self, s: SessionInfo) -> int | None:
        if not s.cwd:
            return None
        target = normalize_path(s.cwd)
        for pid, cwd in running_pids_with_cwd(self.process_names).items():
            if normalize_path(cwd) == target:
                return pid
        return None

    def sessions(self, cfg: dict) -> list[SessionInfo]:
        limit = max(0, int(cfg.get("max_rows_per_agent", 6)))
        if limit == 0:
            return []
        pids = running_pids(*self.process_names)
        if not pids:
            return []

        pids_by_cwd = None
        if type(self).resolve_pid is AgentAdapter.resolve_pid:
            pids_by_cwd = {
                normalize_path(cwd): pid
                for pid, cwd in running_pids_with_cwd(self.process_names).items()
                if cwd
            }

        out = []
        live_count = 0
        claimed_sessions: set[tuple] = set()
        for s in self.find_sessions(cfg):
            self.detect_status(s, cfg, pids=pids, pids_by_cwd=pids_by_cwd)
            is_live = s.status != "offline"
            if is_live:
                if s.key in claimed_sessions:
                    continue
                claimed_sessions.add(s.key)
                live_count += 1
            out.append(s)
            if is_live and live_count >= limit:
                break
        return out

    @staticmethod
    def _merge_usage(a: UsageRecord, b: UsageRecord) -> UsageRecord:
        return UsageRecord(
            ts=b.ts,
            input_tokens=max(0, b.input_tokens - a.input_tokens),
            output_tokens=max(0, b.output_tokens - a.output_tokens),
            cache_read_tokens=max(0, b.cache_read_tokens - a.cache_read_tokens),
        )
