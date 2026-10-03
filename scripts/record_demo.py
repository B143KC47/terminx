"""Record the Windows interface with sample data and a dedicated terminal."""

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def terminal_probe(path):
    path.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
    print("termiX / demonstration terminal\n", flush=True)
    print("Sample project: C:\\Demo\\termiX", flush=True)
    print("This terminal runs no AI CLI or paid model request.", flush=True)
    print("\nSelect its session in termiX to return here.", flush=True)
    print("\nFocus marker: " + path.stem, flush=True)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline and not path.with_suffix(".stop").exists():
        time.sleep(0.1)


if len(sys.argv) > 2 and sys.argv[1] == "--probe":
    terminal_probe(Path(sys.argv[2]))
    raise SystemExit(0)

os.environ["QT_SCALE_FACTOR"] = "1.25"
os.environ.pop("QT_QPA_PLATFORM", None)
sys.path.insert(0, str(ROOT))

import psutil  # noqa: E402
from PySide6.QtCore import QPoint, QRectF, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QCursor, QFont, QImage, QPainter, QPen  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QPushButton,
    QTabWidget,
)

from terminx.agents.base import (  # noqa: E402
    Quota,
    QuotaWindow,
    RuntimeBinding,
    SessionInfo,
)
from terminx.core.live import console_for_pid  # noqa: E402
from terminx.ui import sidebar as sidebar_module  # noqa: E402
from terminx.ui.sidebar_widgets import details_rect  # noqa: E402

FPS = 12
WIDTH, HEIGHT = 1920, 1080
CHAPTERS = [
    (0, "Open AI CLI sessions", "Track open sessions in one Windows sidebar."),
    (4, "Open the rail", "Select the rail to open the panel."),
    (8, "Read session states", "See which session needs your attention."),
    (12, "Find one session", "Search by CLI, folder, or note."),
    (19, "Inspect a session", "Open details for the selected session."),
    (23, "Read public output", "Review recent user and assistant messages."),
    (27, "Keep a local note", "Save a note for this session."),
    (37, "Check account quotas", "Open the account quota panel."),
    (40, "Inspect quota windows", "Read usage and reset details for one account."),
    (48, "Control startup", "Choose whether termiX starts after Windows sign-in."),
    (57, "Return to the terminal", "Select a session to focus its existing terminal."),
    (
        63,
        "Install termiX",
        "Get the installer, portable ZIP, wheel, or source package.",
    ),
]


