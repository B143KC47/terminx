"""Live session inspection, public message preview and explicit management actions."""

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.events import LABELS
from ..core.monitor import runtime_alive
from ..core.preview import read_preview
from ..i18n import t


class SessionDetails(QDialog):
    def __init__(self, sidebar, session):
        super().__init__(sidebar)
        self.sidebar, self.session = sidebar, session
        self.setWindowTitle(t("Session details"))
        self.resize(520, 560)
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel(
            session.title or (Path(session.cwd).name if session.cwd else session.agent)
        )
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setObjectName("brand")
        title.setWordWrap(True)
        title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        header.addWidget(title, 1)
        self.focus_button = QPushButton(t("Focus terminal"))
        self.focus_button.setObjectName("primary")
        self.focus_button.clicked.connect(lambda: sidebar.focus_session(self.session))
        header.addWidget(self.focus_button)
        layout.addLayout(header)
        self.result = QLabel()
        self.result.setTextFormat(Qt.TextFormat.PlainText)
        self.result.setWordWrap(True)
        layout.addWidget(self.result)
        tabs = QTabWidget()
        overview = QWidget()
        overview_layout = QVBoxLayout(overview)
        self.metadata = QLabel()
        self.metadata.setTextFormat(Qt.TextFormat.PlainText)
        self.metadata.setWordWrap(True)
        self.metadata.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        overview_layout.addWidget(self.metadata)
        actions = QHBoxLayout()
        self.copy = QPushButton(t("Copy session ID"))
        self.copy.setEnabled(bool(session.session_id))
        self.copy.clicked.connect(self.copy_id)
        self.folder = QPushButton(t("Open folder"))
        self.folder.clicked.connect(self.open_folder)
        actions.addWidget(self.copy)
        actions.addWidget(self.folder)
        overview_layout.addLayout(actions)
        self.resume = QPushButton(t("Resume this session in a new terminal"))
        self.resume.clicked.connect(self.resume_session)
        overview_layout.addWidget(self.resume)
        overview_layout.addStretch()
        overview_scroll = QScrollArea()
        overview_scroll.setWidgetResizable(True)
        overview_scroll.setWidget(overview)
        tabs.addTab(overview_scroll, t("Overview"))
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setAccessibleName(t("Recent output"))
        tabs.addTab(self.preview, t("Recent output"))
        notes = QWidget()
        notes_layout = QVBoxLayout(notes)
        self.note = QPlainTextEdit(sidebar.note(session))
        self.note.setPlaceholderText(t("Note for this session"))
        notes_layout.addWidget(self.note)
        save = QPushButton(t("Save note"))
        save.setObjectName("primary")
        save.clicked.connect(self.save_note)
        notes_layout.addWidget(save)
        tabs.addTab(notes, t("Notes"))
        layout.addWidget(tabs)
        close = QPushButton(t("Close"))
        close.clicked.connect(self.close)
        layout.addWidget(close)
        self.timer = QTimer(self)
        self.timer.setInterval(1500)
        self.timer.timeout.connect(self.update_session)
        self.timer.start()
        self.update_session()

    def showEvent(self, event):
        super().showEvent(event)
        self.fit_to_screen()
        QTimer.singleShot(0, self.fit_to_screen)
        self.update_session()

    def fit_to_screen(self):
        area = self.screen().availableGeometry().adjusted(16, 16, -16, -16)
        frame = self.frameGeometry()
        extra_width = max(0, frame.width() - self.width())
        extra_height = max(0, frame.height() - self.height())
        self.resize(
            min(self.width(), area.width() - extra_width),
            min(self.height(), area.height() - extra_height),
        )
        frame = self.frameGeometry()
        self.move(
            max(area.left(), min(self.x(), area.right() - frame.width() + 1)),
            max(area.top(), min(self.y(), area.bottom() - frame.height() + 1)),
        )

    def update_session(self):
        if not self.isHidden() or not self.metadata.text():
            self.session = self.sidebar.by_key.get(
                self.sidebar.key(self.session), self.session
            )
            s = self.session
            alive = runtime_alive(s.runtime) if s.runtime else s.presence == "live"
            state = s.status if alive else "exited"
            self.focus_button.setEnabled(
                alive and "focus" not in self.sidebar.callbacks
            )
            self.copy.setEnabled(bool(s.session_id))
            self.resume.setEnabled(not alive and bool(s.cwd and s.session_id))
            self.folder.setEnabled(bool(s.cwd and Path(s.cwd).is_dir()))
            self.metadata.setText(
                f"{s.agent} · {s.session_id or t('Session association pending')}\n\n"
                f"{s.cwd or '—'}\n\n{t(LABELS.get(state, state))}\n"
                f"{t('Source')}: {s.status_source or t('Unknown')}\n"
                f"{t('Updated')}: {s.status_at.astimezone().isoformat(timespec='seconds') if s.status_at else '—'}\n"
                f"{t('Model')}: {s.model or '—'}\n"
                f"PID: {s.runtime.pid if s.runtime else '—'}\n"
                f"{t('Session tokens')}: {s.input_tokens if s.input_tokens is not None else '—'} / {s.output_tokens if s.output_tokens is not None else '—'}\n"
                f"{t('Context used')}: {str(round(s.context_percent, 1)) + '%' if s.context_percent is not None else '—'}"
            )
            messages = read_preview(s)
            text = "\n\n".join(
                t("You" if role == "user" else "Assistant") + "\n" + value
                for role, value in messages
            )
            text = text or t(
                "No public output is available yet. Open the original terminal to see live activity."
            )
            if self.preview.toPlainText() != text:
                bar = self.preview.verticalScrollBar()
                bottom = bar.value() >= bar.maximum()
                position = bar.value()
                self.preview.setPlainText(text)
                bar.setValue(bar.maximum() if bottom else position)

    def open_folder(self):
        if self.session.cwd:
            if not QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(Path(self.session.cwd).resolve()))
            ):
                self.result.setText(t("Could not open folder"))

    def copy_id(self):
        QApplication.clipboard().setText(self.session.session_id)
        self.result.setText(t("Session ID copied"))

    def save_note(self):
        self.sidebar.saved.setdefault("notes", {})[self.sidebar.key(self.session)] = (
            self.note.toPlainText()
        )
        self.sidebar.persist()
        self.sidebar.render_sessions()
        self.result.setText(t("Note saved"))

    def resume_session(self):
        self.sidebar.launch_terminal(self.session.agent, self.session.cwd, self.session)
