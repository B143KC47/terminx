"""Native Windows sidebar. UI widgets read copied monitor snapshots."""

import argparse
import hashlib
import json
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QLockFile,
    QObject,
    QPoint,
    QRectF,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QIcon,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QShortcut,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from ..agents import ADAPTERS
from ..agents.quota import _fmt_countdown, close_helpers, collect_quotas, unavailable
from ..config import load_config
from ..core.events import ACTIVE, ATTENTION, LABELS, state_dir
from ..core.integrations import atomic_write, install, integration_state, uninstall
from ..core.monitor import Monitor
from ..core.paths import configured_home
from ..core.startup import set_startup, startup_enabled
from ..core.terminals import TerminalLocator, launch_session
from ..i18n import set_language, t
from .session_details import SessionDetails
from .sidebar_widgets import (
    ACTIVE_COLOR,
    ATTENTION_COLOR,
    DATA_ROLE,
    MUTED,
    STYLE,
    SURFACE,
    DragHandle,
    QuotaRow,
    RailButton,
    SessionDelegate,
    SessionList,
    line_icon,
)
from .theme import apply_theme


def label(text, name=None):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    if name:
        widget.setObjectName(name)
    return widget


def icon():
    pix = QPixmap(48, 48)
    pix.fill(QColor("#252525"))
    painter = QPainter(pix)
    painter.setPen(QColor("#ffffff"))
    font = painter.font()
    font.setPixelSize(29)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "t›")
    painter.end()
    return QIcon(pix)


