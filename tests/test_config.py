import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from terminx.config import DEFAULTS, load_config


class ConfigurationTests(unittest.TestCase):
    def load(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(data, encoding="utf-8")
            with (
                patch("terminx.config.CONFIG_PATHS", [path]),
                patch.dict("os.environ", {}, clear=True),
            ):
                value = load_config()
            self.assertEqual(path.read_text(encoding="utf-8"), data)
            return value

    def test_invalid_shape_and_types_keep_valid_defaults(self):
        for paths in (None, [], "broken", 42):
            cfg = self.load(
                json.dumps(
                    {
                        "paths": paths,
                        "refresh_sec": "fast",
                        "kimi_start_server": "false",
                        "lang": [],
                    }
                )
            )
            self.assertEqual(cfg, DEFAULTS)

    def test_invalid_numeric_values_do_not_crash_workers(self):
        for value in (True, -1, 0, float("nan"), float("inf"), "3"):
            self.assertEqual(
                self.load(json.dumps({"refresh_sec": value}))["refresh_sec"],
                DEFAULTS["refresh_sec"],
            )
        self.assertEqual(
            self.load('{"max_rows_per_agent": 2.5}')["max_rows_per_agent"],
            DEFAULTS["max_rows_per_agent"],
        )

    def test_valid_values_and_environment_override_remain(self):
        cfg = self.load(
            '{"refresh_sec": 2, "lang": "en", "paths": {"codex": "C:/custom", "kimi": null}}'
        )
        self.assertEqual(cfg["refresh_sec"], 2)
        self.assertEqual(cfg["paths"], {"codex": "C:/custom"})
        with (
            patch("terminx.config.CONFIG_PATHS", []),
            patch.dict("os.environ", {"CODEX_HOME": "C:/env-home"}, clear=True),
        ):
            self.assertEqual(
                Path(load_config()["paths"]["codex"]), Path("C:/env-home/sessions")
            )

    def test_malformed_file_is_preserved(self):
        self.assertEqual(self.load("not JSON"), DEFAULTS)
        self.assertEqual(self.load("[]"), DEFAULTS)

    def test_each_load_has_independent_defaults(self):
        first = self.load("{}")
        first["paths"]["codex"] = "changed"
        self.assertEqual(self.load("{}")["paths"], {})
