import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from terminx.core.runtime import (
    external_dll_paths,
    external_environment,
    module_command,
)


class RuntimeTests(unittest.TestCase):
    def test_frozen_external_dll_scope_restores_original_on_failure(self):
        kernel = MagicMock()

        def capture(capacity, target):
            if capacity:
                target.value = "bundle"
            return 6

        kernel.GetDllDirectoryW.side_effect = capture
        with (
            patch("sys.frozen", True, create=True),
            patch("terminx.core.runtime.os", SimpleNamespace(name="nt")),
            patch("ctypes.windll", SimpleNamespace(kernel32=kernel), create=True),
        ):
            with self.assertRaises(RuntimeError):
                with external_dll_paths():
                    self.assertEqual(kernel.SetDllDirectoryW.call_args.args, (None,))
                    raise RuntimeError("external process failed")
        self.assertEqual(kernel.SetDllDirectoryW.call_args.args, ("bundle",))

    def test_source_helpers_use_python_module(self):
        with patch("terminx.core.paths.sys.executable", "C:/Python/pythonw.exe"):
            self.assertEqual(
                module_command("terminx.launch", "a", "b"),
                [str(Path("C:/Python/python.exe")), "-m", "terminx.launch", "a", "b"],
            )

    def test_frozen_helpers_use_console_sibling(self):
        with (
            patch("sys.frozen", True, create=True),
            patch(
                "terminx.core.paths.sys.executable", "C:/Package/terminx-sidebar.exe"
            ),
        ):
            self.assertEqual(
                module_command("terminx.bridge", "claude"),
                [
                    str(Path("C:/Package/terminx.exe")),
                    "--internal",
                    "terminx.bridge",
                    "claude",
                ],
            )

    def test_arbitrary_module_cannot_be_requested(self):
        with self.assertRaises(ValueError):
            module_command("untrusted.module")

    def test_external_cli_retains_provider_home_and_loses_bundle_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = str(Path(directory) / "_internal")
            user = str(Path(directory) / "user")
            env = {
                "PATH": os.pathsep.join([bundle, str(Path(bundle) / "PySide6"), user]),
                "CODEX_HOME": "custom-home",
                "QT_PLUGIN_PATH": str(Path(bundle) / "plugins"),
                "_PYI_ARCHIVE_FILE": "old",
                "OTHER": "keep",
            }
            with (
                patch("sys.frozen", True, create=True),
                patch("sys._MEIPASS", bundle, create=True),
            ):
                cleaned = external_environment(env)
            self.assertEqual(cleaned["PATH"], user)
            self.assertEqual(cleaned["CODEX_HOME"], "custom-home")
            self.assertNotIn("QT_PLUGIN_PATH", cleaned)
            self.assertNotIn("_PYI_ARCHIVE_FILE", cleaned)
            self.assertEqual(env["_PYI_ARCHIVE_FILE"], "old")