def age_label(seconds):
    if seconds is None:
        return ""
    if seconds < 10:
        return t("Just now")
    if seconds < 60:
        return t("{seconds}s ago", seconds=seconds)
    if seconds < 3600:
        return t("{minutes}m ago", minutes=seconds // 60)
    if seconds < 86400:
        return t("{hours}h ago", hours=seconds // 3600)
    return t("{days}d ago", days=seconds // 86400)


class Collector(QThread):
    snapshot = Signal(object, object)

    def __init__(self, cfg, quotas=False):
        super().__init__()
        self.cfg, self.quotas = cfg, quotas
        self.stop_event = threading.Event()
        self.wake = threading.Event()

    def run(self):
        monitor = None if self.quotas else Monitor(ADAPTERS, self.cfg)
        while not self.stop_event.is_set():
            try:
                rows, errors = (
                    (
                        collect_quotas(
                            ADAPTERS,
                            self.cfg,
                            lambda row: self.snapshot.emit([row], []),
                        ),
                        [],
                    )
                    if self.quotas
                    else monitor.scan()
                )
                self.snapshot.emit(rows, errors)
            except Exception as exc:
                self.snapshot.emit([], [type(exc).__name__])
            self.wake.wait(
                max(5, self.cfg.get("quota_refresh_sec", 120)) if self.quotas else 0.5
            )
            self.wake.clear()

    def stop(self):
        self.stop_event.set()
        self.wake.set()


class ActionBus(QObject):
    done = Signal(str, object)


class Sidebar(QWidget):
    def __init__(self, cfg, start_workers=True):
        super().__init__()
        apply_theme(QApplication.instance())
        self.cfg = cfg
        set_language(cfg.get("lang", "auto"))
        self.store_path = state_dir(cfg) / "sidebar.json"
        try:
            self.saved = json.loads(self.store_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.saved = {}
        if not isinstance(self.saved, dict):
            self.saved = {}
        try:
            self.legacy_notes = json.loads(
                (state_dir(cfg) / "state.json").read_text(encoding="utf-8")
            ).get("notes", {})
        except (OSError, ValueError, AttributeError):
            self.legacy_notes = {}
        if not isinstance(self.legacy_notes, dict):
            self.legacy_notes = {}
        self.rows, self.quotas, self.by_key = [], [], {}
        self.last_states = {}
        self.first_snapshot = True
        self.collapsed = True
        self.quota_expanded = False
        self.quitting = False
        self.drag_start = None
        self.drag_origin = None
        self.drag_moved = False
        self.side = self.saved.get("side", "right")
        self.anchor = self.saved.get("anchor", self.side)
        if self.anchor not in {"free", "left", "right"}:
            self.anchor = "right"
        position = self.saved.get("position", {})
        self.rail_position = (
            QPoint(position["x"], position["y"])
            if isinstance(position, dict)
            and all(isinstance(position.get(k), int) for k in ("x", "y"))
            else None
        )
        self.panel_to_left = self.side == "right"
        self.topmost = self.saved.get("topmost", True)
        self.notifications = self.saved.get("notifications", True)
        self.callbacks = {}
        self.focus_target = None
        self.details_dialog = None
        self.integrations_present = any(
            integration_state(a, state_dir(cfg)).startswith("Installed")
            for a in ["codex", "claude", "kimi", "grok"]
        )
        self.bus = ActionBus()
        self.bus.done.connect(self.action_done)
        self.setWindowTitle("terminX")
        self.setWindowIcon(icon())
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.topmost)
        self.setStyleSheet(STYLE)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(2, 2, 2, 2)
        outer.setSpacing(0)
        self.body = QWidget()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.body)
        outer.addWidget(self.scroll)
        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)
        self.header = DragHandle(self)
        self.header.setToolTip(t("Drag to move"))
        header = QHBoxLayout(self.header)
        header.setContentsMargins(0, 0, 0, 0)
        brand = label("termiX", "brand")
        brand.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        header.addWidget(brand)
        header.addStretch()
        settings = QPushButton()
        settings.setObjectName("icon")
        settings.setIcon(line_icon("more"))
        settings.setFixedSize(32, 32)
        settings.setToolTip(t("Settings and integrations"))
        settings.setAccessibleName(t("Settings and integrations"))
        settings.clicked.connect(self.settings_dialog)
        header.addWidget(settings)
        collapse = QPushButton()
        collapse.setObjectName("icon")
        collapse.setIcon(line_icon("collapse"))
        collapse.setFixedSize(32, 32)
        collapse.setToolTip(t("Collapse sidebar"))
        collapse.setAccessibleName(t("Collapse sidebar"))
        collapse.clicked.connect(self.toggle_collapse)
        header.addWidget(collapse)
        body.addWidget(self.header)
        self.summary = label(t("Discovering open terminals…"), "muted")
        self.summary.setWordWrap(True)
        body.addWidget(self.summary)
        self.setup_hint = QPushButton(t("Set up live status"))
        self.setup_hint.setObjectName("setup")
        self.setup_hint.clicked.connect(self.settings_dialog)
        self.setup_hint.setToolTip(
            t("Enable CLI integrations to associate sessions with running processes")
        )
        self.setup_hint.hide()
        body.addWidget(self.setup_hint)
        self.search = QLineEdit()
        self.search.addAction(
            line_icon("search", MUTED, 17), QLineEdit.ActionPosition.LeadingPosition
        )
        self.search.setPlaceholderText(t("Search sessions, folders, notes"))
        self.search.setAccessibleName(t("Search sessions, folders, notes"))
        self.search.textChanged.connect(self.render_sessions)
        body.addWidget(self.search)
        filters = QHBoxLayout()
        self.filter = QComboBox()
        for text, value in [
            ("Open terminals", "live"),
            ("Working", "active"),
            ("Needs attention", "attention"),
            ("Turn ended", "completed"),
        ]:
            self.filter.addItem(t(text), value)
        self.filter.currentIndexChanged.connect(self.render_sessions)
        filters.addWidget(self.filter, 1)
        new = QPushButton(t("New"))
        new.setIcon(line_icon("plus", SURFACE, 16))
        new.setObjectName("primary")
        new.clicked.connect(self.new_session)
        filters.addWidget(new)
        body.addLayout(filters)
        self.list = SessionList()
        self.list.setItemDelegate(SessionDelegate(self.list))
        self.list.setMouseTracking(True)
        self.list.setCursor(Qt.CursorShape.PointingHandCursor)
        self.list.setAccessibleName(t("Open terminals"))
        self.list.setWordWrap(True)
        self.list.setFixedHeight(86)
        self.list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.itemClicked.connect(self.focus_item)
        self.list.itemActivated.connect(self.focus_item)
        self.list.detailsRequested.connect(lambda item: self.session_details())
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.session_menu)
        body.addWidget(self.list)
        self.feedback = QFrame()
        self.feedback.setObjectName("terminal-feedback")
        feedback_layout = QVBoxLayout(self.feedback)
        feedback_layout.setContentsMargins(12, 10, 12, 10)
        self.feedback_message = label("")
        self.feedback_message.setWordWrap(True)
        feedback_layout.addWidget(self.feedback_message)
        feedback_actions = QHBoxLayout()
        view = QPushButton(t("View session"))
        view.clicked.connect(
            lambda: self.show_details(self.focus_target) if self.focus_target else None
        )
        retry = QPushButton(t("Retry"))
        retry.clicked.connect(
            lambda: self.focus_session(self.focus_target) if self.focus_target else None
        )
        dismiss = QPushButton(t("Dismiss"))
        dismiss.clicked.connect(self.dismiss_feedback)
        for button in (view, retry, dismiss):
            feedback_actions.addWidget(button)
        feedback_layout.addLayout(feedback_actions)
        self.feedback.hide()
        body.addWidget(self.feedback)
        self.empty = label(t("No open terminals"), "muted")
        self.empty.setWordWrap(True)
        body.addWidget(self.empty)
        details = QPushButton(t("Details and notes"))
        details.setObjectName("subtle")
        details.setEnabled(False)
        self.list.currentItemChanged.connect(
            lambda current, old: details.setEnabled(current is not None)
        )
        details.clicked.connect(self.session_details)
        body.addWidget(details)
        divider = QFrame()
        divider.setObjectName("divider")
        body.addWidget(divider)
        self.quota_toggle = QPushButton(t("Account quota"))
        self.quota_toggle.setObjectName("quota-toggle")
        self.quota_toggle.setIcon(line_icon("down", MUTED, 16))
        self.quota_toggle.clicked.connect(self.toggle_quotas)
        body.addWidget(self.quota_toggle)
        self.quota_frame = QFrame()
        self.quota_frame.setObjectName("quotas")
        quota_layout = QVBoxLayout(self.quota_frame)
        quota_layout.setContentsMargins(2, 4, 2, 4)
        quota_layout.setSpacing(0)
        self.quota_buttons = {}
        for agent in [a.name for a in ADAPTERS]:
            title = {
                "codex": "Codex",
                "claude": "Claude",
                "kimi": "Kimi",
                "grok": "Grok",
                "opencode": "OpenCode",
            }[agent]
            button = QuotaRow(title)
            button.setText(agent + "\n" + t("Loading…"))
            button.clicked.connect(lambda checked=False, a=agent: self.quota_details(a))
            quota_layout.addWidget(button)
            self.quota_buttons[agent] = button
        body.addWidget(self.quota_frame)
        self.quota_frame.hide()
        self.status = label(
            t("Click to switch · Use the details icon to inspect"), "muted"
        )
        self.status.setWordWrap(True)
        body.addWidget(self.status)
        self.expand = RailButton(self)
        self.expand.setAccessibleName(t("Expand sidebar"))
        self.expand.setToolTip(t("Click to expand · drag to move"))
        self.expand.clicked.connect(self.toggle_collapse)
        outer.addWidget(self.expand)
        self.scroll.hide()
        self.tray = QSystemTrayIcon(icon(), self)
        menu = QMenu()
        for text, action in [
            ("Show sidebar", self.reveal),
            ("New session", self.new_session),
            ("Settings and integrations", self.settings_dialog),
            ("Quit", self.quit),
        ]:
            item = QAction(t(text), self)
            item.triggered.connect(action)
            menu.addAction(item)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: (
                self.reveal()
                if reason == QSystemTrayIcon.ActivationReason.Trigger
                else None
            )
        )
        self.tray.messageClicked.connect(self.notification_clicked)
        self.notification_key = None
        self.tray.show()
        self.workers = []
        if start_workers:
            for quotas, slot in [
                (False, self.accept_sessions),
                (True, self.accept_quotas),
            ]:
                worker = Collector(cfg, quotas)
                worker.snapshot.connect(slot)
                self.workers.append(worker)
                worker.start()
        for key, action in [
            ("Ctrl+F", self.search.setFocus),
            ("Ctrl+N", self.new_session),
            ("Escape", self.collapse),
            ("F5", self.refresh),
        ]:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(action)
        self.render_tick = QTimer(self)
        self.render_tick.timeout.connect(self.refresh_labels)
        self.render_tick.start(1000)
        self.dock()
        for button in self.findChildren(QPushButton):
            button.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#393939"), 1))
        painter.setBrush(QColor(SURFACE))
        painter.drawRoundedRect(
            QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 16, 16
        )
        painter.end()

    def key(self, session):
        return json.dumps(session.key, ensure_ascii=False)

    def note(self, session):
        key = self.key(session)
        notes = self.saved.setdefault("notes", {})
        if key not in notes:
            legacy = f"{session.agent}::{session.cwd or ''}"
            if key in self.legacy_notes or legacy in self.legacy_notes:
                notes[key] = self.legacy_notes.get(
                    key, self.legacy_notes.get(legacy, "")
                )
        return notes.get(key, "")

    def persist(self):
        self.saved.update(
            side=self.side,
            topmost=self.topmost,
            notifications=self.notifications,
            anchor=self.anchor,
            screen=self.screen().name() if self.screen() else "",
        )
        if self.rail_position is not None:
            self.saved["position"] = {
                "x": self.rail_position.x(),
                "y": self.rail_position.y(),
            }
        atomic_write(
            self.store_path, json.dumps(self.saved, ensure_ascii=False, indent=2)
        )

    def dock(self):
        if self.drag_start is not None:
            return
        screens = QApplication.screens()
        screen = (
            next((s for s in screens if s.name() == self.saved.get("screen")), None)
            or QApplication.screenAt(self.rail_position or QCursor.pos())
            or QApplication.primaryScreen()
        )
        area = screen.availableGeometry()
        width = 48 if self.collapsed else min(360, area.width() - 20)
        list_height = 86 * min(4, max(1, self.list.count()))
        self.list.setFixedHeight(list_height)
        self.body.layout().activate()
        content_height = self.body.layout().minimumSize().height() + 32
        if (
            not self.collapsed
            and self.list.count()
            and content_height > area.height() - 24
        ):
            available = list_height - (content_height - area.height() + 24)
            self.list.setFixedHeight(max(86, available // 86 * 86))
            self.body.layout().activate()
            content_height = self.body.layout().minimumSize().height() + 32
        height = (
            88 if self.collapsed else max(130, min(content_height, area.height() - 24))
        )
        self.setMinimumWidth(48 if self.collapsed else min(320, width))
        self.resize(width, height)
        if self.rail_position is None:
            self.rail_position = QPoint(
                area.right() - 57, area.top() + (area.height() - 88) // 2
            )
        x, y = self.rail_position.x(), self.rail_position.y()
        if self.anchor != "free":
            x = area.left() + 10 if self.anchor == "left" else area.right() - 57
        x = max(area.left() + 10, min(x, area.right() - 57))
        y = max(area.top() + 12, min(y, area.bottom() - 99))
        self.rail_position = QPoint(x, y)
        self.panel_to_left = x + 24 > area.center().x()
        if not self.collapsed and self.panel_to_left:
            x += 48 - width
        self.move(
            max(area.left() + 10, min(x, area.right() - width - 9)),
            max(area.top() + 12, min(y, area.bottom() - height - 11)),
        )

    def toggle_collapse(self):
        self.collapsed = not self.collapsed
        self.scroll.setVisible(not self.collapsed)
        self.expand.setVisible(self.collapsed)
        self.layout().setContentsMargins(
            2, 2, 2, 2
        ) if self.collapsed else self.layout().setContentsMargins(16, 16, 16, 16)
        self.dock()

    def collapse(self):
        if not self.collapsed:
            self.toggle_collapse()

    def toggle_quotas(self):
        self.quota_expanded = not self.quota_expanded
        self.quota_frame.setVisible(self.quota_expanded)
        self.quota_toggle.setIcon(
            line_icon("up" if self.quota_expanded else "down", MUTED, 16)
        )
        self.dock()

    def reveal(self):
        if self.collapsed:
            self.toggle_collapse()
        self.show()
        self.raise_()
        self.activateWindow()

    def begin_drag(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_start = event.globalPosition().toPoint() - self.pos()
            self.drag_origin = event.globalPosition().toPoint()
            self.drag_moved = False

    def move_drag(self, event):
        if self.drag_start is not None:
            if (
                event.globalPosition().toPoint() - self.drag_origin
            ).manhattanLength() >= QApplication.startDragDistance():
                self.drag_moved = True
            if self.drag_moved:
                self.move(event.globalPosition().toPoint() - self.drag_start)

    def end_drag(self, event):
        moved = self.drag_start is not None and self.drag_moved
        if self.drag_start is not None:
            self.drag_start = None
        if moved:
            screen = QApplication.screenAt(self.geometry().center()) or self.screen()
            self.saved["screen"] = screen.name()
            area = screen.availableGeometry()
            left_gap = abs(self.x() - area.left())
            right_gap = abs(area.right() - self.geometry().right())
            self.anchor = (
                "left" if left_gap <= 24 else "right" if right_gap <= 24 else "free"
            )
            self.side = (
                "left" if self.geometry().center().x() < area.center().x() else "right"
            )
            rail_x = self.x() + (
                self.width() - 48 if not self.collapsed and self.side == "right" else 0
            )
            self.rail_position = QPoint(rail_x, self.y())
            self.dock()
            self.persist()
        return moved

    mousePressEvent = begin_drag
    mouseMoveEvent = move_drag
    mouseReleaseEvent = end_drag

    def accept_sessions(self, rows, errors):
        self.rows = rows
        self.by_key = {self.key(s): s for s in rows}
        for s in rows:
            key = self.key(s)
            if (
                not self.first_snapshot
                and self.notifications
                and s.presence == "live"
                and self.last_states.get(key) != s.status
                and s.status in ATTENTION | {"completed"}
            ):
                self.notification_key = key
                self.tray.showMessage(
                    f"{s.agent} · {t(LABELS.get(s.status, s.status))}",
                    s.title or s.cwd or s.session_id,
                )
            self.last_states[key] = s.status
        self.first_snapshot = False
        if errors:
            self.status.setText(
                t("Some sources could not be read") + ": " + ", ".join(errors)
            )
        self.render_sessions()

    def refresh_labels(self):
        self.render_sessions()
        if self.quotas:
            self.accept_quotas(self.quotas, [])

    def render_sessions(self):
        selected = (
            self.list.currentItem().data(Qt.ItemDataRole.UserRole)
            if self.list.currentItem()
            else None
        )
        query = self.search.text().casefold()
        mode = self.filter.currentData()
        rows = [
            s
            for s in self.rows
            if s.presence == "live"
            and query
            in " ".join(
                [s.agent, s.session_id, s.title, s.cwd or "", self.note(s)]
            ).casefold()
        ]
        if mode == "active":
            rows = [s for s in rows if s.status in ACTIVE]
        elif mode == "attention":
            rows = [s for s in rows if s.status in ATTENTION and s.presence == "live"]
        elif mode == "completed":
            rows = [s for s in rows if s.status == "completed"]
        # Stable insertion order within each group; output timestamps don't reshuffle the list.
        old_order = {
            self.list.item(i).data(Qt.ItemDataRole.UserRole): i
            for i in range(self.list.count())
        }
        rows.sort(
            key=lambda s: (
                0 if s.presence == "live" and s.status in ATTENTION else 1,
                old_order.get(self.key(s), 100000),
            )
        )
        scroll = self.list.verticalScrollBar().value()
        desired_keys = [self.key(s) for s in rows]
        current_keys = [
            self.list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.list.count())
        ]
        if current_keys != desired_keys:
            self.list.clear()
            for key in desired_keys:
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, key)
                self.list.addItem(item)
        for index, s in enumerate(rows):
            item = self.list.item(index)
            age = (
                max(0, int(time.time() - s.status_at.timestamp()))
                if s.status_at
                else None
            )
            duration = " · " + age_label(age) if age is not None else ""
            presence = (
                ""
                if s.presence == "live"
                else "\n" + t("Runtime association unverified")
                if s.presence == "unverified"
                else "\n" + t("Process exited")
            )
            title = (
                self.note(s)
                or s.title
                or (Path(s.cwd).name if s.cwd else s.session_id[:16])
            )
            title = title.splitlines()[0][:34] if title else s.session_id[:16]
            path = s.cwd or "—"
            path = "…" + path[-37:] if len(path) > 38 else path
            state = t(LABELS.get(s.status, s.status))
            if s.presence == "unverified":
                state = t("Last observed") + ": " + state
            text = f"{s.agent.upper()}   {title}\n{state}{duration}\n{path}{presence}"
            if item.text() != text:
                item.setText(text)
            display_title = (
                self.note(s)
                or s.title
                or (Path(s.cwd).name if s.cwd else s.session_id[:16])
                or t("Open terminal")
            )
            agent = {
                "codex": "Codex",
                "claude": "Claude",
                "kimi": "Kimi",
                "grok": "Grok",
                "opencode": "OpenCode",
            }.get(s.agent, s.agent)
            color = (
                ATTENTION_COLOR
                if s.status in ATTENTION
                else ACTIVE_COLOR
                if s.status in ACTIVE
                else MUTED
            )
            if s.presence != "live":
                color = MUTED
            payload = {
                "title": display_title.splitlines()[0]
                if display_title
                else s.session_id[:16],
                "agent": agent,
                "folder": (
                    Path(s.cwd).name
                    if s.cwd and (s.title or self.note(s))
                    else s.session_id[:8]
                )
                or t("Session association pending"),
                "state": state,
                "age": duration.removeprefix(" · "),
                "color": color,
            }
            if item.data(DATA_ROLE) != payload:
                item.setData(DATA_ROLE, payload)
            item.setToolTip(
                f"{s.session_id}\n{s.cwd or ''}\n{t('Source')}: {s.status_source or t('Unknown')}{presence}"
            )
            if self.key(s) == selected:
                self.list.setCurrentItem(item)
        self.list.verticalScrollBar().setValue(scroll)
        self.list.setVisible(bool(rows))
        self.list.setFixedHeight(86 * min(4, max(1, len(rows))))
        self.empty.setVisible(not rows)
        live = [s for s in self.rows if s.presence == "live"]
        self.empty.setText(
            t("No matching sessions") if live else t("No open terminals")
        )
        self.setup_hint.setVisible(any(not s.session_id for s in live))
        attention = sum(s.status in ATTENTION for s in live)
        self.summary.setText(
            t(
                "{count} open · {active} active · {attention} need you",
                count=len(live),
                active=sum(s.status in ACTIVE for s in live),
                attention=attention,
            )
        )
        self.expand.count, self.expand.attention = len(live), attention
        self.expand.setToolTip(
            self.summary.text() + "\n" + t("Click to expand · drag to move")
        )
        self.expand.setAccessibleName(t("Expand sidebar") + " · " + self.summary.text())
        self.expand.update()
        self.tray.setToolTip("terminX · " + self.summary.text())
        self.update_quota_summary()
        self.dock()

    def update_quota_summary(self):
        agents = {s.agent for s in self.rows if s.presence == "live"}
        row = next((r for r in self.quotas if r["agent"] in agents), None)
        text = t("Account quota")
        if row:
            button = self.quota_buttons.get(row["agent"])
            if button:
                text += " · " + button.agent + " " + button.text().split("\n", 1)[-1]
        self.quota_toggle.setText(text)

    def accept_quotas(self, rows, errors):
        merged = {r["agent"]: r for r in self.quotas}
        merged.update({r["agent"]: r for r in rows})
        self.quotas = list(merged.values())
        for row in rows:
            q = row["quota"]
            percent = max((w.pct for w in q.windows if w.pct is not None), default=None)
            stale = q.availability == "stale" or (
                q.fetched_at
                and time.time() - q.fetched_at.timestamp()
                > self.cfg.get("quota_refresh_sec", 120) * 2
            )
            status = (
                t("Unavailable")
                if percent is None
                else t("{pct}% used", pct=f"{percent:.0f}")
            )
            if stale:
                status += " · " + t("Stale")
            button = self.quota_buttons.get(row["agent"])
            if button:
                button.percent, button.stale = percent, bool(stale)
                button.setText(row["agent"].upper() + "\n" + status)
                button.setAccessibleName(row["agent"] + " · " + status)
                button.setToolTip(t(q.reason) if q.reason else q.source)
        self.update_quota_summary()

    def run_action(self, name, fn, callback=None):
        if name in self.callbacks:
            return
        self.callbacks[name] = callback

        def work():
            try:
                value = fn()
            except Exception as exc:
                value = str(exc)
            self.bus.done.emit(name, value)

        threading.Thread(target=work, daemon=True).start()

    def action_done(self, name, value):
        callback = self.callbacks.pop(name, None)
        if name == "focus":
            self.list.setEnabled(True)
            message = t(value.message) if hasattr(value, "message") else t(str(value))
            self.status.setText(message)
            if self.details_dialog:
                self.details_dialog.result.setText(message)
                self.details_dialog.update_session()
            if getattr(value, "status", "") == "focused":
                self.feedback.hide()
                if (
                    self.details_dialog
                    and self.focus_target
                    and self.key(self.details_dialog.session)
                    == self.key(self.focus_target)
                ):
                    self.details_dialog.hide()
                self.collapse()
            else:
                self.feedback_message.setText(
                    t("Could not switch to this terminal") + "\n" + message
                )
                self.feedback.show()
                self.dock()
            if callback:
                callback(value)
            return
        if callback:
            callback(value)
        elif hasattr(value, "message"):
            self.status.setText(t(value.message))
            if name == "focus" and getattr(value, "status", "") == "focused":
                self.collapse()
        else:
            self.status.setText(t(str(value)))

    def focus_item(self, item):
        session = self.by_key.get(item.data(Qt.ItemDataRole.UserRole))
        if session:
            self.focus_session(session)

    def focus_session(self, session):
        if "focus" in self.callbacks:
            return
        self.focus_target = session
        self.feedback_message.setText(t("Locating terminal…"))
        self.feedback.show()
        self.list.setEnabled(False)
        self.status.setText(t("Locating terminal…"))
        self.dock()
        self.run_action("focus", lambda: TerminalLocator(self.cfg).focus(session))

    def dismiss_feedback(self):
        self.feedback.hide()
        self.dock()

    def notification_clicked(self):
        session = self.by_key.get(self.notification_key)
        if session:
            self.focus_session(session)

    def session_menu(self, pos):
        item = self.list.itemAt(pos)
        if not item:
            return
        self.list.setCurrentItem(item)
        menu = QMenu(self)
        menu.addAction(t("Details and notes"), self.session_details)
        menu.addAction(t("Focus terminal"), lambda: self.focus_item(item))
        menu.exec(self.list.mapToGlobal(pos))

    def new_session(self):
        agent, ok = QInputDialog.getItem(
            self, t("New session"), t("CLI"), [a.name for a in ADAPTERS], editable=False
        )
        if not ok:
            return
        cwd = QFileDialog.getExistingDirectory(
            self, t("Working directory"), str(Path.home())
        )
        if cwd:
            self.launch_terminal(agent, cwd)

    def launch_terminal(self, agent, cwd, session=None):
        def open_terminal():
            launch_session(agent, cwd, self.cfg, session)
            return True, t("Terminal opened")

        def completed(value):
            opened, message = (
                value if isinstance(value, tuple) else (False, t(str(value)))
            )
            self.status.setText(message)
            if (
                self.details_dialog
                and session
                and self.key(self.details_dialog.session) == self.key(session)
            ):
                self.details_dialog.result.setText(message)
                self.details_dialog.update_session()
            if opened:
                if self.details_dialog:
                    self.details_dialog.hide()
                self.collapse()
                self.refresh()
            else:
                QMessageBox.warning(self, t("Could not open terminal"), message)

        self.run_action("launch", open_terminal, completed)

    def session_details(self):
        item = self.list.currentItem()
        s = self.by_key.get(item.data(Qt.ItemDataRole.UserRole)) if item else None
        if not s:
            return
        self.show_details(s)

    def show_details(self, session):
        if self.details_dialog and self.key(self.details_dialog.session) == self.key(
            session
        ):
            self.details_dialog.show()
            self.details_dialog.update_session()
            self.details_dialog.raise_()
            self.details_dialog.activateWindow()
            return
        if self.details_dialog:
            self.details_dialog.close()
            self.details_dialog.deleteLater()
        self.details_dialog = SessionDetails(self, session)
        self.details_dialog.show()

    def quota_details(self, agent):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        q = next((r["quota"] for r in self.quotas if r["agent"] == agent), None)
        if not q:
            q = unavailable(
                agent, "Quota data has not arrived yet. Refresh to try again."
            )
        dialog = QDialog(self)
        dialog.setWindowTitle(agent + " · " + t("Account quota"))
        layout = QVBoxLayout(dialog)
        lines = [t(q.reason)] if q.reason else []
        if q.availability == "stale":
            lines.append(t("Stale"))
        for w in q.windows:
            try:
                reset = (
                    _fmt_countdown(
                        reset_at=datetime.fromisoformat(w.reset_at).timestamp()
                    )
                    if w.reset_at
                    else None
                )
            except ValueError:
                reset = None
            value = (
                t("{pct}% used", pct=f"{w.pct:.1f}")
                if w.pct is not None
                else t("Unavailable")
            )
            lines.append(f"{w.label}: {value}" + (f" · {reset}" if reset else ""))
        lines += [
            t("Source") + ": " + (q.source or "—"),
            t("Updated")
            + ": "
            + (
                q.fetched_at.astimezone().isoformat(timespec="seconds")
                if q.fetched_at
                else "—"
            ),
        ]
        text = label("\n\n".join(lines))
        text.setWordWrap(True)
        layout.addWidget(text)
        link = QPushButton(t("Open official usage page"))
        link.setEnabled(bool(q.official_url))
        link.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(q.official_url)))
        layout.addWidget(link)
        if agent == "grok":
            layout.addWidget(
                label(t("In Grok, use /usage for account allowance."), "muted")
            )
        refresh = QPushButton(t("Refresh"))
        refresh.clicked.connect(self.refresh)
        layout.addWidget(refresh)
        dialog.resize(400, 300)
        dialog.exec()

    def settings_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(t("Settings and integrations"))
        layout = QVBoxLayout(dialog)
        top = QCheckBox(t("Always on top"))
        top.setChecked(self.topmost)
        notifications = QCheckBox(t("Notify when attention is needed or a turn ends"))
        notifications.setChecked(self.notifications)
        layout.addWidget(top)
        layout.addWidget(notifications)
        startup = QCheckBox(t("Start termiX when I sign in to Windows"))
        startup.setObjectName("startup-setting")
        try:
            startup.setChecked(startup_enabled())
            startup.setEnabled(sys.platform == "win32")
        except (OSError, ValueError) as exc:
            startup.setEnabled(False)
            startup.setToolTip(str(exc))
        layout.addWidget(startup)
        edge = QComboBox()
        edge.addItem(t("Free position"), "free")
        edge.addItem(t("Right edge"), "right")
        edge.addItem(t("Left edge"), "left")
        edge.setCurrentIndex(edge.findData(self.anchor))
        layout.addWidget(edge)
        layout.addWidget(label(t("CLI integrations"), "heading"))
        hint = label(
            t(
                "Codex uses native process and session logs without hooks. Other CLI integrations are optional."
            ),
            "muted",
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        for agent in ["codex", "claude", "kimi", "grok"]:
            row = QHBoxLayout()
            row.addWidget(label(agent), 1)
            if agent == "codex":
                row.addWidget(
                    label(t("Native process and session logs · no hooks"), "muted")
                )
                layout.addLayout(row)
                continue
            enable = QPushButton(t("Enable"))
            remove = QPushButton(t("Remove"))
            state = integration_state(agent, state_dir(self.cfg))
            installed = state.startswith("Installed")
            enable.setText(t("Enabled") if installed else t("Enable"))
            enable.setEnabled(not installed)
            remove.setEnabled(installed)
            enable.setToolTip(t(state))

            def update(action, a=agent, e=enable, r=remove):
                try:
                    kwargs = (
                        {"home": configured_home(a, self.cfg)}
                        if action is install
                        else {}
                    )
                    message = action(a, directory=state_dir(self.cfg), **kwargs)
                    active = action is install
                    e.setEnabled(not active)
                    e.setText(t("Enabled") if active else t("Enable"))
                    r.setEnabled(active)
                    self.integrations_present = any(
                        integration_state(name, state_dir(self.cfg)).startswith(
                            "Installed"
                        )
                        for name in ["codex", "claude", "kimi", "grok"]
                    )
                    self.render_sessions()
                    QMessageBox.information(dialog, a, t(message))
                except Exception as exc:
                    QMessageBox.warning(dialog, a, str(exc))

            enable.clicked.connect(lambda checked=False, fn=update: fn(install))
            remove.clicked.connect(lambda checked=False, fn=update: fn(uninstall))
            row.addWidget(enable)
            row.addWidget(remove)
            layout.addLayout(row)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )

        def save_settings():
            try:
                if startup.isEnabled() and startup.isChecked() != startup_enabled():
                    set_startup(startup.isChecked())
            except (OSError, ValueError) as exc:
                QMessageBox.warning(dialog, t("Start at sign-in"), str(exc))
                return
            dialog.accept()

        buttons.accepted.connect(save_settings)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.topmost, self.notifications, self.anchor = (
                top.isChecked(),
                notifications.isChecked(),
                edge.currentData(),
            )
            if self.anchor != "free":
                self.side = self.anchor
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.topmost)
            self.persist()
            self.dock()
            self.show()

    def refresh(self):
        for worker in self.workers:
            worker.wake.set()

    def closeEvent(self, event):
        if not self.quitting and QSystemTrayIcon.isSystemTrayAvailable():
            event.ignore()
            self.hide()
        else:
            self.shutdown()
            event.accept()

    def shutdown(self):
        self.persist()
        for worker in self.workers:
            worker.stop()
        for worker in self.workers:
            worker.wait(30000)
        self.tray.hide()
        close_helpers()

    def quit(self):
        self.quitting = True
        self.shutdown()
        QApplication.quit()


