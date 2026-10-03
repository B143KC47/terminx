"""Opt-in real Windows mouse checks on a dedicated, fixture-only sidebar."""

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

import psutil

if os.name != "nt":
    raise SystemExit("Windows required")
os.environ["QT_SCALE_FACTOR"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from native_existing_acceptance import verify_focused_probe
from PySide6.QtCore import QPoint, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QPushButton

from terminx.agents.base import RuntimeBinding, SessionInfo
from terminx.core.live import console_for_pid
from terminx.ui.sidebar import Sidebar
from terminx.ui.sidebar_widgets import details_rect


def main():
    user = ctypes.windll.user32
    user.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user.GetParent.argtypes = [wintypes.HWND]
    user.GetParent.restype = wintypes.HWND
    user.GetForegroundWindow.restype = wintypes.HWND
    user.mouse_event.argtypes = [
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_size_t,
    ]
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    cursor = wintypes.POINT()
    user.GetCursorPos(ctypes.byref(cursor))
    results = {}
    directory = tempfile.TemporaryDirectory()
    probe = Path(directory.name) / (uuid.uuid4().hex + ".json")
    subprocess.run(
        [
            "wt",
            "-w",
            "tx-click-" + probe.stem,
            "new-tab",
            "--title",
            "Existing terminal",
            "--useApplicationTitle",
            sys.executable,
            str(Path(__file__).with_name("native_probe.py")),
            str(probe),
            "30",
        ],
        check=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    deadline = time.monotonic() + 6
    while not probe.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    pid = json.loads(probe.read_text())["pid"]
    binding = RuntimeBinding(
        pid, psutil.Process(pid).create_time(), console_hwnd=console_for_pid(pid)
    )
    owner = user.GetParent(binding.console_hwnd)
    window = Sidebar({"lang": "en", "state_dir": directory.name}, start_workers=False)
    window.accept_sessions(
        [
            SessionInfo(
                "codex",
                session_id=probe.stem,
                data_root=directory.name,
                cwd=directory.name,
                title="Fixture terminal",
                status="processing",
                presence="live",
                runtime=binding,
            )
        ],
        [],
    )
    user.WindowFromPoint.argtypes = [wintypes.POINT]
    user.WindowFromPoint.restype = wintypes.HWND
    user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetAncestor.restype = wintypes.HWND
    drag_events = []
    for method in ("begin_drag", "move_drag", "end_drag"):
        original = getattr(window, method)

        def trace(event, original=original, method=method):
            drag_events.append(
                {
                    "event": method,
                    "point": [event.globalPosition().x(), event.globalPosition().y()],
                    "position": [window.x(), window.y()],
                }
            )
            return original(event)

        setattr(window, method, trace)
    window.show()

    def fail(exc):
        results["error"] = str(exc)
        current = wintypes.POINT()
        user.GetCursorPos(ctypes.byref(current))
        results["diagnostic"] = {
            "events": drag_events,
            "cursor": [current.x, current.y],
            "under_pointer": user.GetAncestor(user.WindowFromPoint(current), 2),
            "sidebar_hwnd": int(window.winId()),
            "position": [window.x(), window.y()],
            "scale": window.devicePixelRatioF(),
        }
        window.grab().save(
            str(
                Path(__file__).resolve().parents[1]
                / "_artifacts"
                / "sidebar-native-failure.png"
            )
        )
        finish()

    def guarded(fn):
        try:
            fn()
        except Exception as exc:
            fail(exc)

    def later(fn):
        QTimer.singleShot(100, lambda: guarded(fn))

    def point(widget):
        return widget.mapToGlobal(widget.rect().center())

    def click(widget, after, local=None):
        p = widget.mapToGlobal(local) if local is not None else point(widget)
        QCursor.setPos(p)
        user.mouse_event(2, 0, 0, 0, 0)

        def release():
            user.mouse_event(4, 0, 0, 0, 0)
            later(after)

        later(release)

    def drag(widget, destination, after, local=None):
        p = widget.mapToGlobal(local) if local is not None else point(widget)
        QCursor.setPos(p)
        user.mouse_event(2, 0, 0, 0, 0)

        def move():
            QCursor.setPos(destination)

            def release():
                user.mouse_event(4, 0, 0, 0, 0)
                later(after)

            later(release)

        later(move)

    def start():
        assert window.collapsed and window.expand.height() >= 80
        assert window.expand.count == 1
        drag(window.expand, QPoint(520, 260), rail_moved)

    def rail_moved():
        assert window.collapsed, "Dragging the rail incorrectly expands it"
        assert window.anchor == "free", (
            "Release unexpectedly forces the rail to an edge"
        )
        assert abs(window.x() - 496) < 5 and abs(window.y() - 216) < 5
        saved = json.loads(window.store_path.read_text(encoding="utf-8"))
        assert saved["position"] == {"x": window.x(), "y": window.y()}
        results["rail_drag_saved"] = True
        click(window.expand, expanded)

    def expanded():
        assert not window.collapsed and window.width() == 360
        results["rail_click_expands"] = True
        # The brand label forwards mouse events to the whole draggable header.
        drag(window.header, QPoint(230, 210), header_moved, local=QPoint(30, 16))

    def header_moved():
        assert not window.collapsed and window.anchor == "free"
        results["header_drag"] = True
        click(window.quota_toggle, quotas_open)

    def quotas_open():
        assert window.quota_expanded and not window.quota_frame.isHidden()
        results["quota_click"] = True
        button = next(
            b
            for b in window.findChildren(QPushButton)
            if b.accessibleName() == "Collapse sidebar"
        )
        click(button, collapsed)

    def collapsed():
        assert window.collapsed and window.width() == 48
        results["collapse_click"] = True
        click(window.expand, click_session)

    def click_session():
        assert not window.collapsed
        click(
            window.list.viewport(),
            details_open,
            local=details_rect(window.list.visualItemRect(window.list.item(0)))
            .center()
            .toPoint(),
        )

    def details_open():
        assert window.details_dialog and window.details_dialog.isVisible()
        assert window.details_dialog.session.session_id == probe.stem
        assert not window.collapsed and "focus" not in window.callbacks
        results["row_details_click_without_terminal_switch"] = True
        button = next(
            b
            for b in window.details_dialog.findChildren(QPushButton)
            if b.text() == "Close"
        )
        click(button, focus_session)

    def focus_session():
        assert window.details_dialog.isHidden()
        click(
            window.list.viewport(),
            focus_finished,
            local=window.list.visualItemRect(window.list.item(0)).center(),
        )

    def focus_finished():
        if "focus" in window.callbacks:
            later(focus_finished)
            return
        assert window.collapsed, "Successful native focus did not collapse the sidebar"
        assert user.GetForegroundWindow() == owner, (
            "The original terminal window is not in front"
        )
        assert verify_focused_probe(probe.stem), (
            "The wrong terminal pane received focus"
        )
        results["session_click_exact_terminal_and_collapse"] = True
        finish()

    def finish():
        user.mouse_event(4, 0, 0, 0, 0)
        user.SetCursorPos(cursor.x, cursor.y)
        Path(str(probe) + ".stop").touch()
        window.quit()

    QTimer.singleShot(300, lambda: guarded(start))
    QTimer.singleShot(15000, lambda: fail(RuntimeError("Native controls timed out")))
    app.exec()
    artifacts = Path(__file__).resolve().parents[1] / "_artifacts"
    artifacts.mkdir(exist_ok=True)
    (artifacts / "sidebar-native-controls.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    directory.cleanup()
    print(json.dumps(results))
    if "error" in results:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
