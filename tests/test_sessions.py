import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from terminx.agents.base import RuntimeBinding, SessionInfo
from terminx.agents.claude import ClaudeAdapter
from terminx.agents.codex import CodexAdapter
from terminx.agents.grok import GrokAdapter
from terminx.agents.kimi import KimiAdapter
from terminx.bridge import normalize_hook, normalize_statusline
from terminx.core.events import EventJournal, SessionEvent, apply_event
from terminx.core.logevents import JsonlTail, event_from_log
from terminx.core.monitor import Monitor, runtime_alive
from terminx.core.terminals import TerminalLocator, launch_session


class StateTests(unittest.TestCase):
    def test_equal_native_times_survive_datetime_rounding(self):
        session = SessionInfo("codex", session_id="precision", data_root="root")
        at = 100.1234566
        self.assertTrue(
            apply_event(
                session, SessionEvent("codex", "precision", "root", "tool_finished", at)
            )
        )
        self.assertTrue(
            apply_event(
                session, SessionEvent("codex", "precision", "root", "completed", at)
            )
        )
        self.assertEqual(session.status, "completed")
        self.assertFalse(
            apply_event(
                session,
                SessionEvent("codex", "precision", "root", "processing", at - 0.01),
            )
        )
        self.assertEqual(session.status, "completed")

    def setUp(self):
        self.s = SessionInfo(
            "codex", session_id="one", data_root="root", status="unknown"
        )
        self.now = time.time() - 100

    def event(self, kind, offset=0, turn="a", **data):
        return SessionEvent(
            "codex", "one", "root", kind, self.now + offset, turn_id=turn, data=data
        )

    def test_no_output_does_not_mean_paused(self):
        apply_event(self.s, self.event("turn_started"))
        apply_event(self.s, self.event("heartbeat", 10))
        self.assertEqual(self.s.status, "processing")

    def test_stop_candidate_cannot_finish_turn(self):
        apply_event(self.s, self.event("turn_started"))
        apply_event(self.s, self.event("stop_candidate", 1))
        self.assertEqual(self.s.status, "processing")
        apply_event(self.s, self.event("completed", 2))
        self.assertEqual(self.s.status, "completed")

    def test_old_and_other_turn_end_cannot_override_new_turn(self):
        apply_event(self.s, self.event("turn_started", 10, "b"))
        apply_event(self.s, self.event("completed", 0, "a"))
        apply_event(self.s, self.event("completed", 20, "a"))
        self.assertEqual(self.s.status, "processing")
        self.assertEqual(self.s.turn_id, "b")

    def test_waiting_resolves_only_with_evidence(self):
        apply_event(self.s, self.event("waiting_approval"))
        apply_event(self.s, self.event("heartbeat", 10))
        self.assertEqual(self.s.status, "waiting_approval")
        apply_event(self.s, self.event("tool_running", 11))
        self.assertEqual(self.s.status, "tool_running")

    def test_log_replay_keeps_runtime_from_earlier_registration(self):
        apply_event(self.s, self.event("completed", 50))
        apply_event(self.s, self.event("session_started", 0, pid=20, created_at=10))
        self.assertEqual(self.s.runtime.pid, 20)
        self.assertEqual(self.s.status, "completed")

    def test_delayed_exit_from_previous_runtime_cannot_end_resume(self):
        apply_event(self.s, self.event("session_started", 10, pid=20, created_at=20))
        apply_event(self.s, self.event("exited", 20, pid=10, created_at=10))
        self.assertEqual(self.s.status, "ready")
        self.assertEqual(self.s.runtime.pid, 20)

    def test_hook_does_not_store_content_or_credentials(self):
        event = normalize_hook(
            "claude",
            {
                "session_id": "a",
                "hook_event_name": "PermissionRequest",
                "prompt": "PRIVATE",
                "tool_input": {"secret": "PRIVATE"},
                "accessToken": "PRIVATE",
            },
            root="root",
        )
        self.assertEqual(event.kind, "waiting_approval")
        self.assertNotIn("PRIVATE", json.dumps(event.data))

    def test_queued_prompt_does_not_start_new_turn(self):
        event = normalize_hook(
            "kimi",
            {"session_id": "x", "hook_event_name": "UserPromptQueued"},
            root="root",
        )
        apply_event(self.s, self.event("waiting_input"))
        apply_event(self.s, event)
        self.assertEqual(self.s.status, "waiting_input")

    def test_grok_camel_case_and_cancel(self):
        event = normalize_hook(
            "grok",
            {"sessionId": "one", "hook_event_name": "StopCancelled", "promptId": "a"},
            root="root",
        )
        self.assertEqual(event.kind, "interrupted")
        self.assertEqual(event.turn_id, "a")

    def test_statusline_units_are_not_multiplied(self):
        event = normalize_statusline(
            "claude",
            {
                "session_id": "s",
                "rate_limits": {"five_hour": {"used_percentage": 42, "resets_at": 123}},
                "context_window": {"used_percentage": 19},
            },
            root="root",
        )
        self.assertEqual(event.data["rate_limits"]["five_hour"]["used_percentage"], 42)
        self.assertEqual(event.data["context_percent"], 19)

    def test_pid_reuse_is_not_live(self):
        with patch("psutil.Process") as process:
            process.return_value.create_time.return_value = 101
            self.assertFalse(runtime_alive(RuntimeBinding(123, 100)))


