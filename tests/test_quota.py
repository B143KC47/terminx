import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from terminx.agents import quota
from terminx.agents.base import Quota, QuotaWindow
from terminx.bridge import account_fingerprint
from terminx.core.events import EventJournal, SessionEvent
from terminx.ui.dashboard import Dashboard, _limit_status


class QuotaTests(unittest.TestCase):
    def setUp(self):
        quota._CACHE.clear()

    def test_percentage_scales_and_actual_window_duration(self):
        data = {
            "rateLimits": {
                "primary": {
                    "usedPercent": 37,
                    "windowDurationMins": 300,
                    "resetsAt": time.time() + 100,
                },
                "secondary": {"usedPercent": 4, "windowDurationMins": 10080},
            }
        }
        q = quota.parse_codex(data)
        self.assertEqual([w.pct for w in q.windows], [37, 4])
        self.assertEqual([w.seconds for w in q.windows], [18000, 604800])
        self.assertTrue(q.windows[0].reset_at)
        self.assertFalse(q.limited)
        k = quota.parse_kimi({"usages": {"limit5h": {"usedRatio": 0.42}}})
        self.assertEqual(k.windows[0].pct, 42)

    def test_missing_is_not_zero_and_ninety_is_not_rate_limited(self):
        self.assertEqual(quota.parse_codex({}).windows, [])
        self.assertIsNone(quota.make_window("unknown", None))
        self.assertNotIn("HIT", _limit_status(95).plain)
        self.assertIn("HIT", _limit_status(95, hit=True).plain)

    def test_tui_renders_official_limit_flag(self):
        from io import StringIO

        from rich.console import Console

        dashboard = Dashboard([], {})
        dashboard.view = "usage"
        dashboard._usage_rows = [
            {
                "agent": "codex",
                "quota": Quota(
                    "codex",
                    limited=True,
                    windows=[QuotaWindow("5h", 18000, used_percent=100)],
                ),
            }
        ]
        output = StringIO()
        Console(file=output, width=140).print(dashboard.render())
        self.assertIn("HIT", output.getvalue())

    def test_network_error_retains_old_value_with_stale_marker(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = {"paths": {"codex": td}, "quota_refresh_sec": 5}
            q = quota.fetch_quota(
                "codex",
                cfg,
                lambda *_: Quota(
                    "codex", windows=[QuotaWindow("5h", 18000, used_percent=23)]
                ),
            )
            first = q.fetched_at
            with patch(
                "terminx.agents.quota.time.monotonic",
                return_value=time.monotonic() + 100,
            ):
                q = quota.fetch_quota(
                    "codex",
                    cfg,
                    lambda *_: (_ for _ in ()).throw(TimeoutError("SECRET")),
                )
            self.assertEqual(q.windows[0].pct, 23)
            self.assertEqual(q.availability, "stale")
            self.assertEqual(q.fetched_at, first)
            self.assertNotIn("SECRET", q.reason)

    def test_account_switch_never_reuses_old_quota(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = {"paths": {"codex": td}}
            p = Path(td) / "auth.json"
            p.write_text("account one")
            quota.fetch_quota(
                "codex",
                cfg,
                lambda *_: Quota(
                    "codex", windows=[QuotaWindow("5h", 1, used_percent=99)]
                ),
            )
            p.write_text("account two")
            q = quota.fetch_quota(
                "codex", cfg, lambda *_: (_ for _ in ()).throw(TimeoutError())
            )
            self.assertFalse(q.windows)
            self.assertEqual(q.availability, "unavailable")

    def test_claude_uses_current_account_statusline_and_timestamp(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "claude"
            root.mkdir()
            (root / ".credentials.json").write_text("account")
            state = Path(td) / "state"
            now = time.time() - 600
            EventJournal(state).append(
                SessionEvent(
                    "claude",
                    "one",
                    str(root),
                    "usage",
                    now,
                    "statusline",
                    data={
                        "account_id": account_fingerprint("claude", root),
                        "rate_limits": {
                            "five_hour": {
                                "used_percentage": 51,
                                "resets_at": time.time() + 100,
                            }
                        },
                    },
                )
            )
            q = quota.fetch_claude_quota(
                {"paths": {"claude": str(root)}, "state_dir": str(state)}
            )
            self.assertEqual(q.windows[0].pct, 51)
            self.assertEqual(q.availability, "stale")
            self.assertEqual(q.fetched_at, datetime.fromtimestamp(now, timezone.utc))


if __name__ == "__main__":
    unittest.main()
