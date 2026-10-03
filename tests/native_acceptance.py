"""Opt-in acceptance on the real Windows desktop; creates only dedicated test terminals."""

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from terminx.core.terminals import TerminalLocator  # noqa: E402


def main():
    if os.name != "nt":
        raise SystemExit("Windows required")
    root = Path(__file__).resolve().parents[1]
    artifacts = root / "_artifacts"
    artifacts.mkdir(exist_ok=True)
    run = uuid.uuid4().hex
    files = []

    def create(window, tag, split=False):
        file = artifacts / (uuid.uuid4().hex + ".json")
        files.append(file)
        args = [
            "wt",
            "-w",
            window,
            "split-pane" if split else "new-tab",
            "--title",
            "terminX acceptance [tx:" + tag + "]",
            "--suppressApplicationTitle",
            sys.executable,
            str(root / "tests" / "native_probe.py"),
            str(file),
            "45",
        ]
        subprocess.run(args, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline and not file.exists():
            time.sleep(0.1)
        if not file.exists():
            raise RuntimeError("Test terminal did not start")
        time.sleep(0.3)

    results = {}
    locator = TerminalLocator()
    try:
        a, b, c = uuid.uuid4().hex, uuid.uuid4().hex, uuid.uuid4().hex
        create("tx-test-" + run, a)
        results["single_window"] = locator._focus_tag(a).status
        create("tx-test-" + run, b)
        results["inactive_tab"] = locator._focus_tag(a).status
        results["second_tab"] = locator._focus_tag(b).status
        create("tx-other-" + run, c)
        results["multiple_windows"] = locator._focus_tag(a).status
        results["other_window"] = locator._focus_tag(c).status
        from terminx.core.win32 import _enum_windows, _window_title, user32

        for hwnd in _enum_windows():
            if "[tx:" + c + "]" in _window_title(hwnd):
                user32.ShowWindow(hwnd, 6)
        results["minimized_window"] = locator._focus_tag(c).status
        results["missing_tag"] = locator._focus_tag(uuid.uuid4().hex).status
        create("tx-other-" + run, c, split=True)
        results["duplicate_pane"] = locator._focus_tag(c).status
        create("tx-other-" + run, a)
        results["duplicate_tag"] = locator._focus_tag(a).status
    finally:
        for file in files:
            Path(str(file) + ".stop").touch()
    (artifacts / "native-acceptance.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    print(json.dumps(results))
    if any(
        results.get(k) != "focused"
        for k in [
            "single_window",
            "inactive_tab",
            "second_tab",
            "multiple_windows",
            "other_window",
            "minimized_window",
        ]
    ):
        raise SystemExit(1)
    if results["duplicate_tag"] != "ambiguous" or results["missing_tag"] != "ambiguous":
        raise SystemExit(1)
    if results["duplicate_pane"] not in {"unsupported", "ambiguous"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
