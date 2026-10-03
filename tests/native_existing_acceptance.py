"""Opt-in focus checks for existing, untagged Windows Terminal tabs and panes."""

import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psutil

from terminx.agents.base import RuntimeBinding, SessionInfo
from terminx.core.live import console_for_pid

os.environ["QT_SCALE_FACTOR"] = "1"
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from terminx.ui.sidebar import Sidebar


def read_title(pid):
    code = """import ctypes, sys
kernel = ctypes.windll.kernel32
kernel.FreeConsole()
if not kernel.AttachConsole(int(sys.argv[1])): raise SystemExit(1)
value = ctypes.create_unicode_buffer(65536)
kernel.GetConsoleTitleW(value, len(value))
print(value.value)
kernel.FreeConsole()
"""
    return subprocess.run(
        [sys.executable, "-c", code, str(pid)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=3,
        creationflags=subprocess.CREATE_NO_WINDOW,
    ).stdout.strip()


def verify_focused_probe(token):
    # Read only the model-free fixture's visible text, independently of the locator.
    script = """
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$focused = [System.Windows.Automation.AutomationElement]::FocusedElement
if ($focused.Current.ClassName -ne 'TermControl') { Write-Output 'False'; exit }
$text = $focused.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern).DocumentRange.GetText(-1)
Write-Output ($text.Contains('__TOKEN__'))
""".replace("__TOKEN__", token)
    return (
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        ).stdout.strip()
        == "True"
    )


def main():
    if os.name != "nt":
        raise SystemExit("Windows required")
    root = Path(__file__).resolve().parents[1]
    artifacts = root / "_artifacts"
    artifacts.mkdir(exist_ok=True)
    run = uuid.uuid4().hex
    files = []
    sessions = []
    results = {}
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    directory = tempfile.TemporaryDirectory()
    sidebar = Sidebar({"lang": "en", "state_dir": directory.name}, start_workers=False)
    sidebar.setWindowTitle("terminX native focus acceptance")
    user = ctypes.windll.user32
    user.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user.mouse_event.argtypes = [
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_size_t,
    ]
    user.WindowFromPoint.argtypes = [wintypes.POINT]
    user.WindowFromPoint.restype = wintypes.HWND
    user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetAncestor.restype = wintypes.HWND
    cursor = wintypes.POINT()
    user.GetCursorPos(ctypes.byref(cursor))

    def check(name, session):
        original = read_title(session.runtime.pid)
        started = time.monotonic()
        receipt = []

        def completed(name, value):
            if name == "focus":
                receipt.append(value)

        sidebar.bus.done.connect(completed)
        sidebar.accept_sessions([session], [])
        sidebar.reveal()
        QTest.qWait(150)
        point = sidebar.list.viewport().mapToGlobal(
            sidebar.list.visualItemRect(sidebar.list.item(0)).center()
        )
        under = user.GetAncestor(
            user.WindowFromPoint(wintypes.POINT(point.x(), point.y())), 2
        )
        user.SetCursorPos(point.x(), point.y())
        clicked_point = wintypes.POINT()
        user.GetCursorPos(ctypes.byref(clicked_point))
        user.mouse_event(2, 0, 0, 0, 0)
        QTest.qWait(50)
        user.mouse_event(4, 0, 0, 0, 0)
        QTest.qWait(50)
        deadline = time.monotonic() + 8
        while not receipt and time.monotonic() < deadline:
            QTest.qWait(25)
        sidebar.bus.done.disconnect(completed)
        if not receipt:
            results[name] = {
                "error": "click pending or missed",
                "focus_pending": "focus" in sidebar.callbacks,
                "list_enabled": sidebar.list.isEnabled(),
                "point": [point.x(), point.y()],
                "actual_cursor": [clicked_point.x, clicked_point.y],
                "under_pointer": under,
                "sidebar_hwnd": int(sidebar.winId()),
                "ratio": sidebar.devicePixelRatioF(),
            }
            sidebar.grab().save(str(artifacts / "native-click-failure.png"))
            (artifacts / "native-existing-failure.json").write_text(
                json.dumps(results, indent=2), encoding="utf-8"
            )
            raise RuntimeError("Native test click did not reach the sidebar session")
        result = receipt[0]
        elapsed = round(time.monotonic() - started, 2)
        user.GetForegroundWindow.restype = wintypes.HWND
        user.GetParent.argtypes = [wintypes.HWND]
        user.GetParent.restype = wintypes.HWND
        correct_window = user.GetForegroundWindow() == user.GetParent(
            session.runtime.console_hwnd
        )
        exact = verify_focused_probe(session.session_id) if correct_window else False
        restored = read_title(session.runtime.pid) == original
        results[name] = {
            "status": result.status,
            "exact_window": correct_window,
            "exact_pane": exact,
            "title_restored": restored,
            "collapsed": sidebar.collapsed,
            "seconds": elapsed,
        }

    def create(window, split=False, pinned=False):
        path = artifacts / (uuid.uuid4().hex + ".json")
        files.append(path)
        args = [
            "wt",
            "-w",
            window,
            "split-pane" if split else "new-tab",
            "--title",
            "Agent terminal",
            "--suppressApplicationTitle" if pinned else "--useApplicationTitle",
            sys.executable,
            str(root / "tests/native_probe.py"),
            str(path),
            "90",
        ]
        subprocess.run(args, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline and not path.exists():
            time.sleep(0.05)
        if not path.exists():
            raise RuntimeError("Dedicated terminal did not start")
        pid = json.loads(path.read_text())["pid"]
        binding = RuntimeBinding(
            pid, psutil.Process(pid).create_time(), console_hwnd=console_for_pid(pid)
        )
        session = SessionInfo(
            "codex", session_id=path.stem, runtime=binding, presence="live"
        )
        sessions.append(session)
        time.sleep(0.15)
        return session

    try:
        a = create("tx-existing-" + run)
        check("untagged_single", a)
        b = create("tx-existing-" + run)
        check("untagged_inactive_tab", a)
        check("same_title_second_tab", b)
        c = create("tx-existing-" + run, split=True)
        check("untagged_split_first", b)
        check("untagged_split_second", c)
        d = create("tx-pinned-" + run, pinned=True)
        check("single_pinned_title", d)
        user = ctypes.windll.user32
        user.GetParent.argtypes = [wintypes.HWND]
        user.GetParent.restype = wintypes.HWND
        user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        owner = user.GetParent(d.runtime.console_hwnd)
        user.ShowWindow(owner, 6)
        check("minimized_untagged", d)
    finally:
        sidebar.quitting = True
        sidebar.close()
        user.mouse_event(4, 0, 0, 0, 0)
        user.SetCursorPos(cursor.x, cursor.y)
        for path in files:
            Path(str(path) + ".stop").touch()
        directory.cleanup()
        (artifacts / "native-existing-acceptance.json").write_text(
            json.dumps(results, indent=2), encoding="utf-8"
        )
    (artifacts / "native-existing-acceptance.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    print(json.dumps(results))
    if any(
        value["status"] != "focused"
        or not value["exact_pane"]
        or not value["title_restored"]
        or not value["collapsed"]
        for value in results.values()
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
