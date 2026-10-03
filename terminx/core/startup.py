"""Set the current user's Windows sign-in command."""

import os
import subprocess
import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "termiX"


def startup_command() -> str:
    """Return a quoted command that opens the sidebar without a console."""
    executable = Path(sys.executable).resolve()
    if getattr(sys, "frozen", False):
        executable = executable.with_name("terminx-sidebar.exe")
        args = [str(executable), "--startup"]
    else:
        if executable.name.casefold() == "python.exe":
            executable = executable.with_name("pythonw.exe")
        args = [str(executable), "-m", "terminx.ui.sidebar", "--startup"]
    if not executable.is_file():
        raise OSError(f"Sidebar executable is missing: {executable}")
    command = '"' + args[0] + '"'
    if len(args) > 1:
        command += " " + subprocess.list2cmdline(args[1:])
    if len(command) > 260:
        raise ValueError(
            "The sign-in command exceeds the Windows limit of 260 characters"
        )
    return command


def startup_enabled() -> bool:
    """Read Windows settings instead of a second saved Boolean."""
    if os.name != "nt":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, kind = winreg.QueryValueEx(key, VALUE_NAME)
        return kind == winreg.REG_SZ and value == startup_command()
    except FileNotFoundError:
        return False


def set_startup(enabled: bool) -> None:
    """Change only the termiX value for the current user."""
    if os.name != "nt":
        raise OSError("Start at sign-in is available on Windows")
    import winreg

    if enabled:
        command = startup_command()
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)
    else:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.DeleteValue(key, VALUE_NAME)
        except FileNotFoundError:
            pass
