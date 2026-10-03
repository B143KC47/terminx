"""Positive evidence of an interactive CLI and its open session files."""

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import psutil

from .processes import running_pids
from .runtime import module_command

NAMES = {"codex", "claude", "kimi", "grok", "opencode"}
HELPERS = {
    "codex": {
        "app-server",
        "mcp-server",
        "exec",
        "e",
        "review",
        "debug",
        "features",
        "login",
        "logout",
        "completion",
        "sandbox",
        "cloud",
        "apply",
    },
    "kimi": {"web", "server", "serve", "login", "logout", "info"},
    "grok": {"serve", "server", "login", "logout"},
    "claude": {"mcp", "auth", "doctor", "update"},
    "opencode": {"serve", "web", "run", "auth", "mcp"},
}


def interactive_agent(name, args):
    name = name.lower().removesuffix(".exe")
    agent = name if name in NAMES else None
    arguments = args[1:]
    if name in {"node", "bun"}:
        script = (args[1] if len(args) > 1 else "").lower().replace("\\", "/")
        agent = next(
            (
                a
                for a, marker in [
                    ("codex", "/@openai/codex/"),
                    ("claude", "/claude-code/"),
                    ("kimi", "/kimi-code/"),
                    ("grok", "/@x-ai/grok/"),
                    ("grok", "/@xai/grok/"),
                    ("opencode", "/opencode-ai/"),
                ]
                if marker in script
            ),
            None,
        )
        arguments = args[2:]
    if not agent:
        return None
    tokens = set(arguments)
    if tokens & {"--help", "--version", "-h", "--print", "--headless", "--acp"}:
        return None
    if agent in {"claude", "kimi", "grok"} and "-p" in tokens:
        return None
    # Examine the command slot, not values such as --model review or a prompt word.
    value_flags = {
        "--model",
        "-m",
        "--profile",
        "-p",
        "--config",
        "-c",
        "--cd",
        "-C",
        "--cwd",
        "--directory",
        "--session",
        "--resume",
        "--add-dir",
        "--permission-mode",
        "--sandbox",
    }
    skip = False
    for arg in arguments:
        if skip:
            skip = False
            continue
        if arg in value_flags:
            skip = True
        elif arg.startswith("-"):
            continue
        else:
            if arg in HELPERS[agent]:
                return None
            break
    return agent


def console_for_pid(pid):
    """Get the exact console handle in a different helper process."""
    try:
        result = subprocess.run(
            module_command("terminx.core.runtime", str(pid)),
            capture_output=True,
            text=True,
            timeout=2,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return int(json.loads(result.stdout))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 0


@dataclass
class OpenCLI:
    agent: str
    pid: int
    created_at: float
    cwd: str = ""
    console_hwnd: int = 0
    files: list[str] = field(default_factory=list)
    ancestors: tuple[int, ...] = ()


class LiveProcesses:
    def __init__(self, agents):
        self.agents = set(agents) & NAMES
        self.consoles = {}

    def scan(self):
        if not self.agents:
            return []
        rows = []
        for pid in running_pids(*self.agents, "node", "bun"):
            try:
                process = psutil.Process(pid)
                agent = interactive_agent(process.name(), process.cmdline())
                if agent not in self.agents:
                    continue
                created = process.create_time()
                identity = pid, created
                if os.name == "nt":
                    hwnd = self.consoles.get(identity)
                    if hwnd is None:
                        hwnd = console_for_pid(pid)
                        if hwnd:
                            self.consoles[identity] = hwnd
                    if not hwnd:
                        continue
                else:
                    if not process.terminal():
                        continue
                    hwnd = 0
                try:
                    files = [f.path for f in process.open_files()]
                except (psutil.Error, OSError):
                    files = []
                if not process.is_running():
                    continue
                rows.append(
                    OpenCLI(
                        agent,
                        pid,
                        created,
                        process.cwd(),
                        hwnd,
                        files,
                        tuple(p.pid for p in process.parents()),
                    )
                )
            except (psutil.Error, OSError):
                continue
        # A Node/cmd launcher and its native CLI are one terminal.
        ancestors = {pid for row in rows for pid in row.ancestors}
        rows = [row for row in rows if row.pid not in ancestors]
        identities = {(row.pid, row.created_at) for row in rows}
        self.consoles = {
            key: hwnd for key, hwnd in self.consoles.items() if key in identities
        }
        return rows


def is_rollout(path):
    file = Path(path)
    return file.name.startswith("rollout-") and file.suffix == ".jsonl"
