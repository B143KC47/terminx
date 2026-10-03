import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from terminx.core.cleanup import cleanup
from terminx.core.integrations import install


class CleanupTests(unittest.TestCase):
    def test_uninstall_cleanup_preserves_other_hooks_and_notes(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "provider"
            state = Path(directory) / "state"
            home.mkdir()
            settings = home / "settings.json"
            original = {
                "hooks": {
                    "Stop": [{"hooks": [{"type": "command", "command": "existing"}]}]
                }
            }
            settings.write_text(json.dumps(original), encoding="utf-8")
            install("claude", state, home)
            notes = state / "sidebar.json"
            notes.write_text('{"notes":{"keep":"user note"}}', encoding="utf-8")
            with (
                patch(
                    "terminx.core.cleanup.load_config",
                    return_value={"state_dir": str(state)},
                ),
                patch("terminx.core.cleanup.startup_enabled", return_value=False),
            ):
                cleanup()
                cleanup()
            self.assertEqual(json.loads(settings.read_text(encoding="utf-8")), original)
            self.assertEqual(
                json.loads(notes.read_text(encoding="utf-8"))["notes"]["keep"],
                "user note",
            )
