"""A temporary console title proves tab/pane identity; the original title is restored."""

import json
import os
import queue
import subprocess
import sys
import threading
import uuid
from contextlib import contextmanager

from .runtime import module_command


@contextmanager
def title_challenge(binding):
    marker = "[tx-live:" + uuid.uuid4().hex + "]"
    process = subprocess.Popen(
        module_command(
            "terminx.core.console_identity",
            str(binding.pid),
            str(binding.created_at),
            str(binding.console_hwnd),
            marker,
        ),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    lines = queue.Queue()
    threading.Thread(
        target=lambda: lines.put(process.stdout.readline()), daemon=True
    ).start()
    try:
        try:
            receipt = json.loads(lines.get(timeout=2))
        except (queue.Empty, ValueError):
            receipt = {}
        yield marker if receipt.get("status") == "ready" else ""
    finally:
        try:
            process.stdin.write("\n")
            process.stdin.flush()
        except OSError:
            pass
        try:
            process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=2)
        process.stdout.close()


def main():
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    import psutil

    pid, created, expected, marker = (
        int(sys.argv[1]),
        float(sys.argv[2]),
        int(sys.argv[3]),
        sys.argv[4],
    )
    kernel = ctypes.windll.kernel32
    kernel.GetConsoleWindow.restype = wintypes.HWND
    kernel.GetConsoleTitleW.argtypes = [wintypes.LPWSTR, wintypes.DWORD]
    kernel.SetConsoleTitleW.argtypes = [wintypes.LPCWSTR]
    kernel.FreeConsole()
    original = None

    def title():
        value = ctypes.create_unicode_buffer(65536)
        kernel.GetConsoleTitleW(value, len(value))
        return value.value

    try:
        if abs(
            psutil.Process(pid).create_time() - created
        ) >= 0.01 or not kernel.AttachConsole(pid):
            return
        if kernel.GetConsoleWindow() != expected:
            return
        original = title()
        if not kernel.SetConsoleTitleW(marker):
            return
        print(json.dumps({"status": "ready"}), flush=True)
        restore = threading.Event()

        def receive():
            sys.stdin.readline()
            restore.set()

        threading.Thread(target=receive, daemon=True).start()
        restore.wait(8)
    except (OSError, psutil.Error):
        pass
    finally:
        # Preserve any newer title the CLI set while we were locating its pane.
        if original is not None and title() == marker:
            kernel.SetConsoleTitleW(original)
        kernel.FreeConsole()


if __name__ == "__main__":
    main()
