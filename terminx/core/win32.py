import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

TERMINAL_PROCS = {"windowsterminal.exe", "conhost.exe", "openconsole.exe"}


def _enum_windows() -> list[int]:
    results: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, lparam):
        results.append(hwnd)
        return True

    user32.EnumWindows(callback, 0)
    return results


def _window_title(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if not length:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _process_name(hwnd: int) -> str:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        import psutil

        return psutil.Process(pid.value).name().lower()
    except Exception:
        return ""


def _ancestors(pid: int, max_depth: int = 10) -> list[int]:
    import psutil

    chain = []
    cur = pid
    for _ in range(max_depth):
        try:
            pp = psutil.Process(cur)
        except Exception:
            break
        chain.append(pp.pid)
        cur = pp.ppid()
    return chain


def _window_pids() -> dict[int, int]:
    out = {}
    for hwnd in _enum_windows():
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        out[hwnd] = pid.value
    return out


def _normalize_title(title: str) -> str:
    import re

    t = re.sub(r"^[^\w]+", "", title)
    t = re.sub(r"\s*\.\.\.$", "", t)
    return t.lower()


def _title_score(title: str, strong: list[str], weak: list[str]) -> int:
    score = 0
    for f in strong:
        if f in title:
            score += 2
        elif f.split()[0] in title:
            score += 1
    for w in weak:
        if w in title:
            score += 1
    return score


def _tab_of_process(pid: int) -> int | None:
    """Map an agent process to its visible terminal tab window via the console-owning ancestor."""
    chain = _ancestors(pid)
    win_pids = _window_pids()
    by_pid: dict[int, int] = {}
    for hwnd, wpid in win_pids.items():
        by_pid.setdefault(wpid, hwnd)
    for cpid in chain:
        console_hwnd = by_pid.get(cpid)
        if not console_hwnd:
            continue
        parent = user32.GetParent(console_hwnd)
        if parent and parent in win_pids:
            return parent
        if parent:
            return parent
        return console_hwnd
    return None


def pid_cwd_matches(pid: int | None, cwd: str | None) -> bool:
    if not pid or not cwd:
        return False
    import psutil

    from .processes import normalize_path

    try:
        return normalize_path(psutil.Process(pid).cwd() or "") == normalize_path(cwd)
    except Exception:
        return False


def find_terminal_window(strong: list[str], weak: list[str], agent_pid: int | None = None) -> int | None:
    """Find the terminal window (tab) hosting the session.

    Primary: walk the agent process's ancestor chain to its console-owning
    window and GetParent to the visible tab. Fallback: match window titles,
    which agents set to the project folder name (spinner prefix + '...' truncation).
    """
    if agent_pid:
        hwnd = _tab_of_process(agent_pid)
        if hwnd:
            return hwnd
    strong = [s.lower() for s in strong if s]
    weak = [w.lower() for w in weak if w]
    best: int | None = None
    best_score = 0
    for hwnd in _enum_windows():
        if not user32.IsWindowVisible(hwnd):
            continue
        if _process_name(hwnd) not in TERMINAL_PROCS:
            continue
        title = _normalize_title(_window_title(hwnd))
        if not title:
            continue
        score = _title_score(title, strong, weak)
        if score > best_score:
            best = hwnd
            best_score = score
    return best if best_score > 0 else None


def focus_window(hwnd: int) -> None:
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)
    user32.ShowWindow(hwnd, 5)
    user32.SetForegroundWindow(hwnd)
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, 2, 0)
