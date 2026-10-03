import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from terminx.core.startup import (
    RUN_KEY,
    VALUE_NAME,
    set_startup,
    startup_command,
    startup_enabled,
)


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="termix start ")
        self.executable = Path(self.temp.name) / "python.exe"
        self.executable.touch()
        self.executable.with_name("pythonw.exe").touch()
        self.executable.with_name("terminx-sidebar.exe").touch()
        self.registry = MagicMock()
        self.modules = patch.dict("sys.modules", winreg=self.registry)
        self.modules.start()
        self.python = patch("terminx.core.startup.sys.executable", str(self.executable))
        self.python.start()
        self.windows = patch("terminx.core.startup.os", SimpleNamespace(name="nt"))
        self.windows.start()

    def tearDown(self):
        self.windows.stop()
        self.python.stop()
        self.modules.stop()
        self.temp.cleanup()

    def test_source_command_uses_windowed_python_and_quotes_spaces(self):
        command = startup_command()
        self.assertTrue(command.startswith('"'))
        self.assertIn('pythonw.exe" -m terminx.ui.sidebar --startup', command)

    def test_frozen_command_uses_bundled_sidebar(self):
        with patch("sys.frozen", True, create=True):
            self.assertTrue(
                startup_command().endswith('terminx-sidebar.exe" --startup')
            )

    def test_enable_and_disable_change_only_our_user_value(self):
        set_startup(True)
        self.registry.CreateKeyEx.assert_called_once_with(
            self.registry.HKEY_CURRENT_USER, RUN_KEY, 0, self.registry.KEY_SET_VALUE
        )
        self.assertEqual(self.registry.SetValueEx.call_args.args[1], VALUE_NAME)
        self.assertEqual(self.registry.SetValueEx.call_args.args[4], startup_command())
        set_startup(False)
        self.assertEqual(self.registry.DeleteValue.call_args.args[1], VALUE_NAME)

    def test_status_comes_from_exact_registry_command(self):
        self.registry.QueryValueEx.return_value = (
            startup_command(),
            self.registry.REG_SZ,
        )
        self.assertTrue(startup_enabled())
        self.registry.QueryValueEx.return_value = (
            '"C:/Other/terminx-sidebar.exe" --startup',
            self.registry.REG_SZ,
        )
        self.assertFalse(startup_enabled())

    def test_absent_value_is_disabled_and_removal_is_idempotent(self):
        self.registry.OpenKey.side_effect = FileNotFoundError
        self.assertFalse(startup_enabled())
        set_startup(False)

    def test_permission_error_is_not_reported_as_success(self):
        self.registry.CreateKeyEx.side_effect = PermissionError("denied")
        with self.assertRaises(PermissionError):
            set_startup(True)

    def test_long_command_and_missing_executable_do_not_write_registry(self):
        with patch(
            "terminx.core.startup.subprocess.list2cmdline", return_value="x" * 261
        ):
            with self.assertRaises(ValueError):
                set_startup(True)
        self.executable.with_name("pythonw.exe").unlink()
        with self.assertRaises(OSError):
            set_startup(True)
        self.registry.SetValueEx.assert_not_called()

    def test_other_platform_does_not_write_registry(self):
        with patch("terminx.core.startup.os", SimpleNamespace(name="posix")):
            self.assertFalse(startup_enabled())
            with self.assertRaises(OSError):
                set_startup(True)
