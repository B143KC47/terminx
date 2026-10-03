"""A single dark palette for the panel, dialogs, menus and native Qt controls."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette


def apply_theme(app):
    if getattr(app, "_terminx_dark_theme", False):
        return
    app._terminx_dark_theme = True
    app.setStyle("Fusion")
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    palette = QPalette()
    for role, color in {
        QPalette.ColorRole.Window: "#171717",
        QPalette.ColorRole.WindowText: "#ececec",
        QPalette.ColorRole.Base: "#212121",
        QPalette.ColorRole.AlternateBase: "#262626",
        QPalette.ColorRole.Text: "#ececec",
        QPalette.ColorRole.Button: "#262626",
        QPalette.ColorRole.ButtonText: "#ececec",
        QPalette.ColorRole.ToolTipBase: "#303030",
        QPalette.ColorRole.ToolTipText: "#ececec",
        QPalette.ColorRole.Highlight: "#404040",
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.Link: "#b5d8f7",
    }.items():
        palette.setColor(role, QColor(color))
    for role in [
        QPalette.ColorRole.Text,
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.ButtonText,
    ]:
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#787878"))
    app.setPalette(palette)
