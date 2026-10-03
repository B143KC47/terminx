import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    from terminx.agents.base import Quota, QuotaWindow, SessionInfo
    from terminx.ui.sidebar import Sidebar
except ModuleNotFoundError as exc:
    if not (exc.name or "").startswith("PySide6"):
        raise
    Sidebar = None


@unittest.skipIf(Sidebar is None, "Install desktop extra to test Qt")
class SidebarTests(unittest.TestCase):
    def instance_client(self, name, command):
        return subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).with_name("instance_client.py")),
                name,
                command,
                self.temp.name,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=Path(__file__).resolve().parents[1],
        )

    def finish_instance_client(self, client):
        from PySide6.QtTest import QTest

        deadline = time.monotonic() + 12
        while client.poll() is None and time.monotonic() < deadline:
            QTest.qWait(10)
        if client.poll() is None:
            client.kill()
        stdout, stderr = client.communicate(timeout=3)
        self.assertEqual(client.returncode, 0, (stdout, stderr))

    def test_single_instance_commands_receive_acknowledgement(self):
        from unittest.mock import Mock

        from PySide6.QtNetwork import QLocalServer

        from terminx.ui.sidebar import receive_instance_command

        name = "terminx-test-" + uuid.uuid4().hex
        server = QLocalServer()
        self.assertTrue(server.listen(name))
        window = Mock()
        server.newConnection.connect(lambda: receive_instance_command(server, window))
        try:
            for message in ("quit", "show", "startup"):
                self.finish_instance_client(self.instance_client(name, message))
            window.quit.assert_called_once()
            window.reveal.assert_called_once()
        finally:
            server.close()
            QLocalServer.removeServer(name)

    def test_close_command_is_acknowledged_before_server_process_exits(self):
        from PySide6.QtTest import QTest

        name = "terminx-test-" + uuid.uuid4().hex
        server = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).with_name("instance_server.py")),
                name,
                self.temp.name,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=Path(__file__).resolve().parents[1],
        )
        try:
            deadline = time.monotonic() + 6
            while (
                not (Path(self.temp.name) / "server-ready").exists()
                and time.monotonic() < deadline
            ):
                QTest.qWait(10)
            self.assertTrue((Path(self.temp.name) / "server-ready").exists())
            self.finish_instance_client(self.instance_client(name, "quit"))
            self.finish_instance_client(server)
        finally:
            if server.poll() is None:
                server.kill()
                server.communicate(timeout=3)

    def test_partial_instance_command_waits_for_complete_frame(self):
        from unittest.mock import Mock

        from PySide6.QtNetwork import QLocalServer
        from PySide6.QtTest import QTest

        from terminx.ui.sidebar import receive_instance_command

        name = "terminx-test-" + uuid.uuid4().hex
        server = QLocalServer()
        self.assertTrue(server.listen(name))
        window = Mock()
        server.newConnection.connect(lambda: receive_instance_command(server, window))
        client = self.instance_client(name, "partial")
        try:
            deadline = time.monotonic() + 8
            while (
                not (Path(self.temp.name) / "partial").exists()
                and time.monotonic() < deadline
            ):
                QTest.qWait(10)
            self.assertTrue((Path(self.temp.name) / "partial").exists())
            QTest.qWait(30)
            window.quit.assert_not_called()
            (Path(self.temp.name) / "complete").touch()
            self.finish_instance_client(client)
            window.quit.assert_called_once()
        finally:
            if client.poll() is None:
                client.kill()
                client.communicate(timeout=3)
            server.close()
            QLocalServer.removeServer(name)

    def settings_action(self, action):
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox

        errors = []

        def interact():
            dialog = next(
                widget
                for widget in self.app.topLevelWidgets()
                if isinstance(widget, QDialog)
                and widget.parent() is self.window
                and widget.isVisible()
            )
            try:
                action(
                    dialog,
                    dialog.findChild(QCheckBox, "startup-setting"),
                    dialog.findChild(QDialogButtonBox),
                )
            except Exception as exc:
                errors.append(exc)
                dialog.reject()

        QTimer.singleShot(0, interact)
        self.window.settings_dialog()
        if errors:
            raise errors[0]

    def test_settings_save_changes_startup_and_cancel_keeps_it(self):
        from PySide6.QtWidgets import QDialogButtonBox

        with (
            patch("terminx.ui.sidebar.sys.platform", "win32"),
            patch("terminx.ui.sidebar.startup_enabled", return_value=False),
            patch("terminx.ui.sidebar.set_startup") as startup,
        ):

            def save(dialog, checkbox, buttons):
                self.assertTrue(checkbox.isEnabled())
                checkbox.setChecked(True)
                buttons.button(QDialogButtonBox.StandardButton.Save).click()

            self.settings_action(save)
            startup.assert_called_once_with(True)
            startup.reset_mock()

            def cancel(dialog, checkbox, buttons):
                checkbox.setChecked(True)
                buttons.button(QDialogButtonBox.StandardButton.Cancel).click()

            self.settings_action(cancel)
            startup.assert_not_called()

    def test_settings_write_failure_keeps_dialog_open_and_reports_failure(self):
        from PySide6.QtWidgets import QDialogButtonBox

        with (
            patch("terminx.ui.sidebar.sys.platform", "win32"),
            patch("terminx.ui.sidebar.startup_enabled", return_value=False),
            patch(
                "terminx.ui.sidebar.set_startup", side_effect=PermissionError("denied")
            ),
            patch("terminx.ui.sidebar.QMessageBox.warning") as warning,
        ):

            def fail(dialog, checkbox, buttons):
                checkbox.setChecked(True)
                buttons.button(QDialogButtonBox.StandardButton.Save).click()
                warning.assert_called_once()
                self.assertTrue(dialog.isVisible())
                buttons.button(QDialogButtonBox.StandardButton.Cancel).click()

            self.settings_action(fail)

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.window = Sidebar(
            {"lang": "zh_CN", "state_dir": self.temp.name}, start_workers=False
        )

    def tearDown(self):
        self.window.quitting = True
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def rows(self):
        return [
            SessionInfo(
                "codex",
                session_id=str(i),
                data_root="root",
                cwd="C:/same",
                title=f"Work {i}",
                status="processing",
                presence="live",
            )
            for i in range(3)
        ]

    def test_same_directory_cards_selection_stays_stable(self):
        rows = self.rows()
        self.window.accept_sessions(rows, [])
        self.assertEqual(self.window.list.count(), 3)
        self.window.list.setCurrentRow(1)
        selected = self.window.list.currentItem().data(Qt.ItemDataRole.UserRole)
        self.window.accept_sessions(list(reversed(rows)), [])
        self.assertEqual(
            self.window.list.currentItem().data(Qt.ItemDataRole.UserRole), selected
        )

    def test_main_list_shows_only_open_terminals(self):
        rows = self.rows()
        rows[1].presence = "unverified"
        rows[2].presence = "exited"
        self.window.accept_sessions(rows, [])
        self.assertEqual(self.window.list.count(), 1)
        self.assertEqual(self.window.filter.currentData(), "live")

    def test_ended_filter_never_includes_closed_terminal(self):
        rows = self.rows()
        for row in rows:
            row.status = "completed"
        rows[1].presence = "unverified"
        rows[2].presence = "exited"
        self.window.accept_sessions(rows, [])
        self.window.filter.setCurrentIndex(3)
        self.assertEqual(self.window.list.count(), 1)

    def test_closed_terminal_disappears_without_losing_other_selection(self):
        rows = self.rows()
        self.window.accept_sessions(rows, [])
        self.window.list.setCurrentRow(1)
        key = self.window.list.currentItem().data(Qt.ItemDataRole.UserRole)
        rows[0].presence = "exited"
        self.window.accept_sessions(rows, [])
        self.assertEqual(self.window.list.count(), 2)
        self.assertEqual(
            self.window.list.currentItem().data(Qt.ItemDataRole.UserRole), key
        )

    def test_search_notes_and_attention_filter(self):
        rows = self.rows()
        rows[1].status = "waiting_approval"
        self.window.saved["notes"] = {self.window.key(rows[0]): "unique note"}
        self.window.accept_sessions(rows, [])
        self.window.search.setText("unique note")
        self.assertEqual(self.window.list.count(), 1)
        self.window.search.clear()
        self.window.filter.setCurrentIndex(2)
        self.assertEqual(self.window.list.count(), 1)
        self.assertIn("等待批准", self.window.list.item(0).text())

    def test_collapse_restore_keeps_expanded_width(self):
        self.assertTrue(self.window.collapsed)
        self.assertEqual(self.window.size().width(), 48)
        self.assertEqual(self.window.size().height(), 88)
        self.window.show()
        self.app.processEvents()
        self.assertGreaterEqual(self.window.expand.height(), 80)
        self.window.reveal()
        self.window.toggle_collapse()
        self.app.processEvents()
        self.assertTrue(self.window.collapsed)
        self.assertLessEqual(self.window.width(), 80)
        self.window.toggle_collapse()
        self.app.processEvents()
        self.assertEqual(self.window.width(), 360)

    def drag(self, widget, destination):
        start = widget.mapToGlobal(QPoint(10, 10))
        for kind, point, button, buttons in [
            (
                QEvent.Type.MouseButtonPress,
                start,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
            ),
            (
                QEvent.Type.MouseMove,
                destination,
                Qt.MouseButton.NoButton,
                Qt.MouseButton.LeftButton,
            ),
            (
                QEvent.Type.MouseButtonRelease,
                destination,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton,
            ),
        ]:
            event = QMouseEvent(
                kind,
                QPointF(widget.mapFromGlobal(point)),
                QPointF(point),
                button,
                buttons,
                Qt.KeyboardModifier.NoModifier,
            )
            self.app.sendEvent(widget, event)
        self.app.processEvents()

    def test_dragging_rail_moves_without_expanding_and_persists(self):
        self.window.show()
        self.app.processEvents()
        self.drag(self.window.expand, QPoint(320, 220))
        self.assertTrue(self.window.collapsed)
        self.assertEqual(self.window.anchor, "free")
        before = self.window.pos()
        self.window.refresh_labels()
        self.assertEqual(self.window.pos(), before)
        saved = json.loads(self.window.store_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["anchor"], "free")
        self.assertEqual(saved["position"], {"x": before.x(), "y": before.y()})

    def test_header_drag_keeps_free_position_through_collapse(self):
        self.window.reveal()
        self.app.processEvents()
        self.drag(self.window.header, QPoint(180, 150))
        self.assertFalse(self.window.collapsed)
        self.assertEqual(self.window.anchor, "free")
        expanded = self.window.pos()
        self.window.collapse()
        self.window.reveal()
        self.assertEqual(self.window.pos(), expanded)

    def test_saved_free_position_restores_on_next_start(self):
        self.window.show()
        self.app.processEvents()
        self.drag(self.window.expand, QPoint(320, 220))
        expected = self.window.pos()
        restored = Sidebar(
            {"lang": "zh_CN", "state_dir": self.temp.name}, start_workers=False
        )
        try:
            self.assertTrue(restored.collapsed)
            self.assertEqual(restored.anchor, "free")
            self.assertEqual(restored.pos(), expected)
        finally:
            restored.quitting = True
            restored.close()
            restored.deleteLater()

    def test_panel_adapts_to_open_terminals_and_quota_drawer(self):
        self.window.reveal()
        self.window.accept_sessions(self.rows()[:1], [])
        one = self.window.height()
        self.window.accept_sessions(self.rows(), [])
        many = self.window.height()
        self.assertGreater(many, one)
        self.window.toggle_quotas()
        self.assertGreater(self.window.height(), many)
        self.assertFalse(self.window.quota_frame.isHidden())

    def test_successful_focus_collapses_and_failed_focus_stays_open(self):
        from types import SimpleNamespace

        self.window.reveal()
        self.window.action_done(
            "focus", SimpleNamespace(status="unsupported", message="Unsupported")
        )
        self.assertFalse(self.window.collapsed)
        self.window.action_done(
            "focus", SimpleNamespace(status="focused", message="Terminal focused")
        )
        self.assertTrue(self.window.collapsed)

    def test_clicked_terminal_exposes_actionable_failure(self):
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QFrame

        from terminx.core.terminals import FocusResult

        self.window.accept_sessions(self.rows()[:1], [])
        self.window.reveal()
        self.app.processEvents()
        with patch("terminx.ui.sidebar.TerminalLocator") as locator:
            locator.return_value.focus.return_value = FocusResult(
                "unsupported",
                "Existing Windows Terminal tabs and panes require a verified automatic identity",
            )
            QTest.mouseClick(
                self.window.list.viewport(),
                Qt.MouseButton.LeftButton,
                pos=self.window.list.visualItemRect(self.window.list.item(0)).center(),
            )
            QTest.qWait(100)
            locator.return_value.focus.assert_called_once()
            feedback = self.window.findChild(QFrame, "terminal-feedback")
            self.assertIsNotNone(feedback)
            self.assertFalse(feedback.isHidden())

    def test_quota_click_always_opens_details_before_data_arrives(self):
        with patch("terminx.ui.sidebar.QDialog.exec", return_value=0) as show:
            self.window.quota_details("codex")
            show.assert_called_once()

    def test_row_details_click_opens_inspector_without_switching_terminal(self):
        from PySide6.QtTest import QTest

        from terminx.core.terminals import FocusResult
        from terminx.ui.sidebar_widgets import details_rect

        row = self.rows()[0]
        self.window.accept_sessions([row], [])
        self.window.reveal()
        self.app.processEvents()
        item_rect = self.window.list.visualItemRect(self.window.list.item(0))
        with patch("terminx.ui.sidebar.TerminalLocator") as locator:
            QTest.mouseClick(
                self.window.list.viewport(),
                Qt.MouseButton.LeftButton,
                pos=details_rect(item_rect).center().toPoint(),
            )
            self.app.processEvents()
            self.assertIsNotNone(self.window.details_dialog)
            self.assertEqual(self.window.details_dialog.session.key, row.key)
            self.assertFalse(self.window.collapsed)
            locator.assert_not_called()
            self.window.details_dialog.close()
            self.app.processEvents()
            locator.return_value.focus.return_value = FocusResult(
                "unsupported", "Unsupported"
            )
            QTest.mouseClick(
                self.window.list.viewport(),
                Qt.MouseButton.LeftButton,
                pos=item_rect.center(),
            )
            QTest.qWait(100)
            locator.return_value.focus.assert_called_once()

    def test_quota_missing_percent_and_invalid_reset_still_opens(self):
        self.window.accept_quotas(
            [
                {
                    "agent": "codex",
                    "quota": Quota(
                        "codex", windows=[QuotaWindow("5h", 18000, reset_at="invalid")]
                    ),
                }
            ],
            [],
        )
        with patch("terminx.ui.sidebar.QDialog.exec", return_value=0) as show:
            self.window.quota_details("codex")
            show.assert_called_once()

    def test_details_copy_folder_notes_and_live_public_preview(self):
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QPushButton, QTabWidget

        from terminx.i18n import t

        row = self.rows()[0]
        row.cwd = self.temp.name
        log = Path(self.temp.name) / "messages.jsonl"
        row.activity_path = str(log)
        public = {
            "type": "event_msg",
            "payload": {"type": "agent_message", "message": "Visible reply"},
        }
        private = {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "channel": "analysis",
                "content": [{"type": "output_text", "text": "Private reasoning"}],
            },
        }
        log.write_text(
            json.dumps(public) + "\n" + json.dumps(private) + "\n", encoding="utf-8"
        )
        self.window.accept_sessions([row], [])
        self.window.show_details(row)
        self.app.processEvents()
        dialog = self.window.details_dialog
        self.assertTrue(dialog.focus_button.isEnabled())
        self.assertFalse(dialog.resume.isEnabled())
        self.assertTrue(dialog.preview.isReadOnly())
        self.assertIn("Visible reply", dialog.preview.toPlainText())
        self.assertNotIn("Private reasoning", dialog.preview.toPlainText())
        QTest.mouseClick(dialog.copy, Qt.MouseButton.LeftButton)
        self.assertEqual(self.app.clipboard().text(), row.session_id)
        with patch(
            "terminx.ui.session_details.QDesktopServices.openUrl", return_value=True
        ) as open_folder:
            QTest.mouseClick(dialog.folder, Qt.MouseButton.LeftButton)
            self.assertEqual(
                Path(open_folder.call_args.args[0].toLocalFile()),
                Path(self.temp.name).resolve(),
            )
        tabs = dialog.findChild(QTabWidget)
        tabs.setCurrentIndex(2)
        dialog.note.setPlainText("Saved from the actual note button")
        save = next(
            button
            for button in dialog.findChildren(QPushButton)
            if button.text() == t("Save note")
        )
        QTest.mouseClick(save, Qt.MouseButton.LeftButton)
        self.assertEqual(
            json.loads(self.window.store_path.read_text(encoding="utf-8"))["notes"][
                self.window.key(row)
            ],
            "Saved from the actual note button",
        )
        public["payload"]["message"] = "New reply"
        with log.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(public) + "\n")
        dialog.update_session()
        self.assertIn("New reply", dialog.preview.toPlainText())
        row.presence = "exited"
        dialog.update_session()
        self.assertFalse(dialog.focus_button.isEnabled())
        self.assertTrue(dialog.resume.isEnabled())

    def test_launch_failure_has_visible_feedback_and_success_collapses(self):
        from PySide6.QtTest import QTest

        self.window.reveal()
        with (
            patch(
                "terminx.ui.sidebar.launch_session",
                side_effect=RuntimeError("CLI is not installed"),
            ),
            patch("terminx.ui.sidebar.QMessageBox.warning") as warning,
        ):
            self.window.launch_terminal("claude", self.temp.name)
            for _ in range(50):
                QTest.qWait(10)
                if "launch" not in self.window.callbacks:
                    break
            warning.assert_called_once()
            self.assertFalse(self.window.collapsed)
        with patch("terminx.ui.sidebar.launch_session", return_value="fixture"):
            self.window.launch_terminal("codex", self.temp.name)
            for _ in range(50):
                QTest.qWait(10)
                if "launch" not in self.window.callbacks:
                    break
            self.assertTrue(self.window.collapsed)

    def test_missing_and_stale_quota_are_visible(self):
        self.window.accept_quotas(
            [
                {"agent": "grok", "quota": Quota("grok", availability="unavailable")},
                {
                    "agent": "codex",
                    "quota": Quota(
                        "codex",
                        availability="stale",
                        windows=[QuotaWindow("5h", 1, used_percent=35)],
                    ),
                },
            ],
            [],
        )
        self.assertIn("暂不可读取", self.window.quota_buttons["grok"].text())
        self.assertIn("已过期", self.window.quota_buttons["codex"].text())

    def test_background_updates_do_not_focus_terminal(self):
        with patch("terminx.ui.sidebar.TerminalLocator") as locator:
            self.window.accept_sessions(self.rows(), [])
            self.window.refresh_labels()
            locator.assert_not_called()

    def test_legacy_notes_import_without_overwriting_new_notes(self):
        self.window.legacy_notes = {"codex::C:/same": "old note"}
        row = self.rows()[0]
        self.assertEqual(self.window.note(row), "old note")
        self.window.saved["notes"][self.window.key(row)] = "edited"
        self.assertEqual(self.window.note(row), "edited")
        self.window.persist()
        saved = json.loads(
            (Path(self.temp.name) / "sidebar.json").read_text(encoding="utf-8")
        )
        self.assertEqual(saved["notes"][self.window.key(row)], "edited")

    def test_small_desktop_keeps_window_inside_available_geometry(self):
        from unittest.mock import Mock

        from PySide6.QtCore import QRect

        screen = Mock()
        screen.availableGeometry.return_value = QRect(0, 0, 680, 480)
        with (
            patch("terminx.ui.sidebar.QApplication.screens", return_value=[screen]),
            patch("terminx.ui.sidebar.QApplication.screenAt", return_value=screen),
        ):
            self.window.accept_sessions(self.rows(), [])
            self.window.reveal()
            self.window.toggle_quotas()
            self.window.dock()
            self.window.show()
            self.app.processEvents()
            self.assertLessEqual(self.window.height(), 456)
            self.assertLessEqual(self.window.y() + self.window.height(), 480)
            self.assertGreater(self.window.scroll.verticalScrollBar().maximum(), 0)


if __name__ == "__main__":
    unittest.main()
