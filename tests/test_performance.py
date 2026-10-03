import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from terminx.agents.base import AgentAdapter, SessionInfo
from terminx.agents.codex import CodexAdapter
from terminx.agents.kimi import KimiAdapter, _read_state_json
from terminx.core import processes


class FakeAdapter(AgentAdapter):
    name = "fake"
    process_names = ["fake"]

    def __init__(self, rows=None):
        self.rows = rows or []
        self.find_calls = 0

    def find_sessions(self, cfg):
        self.find_calls += 1
        return list(self.rows)

    def usage_records(self, since, cfg):
        return []


class ProcessSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.snapshot = processes._snapshot
        self.snapshot_at = processes._snapshot_at
        self.cwd_cache = dict(processes._cwd_cache)
        processes._snapshot = []
        processes._snapshot_at = 0.0
        processes._cwd_cache.clear()

    def tearDown(self):
        processes._snapshot = self.snapshot
        processes._snapshot_at = self.snapshot_at
        processes._cwd_cache.clear()
        processes._cwd_cache.update(self.cwd_cache)

    def test_concurrent_refresh_is_single_flight(self):
        barrier = threading.Barrier(4)

        def call_running(_):
            barrier.wait()
            return processes.running_pids("fake")

        def slow_snapshot():
            time.sleep(0.05)
            return [(42, "fake")]

        with patch.object(
            processes, "_read_process_rows", side_effect=slow_snapshot, create=True
        ) as read:
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(call_running, range(4)))

        self.assertEqual(read.call_count, 1)

    def test_windows_snapshot_falls_back_when_toolhelp_fails(self):
        fallback = [(42, "fake")]
        with (
            patch.object(processes.os, "name", "nt"),
            patch.object(processes, "_toolhelp_rows", side_effect=OSError, create=True),
            patch.object(
                processes, "_tasklist_rows", return_value=fallback, create=True
            ),
        ):
            self.assertEqual(processes._read_process_rows(), fallback)

    def test_non_windows_snapshot_uses_psutil(self):
        expected = [(42, "fake")]
        with (
            patch.object(processes.os, "name", "posix"),
            patch.object(
                processes, "_psutil_rows", return_value=expected
            ) as psutil_rows,
            patch.object(processes, "_toolhelp_rows") as toolhelp_rows,
        ):
            self.assertEqual(processes._read_process_rows(), expected)
        psutil_rows.assert_called_once_with()
        toolhelp_rows.assert_not_called()


class AdapterScanTest(unittest.TestCase):
    def test_no_process_skips_session_store_scan(self):
        adapter = FakeAdapter([SessionInfo(agent="fake", cwd="C:/work")])
        with patch("terminx.agents.base.running_pids", return_value=[]):
            self.assertEqual(adapter.sessions({}), [])
        self.assertEqual(adapter.find_calls, 0)

    def test_row_limit_is_applied_after_live_process_matching(self):
        adapter = FakeAdapter(
            [
                SessionInfo(agent="fake", cwd="C:/stale"),
                SessionInfo(agent="fake", cwd="C:/live-a"),
                SessionInfo(agent="fake", cwd="C:/live-b"),
            ]
        )
        with (
            patch("terminx.agents.base.running_pids", return_value=[10, 11]),
            patch(
                "terminx.agents.base.running_pids_with_cwd",
                return_value={10: "C:\\live-a", 11: "C:\\live-b"},
                create=True,
            ),
        ):
            rows = adapter.sessions({"max_rows_per_agent": 1})

        live = [row for row in rows if row.status != "offline"]
        self.assertEqual([row.cwd for row in live], ["C:/live-a"])

    def test_same_directory_history_is_preserved_without_claiming_pid_ownership(self):
        adapter = FakeAdapter(
            [
                SessionInfo(agent="fake", cwd="C:/live", source="new"),
                SessionInfo(agent="fake", cwd="C:/live", source="old"),
            ]
        )
        with (
            patch("terminx.agents.base.running_pids", return_value=[10]),
            patch(
                "terminx.agents.base.running_pids_with_cwd",
                return_value={10: "C:\\live"},
            ),
        ):
            rows = adapter.sessions({"max_rows_per_agent": 6})

        live = [row for row in rows if row.status != "offline"]
        self.assertEqual(
            [(row.pid, row.source) for row in live], [(None, "new"), (None, "old")]
        )
        self.assertTrue(
            all(
                row.presence == "unverified" and row.status == "unknown" for row in live
            )
        )


class SessionStoreScanTest(unittest.TestCase):
    def test_codex_rollout_scan_uses_directory_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            day = root / "2026" / "08" / "30"
            day.mkdir(parents=True)
            recent = day / "rollout-recent.jsonl"
            old = day / "rollout-old.jsonl"
            recent.write_text("{}\n", encoding="utf-8")
            old.write_text("{}\n", encoding="utf-8")
            now = time.time()
            os.utime(recent, (now, now))
            os.utime(old, (now - 7200, now - 7200))
            since = datetime.fromtimestamp(now - 3600, tz=timezone.utc)

            with patch.object(
                Path, "stat", side_effect=AssertionError("per-file Path.stat")
            ):
                files = CodexAdapter()._rollout_files(root, since)

            self.assertEqual(files, [recent])

    def test_kimi_skips_parsing_expired_state_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sessions = root / "sessions" / "wd_test"
            sessions.mkdir(parents=True)
            now = time.time()
            for index in range(12):
                state = sessions / f"old-{index}" / "state.json"
                state.parent.mkdir()
                state.write_text('{"workDir":"C:/old"}', encoding="utf-8")
                os.utime(state, (now - 7200, now - 7200))
            recent = sessions / "recent" / "state.json"
            recent.parent.mkdir()
            recent.write_text('{"workDir":"C:/recent"}', encoding="utf-8")

            calls = []

            def counted(path):
                calls.append(path)
                return _read_state_json(path)

            with patch("terminx.agents.kimi._read_state_json", new=counted):
                rows = KimiAdapter().find_sessions(
                    {
                        "paths": {"kimi": str(root)},
                        "show_recent_hours": 1,
                        "max_rows_per_agent": 6,
                    }
                )

            self.assertEqual([row.cwd for row in rows], ["C:/recent"])
            self.assertEqual(calls, [recent])


if __name__ == "__main__":
    unittest.main()
