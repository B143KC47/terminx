"""Quiet, monochrome desktop components; color communicates session state only."""

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QListWidget,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QWidget,
)

from ..i18n import t

INK = "#ececec"
MUTED = "#aaaaaa"
SURFACE = "#171717"
ACTIVE_COLOR = "#80cfa8"
ATTENTION_COLOR = "#e6c08b"
DATA_ROLE = Qt.ItemDataRole.UserRole + 1

STYLE = """
QWidget { color: #ececec; font-family: 'Segoe UI', 'Microsoft YaHei UI'; font-size: 12px; background: transparent; }
QDialog, QMessageBox, QInputDialog { background: #171717; }
QLabel#brand { font-size: 17px; font-weight: 600; letter-spacing: -0.3px; }
QLabel#muted { color: #aaaaaa; font-size: 11px; }
QLabel#heading { color: #aaaaaa; font-size: 11px; font-weight: 500; }
QPushButton { background: #252525; border: 1px solid #3a3a3a; border-radius: 9px; padding: 8px 12px; }
QPushButton:hover { background: #303030; border-color: #545454; }
QPushButton:focus { border-color: #a4a4a4; }
QPushButton:disabled { color: #787878; background: #202020; border-color: #303030; }
QPushButton#primary { background: #ececec; color: #171717; border: 1px solid #ececec; font-weight: 600; }
QPushButton#primary:hover { background: #ffffff; }
QPushButton#primary:focus { border: 2px solid #a4a4a4; }
QPushButton#primary:disabled { background: #303030; color: #787878; border-color: #3a3a3a; }
QPushButton#icon, QPushButton#subtle { background: transparent; border: 1px solid transparent; }
QPushButton#icon:hover, QPushButton#subtle:hover { background: #2a2a2a; }
QPushButton#icon:focus, QPushButton#subtle:focus { border-color: #a4a4a4; }
QPushButton#quota-toggle { background: transparent; border: 0; padding: 6px 0; text-align: left; color: #aaaaaa; }
QPushButton#quota-toggle:hover { color: #ececec; }
QPushButton#quota-toggle:focus { border: 1px solid #a4a4a4; }
QPushButton#setup { background: #252525; border: 1px solid #454545; text-align: left; }
QLineEdit, QPlainTextEdit { background: #212121; border: 1px solid #3a3a3a; border-radius: 10px; padding: 9px; selection-background-color: #454545; selection-color: #ffffff; }
QLineEdit:focus, QPlainTextEdit:focus { border-color: #a4a4a4; }
QComboBox { border: 1px solid transparent; border-radius: 8px; padding: 7px 8px; color: #ececec; }
QComboBox:hover { background: #2a2a2a; }
QComboBox:focus { border-color: #a4a4a4; }
QComboBox::drop-down { border: 0; width: 20px; }
QComboBox QAbstractItemView { background: #252525; color: #ececec; selection-background-color: #383838; selection-color: #ffffff; outline: 0; border: 1px solid #454545; padding: 4px; }
QListWidget { border: 0; outline: 0; background: transparent; }
QScrollArea { border: 0; background: transparent; }
QScrollBar:vertical { background: transparent; width: 4px; margin: 2px 0; }
QScrollBar::handle:vertical { background: #686868; border-radius: 2px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QFrame#divider { background: #333333; max-height: 1px; }
QFrame#quotas { background: #212121; border: 1px solid #343434; border-radius: 12px; }
QFrame#terminal-feedback { background: #28241e; border: 1px solid #655139; border-radius: 10px; }
QFrame#terminal-feedback QPushButton { background: transparent; padding: 6px 10px; }
QTabWidget::pane { border: 1px solid #3a3a3a; border-radius: 8px; background: #212121; }
QTabBar::tab { background: transparent; color: #aaaaaa; padding: 9px 13px; }
QTabBar::tab:selected { color: #ececec; border-bottom: 2px solid #ececec; }
QTabBar::tab:hover { color: #ffffff; background: #252525; }
QMenu { background: #252525; border: 1px solid #454545; padding: 5px; }
QMenu::item { padding: 7px 16px; border-radius: 6px; }
QMenu::item:selected { background: #383838; }
QToolTip { background: #303030; color: #ececec; border: 1px solid #555555; padding: 6px; }
"""


