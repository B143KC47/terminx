"""Idempotent installation and surgical removal of user-level integrations."""

import json
import os
import uuid
from copy import deepcopy
from pathlib import Path

from .events import state_dir
from .paths import provider_home
from .runtime import module_command

COMMON = [
    "SessionStart",
    "SessionEnd",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "Stop",
]
EVENTS = {
    "claude": COMMON
    + ["PermissionRequest", "Notification", "StopFailure", "PostToolUseFailure"],
    "kimi": COMMON
    + [
        "PermissionRequest",
        "PermissionResult",
        "TurnStarted",
        "SessionHeartbeat",
        "Interrupt",
        "StopFailure",
    ],
    "grok": COMMON
    + ["Notification", "StopFailure", "StopCancelled", "PostToolUseFailure"],
}


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def config_path(agent, home):
    return (
        home
        / {
            "codex": "hooks.json",
            "claude": "settings.json",
            "kimi": "config.toml",
            "grok": "hooks/terminx.json",
        }[agent]
    )


def hook_command(agent, statusline=False, directory=None, home=None):
    args = module_command("terminx.bridge", agent)
    if statusline:
        args.append("--statusline")
    if directory:
        args.extend(["--state-dir", str(directory)])
    if home:
        args.extend(["--data-home", str(home)])
    # Forward slashes survive both Git Bash and cmd.exe on Windows.
    if os.name == "nt":
        return " ".join('"' + arg.replace("\\", "/") + '"' for arg in args)
    return __import__("shlex").join(args)


def install(agent, directory=None, home=None):
    if agent not in EVENTS:
        raise ValueError("Integration is unavailable for this CLI")
    directory = Path(directory or state_dir())
    manifest_path = directory / "integrations" / f"{agent}.json"
    if manifest_path.exists():
        return "Already installed; restart the CLI if needed"
    home = Path(home or provider_home(agent)).resolve()
    path = config_path(agent, home)
    before = path.read_text(encoding="utf-8") if path.exists() else ""
    is_toml = agent == "kimi"
    if is_toml:
        import tomlkit

        config = tomlkit.parse(before)
    else:
        config = json.loads(before) if before.strip() else {}
    if not isinstance(config, dict):
        raise ValueError("Expected a configuration object; no changes made")
    command = hook_command(agent, directory=directory, home=home)
    added = []
    for event in EVENTS[agent]:
        if is_toml:
            entry = {"event": event, "command": command, "timeout": 1}
            if "hooks" not in config:
                config["hooks"] = tomlkit.aot()
            config["hooks"].append(entry)
        else:
            entry = {"hooks": [{"type": "command", "command": command, "timeout": 1}]}
            config.setdefault("hooks", {}).setdefault(event, []).append(entry)
        added.append([event, entry])
    original_statusline = (
        deepcopy(config.get("statusLine")) if agent == "claude" else None
    )
    new_statusline = None
    if agent == "claude":
        if original_statusline is not None and not isinstance(
            original_statusline, dict
        ):
            raise ValueError("Expected a statusLine object; no changes made")
        new_statusline = dict(original_statusline or {})
        new_statusline.update(
            type="command", command=hook_command(agent, True, directory, home)
        )
        config["statusLine"] = new_statusline
    after = (
        tomlkit.dumps(config)
        if is_toml
        else json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    )
    manifest = {
        "path": str(path),
        "added": added,
        "original_statusline": original_statusline,
        "new_statusline": new_statusline,
        "existed": bool(before),
    }
    # Backup and manifest are durable before the provider config is changed.
    backup = directory / "integrations" / f"{agent}.original"
    atomic_write(backup, before)
    atomic_write(manifest_path, json.dumps(manifest, indent=2))
    try:
        atomic_write(path, after)
    except Exception:
        manifest_path.unlink(missing_ok=True)
        raise
    return "Installed; restart CLI"


def uninstall(agent, directory=None):
    directory = Path(directory or state_dir())
    manifest_path = directory / "integrations" / f"{agent}.json"
    if not manifest_path.exists():
        return "Not installed"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    path = Path(manifest["path"])
    before = path.read_text(encoding="utf-8") if path.exists() else ""
    if agent == "kimi":
        import tomlkit

        config = tomlkit.parse(before)
        for _, entry in manifest["added"]:
            hooks = config.get("hooks", [])
            for index in reversed(range(len(hooks))):
                if dict(hooks[index]) == entry:
                    del hooks[index]
        after = tomlkit.dumps(config)
    else:
        config = json.loads(before) if before.strip() else {}
        for event, entry in manifest["added"]:
            hooks = config.get("hooks", {}).get(event, [])
            if entry in hooks:
                hooks.remove(entry)
            if not hooks:
                config.get("hooks", {}).pop(event, None)
        if not config.get("hooks"):
            config.pop("hooks", None)
        if agent == "claude" and config.get("statusLine") == manifest["new_statusline"]:
            if manifest["original_statusline"] is None:
                config.pop("statusLine", None)
            else:
                config["statusLine"] = manifest["original_statusline"]
        after = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    atomic_write(path, after)
    manifest_path.unlink()
    return "Removed; other CLI settings preserved"


def integration_state(agent, directory=None):
    if agent == "codex":
        return "Native process and session logs · no hooks"
    if agent not in EVENTS:
        return "Passive discovery"
    path = Path(directory or state_dir()) / "integrations" / f"{agent}.json"
    return "Installed · awaiting CLI events" if path.exists() else "Not installed"