def notify_running_instance(name, message):
    """Keep the command connection open until the server confirms receipt."""
    socket = QLocalSocket()
    socket.connectToServer(name)
    if not socket.waitForConnected(300):
        return False
    socket.write(message + b"\n")
    socket.flush()
    if socket.bytesToWrite() and not socket.waitForBytesWritten(3000):
        raise OSError("The sidebar command could not be sent")
    if not socket.bytesAvailable() and not socket.waitForReadyRead(3000):
        raise OSError("The running sidebar did not acknowledge the command")
    if bytes(socket.readAll()).strip() != b"ok":
        raise OSError("The running sidebar returned an invalid acknowledgement")
    socket.disconnectFromServer()
    return True


def receive_instance_command(server, window):
    """Read one complete command and confirm receipt before its connection closes."""
    client = server.nextPendingConnection()
    if not client:
        return
    client.disconnected.connect(client.deleteLater)
    buffer = bytearray()

    def receive():
        buffer.extend(bytes(client.readAll()))
        if b"\n" not in buffer:
            if len(buffer) > 32:
                client.abort()
            return
        message = bytes(buffer).split(b"\n", 1)[0]
        if message not in {b"quit", b"show", b"startup"}:
            client.abort()
            return
        client.write(b"ok\n")
        client.flush()
        client.disconnectFromServer()
        if message == b"quit":
            window.quit()
        elif message == b"show":
            window.reveal()

    client.readyRead.connect(receive)
    if client.bytesAvailable():
        receive()


