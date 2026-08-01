"""i18n sanity tests: catalog completeness, fallback, formatting, detection."""

import json
import os
import re
import unittest
from pathlib import Path

import terminx.i18n as i18n

ROOT = Path(__file__).resolve().parents[1]


def _t_keys() -> set[str]:
    text = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "terminx").rglob("*.py"))
    return set(re.findall(r'(?<![A-Za-z0-9_])t\(["\']([^"\']+)["\']', text))


def _catalog(name: str) -> dict:
    return json.loads((ROOT / "terminx" / "locales" / f"{name}.json").read_text(encoding="utf-8"))


class CatalogTest(unittest.TestCase):
    def test_catalog_has_every_literal_key(self):
        missing = _t_keys() - set(_catalog("zh_CN"))
        self.assertEqual(missing, set())

    def test_catalog_keys_are_reachable(self):
        dyn = {
            "working", "blocked", "idle", "running", "offline",
            "weekly", "5h", "7d", "7d sonnet", "7d opus", "limit",
            "[green]{working} working[/] · [yellow]{blocked} blocked[/] · [cyan]{running} running[/]",
            "scan: {time}", "refresh {sec}s",
            "✎ note for [bold]{agent}[/] ({cwd}): ",
            "agent:", "status:", "model:", "provider:", "directory:",
            "branch:", "pid:", "plan:", "session:", "note:",
        }
        for key in dyn:
            self.assertIn(key, _catalog("zh_CN"))

    def test_no_dead_keys(self):
        dead = set(_catalog("zh_CN")) - _t_keys() - {
            "working", "blocked", "idle", "running", "offline",
            "weekly", "5h", "7d", "7d sonnet", "7d opus", "limit",
            "[green]{working} working[/] · [yellow]{blocked} blocked[/] · [cyan]{running} running[/]",
            "scan: {time}", "refresh {sec}s",
            "✎ note for [bold]{agent}[/] ({cwd}): ",
            "agent:", "status:", "model:", "provider:", "directory:",
            "branch:", "pid:", "plan:", "session:", "note:",
        }
        self.assertEqual(dead, set())


class TranslatorTest(unittest.TestCase):
    def test_english_fallback(self):
        i18n.set_language("en")
        self.assertEqual(i18n.t("working"), "working")
        self.assertEqual(i18n.t("unknown string"), "unknown string")

    def test_zh_translation(self):
        i18n.set_language("zh_CN")
        self.assertEqual(i18n.t("working"), "工作中")
        self.assertEqual(i18n.t("no agents running"), "没有代理在运行")

    def test_placeholder_formatting(self):
        i18n.set_language("zh_CN")
        self.assertEqual(i18n.t("resets in {days}d {hours}h", days=1, hours=2), "重置剩余 1 天 2 小时")

    def test_unknown_language_falls_back(self):
        i18n.set_language("xx_YY")
        self.assertEqual(i18n.t("working"), "工作中" if i18n._lang == "zh_CN" else "working")


class DetectionTest(unittest.TestCase):
    def test_env_zh(self):
        old = {k: os.environ.get(k) for k in ("LANG", "LC_ALL", "LC_MESSAGES")}
        try:
            for k in old:
                os.environ.pop(k, None)
            os.environ["LANG"] = "zh_CN.UTF-8"
            self.assertEqual(i18n.detect_language(), "zh_CN")
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_env_en(self):
        old = {k: os.environ.get(k) for k in ("LANG", "LC_ALL", "LC_MESSAGES")}
        try:
            for k in old:
                os.environ.pop(k, None)
            os.environ["LANG"] = "en_US.UTF-8"
            self.assertEqual(i18n.detect_language(), "en")
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
