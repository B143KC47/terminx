import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_epoch_ms(ms: int | float) -> datetime:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


@dataclass
class UsageRecord:
    ts: datetime
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_read_tokens


def iter_json_lines(path: Path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def mtime_utc(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


_cache: dict[str, tuple[float, int, list[UsageRecord]]] = {}
_json_cache: dict[str, tuple[float, int, object]] = {}


def cached_json_parse(path: Path, fn) -> object:
    try:
        st = path.stat()
    except OSError:
        return None
    key = (str(path), fn.__name__)
    hit = _json_cache.get(key)
    if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
        return hit[2]
    value = fn(path)
    _json_cache[key] = (st.st_mtime, st.st_size, value)
    return value


def parse_file_cached(path: Path, parser) -> list[UsageRecord]:
    try:
        st = path.stat()
    except OSError:
        return []
    key = str(path)
    hit = _cache.get(key)
    if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
        return hit[2]
    records = parser(path)
    _cache[key] = (st.st_mtime, st.st_size, records)
    return records


def read_tail(path: Path, max_bytes: int = 524288) -> list[str]:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            start = max(0, size - max_bytes)
            fh.seek(start)
            data = fh.read().decode("utf-8", errors="ignore")
        if start > 0:
            data = data.split("\n", 1)[-1]
        return data.splitlines()
    except OSError:
        return []


def read_head(path: Path, max_bytes: int = 524288) -> list[str]:
    try:
        with open(path, "rb") as fh:
            data = fh.read(max_bytes).decode("utf-8", errors="ignore")
        return data.splitlines()
    except OSError:
        return []


def aggregate(records: list[UsageRecord], since: datetime) -> dict[str, int]:
    out = {"input": 0, "output": 0, "cache_read": 0, "total": 0}
    for r in records:
        if r.ts >= since:
            out["input"] += r.input_tokens
            out["output"] += r.output_tokens
            out["cache_read"] += r.cache_read_tokens
            out["total"] += r.total
    return out


def find_usage_dicts(obj, path=""):
    if isinstance(obj, dict):
        if "input_tokens" in obj and "output_tokens" in obj:
            yield obj
        for v in obj.values():
            yield from find_usage_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from find_usage_dicts(v)
