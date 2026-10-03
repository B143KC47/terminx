import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from terminx.core.integrations import (
    hook_command,
    install,
    integration_state,
    uninstall,
)


class IntegrationTests(unittest.TestCase):
    def test_desktop_hook_uses_console_interpreter_and_explicit_home(self):
        with patch("terminx.core.paths.sys.executable", "C:/Python/pythonw.exe"):
            command = hook_command(
                "claude", directory="C:/state dir", home="C:/custom-home"
            )
        self.assertNotIn("pythonw.exe", command)
        self.assertIn("python.exe", command)
        self.assertIn("--data-home", command)
        self.assertIn("C:/custom-home", command)

    def test_json_install_idempotent_and_uninstall_preserves_other_hooks_and_edits(
        self,
    ):
        for agent, filename in [
            ("claude", "settings.json"),
            ("grok", "hooks/terminx.json"),
        ]:
            with self.subTest(agent=agent), tempfile.TemporaryDirectory() as td:
                home = Path(td) / "home"
                state = Path(td) / "state"
                file = home / filename
                file.parent.mkdir(parents=True)
                original = {
                    "hooks": {
                        "Stop": [
                            {"hooks": [{"type": "command", "command": "original"}]}
                        ]
                    },
                    "other": True,
                }
                if agent == "claude":
                    original["statusLine"] = {
                        "type": "command",
                        "command": "existing --status",
                        "padding": 2,
                    }
                file.write_text(json.dumps(original))
                install(agent, state, home)
                first = file.read_text()
                install(agent, state, home)
                self.assertEqual(file.read_text(), first)
                edited = json.loads(first)
                edited["later_edit"] = 42
                file.write_text(json.dumps(edited))
                uninstall(agent, state)
                result = json.loads(file.read_text())
                self.assertEqual(result, {**original, "later_edit": 42})

    def test_codex_hook_install_is_disabled_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            state = Path(td) / "state"
            with self.assertRaises(ValueError):
                install("codex", state, home)
            self.assertEqual(list(Path(td).iterdir()), [])
            self.assertEqual(
                integration_state("codex", state),
                "Native process and session logs · no hooks",
            )

    def test_legacy_codex_hooks_can_still_be_removed_surgically(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            state = Path(td) / "state"
            home.mkdir()
            entry = {
                "hooks": [
                    {
                        "type": "command",
                        "command": "python -m terminx.bridge codex",
                        "timeout": 1,
                    }
                ]
            }
            original = {"hooks": [{"type": "command", "command": "existing-user-hook"}]}
            config = home / "hooks.json"
            config.write_text(
                json.dumps(
                    {"hooks": {"PreToolUse": [original, entry]}, "user_setting": True}
                )
            )
            folder = state / "integrations"
            folder.mkdir(parents=True)
            manifest = folder / "codex.json"
            manifest.write_text(
                json.dumps({"path": str(config), "added": [["PreToolUse", entry]]})
            )
            uninstall("codex", state)
            self.assertEqual(
                json.loads(config.read_text()),
                {"hooks": {"PreToolUse": [original]}, "user_setting": True},
            )
            self.assertFalse(manifest.exists())

    def test_user_changed_statusline_is_not_overwritten_on_uninstall(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            state = Path(td) / "state"
            install("claude", state, home)
            file = home / "settings.json"
            config = json.loads(file.read_text())
            config["statusLine"] = {"type": "command", "command": "changed-later"}
            file.write_text(json.dumps(config))
            uninstall("claude", state)
            self.assertEqual(
                json.loads(file.read_text())["statusLine"]["command"], "changed-later"
            )

    def test_kimi_toml_comments_and_existing_hooks_survive(self):
        try:
            import tomlkit
        except ImportError:
            self.skipTest("desktop extra")
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            home.mkdir()
            file = home / "config.toml"
            state = Path(td) / "state"
            original = '# user comment\nmodel="custom"\n[[hooks]]\nevent="Stop"\ncommand="existing"\n'
            file.write_text(original)
            install("kimi", state, home)
            uninstall("kimi", state)
            self.assertIn("# user comment", file.read_text())
            self.assertEqual(
                tomlkit.parse(file.read_text()).unwrap(),
                tomlkit.parse(original).unwrap(),
            )

    def test_malformed_config_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            home.mkdir()
            p = home / "settings.json"
            p.write_text("{bad")
            with self.assertRaises(ValueError):
                install("claude", Path(td) / "state", home)
            self.assertEqual(p.read_text(), "{bad")


if __name__ == "__main__":
    unittest.main()
