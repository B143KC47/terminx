import json
from pathlib import Path

HOME = Path.home()

DEFAULTS = {
    "refresh_sec": 3,
    "working_threshold_sec": 60,
    "blocked_threshold_sec": 600,
    "show_recent_hours": 24,
    "max_rows_per_agent": 6,
    "paths": {},
    "kimi_api_key": "",
    "codex_usage_url": "https://chatgpt.com/backend-api",
    "kimi_usage_url": "https://api.kimi.com/coding/v1",
}

CONFIG_PATHS = [
    HOME / ".config" / "terminx" / "config.json",
    HOME / ".terminx.json",
]


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    for p in CONFIG_PATHS:
        if p.exists():
            try:
                user = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(user, dict):
                    cfg.update(user)
            except Exception:
                pass
            break
    return cfg
