import unittest
from datetime import datetime, timedelta, timezone

from terminx.agents.base import SessionInfo
from terminx.ui.dashboard import Dashboard


class DashboardAdapter:
    name = "fake"

    def __init__(self, rows):
        self.rows = rows
        self.quota_calls = 0

    def sessions(self, cfg):
        return list(self.rows)

    def quota(self, cfg):
        self.quota_calls += 1
        return None


def _row(source, status="working", seconds_ago=0):
    return SessionInfo(
        agent="fake",
        cwd=f"C:/work/{source}",
        source=source,
        status=status,
        last_activity=datetime.now(timezone.utc) - timedelta(seconds=seconds_ago),
    )


class DashboardScanTest(unittest.TestCase):
    def test_terminal_scan_does_not_wait_for_quota(self):
        adapter = DashboardAdapter([_row("a")])
        dash = Dashboard([adapter], {"refresh_sec": 3})

        dash.scan_sessions()

        self.assertEqual([row.source for row in dash._rows], ["a"])
        self.assertEqual(adapter.quota_calls, 0)

    def test_selected_session_survives_activity_reordering(self):
        first = _row("first", seconds_ago=10)
        selected = _row("selected", seconds_ago=20)
        adapter = DashboardAdapter([first, selected])
        dash = Dashboard([adapter], {"refresh_sec": 3})
        dash.scan_sessions()
        dash.cursor = 1

        selected.last_activity = datetime.now(timezone.utc)
        adapter.rows = [selected, first]
        dash.scan_sessions()

        self.assertEqual(dash._rows[dash.cursor].source, "selected")

    def test_blocked_key_jumps_to_next_blocked_session(self):
        dash = Dashboard([], {"refresh_sec": 3})
        dash._rows = [
            _row("working"),
            _row("blocked-1", status="blocked"),
            _row("idle", status="idle"),
            _row("blocked-2", status="blocked"),
        ]
        dash.cursor = 0
        dash._keys.put("blocked")

        dash._handle_keys()

        self.assertEqual(dash.cursor, 1)


if __name__ == "__main__":
    unittest.main()
