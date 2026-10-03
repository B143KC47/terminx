"""Remove termiX hooks before the Windows package is removed."""

import sys

from ..config import load_config
from .events import state_dir
from .integrations import uninstall
from .startup import set_startup, startup_enabled


def cleanup() -> None:
    """Keep user notes and unrelated CLI settings."""
    from .integrations import integration_state

    directory = state_dir(load_config())
    for agent in ("claude", "kimi", "grok", "codex"):
        if (
            integration_state(agent, directory).startswith("Installed")
            or (directory / "integrations" / f"{agent}.json").exists()
        ):
            uninstall(agent, directory)
    if sys.platform == "win32" and startup_enabled():
        set_startup(False)
