import subprocess
import time


def normalize_path(p: str) -> str:
    """Case- and separator-insensitive path key for cwd comparisons (Windows).

    Session files may store ``C:/foo`` while psutil reports ``C:\\foo``.
    """
    return p.lower().replace("/", "\\").rstrip("\\")


_snapshot: list[tuple[int, str]] = []
_snapshot_at = 0.0
_TTL = 3.0

_cwd_cache: dict[int, tuple[float, str]] = {}


def _refresh() -> None:
    global _snapshot, _snapshot_at
    now = time.monotonic()
    if now - _snapshot_at < _TTL:
        return
    try:
        out = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except Exception:
        _snapshot = []
        _snapshot_at = now
        return
    rows = []
    for line in out.splitlines():
        parts = line.split('","')
        if len(parts) < 2:
            continue
        name = parts[0].strip('"').lower().removesuffix(".exe")
        try:
            pid = int(parts[1].strip('"'))
        except ValueError:
            continue
        rows.append((pid, name))
    _snapshot = rows
    _snapshot_at = now


def _bare(name: str) -> str:
    return name.lower().removesuffix(".exe")


def running_pids(*names: str) -> list[int]:
    _refresh()
    wanted = {_bare(n) for n in names}
    return [pid for pid, name in _snapshot if name in wanted]


def running_pids_with_cwd(names: list[str]) -> dict[int, str]:
    """Map pid -> cwd for running processes matching any of the given names.

    Uses the cached tasklist snapshot (cheap) for name matching, then a
    per-pid psutil cwd lookup (0.1ms each) with its own cache.
    """
    import psutil

    _refresh()
    wanted = {_bare(n) for n in names}
    now = time.monotonic()
    out: dict[int, str] = {}
    for pid, name in _snapshot:
        if name not in wanted:
            continue
        hit = _cwd_cache.get(pid)
        if hit and now - hit[0] < _TTL:
            out[pid] = hit[1]
            continue
        try:
            cwd = psutil.Process(pid).cwd() or ""
        except Exception:
            cwd = ""
        _cwd_cache[pid] = (now, cwd)
        if cwd:
            out[pid] = cwd
    return out


def is_running(*names: str) -> bool:
    return bool(running_pids(*names))


def cpu_usage(pid: int) -> float | None:
    try:
        import psutil

        return psutil.Process(pid).cpu_percent(interval=None)
    except Exception:
        return None
