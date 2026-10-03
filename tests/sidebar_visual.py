"""Opt-in native Qt render check. All displayed sessions and quotas are fixtures."""

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QTabWidget

from terminx.agents.base import Quota, QuotaWindow, SessionInfo
from terminx.core.terminals import FocusResult
from terminx.ui.sidebar import Sidebar


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output")
    args = parser.parse_args()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    results = {}
    with tempfile.TemporaryDirectory() as directory:
        window = Sidebar({"lang": "zh_CN", "state_dir": directory}, start_workers=False)
        now = datetime.now(timezone.utc)
        agents = ["codex", "claude", "kimi", "grok", "opencode"]
        states = [
            "outputting",
            "waiting_approval",
            "waiting_input",
            "completed",
            "unknown",
        ]
        titles = [
            "示例：实现会话侧边栏",
            "示例：等待文件修改批准",
            "示例：等待选择测试方案",
            "示例：文档更新已结束",
            "示例：很长的项目名称与目录用于检查窄屏布局",
        ]
        window.accept_sessions(
            [
                SessionInfo(
                    a,
                    session_id="demo-" + a,
                    data_root=directory,
                    cwd="C:/Projects/同一个目录/session-sidebar",
                    title=title,
                    status=state,
                    status_at=now,
                    status_source="fixture",
                    presence="live" if a != "opencode" else "unverified",
                )
                for a, state, title in zip(agents, states, titles)
            ],
            [],
        )
        log = Path(directory) / "public-preview.jsonl"
        log.write_text(
            json.dumps(
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "agent_message",
                        "message": "示例输出：已完成终端定位修复，正在检查侧边栏交互。",
                    },
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        window.rows[0].activity_path = str(log)
        window.accept_quotas(
            [
                {
                    "agent": a,
                    "quota": Quota(
                        a,
                        source="Fixture",
                        fetched_at=now,
                        availability="unavailable"
                        if a in {"grok", "opencode"}
                        else "ok",
                        windows=[]
                        if a in {"grok", "opencode"}
                        else [QuotaWindow("5h", 18000, used_percent=pct)],
                    ),
                }
                for a, pct in zip(agents, [38, 72, 21, 0, 0])
            ],
            [],
        )
        window.show()

        def capture():
            try:
                area = window.screen().availableGeometry()
                assert area.contains(window.geometry()), (
                    "Sidebar extends outside the available screen"
                )
                path = Path(args.output)
                path.parent.mkdir(parents=True, exist_ok=True)
                assert window.collapsed and window.height() == 88
                assert window.grab().save(str(path.with_stem(path.stem + "-rail")))
                window.reveal()
                app.processEvents()
                assert window.list.count() == 4, (
                    "History must not appear as an open terminal"
                )
                window.list.setCurrentRow(1)
                key = window.list.currentItem().data(Qt.ItemDataRole.UserRole)
                window.toggle_collapse()
                assert window.width() <= 80
                window.reveal()
                app.processEvents()
                assert window.list.currentItem().data(Qt.ItemDataRole.UserRole) == key
                assert window.grab().save(str(path))
                compact_height = window.height()
                window.toggle_quotas()
                app.processEvents()
                assert area.contains(window.geometry()), (
                    "Quota drawer exceeds screen bounds"
                )
                assert window.grab().save(str(path.with_stem(path.stem + "-quota")))
                results.update(
                    scale=window.devicePixelRatioF(),
                    width=window.width(),
                    height=window.height(),
                    compact_height=compact_height,
                    open_terminals=window.list.count(),
                    within_screen=True,
                    collapsed_restored=True,
                    selection_preserved=True,
                )
                window.focus_target = window.rows[0]
                window.action_done(
                    "focus",
                    FocusResult(
                        "unsupported",
                        "This terminal layout cannot be identified automatically",
                    ),
                )
                app.processEvents()
                assert area.contains(window.geometry()), (
                    "Focus feedback exceeds screen bounds"
                )
                assert window.grab().save(str(path.with_stem(path.stem + "-feedback")))
                window.show_details(window.rows[0])
                app.processEvents()
                dialog = window.details_dialog
                assert area.contains(dialog.frameGeometry()), (
                    f"Session details exceed screen bounds: {dialog.frameGeometry()} vs {area}"
                )
                assert dialog.grab().save(str(path.with_stem(path.stem + "-details")))
                dialog.findChild(QTabWidget).setCurrentIndex(1)
                app.processEvents()
                assert "示例输出" in dialog.preview.toPlainText()
                assert dialog.grab().save(str(path.with_stem(path.stem + "-output")))
                results.update(
                    details_within_screen=True,
                    public_preview=True,
                    visible_failure=True,
                )
            except Exception as exc:
                results["error"] = str(exc)
            finally:
                window.quit()

        QTimer.singleShot(750, capture)
        app.exec()
    print(json.dumps(results))
    if "error" in results:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
