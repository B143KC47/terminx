"""Open terminal identity must come from processes and exact files, never cwd."""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from terminx.agents.codex import CodexAdapter
from terminx.core.live import OpenCLI, interactive_agent
from terminx.core.monitor import Monitor


class RoleTests(unittest.TestCase):
    def test_background_helpers_are_not_terminals(self):
        for name, command in [
            ("codex", "app-server"),
            ("codex", "exec"),
            ("codex", "mcp-server"),
            ("kimi", "web"),
            ("grok", "serve"),
            ("opencode", "web"),
        ]:
            self.assertIsNone(interactive_agent(name + ".exe", [name, command]))
        self.assertIsNone(interactive_agent("claude.exe", ["claude", "-p", "hello"]))

    def test_interactive_resume_and_option_values_remain_visible(self):
        self.assertEqual(
            interactive_agent("codex.exe", ["codex", "resume", "native-id"]), "codex"
        )
        self.assertEqual(
            interactive_agent("codex.exe", ["codex", "--model", "review"]), "codex"
        )
        self.assertEqual(
            interactive_agent(
                "node.exe", ["node", "C:/npm/@openai/codex/bin/codex.js"]
            ),
            "codex",
        )
        self.assertIsNone(
            interactive_agent(
                "node.exe", ["node", "C:/unrelated/app.js", "@openai/codex/"]
            )
        )


class OpenTerminalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.folder = self.home / "sessions" / "2026" / "10" / "01"
        self.folder.mkdir(parents=True)
        self.scanner = Mock()
        self.scanner.scan.return_value = []
        self.monitor = Monitor(
            [CodexAdapter()],
            {
                "state_dir": str(self.home / "events"),
                "paths": {"codex": str(self.home)},
            },
            live_processes=self.scanner,
        )
        self.alive = patch("terminx.core.monitor.runtime_alive", return_value=True)
        self.alive.start()

    def tearDown(self):
        self.alive.stop()
        self.temp.cleanup()

    def rollout(self, sid, source="cli"):
        file = self.folder / f"rollout-{sid}.jsonl"
        records = [
            dict(
                type="session_meta", payload=dict(id=sid, cwd="C:/same", source=source)
            ),
            dict(
                timestamp=time.time() - 10,
                type="event_msg",
                payload=dict(type="task_started", turn_id="turn"),
            ),
        ]
        file.write_text("\n".join(json.dumps(row) for row in records) + "\n")
        return str(file)

    def scan(self, clis):
        self.scanner.scan.return_value = clis
        self.monitor.last_discovery = 0
        rows, errors = self.monitor.scan()
        self.assertFalse(errors)
        return [row for row in rows if row.presence == "live"]

    def cli(self, files, pid=10):
        return OpenCLI("codex", pid, 100, "C:/same", 123, files)

    def test_only_held_session_is_open_even_in_same_folder(self):
        self.rollout("history")
        held = self.rollout("held")
        live = self.scan([self.cli([held])])
        self.assertEqual([row.session_id for row in live], ["held"])
        self.assertEqual(live[0].status, "processing")
        self.assertEqual(live[0].runtime.console_hwnd, 123)

    def test_progress_and_completion_without_hook_config_or_journal(self):
        held = self.rollout("passive")
        for kind, state in [
            ("agent_message", "outputting"),
            ("exec_command_begin", "tool_running"),
            ("exec_command_end", "processing"),
            ("task_complete", "completed"),
        ]:
            with Path(held).open("a") as stream:
                stream.write(
                    json.dumps(
                        {
                            "timestamp": time.time(),
                            "type": "event_msg",
                            "payload": {"type": kind, "turn_id": "turn"},
                        }
                    )
                    + "\n"
                )
            rows = self.scan([self.cli([held])])
            self.assertEqual(rows[0].status, state)
            self.assertEqual(rows[0].status_source, "log")
        self.assertFalse(self.monitor.journal.path.exists())
        self.assertFalse((self.home / "hooks.json").exists())

    def test_older_open_session_bypasses_history_cutoff(self):
        held = self.rollout("old")
        os.utime(held, (1, 1))
        self.assertEqual(
            [row.session_id for row in self.scan([self.cli([held])])], ["old"]
        )

    def test_missing_handle_evidence_does_not_choose_recent_history(self):
        self.rollout("recent")
        rows = self.scan([self.cli([])])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].session_id, "")
        self.assertEqual(rows[0].status, "unknown")
        self.assertIsNone(rows[0].resume_cmd)

    def test_multiple_files_do_not_invent_multiple_terminals(self):
        files = [self.rollout("one"), self.rollout("two")]
        rows = self.scan([self.cli(files)])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].session_id, "")

    def test_subagent_file_is_not_another_open_terminal(self):
        files = [
            self.rollout("parent"),
            self.rollout("child", {"subagent": {"parent_thread_id": "parent"}}),
        ]
        self.assertEqual(
            [row.session_id for row in self.scan([self.cli(files)])], ["parent"]
        )

    def test_switch_session_in_same_process_and_exit(self):
        one, two = self.rollout("one"), self.rollout("two")
        self.assertEqual(self.scan([self.cli([one])])[0].session_id, "one")
        self.assertEqual(self.scan([self.cli([two])])[0].session_id, "two")
        self.assertEqual(self.scan([]), [])

    def test_two_terminals_sharing_a_file_are_not_silently_merged(self):
        file = self.rollout("one")
        live = self.scan([self.cli([file]), self.cli([file], pid=20)])
        self.assertEqual(len(live), 2)
        self.assertEqual({row.runtime.pid for row in live}, {10, 20})
        self.assertEqual(len({row.key for row in live}), 2)

    def test_owned_launch_keeps_exact_marker_through_native_wrapper(self):
        file = self.rollout("owned")
        folder = self.home / "events" / "launches"
        folder.mkdir(parents=True)
        tag = "a" * 32
        path = folder / (tag + ".json")
        path.write_text(
            json.dumps(
                {
                    "agent": "codex",
                    "data_root": str(self.home),
                    "pid": 5,
                    "created_at": 90,
                    "session_id": "",
                }
            )
        )
        cli = self.cli([file])
        cli.ancestors = (5,)
        row = self.scan([cli])[0]
        self.assertEqual(row.runtime.launch_id, tag)
        self.assertEqual(row.runtime.pid, 10)
        self.assertEqual(json.loads(path.read_text())["session_id"], "owned")

    def test_reopened_terminal_does_not_keep_exited_state(self):
        file = self.rollout("resume")
        row = self.scan([self.cli([file])])[0]
        self.monitor.sessions[row.key].status = "exited"
        cli = self.cli([file], pid=20)
        cli.created_at = 200
        row = self.scan([cli])[0]
        self.assertEqual(row.status, "unknown")
        self.assertEqual(row.runtime.pid, 20)


if __name__ == "__main__":
    unittest.main()