def main():
    parser = argparse.ArgumentParser(prog="terminx-sidebar")
    parser.add_argument(
        "--screenshot", help="Save the native window after data arrives"
    )
    parser.add_argument(
        "--exit-after",
        type=float,
        default=0,
        help="Quit after N seconds (smoke testing)",
    )
    parser.add_argument(
        "--expanded", action="store_true", help="Open the panel on startup"
    )
    parser.add_argument(
        "--startup", action="store_true", help="Start after Windows sign-in"
    )
    parser.add_argument(
        "--quit", action="store_true", help="Gracefully quit the running sidebar"
    )
    from .. import __version__

    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--settings", action="store_true", help="Open the settings dialog"
    )
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("terminX")
    cfg = load_config()
    directory = state_dir(cfg)
    directory.mkdir(parents=True, exist_ok=True)
    name = "terminx-" + hashlib.sha256(str(directory).encode()).hexdigest()[:20]
    message = b"quit" if args.quit else b"startup" if args.startup else b"show"
    if notify_running_instance(name, message):
        return
    if args.quit:
        return
    lock = QLockFile(str(directory / "sidebar.lock"))
    if not lock.tryLock(100):
        return
    QLocalServer.removeServer(name)
    server = QLocalServer()
    server.listen(name)
    window = Sidebar(cfg)

    server.newConnection.connect(lambda: receive_instance_command(server, window))
    app.screenRemoved.connect(lambda screen: window.dock())
    for screen in app.screens():
        screen.availableGeometryChanged.connect(lambda rect: window.dock())
    window.show()
    if args.expanded:
        window.reveal()
    if args.settings:
        QTimer.singleShot(0, window.settings_dialog)
    if args.screenshot:
        QTimer.singleShot(7000, lambda: window.grab().save(args.screenshot))
    if args.exit_after:
        QTimer.singleShot(int(args.exit_after * 1000), window.quit)
    app.exec()
    server.close()
    lock.unlock()


if __name__ == "__main__":
    main()
