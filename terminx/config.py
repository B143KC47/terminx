import json
import math
import os
from copy import deepcopy
from pathlib import Path

HOME = Path.home()

DEFAULTS = {
    "lang": "auto",
    "refresh_sec": 3,
    "quota_refresh_sec": 120,
    "show_recent_hours": 24,
    "max_rows_per_agent": 100,
    "kimi_start_server": True,
    "kimi_server_port": 58627,
    "paths": {},
}

CONFIG_PATHS = [
    HOME / ".config" / "terminx" / "config.json",
    HOME / ".terminx.json",
]

NUMERIC_LIMITS = {
    "refresh_sec": (1, 3600),
    "quota_refresh_sec": (1, 86400),
    "show_recent_hours": (1, 8760),
    "max_rows_per_agent": (1, 10000),
    "kimi_server_port": (1, 65535),
}


def valid_settings(user: dict) -> dict:
    """Keep valid settings without changing the user's file."""
    result = dict(user)
    for name, (low, high) in NUMERIC_LIMITS.items():
        value = result.get(name)
        if name in result and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not low <= value <= high
            or (
                name in {"max_rows_per_agent", "kimi_server_port"}
                and not isinstance(value, int)
            )
        ):
            result.pop(name)
    if "paths" in result:
        paths = result["paths"]
        result["paths"] = (
            {
                name: value
                for name, value in paths.items()
                if isinstance(value, str) and value
            }
            if isinstance(paths, dict)
            else {}
        )
    if "lang" in result and result["lang"] not in ("auto", "en", "zh_CN"):
        result.pop("lang")
    if "kimi_start_server" in result and not isinstance(
        result["kimi_start_server"], bool
    ):
        result.pop("kimi_start_server")
    if "state_dir" in result and not isinstance(result["state_dir"], str):
        result.pop("state_dir")
    if "colors" in result and not isinstance(result["colors"], dict):
        result.pop("colors")
    return result


def load_config() -> dict:
    cfg = deepcopy(DEFAULTS)
    selected = (
        [Path(os.environ["TERMINX_CONFIG"])]
        if os.environ.get("TERMINX_CONFIG")
        else CONFIG_PATHS
    )
    for p in selected:
        if p.exists():
            try:
                user = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(user, dict):
                    cfg.update(valid_settings(user))
            except (OSError, UnicodeError, ValueError):
                pass
            break
    for agent, var in [
        ("codex", "CODEX_HOME"),
        ("claude", "CLAUDE_CONFIG_DIR"),
        ("kimi", "KIMI_CODE_HOME"),
        ("grok", "GROK_HOME"),
    ]:
        if os.environ.get(var) and agent not in cfg["paths"]:
            cfg["paths"][agent] = (
                str(Path(os.environ[var]) / "sessions")
                if agent == "codex"
                else os.environ[var]
            )
    return cfg