class Recording:
    def __init__(self, args):
        self.args = args
        self.output = args.output.resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        if any(self.output.iterdir()):
            raise ValueError("Select an empty recording directory")
        self.state = self.output / "state"
        self.state.mkdir()
        (self.state / "sidebar.json").write_text(
            json.dumps({"topmost": True, "notifications": False}), encoding="utf-8"
        )
        self.errors, self.events = [], []
        self.cursor_before = QCursor.pos()
        self.frames = 0
        self.captions = []
        self.finished = False
        self.focus_result = None
        self.focus_verified = False
        self.focus_deadline = None
        self.startup_before = self.installed_startup()
        self.original_startup = sidebar_module.startup_enabled
        sidebar_module.startup_enabled = self.installed_startup
        self.probe = self.output / (uuid.uuid4().hex + ".json")
        self.terminal_hwnd = 0
        self.encoder = None
        self.encoder_log = None
        self.start_terminal()
        self.window = sidebar_module.Sidebar(
            {
                "lang": "en",
                "state_dir": str(self.state),
                "paths": {
                    agent: str(self.state / agent)
                    for agent in ("codex", "claude", "kimi", "grok", "opencode")
                },
            },
            start_workers=False,
        )
        self.window.bus.done.connect(self.focus_done)
        self.sessions = self.samples()
        self.window.accept_sessions(self.sessions, [])
        self.window.accept_quotas(self.sample_quotas(), [])
        self.window.show()
        self.window.move(120, 140)
        self.terminal_image = None
        self.timer = QTimer()
        self.timer.timeout.connect(self.capture)

    def installed_startup(self):
        result = subprocess.run(
            [str(self.args.installed_console), "--startup", "status"],
            capture_output=True,
            check=True,
            encoding="utf-8",
            timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return result.stdout.strip() == "enabled"

    def start_terminal(self):
        subprocess.run(
            [
                "wt",
                "-w",
                "terminx-demo-" + self.probe.stem,
                "new-tab",
                "--title",
                "termiX demonstration terminal",
                "--suppressApplicationTitle",
                sys.executable,
                str(Path(__file__).resolve()),
                "--probe",
                str(self.probe),
            ],
            check=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        deadline = time.monotonic() + 10
        while not self.probe.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        pid = json.loads(self.probe.read_text(encoding="utf-8"))["pid"]
        self.binding = RuntimeBinding(
            pid, psutil.Process(pid).create_time(), console_hwnd=console_for_pid(pid)
        )
        user = ctypes.windll.user32
        user.GetParent.argtypes = [wintypes.HWND]
        user.GetParent.restype = wintypes.HWND
        user.MoveWindow.argtypes = [
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.BOOL,
        ]
        self.terminal_hwnd = user.GetParent(self.binding.console_hwnd)
        if not self.terminal_hwnd:
            raise RuntimeError("The dedicated terminal has no verified window")
        user.MoveWindow(self.terminal_hwnd, 650, 180, 960, 600, True)

    def samples(self):
        log = self.state / "sample-output.jsonl"
        messages = [
            ("user_message", "Review the sample release and its startup option."),
            ("agent_message", "The checks passed. Review the package record next."),
        ]
        log.write_text(
            "\n".join(
                json.dumps(
                    {"type": "event_msg", "payload": {"type": kind, "message": text}}
                )
                for kind, text in messages
            )
            + "\n",
            encoding="utf-8",
        )
        now = datetime.now(timezone.utc)
        return [
            SessionInfo(
                agent,
                session_id=f"demo-{agent}-001",
                cwd=r"C:\Demo\termiX",
                data_root=r"C:\Demo\provider",
                title=title,
                status=status,
                status_source="Sample events",
                status_at=now,
                last_activity=now,
                presence="live",
                activity_path=str(log) if agent == "codex" else "",
                runtime=self.binding if agent == "codex" else None,
                model="Demo model",
                input_tokens=4200,
                output_tokens=1200,
                context_percent=34,
            )
            for agent, title, status in (
                ("codex", "Review the release", "processing"),
                ("claude", "Review the interface", "waiting_input"),
                ("kimi", "Read the documentation", "outputting"),
                ("grok", "Check the installation", "completed"),
                ("opencode", "Inspect the sample code", "idle"),
            )
        ]

    def sample_quotas(self):
        return [
            {
                "agent": agent,
                "quota": Quota(
                    provider=agent,
                    plan="Sample plan",
                    source="Sample quota data",
                    account_id="demo-account",
                    fetched_at=datetime.now(timezone.utc),
                    windows=[
                        QuotaWindow("5 hours", 18000, used_percent=25 + index * 8),
                        QuotaWindow("7 days", 604800, used_percent=41 + index * 4),
                    ],
                ),
            }
            for index, agent in enumerate(
                ("codex", "claude", "kimi", "grok", "opencode")
            )
        ]

    def guarded(self, name, action):
        if self.finished:
            return
        try:
            event = {"action": name, "at_seconds": round(self.elapsed(), 2)}
            self.events.append(event)
            action()
            event["completed_at_seconds"] = round(self.elapsed(), 2)
        except Exception as exc:
            self.errors.append(f"{name}: {type(exc).__name__}: {exc}")
            self.finish()

    def elapsed(self):
        return time.monotonic() - self.started

    def button(self, parent, name):
        return next(
            widget
            for widget in parent.findChildren(QPushButton)
            if widget.text() == name or widget.accessibleName() == name
        )

    def click(self, widget):
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton)

    def codex_item(self):
        key = self.window.key(self.sessions[0])
        return next(
            self.window.list.item(index)
            for index in range(self.window.list.count())
            if self.window.list.item(index).data(Qt.ItemDataRole.UserRole) == key
        )

    def open_details(self):
        item = self.codex_item()
        self.window.list.setCurrentItem(item)
        self.window.list.scrollToItem(item)
        rect = self.window.list.visualItemRect(item)
        QTest.mouseClick(
            self.window.list.viewport(),
            Qt.MouseButton.LeftButton,
            pos=details_rect(rect).center().toPoint(),
        )
        if self.window.details_dialog is None:
            raise RuntimeError("The details control did not open its dialog")

    def tab(self, number):
        tabs = self.window.details_dialog.findChild(QTabWidget)
        self.click_tab(tabs, number)

    def click_tab(self, tabs, number):
        QTest.mouseClick(
            tabs.tabBar(),
            Qt.MouseButton.LeftButton,
            pos=tabs.tabBar().tabRect(number).center(),
        )

    def settings_dialog(self):
        return next(
            widget
            for widget in QApplication.topLevelWidgets()
            if isinstance(widget, QDialog)
            and widget.isVisible()
            and widget.windowTitle() == "Settings and integrations"
        )

    def toggle_startup(self):
        self.click(self.settings_dialog().findChild(QCheckBox, "startup-setting"))

    def save_settings(self):
        dialog = self.settings_dialog()
        option = dialog.findChild(QCheckBox, "startup-setting")
        if option.isChecked() != self.startup_before:
            raise RuntimeError("The recording would change the machine startup option")
        buttons = dialog.findChild(QDialogButtonBox)
        self.click(buttons.button(QDialogButtonBox.StandardButton.Save))

    def close_dialogs(self):
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, QDialog) and widget.isVisible():
                widget.reject()

    def focus_terminal(self):
        self.window.raise_()
        self.window.activateWindow()
        QTest.qWait(150)
        item = self.codex_item()
        self.window.list.scrollToItem(item)
        rect = self.window.list.visualItemRect(item)
        point = self.window.list.viewport().mapToGlobal(
            QPoint(rect.left() + 50, rect.center().y())
        )
        QCursor.setPos(point)
        QTest.qWait(80)
        user = ctypes.windll.user32
        user.WindowFromPoint.argtypes = [wintypes.POINT]
        user.WindowFromPoint.restype = wintypes.HWND
        user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user.GetAncestor.restype = wintypes.HWND
        current = wintypes.POINT()
        user.GetCursorPos(ctypes.byref(current))
        under_pointer = user.GetAncestor(user.WindowFromPoint(current), 2)
        if under_pointer != int(self.window.winId()):
            raise RuntimeError(
                f"The dedicated sidebar is not under the pointer: {under_pointer}; "
                f"expected {int(self.window.winId())}; point {current.x},{current.y}; "
                f"Qt point {point.x()},{point.y()}"
            )
        user.mouse_event.argtypes = [wintypes.DWORD] * 4 + [ctypes.c_size_t]
        user.mouse_event(2, 0, 0, 0, 0)
        QTest.qWait(50)
        user.mouse_event(4, 0, 0, 0, 0)

    def focus_done(self, name, result):
        if name == "focus":
            self.focus_result = {
                "status": getattr(result, "status", ""),
                "message": getattr(result, "message", str(result)),
            }

    def verify_focus(self):
        script = r"""
Add-Type -AssemblyName UIAutomationClient,UIAutomationTypes
$focused = [System.Windows.Automation.AutomationElement]::FocusedElement
if ($focused.Current.ClassName -ne 'TermControl') { Write-Output 'False'; exit }
$text = $focused.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern).DocumentRange.GetText(-1)
Write-Output ($text.Contains('__MARKER__'))
""".replace("__MARKER__", self.probe.stem)
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            encoding="utf-8",
            check=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self.focus_verified = result.stdout.strip() == "True"
        if (
            not self.focus_verified
            or not self.focus_result
            or self.focus_result["status"] != "focused"
        ):
            raise RuntimeError(
                "The dedicated terminal focus was not independently verified"
            )
        self.terminal_image = self.capture_terminal()

    def wait_for_focus(self):
        if self.finished:
            return
        if self.focus_result is None and time.monotonic() < self.focus_deadline:
            QTimer.singleShot(200, self.wait_for_focus)
            return
        self.guarded("verify_focus", self.verify_focus)
        if self.finished:
            return
        if self.args.focus_segment:
            self.start_focus_segment()
        elif self.args.focus_only:
            self.preview()

    def capture_terminal(self):
        user, gdi = ctypes.windll.user32, ctypes.windll.gdi32
        user.GetForegroundWindow.restype = wintypes.HWND
        user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user.GetDC.argtypes = [wintypes.HWND]
        user.GetDC.restype = wintypes.HDC
        user.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        if user.GetForegroundWindow() != self.terminal_hwnd:
            raise RuntimeError("The demonstration terminal is no longer in front")
        rect = wintypes.RECT()
        if not user.GetWindowRect(self.terminal_hwnd, ctypes.byref(rect)):
            raise RuntimeError("The demonstration window bounds are unavailable")
        rect.left += 12
        rect.right -= 12
        rect.top += 44
        rect.bottom -= 12
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if not 100 <= width <= 1920 or not 100 <= height <= 1080:
            raise RuntimeError("The demonstration window bounds are unexpected")
        gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
        gdi.CreateCompatibleDC.restype = wintypes.HDC
        gdi.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
        gdi.CreateCompatibleBitmap.restype = wintypes.HBITMAP
        gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        gdi.SelectObject.restype = wintypes.HGDIOBJ
        gdi.BitBlt.argtypes = [
            wintypes.HDC,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HDC,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.DWORD,
        ]
        gdi.GetDIBits.argtypes = [
            wintypes.HDC,
            wintypes.HBITMAP,
            wintypes.UINT,
            wintypes.UINT,
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.UINT,
        ]
        gdi.DeleteDC.argtypes = [wintypes.HDC]
        gdi.DeleteObject.argtypes = [wintypes.HGDIOBJ]

        class BitmapHeader(ctypes.Structure):
            _fields_ = [
                ("size", wintypes.DWORD),
                ("width", wintypes.LONG),
                ("height", wintypes.LONG),
                ("planes", wintypes.WORD),
                ("bits", wintypes.WORD),
                ("compression", wintypes.DWORD),
                ("image_size", wintypes.DWORD),
                ("x_ppm", wintypes.LONG),
                ("y_ppm", wintypes.LONG),
                ("colors", wintypes.DWORD),
                ("important_colors", wintypes.DWORD),
            ]

        desktop = user.GetDC(None)
        memory = gdi.CreateCompatibleDC(desktop)
        bitmap = gdi.CreateCompatibleBitmap(desktop, width, height)
        previous = gdi.SelectObject(memory, bitmap)
        try:
            if not gdi.BitBlt(
                memory, 0, 0, width, height, desktop, rect.left, rect.top, 0x40CC0020
            ):
                raise RuntimeError("The demonstration window capture failed")
            if user.GetForegroundWindow() != self.terminal_hwnd:
                raise RuntimeError("The demonstration window lost foreground focus")
            gdi.SelectObject(memory, previous)
            buffer = ctypes.create_string_buffer(width * height * 4)
            header = BitmapHeader()
            header.size = ctypes.sizeof(header)
            header.width, header.height = width, -height
            header.planes, header.bits = 1, 32
            if (
                gdi.GetDIBits(
                    memory, bitmap, 0, height, buffer, ctypes.byref(header), 0
                )
                != height
            ):
                raise RuntimeError("The demonstration window pixels are unavailable")
            image = QImage(buffer.raw, width, height, QImage.Format.Format_RGB32).copy()
            colors = {
                image.pixel(x, y)
                for x in range(0, width, 7)
                for y in range(0, height, 7)
            }
            if len(colors) < 10:
                raise RuntimeError("The demonstration terminal capture is blank")
            image.save(str(self.output / "terminal.png"))
            return image
        finally:
            gdi.SelectObject(memory, previous)
            gdi.DeleteObject(bitmap)
            gdi.DeleteDC(memory)
            user.ReleaseDC(None, desktop)

    def start(self):
        self.started = time.monotonic()
        if self.args.focus_only or self.args.focus_segment:
            self.window.reveal()
            self.focus_deadline = time.monotonic() + 20
            QTimer.singleShot(800, lambda: self.guarded("focus", self.focus_terminal))
            QTimer.singleShot(1500, self.wait_for_focus)
            return
        if self.args.preview_only:
            self.window.reveal()
            self.open_details()
            QTimer.singleShot(800, self.preview)
            return
        self.start_encoder()
        self.schedule_actions()

    def start_focus_segment(self):
        if self.finished:
            return
        self.started = time.monotonic() - 57
        self.start_encoder()
        self.timer.start(1000 // FPS)
        QTimer.singleShot(12000, self.finish)

    def start_encoder(self):
        self.encoder_log = (self.output / "ffmpeg.log").open("w", encoding="utf-8")
        self.encoder = subprocess.Popen(
            [
                str(self.args.ffmpeg),
                "-hide_banner",
                "-loglevel",
                "warning",
                "-n",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "bgra",
                "-video_size",
                f"{WIDTH}x{HEIGHT}",
                "-framerate",
                str(FPS),
                "-i",
                "pipe:0",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(self.output / "terminx-0.3.0-demo.mp4"),
            ],
            stdin=subprocess.PIPE,
            stderr=self.encoder_log,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    def schedule_actions(self):
        actions = [
            (4, "expand", lambda: self.click(self.window.expand)),
            (8, "state", self.update_state),
            (12, "search", lambda: QTest.keyClicks(self.window.search, "claude")),
            (17, "clear_search", lambda: self.window.search.clear()),
            (19, "details", self.open_details),
            (23, "output", lambda: self.tab(1)),
            (27, "notes", lambda: self.tab(2)),
            (
                28,
                "write_note",
                lambda: QTest.keyClicks(
                    self.window.details_dialog.note, "Review the startup option."
                ),
            ),
            (
                31,
                "save_note",
                lambda: self.click(
                    self.button(self.window.details_dialog, "Save note")
                ),
            ),
            (35, "close_details", self.close_dialogs),
            (37, "quotas", lambda: self.click(self.window.quota_toggle)),
            (
                40,
                "quota_details",
                lambda: self.click(self.window.quota_buttons["codex"]),
            ),
            (45, "close_quota", self.close_dialogs),
            (46, "collapse_quotas", lambda: self.click(self.window.quota_toggle)),
            (
                48,
                "settings",
                lambda: self.click(
                    self.button(self.window.header, "Settings and integrations")
                ),
            ),
            (52, "startup_toggle", self.toggle_startup),
            (54, "startup_restore", self.toggle_startup),
            (55, "save_settings", self.save_settings),
            (57, "focus_terminal", self.focus_terminal),
            (61, "verify_focus", self.verify_focus),
        ]
        if self.args.features_only:
            actions = [action for action in actions if action[0] < 57]
            actions.append(
                (
                    57,
                    "collapse",
                    lambda: self.click(
                        self.button(self.window.header, "Collapse sidebar")
                    ),
                )
            )
        for seconds, name, action in actions:
            QTimer.singleShot(
                seconds * 1000, lambda n=name, fn=action: self.guarded(n, fn)
            )
        QTimer.singleShot(69000, self.finish)
        self.timer.start(1000 // FPS)

    def update_state(self):
        self.sessions[0].status = "outputting"
        self.window.accept_sessions(self.sessions, [])

    def draw_text(self, painter, x, y, text, size, color="#ededed", bold=False):
        painter.setPen(QColor(color))
        font = QFont("Segoe UI")
        font.setPixelSize(size)
        font.setBold(bold)
        painter.setFont(font)
        painter.drawText(x, y, text)

    def draw_widget(self, painter, widget, x, y, max_width, max_height):
        image = widget.grab().toImage()
        self.draw_image(painter, image, x, y, max_width, max_height)

    def draw_image(self, painter, image, x, y, max_width, max_height):
        factor = min(max_width / image.width(), max_height / image.height(), 1.5)
        width, height = image.width() * factor, image.height() * factor
        painter.drawImage(QRectF(x, y, width, height), image)

    def frame(self):
        image = QImage(WIDTH, HEIGHT, QImage.Format.Format_ARGB32)
        image.fill(QColor("#151515"))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.draw_text(painter, 64, 76, "termiX", 46, bold=True)
        self.draw_text(painter, 1485, 71, "0.3.0 / WINDOWS", 23, "#aaaaaa")
        painter.setPen(QPen(QColor("#343434"), 1))
        painter.drawLine(64, 109, WIDTH - 64, 109)
        seconds = self.elapsed()
        chapter = next(row for row in reversed(CHAPTERS) if seconds >= row[0])
        if self.args.features_only and 57 <= seconds < 63:
            chapter = (
                57,
                "Close to the rail",
                "Select the collapse control to return to the rail.",
            )
        self.current_caption = chapter[2]
        self.draw_text(painter, 64, 163, chapter[1], 29, bold=True)
        self.draw_text(
            painter,
            64,
            201,
            "Sample sessions and quotas / isolated local data",
            22,
            "#aaaaaa",
        )
        painter.setPen(QPen(QColor("#292929"), 1))
        painter.setBrush(QColor("#1b1b1b"))
        painter.drawRoundedRect(QRectF(64, 238, WIDTH - 128, 706), 20, 20)
        self.draw_widget(painter, self.window, 220, 265, 580, 650)
        dialogs = [
            widget
            for widget in QApplication.topLevelWidgets()
            if isinstance(widget, QDialog) and widget.isVisible()
        ]
        if dialogs:
            self.draw_widget(painter, dialogs[-1], 870, 262, 850, 656)
        elif self.terminal_image is not None:
            self.draw_image(painter, self.terminal_image, 820, 290, 920, 605)
            self.draw_text(
                painter,
                820,
                895,
                "Verified focus / dedicated demonstration terminal",
                22,
                "#b5b5b5",
            )
        else:
            self.draw_text(painter, 945, 415, "One rail. Five CLIs.", 40, bold=True)
            self.draw_text(
                painter, 945, 475, "Sessions / details / notes / quotas", 27, "#aaaaaa"
            )
            self.draw_text(
                painter,
                945,
                535,
                "Your terminal stays in its own window.",
                25,
                "#aaaaaa",
            )
        self.draw_text(painter, 64, 1005, chapter[2], 30)
        self.draw_text(painter, 64, 1047, "github.com/B143KC47/terminx", 21, "#969696")
        painter.setPen(QPen(QColor("#777777"), 3))
        painter.drawLine(64, 1065, 64 + int((WIDTH - 128) * min(seconds / 69, 1)), 1065)
        painter.end()
        return image

    def capture(self):
        try:
            frame = self.frame()
            if not self.captions or self.captions[-1]["text"] != self.current_caption:
                self.captions.append(
                    {"frame": self.frames, "text": self.current_caption}
                )
            self.encoder.stdin.write(bytes(frame.constBits()))
            self.frames += 1
            if self.frames == FPS * 9:
                frame.save(str(self.output / "poster.png"))
        except Exception as exc:
            self.errors.append(f"capture: {exc}")
            self.finish()

    def preview(self):
        self.frame().save(str(self.output / "poster.png"))
        self.finish()

    def finish(self):
        if self.finished:
            return
        self.finished = True
        self.timer.stop()
        self.close_dialogs()
        if self.encoder:
            self.encoder.stdin.close()
            if self.encoder.wait(timeout=30):
                self.errors.append("The video encoder failed")
            self.encoder_log.close()
        sidebar_module.startup_enabled = self.original_startup
        self.probe.with_suffix(".stop").touch()
        startup_after = self.installed_startup()
        if startup_after != self.startup_before:
            self.errors.append("The machine startup setting changed")
        self.window.shutdown()
        self.window.quitting = True
        self.window.close()
        QCursor.setPos(self.cursor_before)
        receipt = {
            "application_version": "0.3.0",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "capture": "Live Windows Qt widgets and a dedicated Windows Terminal",
            "virtual_machine": False,
            "sample_sessions_and_quotas": True,
            "provider_workers_started": False,
            "private_desktop_captured": False,
            "frames": self.frames,
            "frame_rate": FPS,
            "width": WIDTH,
            "height": HEIGHT,
            "startup_before": self.startup_before,
            "startup_after": startup_after,
            "note_saved": "Review the startup option."
            in self.window.saved.get("notes", {}).values(),
            "focus": self.focus_result,
            "focus_independently_verified": self.focus_verified,
            "events": self.events,
            "captions": self.captions,
            "errors": self.errors,
        }
        video = self.output / "terminx-0.3.0-demo.mp4"
        if video.exists():
            receipt["video_sha256"] = hashlib.sha256(video.read_bytes()).hexdigest()
            self.save_captions()
        (self.output / "recording.json").write_text(
            json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(receipt))
        QApplication.exit(1 if self.errors else 0)

    def save_captions(self):
        def stamp(frame):
            milliseconds = frame * 1000 // FPS
            seconds, milliseconds = divmod(milliseconds, 1000)
            minutes, seconds = divmod(seconds, 60)
            hours, minutes = divmod(minutes, 60)
            return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"

        lines = []
        for index, caption in enumerate(self.captions):
            end = (
                self.captions[index + 1]["frame"]
                if index + 1 < len(self.captions)
                else self.frames
            )
            lines.extend(
                [
                    str(index + 1),
                    f"{stamp(caption['frame'])} --> {stamp(end)}",
                    caption["text"],
                    "",
                ]
            )
        (self.output / "terminx-0.3.0-demo.srt").write_text(
            "\n".join(lines), encoding="utf-8"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--installed-console", type=Path, required=True)
    parser.add_argument(
        "--ffmpeg", type=Path, default=Path(shutil.which("ffmpeg") or "ffmpeg")
    )
    parser.add_argument("--preview-only", action="store_true")
    parser.add_argument("--focus-only", action="store_true")
    parser.add_argument("--focus-segment", action="store_true")
    parser.add_argument("--features-only", action="store_true")
    args = parser.parse_args()
    if os.name != "nt":
        raise SystemExit("This recording needs Windows and Windows Terminal")
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    recording = Recording(args)
    try:
        recording.start()
    except Exception as exc:
        recording.errors.append(f"start: {exc}")
        recording.finish()
        raise
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
