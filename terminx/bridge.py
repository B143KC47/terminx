"""Passive CLI hook/statusline bridge. It never emits hook decisions."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .core.events import EventJournal, SessionEvent, state_dir
from .core.paths import HOME_NAME, provider_home
from .core.runtime import external_run


def identify_runtime(agent):
    """Check the nearest CLI ancestor, including Grok's Claude compatibility hooks."""
    import psutil

    try:
        for process in psutil.Process().parents()[:12]:
            name = process.name().lower().removesuffix(".exe")
            identified = next(
                (a for a in HOME_NAME if name == a or name == f"{a}-code"), None
            )
            args = process.cmdline()
            if name in {"node", "bun"}:
                script = " ".join(args[:2]).lower().replace("\\", "/")
                identified = next(
                    (
                        a
                        for a, marker in [
                            ("kimi", "kimi-code"),
                            ("claude", "claude-code"),
                            ("codex", "@openai/codex"),
                            ("grok", "grok"),
                        ]
                        if marker in script
                    ),
                    None,
                )
            if identified:
                if identified != agent:
                    return None
                console_hwnd = 0
                if os.name == "nt":
                    import ctypes

                    k = ctypes.windll.kernel32
                    k.FreeConsole()
                    if k.AttachConsole(process.pid):
                        k.GetConsoleWindow.restype = ctypes.c_void_p
                        console_hwnd = k.GetConsoleWindow() or 0
                return {
                    "pid": process.pid,
                    "created_at": process.create_time(),
                    "console_hwnd": console_hwnd,
                    "wt_session": os.environ.get("WT_SESSION", ""),
                    "launch_id": os.environ.get("TERMINX_LAUNCH_ID", ""),
                }
    except (psutil.Error, OSError):
        pass
    return None


def normalize_hook(agent, payload, runtime=None, root=None, now=None):
    sid = payload.get("session_id") or payload.get("sessionId")
    if not isinstance(sid, str) or not sid or len(sid) > 256:
        return None
    name = payload.get("hook_event_name") or payload.get("hookEventName") or ""
    mapping = {
        "SessionStart": "session_started",
        "SessionEnd": "exited",
        "SessionHeartbeat": "heartbeat",
        "UserPromptSubmit": "processing",
        "TurnStarted": "turn_started",
        "UserPromptQueued": "queued",
        "PreToolUse": "processing",
        "PostToolUse": "tool_finished",
        "PostToolUseFailure": "tool_finished",
        "PermissionRequest": "waiting_approval",
        "PermissionResult": "processing",
        "Stop": "stop_candidate",
        "StopFailure": "error",
        "Interrupt": "interrupted",
        "StopCancelled": "interrupted",
        "PreCompact": "processing",
        "PostCompact": "processing",
    }
    kind = mapping.get(name)
    if name == "Notification":
        notification = payload.get("notification_type") or payload.get(
            "notificationType"
        )
        kind = {
            "permission_prompt": "waiting_approval",
            "idle_prompt": "ready",
            "elicitation_dialog": "waiting_input",
        }.get(notification)
    tool = payload.get("tool_name") or payload.get("toolName") or ""
    if name == "PreToolUse" and tool in {
        "AskUserQuestion",
        "ask_user",
        "request_user_input",
    }:
        kind = "waiting_input"
    if not kind:
        return None
    data = dict(runtime or {})
    for dest, keys in {
        "cwd": ("cwd",),
        "title": ("session_title",),
        "model": ("model",),
        "activity_path": ("transcript_path",),
        "parent_id": ("parent_session_id",),
    }.items():
        for key in keys:
            if isinstance(payload.get(key), str):
                data[dest] = payload[key][:4096]
                break
    # Never copy prompt, command arguments, transcript text, or credentials.
    return SessionEvent(
        agent,
        sid,
        str(root or provider_home(agent)),
        kind,
        now or time.time(),
        turn_id=str(payload.get("turn_id") or payload.get("promptId") or ""),
        data=data,
    )


def normalize_statusline(agent, payload, runtime=None, root=None):
    sid = payload.get("session_id")
    if not sid:
        return None
    data = dict(runtime or {})
    model = payload.get("model") or {}
    workspace = payload.get("workspace") or {}
    context = payload.get("context_window") or {}
    data.update(
        model=model.get("display_name"),
        cwd=workspace.get("current_dir"),
        input_tokens=context.get(
            "total_input_tokens", context.get("session_input_tokens")
        ),
        output_tokens=context.get(
            "total_output_tokens", context.get("session_output_tokens")
        ),
        context_percent=context.get("used_percentage"),
    )
    limits = payload.get("rate_limits")
    if isinstance(limits, dict):
        data["rate_limits"] = {
            k: {
                f: v[f]
                for f in ("used_percentage", "resets_at")
                if isinstance(v.get(f), (int, float))
            }
            for k, v in limits.items()
            if isinstance(v, dict)
        }
    return SessionEvent(
        agent,
        str(sid),
        str(root or provider_home(agent)),
        "usage",
        time.time(),
        "statusline",
        data=data,
    )


def forward_statusline(agent, raw):
    """Preserve the user's pre-existing command and its stdout byte for byte."""
    path = state_dir() / "integrations" / f"{agent}.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        original = manifest.get("original_statusline") or {}
        command = original.get("command")
        if command:
            # This is the exact user-authored shell command, never derived from event input.
            result = external_run(
                command,
                shell=True,
                input=raw,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if sys.stdout:
                sys.stdout.buffer.write(result.stdout)
                sys.stdout.flush()
    except Exception:
        pass


def account_fingerprint(agent, root):
    """Opaque local cache key changes on credential/account switches; never stores a token."""
    path = Path(root) / {"claude": ".credentials.json", "codex": "auth.json"}.get(
        agent, "auth.json"
    )
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return hashlib.sha256(str(root).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("agent", choices=HOME_NAME)
    parser.add_argument("--statusline", action="store_true")
    parser.add_argument("--state-dir")
    parser.add_argument("--data-home")
    args = parser.parse_args()
    if args.state_dir:
        os.environ["TERMINX_STATE_DIR"] = args.state_dir
    raw = b""
    try:
        raw = sys.stdin.buffer.read(2_000_000)
        payload = json.loads(raw)
        runtime = identify_runtime(args.agent)
        if runtime is not None:
            root = Path(args.data_home) if args.data_home else provider_home(args.agent)
            event = (normalize_statusline if args.statusline else normalize_hook)(
                args.agent, payload, runtime, root
            )
            if event:
                if args.statusline:
                    event.data["account_id"] = account_fingerprint(args.agent, root)
                EventJournal().append(event)
    except Exception:
        pass  # Observability failure must never block a user's CLI.
    if args.statusline:
        forward_statusline(args.agent, raw)


if __name__ == "__main__":
    main()