class LogTests(unittest.TestCase):
    def test_oversized_record_does_not_block_later_complete_events(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            path.write_bytes(b'{"n":1}\n')
            tail = JsonlTail()
            self.assertEqual(tail.read(path)[0], [{"n": 1}])
            with path.open("ab") as stream:
                stream.write(
                    json.dumps({"text": "x" * 2_100_000}).encode() + b'\n{"n":2}\n'
                )
            rows = []
            for _ in range(3):
                rows.extend(tail.read(path)[0])
            self.assertIn({"n": 2}, rows)

    def test_current_codex_item_events_report_progress_without_retaining_content(self):
        for item, kind in [
            ("Reasoning", "processing"),
            ("AgentMessage", "outputting"),
            ("CommandExecution", "processing"),
        ]:
            event = event_from_log(
                SessionInfo("codex"),
                {
                    "timestamp": time.time(),
                    "type": "event_msg",
                    "payload": {
                        "type": "item_completed",
                        "turn_id": "live-turn",
                        "item": {
                            "type": item,
                            "content": "PRIVATE",
                            "stdout": "PRIVATE",
                        },
                    },
                },
            )
            self.assertEqual(event.kind, kind)
            self.assertEqual(event.turn_id, "live-turn")
            self.assertNotIn("PRIVATE", json.dumps(event.data))

    def test_invalid_nested_payloads_are_ignored(self):
        for agent, payload in [
            ("codex", {"payload": []}),
            ("kimi", {"event": []}),
            ("grok", {"params": {"update": []}}),
        ]:
            self.assertIsNone(
                event_from_log(
                    SessionInfo(agent), {"timestamp": time.time(), **payload}
                )
            )

    def test_incomplete_line_truncation_and_replacement(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "events.jsonl"
            tail = JsonlTail()
            p.write_bytes(b'{"n":1}\n{"n":')
            self.assertEqual(tail.read(p)[0], [{"n": 1}])
            with p.open("ab") as f:
                f.write(b"2}\n")
            self.assertEqual(tail.read(p)[0], [{"n": 2}])
            self.assertEqual(tail.read(p)[0], [])
            p.write_bytes(b'{"n":3}\n')
            rows, reset = tail.read(p)
            self.assertTrue(reset)
            self.assertEqual(rows, [{"n": 3}])

    def test_provider_finish_records_and_nonfinal_claude(self):
        rows = {
            "codex": {
                "timestamp": time.time(),
                "type": "event_msg",
                "payload": {"type": "task_complete"},
            },
            "claude": {
                "timestamp": time.time(),
                "type": "system",
                "subtype": "turn_duration",
            },
            "kimi": {
                "time": time.time() * 1000,
                "type": "turn.ended",
                "reason": "completed",
            },
            "grok": {
                "timestamp": time.time() * 1000,
                "method": "session/update",
                "params": {
                    "update": {
                        "sessionUpdate": "turn_completed",
                        "stop_reason": "end_turn",
                    }
                },
            },
        }
        for agent, obj in rows.items():
            self.assertEqual(event_from_log(SessionInfo(agent), obj).kind, "completed")
        e = event_from_log(
            SessionInfo("claude"),
            {
                "timestamp": time.time(),
                "type": "assistant",
                "message": {"stop_reason": "end_turn"},
            },
        )
        self.assertNotEqual(e.kind, "completed")

    def test_journal_deduplicates_and_does_not_hold_db_open(self):
        with tempfile.TemporaryDirectory() as td:
            journal = EventJournal(td)
            e = SessionEvent("kimi", "id", "root", "turn_started", time.time())
            journal.append(e)
            journal.append(e)
            self.assertEqual(len(journal.read()), 1)
            Path(journal.path).rename(Path(td) / "renamed.db")


class DiscoveryTests(unittest.TestCase):
    def test_codex_home_override_and_malformed_rows_keep_valid_session(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td) / "sessions" / "2026" / "10" / "01"
            folder.mkdir(parents=True)
            (folder / "rollout-test.jsonl").write_text(
                '[]\n{"payload":[]}\n'
                + json.dumps(
                    {
                        "type": "session_meta",
                        "payload": {"id": "test", "cwd": "C:/work"},
                    }
                )
                + "\n"
            )
            rows = CodexAdapter().find_sessions({"paths": {"codex": td}})
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].data_root, td)

    def test_bad_record_does_not_hide_other_sessions(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "log.jsonl"
            now = time.time()
            log.write_text(
                "\n".join(
                    json.dumps(e)
                    for e in [
                        {
                            "timestamp": now,
                            "type": "event_msg",
                            "payload": {"type": "token_count", "info": []},
                        },
                        {
                            "timestamp": now,
                            "type": "event_msg",
                            "payload": {"type": "task_complete"},
                        },
                    ]
                )
                + "\n"
            )
            adapter = unittest.mock.Mock()
            adapter.name = "codex"
            adapter.find_sessions.return_value = [
                SessionInfo("codex", session_id="one", activity_path=str(log))
            ]
            scanner = unittest.mock.Mock()
            scanner.scan.return_value = []
            rows, errors = Monitor(
                [adapter], {"state_dir": td}, live_processes=scanner
            ).scan()
            self.assertEqual(rows[0].status, "completed")
            self.assertFalse(errors)

    def test_codex_same_directory_sessions_are_not_merged(self):
        with tempfile.TemporaryDirectory() as td:
            day = Path(td) / "2026" / "10" / "01"
            day.mkdir(parents=True)
            for sid in ["one", "two", "three"]:
                (day / f"rollout-{sid}.jsonl").write_text(
                    json.dumps(
                        {
                            "type": "session_meta",
                            "payload": {"id": sid, "cwd": "C:/same"},
                        }
                    )
                    + "\n"
                )
            rows = CodexAdapter().find_sessions({"paths": {"codex": td}})
            self.assertEqual({s.session_id for s in rows}, {"one", "two", "three"})

    def test_claude_keeps_all_sessions_in_project(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td) / "projects" / "same"
            project.mkdir(parents=True)
            for sid in ["one", "two"]:
                (project / f"{sid}.jsonl").write_text(
                    json.dumps({"type": "user", "cwd": "C:/same"}) + "\n"
                )
            self.assertEqual(
                len(ClaudeAdapter().find_sessions({"paths": {"claude": td}})), 2
            )

    def test_kimi_resume_uses_exact_id(self):
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "sessions" / "wd_test" / "exact-id" / "state.json"
            state.parent.mkdir(parents=True)
            state.write_text('{"workDir":"C:/same"}')
            s = KimiAdapter().find_sessions({"paths": {"kimi": td}})[0]
            self.assertEqual(s.resume_cmd, ["kimi", "--session", "exact-id"])

    def test_grok_metadata_and_resume(self):
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "sessions" / "C%3A%5Cwork" / "grok-id" / "summary.json"
            state.parent.mkdir(parents=True)
            state.write_text(
                '{"generated_title":"Sample","current_model_id":"grok-code"}'
            )
            s = GrokAdapter().find_sessions({"paths": {"grok": td}})[0]
            self.assertEqual(s.cwd, "C:\\work")
            self.assertEqual(s.resume_cmd, ["grok", "--resume", "grok-id"])

    def test_monitor_reconciles_exit_and_identity(self):
        with tempfile.TemporaryDirectory() as td:
            adapter = unittest.mock.Mock(name="adapter")
            adapter.name = "codex"
            adapter.find_sessions.return_value = []
            j = EventJournal(td)
            j.append(
                SessionEvent(
                    "codex",
                    "one",
                    "root",
                    "turn_started",
                    time.time(),
                    data={"pid": 99999999, "created_at": 1},
                )
            )
            scanner = unittest.mock.Mock()
            scanner.scan.return_value = []
            rows, errors = Monitor(
                [adapter], {"state_dir": td}, live_processes=scanner
            ).scan()
            self.assertFalse(errors)
            self.assertEqual(rows[0].status, "exited")


class FocusTests(unittest.TestCase):
    def test_owned_native_binding_can_focus_with_empty_hook_journal(self):
        if __import__("os").name != "nt":
            self.skipTest("Windows launch path")
        with tempfile.TemporaryDirectory() as td:
            tag = "a" * 32
            folder = Path(td) / "launches"
            folder.mkdir()
            (folder / (tag + ".json")).write_text(
                json.dumps(
                    {
                        "agent": "codex",
                        "data_root": "root",
                        "pid": 10,
                        "created_at": 100,
                        "session_id": "one",
                    }
                )
            )
            with EventJournal(td).connect():
                pass
            process = unittest.mock.Mock()
            process.pid = 10
            process.create_time.return_value = 100
            process.parents.return_value = []
            session = SessionInfo(
                "codex",
                session_id="one",
                data_root="root",
                runtime=RuntimeBinding(10, 100, launch_id=tag),
            )
            with (
                patch("terminx.core.terminals.runtime_alive", return_value=True),
                patch("terminx.core.terminals.psutil.Process", return_value=process),
                patch.object(TerminalLocator, "_focus_tag") as focus,
            ):
                TerminalLocator({"state_dir": td}).focus(session)
                focus.assert_called_once_with(tag)

    def test_unverified_never_guesses_or_resumes(self):
        with patch("terminx.core.terminals.subprocess.Popen") as spawn:
            result = TerminalLocator().focus(SessionInfo("codex", cwd="C:/same"))
            self.assertEqual(result.status, "unsupported")
            spawn.assert_not_called()

    def test_exited_pid_never_focuses(self):
        with (
            patch("terminx.core.terminals.os.name", "nt"),
            patch("terminx.core.terminals.runtime_alive", return_value=False),
        ):
            result = TerminalLocator().focus(
                SessionInfo("codex", runtime=RuntimeBinding(1, 1))
            )
            self.assertEqual(result.status, "exited")

    def test_live_resume_rejected(self):
        with (
            tempfile.TemporaryDirectory() as td,
            patch("terminx.core.terminals.shutil.which", return_value="cli"),
            patch("terminx.core.terminals.runtime_alive", return_value=True),
        ):
            if __import__("os").name != "nt":
                self.skipTest("Windows launch path")
            with self.assertRaisesRegex(RuntimeError, "already running"):
                launch_session(
                    "codex",
                    td,
                    session=SessionInfo(
                        "codex", session_id="one", runtime=RuntimeBinding(1, 1)
                    ),
                )

    def test_launch_uses_console_python_and_preserves_data_home(self):
        if __import__("os").name != "nt":
            self.skipTest("Windows launch path")
        with (
            tempfile.TemporaryDirectory() as td,
            patch("terminx.core.terminals.shutil.which", return_value="cli"),
            patch("terminx.core.paths.sys.executable", "C:/Python/pythonw.exe"),
            patch("terminx.core.terminals.subprocess.Popen") as spawn,
        ):
            cfg = {
                "state_dir": td,
                "paths": {"codex": str(Path(td) / "custom" / "sessions")},
            }
            sid = launch_session("codex", td, cfg)
            record = json.loads((Path(td) / "launches" / f"{sid}.json").read_text())
            self.assertEqual(Path(record["data_root"]), Path(td) / "custom")
            self.assertIn("C:\\Python\\python.exe", spawn.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