def line_icon(name, color=INK, size=20):
    pix = QPixmap(size * 2, size * 2)
    pix.setDevicePixelRatio(2)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 20, size / 20)
    p.setPen(
        QPen(
            QColor(color),
            1.5,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
    )
    if name == "search":
        p.drawEllipse(QRectF(3, 3, 10, 10))
        p.drawLine(QPointF(11.5, 11.5), QPointF(17, 17))
    elif name == "collapse":
        p.drawRoundedRect(QRectF(2.5, 3.5, 15, 13), 2, 2)
        p.drawLine(QPointF(12.5, 3.5), QPointF(12.5, 16.5))
    elif name == "more":
        for x in (4, 10, 16):
            p.drawEllipse(QPointF(x, 10), 0.8, 0.8)
    elif name == "plus":
        p.drawLine(QPointF(10, 4), QPointF(10, 16))
        p.drawLine(QPointF(4, 10), QPointF(16, 10))
    elif name == "arrow":
        p.drawLine(QPointF(5, 15), QPointF(15, 5))
        p.drawLine(QPointF(7, 5), QPointF(15, 5))
        p.drawLine(QPointF(15, 5), QPointF(15, 13))
    elif name == "terminal":
        p.drawLine(QPointF(3, 5), QPointF(8, 10))
        p.drawLine(QPointF(8, 10), QPointF(3, 15))
        p.drawLine(QPointF(10, 15), QPointF(17, 15))
    elif name == "details":
        p.drawRoundedRect(QRectF(3, 3, 14, 14), 2.5, 2.5)
        p.drawLine(QPointF(7, 7), QPointF(13, 7))
        p.drawLine(QPointF(7, 10), QPointF(13, 10))
        p.drawLine(QPointF(7, 13), QPointF(10, 13))
    elif name == "down":
        p.drawLine(QPointF(5, 7), QPointF(10, 12))
        p.drawLine(QPointF(10, 12), QPointF(15, 7))
    elif name == "up":
        p.drawLine(QPointF(5, 12), QPointF(10, 7))
        p.drawLine(QPointF(10, 7), QPointF(15, 12))
    p.end()
    return QIcon(pix)


def _font(painter, size, weight=QFont.Weight.Normal):
    font = painter.font()
    font.setFamilies(["Segoe UI", "Microsoft YaHei UI"])
    font.setPixelSize(size)
    font.setWeight(weight)
    painter.setFont(font)


class DragHandle(QWidget):
    """A deliberate drag surface; header action buttons keep their own clicks."""

    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setCursor(Qt.CursorShape.SizeAllCursor)

    def mousePressEvent(self, event):
        self.owner.begin_drag(event)

    def mouseMoveEvent(self, event):
        self.owner.move_drag(event)

    def mouseReleaseEvent(self, event):
        self.owner.end_drag(event)


class RailButton(QPushButton):
    """The collapsed rail distinguishes a click from a drag using the OS threshold."""

    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.count = self.attention = 0
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):
        self.owner.begin_drag(event)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        self.owner.move_drag(event)
        if self.owner.drag_moved:
            self.setDown(False)
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        moved = self.owner.end_drag(event)
        if moved:
            self.setDown(False)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.underMouse() or self.hasFocus():
            p.setPen(QPen(QColor(MUTED), 1) if self.hasFocus() else Qt.PenStyle.NoPen)
            p.setBrush(QColor("#303030"))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(2, 2, -2, -2), 12, 12)
        line_icon("terminal", INK, 20).paint(p, (self.width() - 20) // 2, 14, 20, 20)
        _font(p, 14, QFont.Weight.DemiBold)
        p.setPen(QColor(INK))
        p.drawText(
            QRectF(0, 39, self.width(), 22),
            Qt.AlignmentFlag.AlignCenter,
            str(self.count),
        )
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(ATTENTION_COLOR if self.attention else MUTED))
        if self.attention:
            p.drawEllipse(QPointF(self.width() - 10, 11), 3, 3)
        p.setBrush(QColor("#787878"))
        for x in (-4, 0, 4):
            p.drawEllipse(QPointF(self.width() / 2 + x, self.height() - 12), 1, 1)
        p.end()


class SessionDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(280, 86)

    def paint(self, p, option, index):
        data = index.data(DATA_ROLE) or {}
        rect = QRectF(option.rect).adjusted(0, 2, -5, -5)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        p.setBrush(QColor("#2a2a2a" if selected else "#252525" if hover else "#1d1d1d"))
        p.setPen(
            QPen(
                QColor("#707070" if selected else "#343434" if hover else "#262626"), 1
            )
        )
        p.drawRoundedRect(rect, 11, 11)
        x, y, width = rect.x() + 13, rect.y() + 10, rect.width() - 26
        _font(p, 13, QFont.Weight.DemiBold)
        p.setPen(QColor(INK))
        title = p.fontMetrics().elidedText(
            data.get("title", ""), Qt.TextElideMode.ElideRight, int(width - 30)
        )
        p.drawText(QRectF(x, y, width - 30, 21), Qt.AlignmentFlag.AlignVCenter, title)
        details = details_rect(option.rect)
        line_icon("details", INK if selected or hover else MUTED, 16).paint(
            p, int(details.x() + 6), int(details.y() + 6), 16, 16
        )
        _font(p, 11)
        p.setPen(QColor(MUTED))
        meta = data.get("agent", "") + "  ·  " + data.get("folder", "—")
        p.drawText(
            QRectF(x, y + 25, width, 17),
            Qt.AlignmentFlag.AlignVCenter,
            p.fontMetrics().elidedText(meta, Qt.TextElideMode.ElideMiddle, int(width)),
        )
        color = data.get("color", MUTED)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        p.drawEllipse(QPointF(x + 3, y + 51), 3, 3)
        p.setPen(QColor(color))
        state = data.get("state", "")
        age = data.get("age", "")
        age_width = p.fontMetrics().horizontalAdvance(age)
        p.drawText(
            QRectF(x + 12, y + 41, width - age_width - 24, 20),
            Qt.AlignmentFlag.AlignVCenter,
            p.fontMetrics().elidedText(
                state, Qt.TextElideMode.ElideRight, int(width - age_width - 24)
            ),
        )
        p.setPen(QColor(MUTED))
        p.drawText(
            QRectF(x + width - age_width, y + 41, age_width, 20),
            Qt.AlignmentFlag.AlignVCenter,
            age,
        )
        p.restore()


def details_rect(rect):
    rect = QRectF(rect)
    return QRectF(rect.right() - 38, rect.top() + 8, 28, 28)


class SessionList(QListWidget):
    detailsRequested = Signal(object)

    def mouseMoveEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if item and details_rect(self.visualItemRect(item)).contains(event.position()):
            self.setToolTip(t("Session details"))
        else:
            self.setToolTip("")
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if (
            item
            and event.button() == Qt.MouseButton.LeftButton
            and details_rect(self.visualItemRect(item)).contains(event.position())
        ):
            self.setCurrentItem(item)
            self.detailsRequested.emit(item)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class QuotaRow(QPushButton):
    def __init__(self, agent, parent=None):
        super().__init__(parent)
        self.agent = agent
        self.percent = None
        self.stale = False
        self.setFixedHeight(36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(4, 1, -4, -1)
        if self.underMouse() or self.hasFocus():
            p.setPen(QPen(QColor(MUTED), 1) if self.hasFocus() else Qt.PenStyle.NoPen)
            p.setBrush(QColor("#303030"))
            p.drawRoundedRect(rect, 7, 7)
        _font(p, 12, QFont.Weight.Medium)
        p.setPen(QColor(INK))
        p.drawText(
            QRectF(13, 0, 80, self.height()), Qt.AlignmentFlag.AlignVCenter, self.agent
        )
        status = self.text().split("\n", 1)[-1]
        _font(p, 11)
        p.setPen(QColor(ATTENTION_COLOR if self.stale else MUTED))
        p.drawText(
            QRectF(100, 0, self.width() - 113, self.height()),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            status,
        )
        if self.percent is not None and not self.stale:
            track = QRectF(103, self.height() / 2 - 2, max(30, self.width() - 201), 4)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#444444"))
            p.drawRoundedRect(track, 2, 2)
            track.setWidth(track.width() * min(100, max(0, self.percent)) / 100)
            p.setBrush(QColor(ATTENTION_COLOR if self.percent >= 80 else "#d4d4d4"))
            p.drawRoundedRect(track, 2, 2)
        p.end()
