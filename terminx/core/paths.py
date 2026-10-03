"""CLI data homes and the console interpreter used by native integrations."""

import os
import sys
from pathlib import Path

HOME_ENV = {
    "codex": "CODEX_HOME",
    "claude": "CLAUDE_CONFIG_DIR",
    "kimi": "KIMI_CODE_HOME",
    "grok": "GROK_HOME",
}
HOME_NAME = {
    "codex": ".codex",
    "claude": ".claude",
    "kimi": ".kimi-code",
    "grok": ".grok",
}


def provider_home(agent):
    if agent == "opencode":
        return (
            Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
            / "opencode"
        )
    return Path(os.environ.get(HOME_ENV[agent]) or Path.home() / HOME_NAME[agent])


def configured_home(agent, cfg=None):
    path = Path(
        (cfg or {}).get("paths", {}).get(agent) or provider_home(agent)
    ).expanduser()
    # Preserve the original Codex override, which points at its sessions directory.
    if agent == "codex" and path.name.casefold() == "sessions":
        path = path.parent
    return path.resolve()


def console_python():
    path = Path(sys.executable)
    if getattr(sys, "frozen", False):
        return str(path.with_name("terminx.exe"))
    if path.name.lower() == "pythonw.exe":
        return str(path.with_name("python.exe"))
    return str(path)
