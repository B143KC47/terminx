"""Regression tests for adapter parsing bugs."""

import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from terminx.agents.claude import ClaudeAdapter
from terminx.agents.opencode import OpenCodeAdapter
from terminx.core.usage import utcnow


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


class ClaudeWaitingTest(unittest.TestCase):
    """waiting reflects the LAST event: an assistant reply clears it."""

    def test_waiting_cleared_by_later_assistant_reply(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "s.jsonl"
            _write_jsonl(
                f,
                [
                    {"type": "user", "cwd": "C:/proj"},
                    {"type": "assistant", "message": {"model": "claude-x"}},
                ],
            )
            meta = ClaudeAdapter._read_session_tail(f)
            self.assertFalse(meta["waiting"])

    def test_waiting_when_last_event_is_user(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "s.jsonl"
            _write_jsonl(
                f,
                [
                    {"type": "assistant", "message": {"model": "claude-x"}},
                    {"type": "user", "cwd": "C:/proj"},
                ],
            )
            meta = ClaudeAdapter._read_session_tail(f)
            self.assertTrue(meta["waiting"])


class OpenCodeSortTest(unittest.TestCase):
    """find_sessions must not crash when a session has no parseable timestamp
    (naive datetime.min vs aware datetimes used to raise TypeError)."""

    def test_mixed_naive_and_aware_timestamps(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "log" / "opencode.log"
            log.parent.mkdir(parents=True)
            recent = (utcnow() - timedelta(minutes=1)).isoformat()
            lines = [
                # session with an aware timestamp
                f'timestamp={recent} message=created id=ses_aaa directory="C:/proj/a"',
                # session without any timestamp -> last_seen stays None
                'message=created id=ses_bbb directory="C:/proj/b"',
            ]
            log.write_text("\n".join(lines) + "\n", encoding="utf-8")
            cfg = {
                "paths": {"opencode": td},
                "show_recent_hours": 24,
                "max_rows_per_agent": 6,
            }
            rows = OpenCodeAdapter().find_sessions(cfg)
            self.assertEqual(len(rows), 2)


class NormalizePathTest(unittest.TestCase):
    """pid↔cwd matching must treat C:/foo (session files) and C:\\foo (psutil) as equal."""

    def test_separators_and_case(self):
        from terminx.core.processes import normalize_path

        self.assertEqual(
            normalize_path("C:/Users/ko202/Desktop/project"),
            normalize_path("c:\\Users\\ko202\\Desktop\\project"),
        )

    def test_trailing_separator(self):
        from terminx.core.processes import normalize_path

        self.assertEqual(normalize_path("C:/foo/"), normalize_path("C:\\foo"))


if __name__ == "__main__":
    unittest.main()
