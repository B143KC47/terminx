import csv
import io
import os
import subprocess
import threading
import time


def normalize_path(p: str) -> str:
    """Case- and separator-insensitive path key for cwd comparisons (Windows).

    Session files may store ``C:/foo`` while psutil reports ``C:\\foo``.
    """
    return p.lower().replace("/", "\\").rstrip("\\")


_snapshot: list[tuple[int, str]] = []
_snapshot_at = 0.0
_TTL = 3.0
_refresh_lock = threading.Lock()

_cwd_cache: dict[int, tuple[float, str]] = {}
_cwd_lock = threading.Lock()


def _toolhelp_rows() -> list[tuple[int, str]]:
    if os.name != "nt":
        raise OSError("Toolhelp is only available on Windows")

    import ctypes
    from ctypes import wintypes

    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    rows: list[tuple[int, str]] = []
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        ok = kernel32.Process32FirstW(handle, ctypes.byref(entry))
        if not ok and ctypes.get_last_error() not in (0, 18):
            raise ctypes.WinError(ctypes.get_last_error())
        while ok:
            name = entry.szExeFile.lower().removesuffix(".exe")
            rows.append((int(entry.th32ProcessID), name))
            ok = kernel32.Process32NextW(handle, ctypes.byref(entry))
        if ctypes.get_last_error() not in (0, 18):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel32.CloseHandle(handle)
    return rows


def _tasklist_rows() -> list[tuple[int, str]]:
    out = subprocess.run(
        ["tasklist", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout
    rows = []
    for parts in csv.reader(io.StringIO(out)):
        if len(parts) < 2:
            continue
        name = parts[0].lower().removesuffix(".exe")
        try:
            pid = int(parts[1])
        except ValueError:
            continue
        rows.append((pid, name))
    return rows


def _psutil_rows() -> list[tuple[int, str]]:
    import psutil

    rows = []
    for process in psutil.process_iter(["pid", "name"]):
        try:
            name = (process.info.get("name") or "").lower().removesuffix(".exe")
            rows.append((int(process.info["pid"]), name))
        except (KeyError, TypeError, ValueError, psutil.Error):
            continue
    return rows


def _read_process_rows() -> list[tuple[int, str]]:
    if os.name == "nt":
        try:
            return _toolhelp_rows()
        except OSError:
            return _tasklist_rows()
    return _psutil_rows()


def _refresh() -> None:
    global _snapshot, _snapshot_at
    now = time.monotonic()
    if now - _snapshot_at < _TTL:
        return
    with _refresh_lock:
        now = time.monotonic()
        if now - _snapshot_at < _TTL:
            return
        try:
            rows = _read_process_rows()
        except Exception:
            _snapshot = []
            _snapshot_at = now
            return
        _snapshot = rows
        _snapshot_at = now
        live_pids = {pid for pid, _ in rows}
        with _cwd_lock:
            for pid in list(_cwd_cache):
                if pid not in live_pids:
                    _cwd_cache.pop(pid, None)


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
        with _cwd_lock:
            hit = _cwd_cache.get(pid)
        if hit and now - hit[0] < _TTL:
            out[pid] = hit[1]
            continue
        try:
            cwd = psutil.Process(pid).cwd() or ""
        except Exception:
            cwd = ""
        with _cwd_lock:
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
