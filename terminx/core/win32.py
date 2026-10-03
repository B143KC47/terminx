import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
user32.GetForegroundWindow.restype = wintypes.HWND
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND

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
    """Map an agent process to its terminal tab through the console owner."""
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


def find_terminal_window(
    strong: list[str], weak: list[str], agent_pid: int | None = None
) -> int | None:
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


def focus_window(hwnd: int) -> bool:
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)
    user32.ShowWindow(hwnd, 5)
    user32.SetForegroundWindow(hwnd)
    return user32.GetForegroundWindow() == hwnd


def native_console_for_pid(hwnd, pid):
    if not user32.IsWindowVisible(hwnd):
        return False
    name = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, name, 256)
    if name.value != "ConsoleWindowClass":
        return False
    from .live import console_for_pid

    return console_for_pid(pid) == hwnd


def pseudo_console_owner(hwnd, pid):
    from .live import console_for_pid

    name = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, name, len(name))
    if name.value != "PseudoConsoleWindow" or console_for_pid(pid) != hwnd:
        return 0
    owner = user32.GetParent(hwnd)
    user32.GetClassNameW(owner, name, len(name))
    return owner if name.value == "CASCADIA_HOSTING_WINDOW_CLASS" else 0
