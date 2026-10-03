"""Run internal helpers from source or from the Windows package."""

import os
import subprocess
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

from .paths import console_python

HELPERS = {
    "terminx.bridge",
    "terminx.launch",
    "terminx.core.console_identity",
    "terminx.core.runtime",
}
_DLL_LOCK = threading.RLock()


def module_command(module: str, *args: str) -> list[str]:
    if module not in HELPERS:
        raise ValueError(f"Unknown internal helper: {module}")
    if getattr(sys, "frozen", False):
        return [console_python(), "--internal", module, *map(str, args)]
    return [console_python(), "-m", module, *map(str, args)]


def external_environment(env=None) -> dict[str, str]:
    """Remove package loader paths before an external CLI starts."""
    cleaned = dict(os.environ if env is None else env)
    if not getattr(sys, "frozen", False):
        return cleaned
    bundle = Path(sys._MEIPASS).resolve()

    def from_bundle(value):
        try:
            return Path(value).resolve().is_relative_to(bundle)
        except (OSError, ValueError):
            return False

    cleaned["PATH"] = os.pathsep.join(
        p for p in cleaned.get("PATH", "").split(os.pathsep) if not from_bundle(p)
    )
    for name in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH"):
        if name in cleaned and from_bundle(cleaned[name]):
            cleaned.pop(name)
    for name in list(cleaned):
        if name.startswith("_PYI_"):
            cleaned.pop(name)
    return cleaned


@contextmanager
def external_dll_paths():
    """Keep Qt DLLs out of a child CLI's Windows loader search path."""
    if os.name != "nt" or not getattr(sys, "frozen", False):
        yield
        return
    import ctypes

    with _DLL_LOCK:
        kernel = ctypes.windll.kernel32
        kernel.SetDllDirectoryW.argtypes = [ctypes.c_wchar_p]
        size = kernel.GetDllDirectoryW(0, None)
        original = ctypes.create_unicode_buffer(size + 1)
        kernel.GetDllDirectoryW(len(original), original)
        if not kernel.SetDllDirectoryW(None):
            raise ctypes.WinError()
        try:
            yield
        finally:
            kernel.SetDllDirectoryW(original.value or None)


def external_popen(command, **kwargs):
    kwargs["env"] = external_environment(kwargs.get("env"))
    with external_dll_paths():
        return subprocess.Popen(command, **kwargs)


def external_run(command, **kwargs):
    kwargs["env"] = external_environment(kwargs.get("env"))
    with external_dll_paths():
        return subprocess.run(command, **kwargs)


def main():
    """Print the console handle for one process."""
    if os.name != "nt":
        print(0)
        return
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.windll.kernel32
    kernel.GetConsoleWindow.restype = wintypes.HWND
    kernel.FreeConsole()
    attached = kernel.AttachConsole(int(sys.argv[1]))
    try:
        print(int(kernel.GetConsoleWindow() or 0) if attached else 0)
    finally:
        kernel.FreeConsole()


if __name__ == "__main__":
    main()
