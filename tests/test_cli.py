import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ConsoleOutputTests(unittest.TestCase):
    def test_chinese_frame_survives_redirected_legacy_encoding(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            config = work / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "lang": "zh_CN",
                        "kimi_start_server": False,
                        "paths": {
                            agent: str(work / agent)
                            for agent in ("codex", "claude", "kimi", "grok", "opencode")
                        },
                    }
                ),
                encoding="utf-8",
            )
            environment = dict(
                os.environ,
                TERMINX_CONFIG=str(config),
                TERMINX_STATE_DIR=str(work / "state"),
                PYTHONIOENCODING="cp1252:strict",
                PYTHONUTF8="0",
            )
            result = subprocess.run(
                [sys.executable, "-m", "terminx", "--once"],
                cwd=Path(__file__).resolve().parents[1],
                env=environment,
                capture_output=True,
                timeout=45,
            )
            self.assertEqual(
                result.returncode, 0, result.stderr.decode(errors="replace")
            )
            output = result.stdout.decode("utf-8")
            self.assertIn("termiX", output)
            self.assertRegex(output, r"[\u4e00-\u9fff]")
