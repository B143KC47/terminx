"""Runs inside a user-requested terminal; does not emulate or pipe the CLI TUI."""

import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

from .core.events import EventJournal, SessionEvent
from .core.integrations import atomic_write
from .core.paths import HOME_ENV, provider_home
from .core.runtime import external_popen


def main():
    identifier, directory = sys.argv[1:3]
    if not re.fullmatch(r"[a-f0-9]{32}", identifier):
        raise ValueError("Invalid launch identifier")
    path = Path(directory) / "launches" / f"{identifier}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    env = dict(os.environ, TERMINX_LAUNCH_ID=identifier, TERMINX_STATE_DIR=directory)
    root = record.get("data_root") or str(provider_home(record["agent"]))
    if record["agent"] in HOME_ENV:
        env[HOME_ENV[record["agent"]]] = root
    elif record["agent"] == "opencode":
        env["XDG_DATA_HOME"] = str(Path(root).parent)
    command = record["command"]
    command[0] = shutil.which(command[0]) or command[0]
    proc = external_popen(command, cwd=record["cwd"], env=env)
    import psutil

    record.update(pid=proc.pid, created_at=psutil.Process(proc.pid).create_time())
    atomic_write(path, json.dumps(record))
    # Hooks map new native IDs; for resumes the native ID is already known.
    if record.get("session_id"):
        EventJournal(directory).append(
            SessionEvent(
                record["agent"],
                record["session_id"],
                root,
                "session_started",
                time.time(),
                "launcher",
                data={
                    "cwd": record["cwd"],
                    "pid": record["pid"],
                    "created_at": record["created_at"],
                    "launch_id": identifier,
                    "wt_session": os.environ.get("WT_SESSION", ""),
                },
            )
        )
    try:
        return proc.wait()
    except KeyboardInterrupt:
        return proc.wait()


if __name__ == "__main__":
    sys.exit(main())
