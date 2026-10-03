"""Bounded incremental JSONL reading. No prompts or outputs are retained."""

import json
import math
from datetime import timezone
from pathlib import Path

from .events import SessionEvent
from .usage import parse_ts


class JsonlTail:
    def __init__(self):
        self.files = {}
        self.discarding = set()

    def read(self, path):
        p = Path(path)
        key = str(p)
        try:
            stat = p.stat()
            identity = (stat.st_dev, stat.st_ino)
            prior = self.files.get(key)
            reset = (
                not prior
                or prior[0] != identity
                or stat.st_size < prior[1]
                or (stat.st_size == prior[1] and stat.st_mtime_ns != prior[2])
            )
            offset = max(0, stat.st_size - 1_000_000) if reset else prior[1]
            if reset:
                self.discarding.discard(key)
            if prior and not reset and stat.st_size == offset:
                return [], False
            with p.open("rb") as stream:
                stream.seek(offset)
                if reset and offset:
                    stream.readline()
                start = stream.tell()
                data = stream.read(2_000_000)
            end = data.rfind(b"\n") + 1
            first = 0
            if key in self.discarding:
                newline = data.find(b"\n")
                if newline < 0:
                    self.files[key] = (identity, start + len(data), stat.st_mtime_ns)
                    return [], bool(reset)
                first = newline + 1
                self.discarding.discard(key)
            elif not end and len(data) == 2_000_000:
                # Skip an oversized record across bounded reads. A partial
                # ordinary record stays unread until its newline arrives.
                self.discarding.add(key)
                self.files[key] = (identity, start + len(data), stat.st_mtime_ns)
                return [], bool(reset)
            self.files[key] = (identity, start + end, stat.st_mtime_ns)
            rows = []
            for line in data[first:end].splitlines():
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        rows.append(obj)
                except (ValueError, UnicodeError):
                    continue
            return rows, bool(reset)
        except OSError:
            return [], False


def timestamp(value):
    if isinstance(value, (int, float)):
        return (
            (value / 1000 if value > 100_000_000_000 else float(value))
            if math.isfinite(value)
            else 0
        )
    dt = parse_ts(value) if isinstance(value, str) else None
    return (
        dt.replace(tzinfo=timezone.utc).timestamp()
        if dt and dt.tzinfo is None
        else dt.timestamp()
        if dt
        else 0
    )


def _object(value):
    return value if isinstance(value, dict) else {}


def event_from_log(s, obj):
    kind, turn, data = None, "", {}
    at = timestamp(obj.get("timestamp") or obj.get("time"))
    if not at:
        return None
    if s.agent == "codex":
        p = _object(obj.get("payload"))
        if obj.get("type") == "event_msg":
            typ = p.get("type")
            kind = {
                "task_started": "turn_started",
                "task_complete": "completed",
                "turn_aborted": "interrupted",
                "agent_message": "outputting",
                "user_message": "processing",
                "exec_command_begin": "tool_running",
                "exec_command_end": "tool_finished",
            }.get(typ)
            turn = str(p.get("turn_id") or "")
            if typ in {"item_started", "item_completed"}:
                item = _object(p.get("item"))
                item_type = item.get("type")
                kind = {
                    "Reasoning": "processing",
                    "AgentMessage": "outputting",
                    "CommandExecution": "tool_running"
                    if typ == "item_started"
                    else "processing",
                    "McpToolCall": "tool_running"
                    if typ == "item_started"
                    else "processing",
                }.get(item_type)
            if typ == "token_count":
                u = _object(_object(p.get("info")).get("total_token_usage"))
                data = {
                    "input_tokens": u.get("input_tokens"),
                    "output_tokens": u.get("output_tokens"),
                }
                kind = "usage"
    elif s.agent == "claude":
        if obj.get("isSidechain"):
            return None
        typ = obj.get("type")
        if typ == "user":
            kind = "processing"
        elif typ == "assistant":
            kind = "error" if obj.get("isApiErrorMessage") else "processing"
            # Persisted assistant chunks may precede a blocking Stop hook.
            data = {}  # per-message usage must not be mistaken for session totals
        elif typ == "system" and obj.get("subtype") == "turn_duration":
            kind = "completed"
    elif s.agent == "kimi":
        typ = obj.get("type")
        e = _object(obj.get("event"))
        turn = str(obj.get("turnId") or e.get("turnId") or "")
        if typ == "turn.ended":
            kind = {
                "completed": "completed",
                "interrupted": "interrupted",
                "cancelled": "interrupted",
                "error": "error",
            }.get(obj.get("reason"), "unknown")
        elif typ == "llm.request":
            kind = "processing"
            data["model"] = obj.get("model")
        elif typ == "context.append_loop_event":
            kind = {
                "step.begin": "processing",
                "content.part": "outputting",
                "tool.result": "tool_finished",
            }.get(e.get("type"))
    elif s.agent == "grok":
        update = _object(_object(obj.get("params")).get("update"))
        typ = update.get("sessionUpdate")
        kind = {
            "user_message_chunk": "processing",
            "agent_message_chunk": "outputting",
            "agent_thought_chunk": "processing",
        }.get(typ)
        if typ == "turn_completed":
            stop = update.get("stop_reason")
            kind = (
                "completed"
                if stop in {"end_turn", "completed", "stop"}
                else "interrupted"
                if stop in {"cancelled", "interrupted"}
                else "unknown"
            )
        elif typ in {"tool_call", "tool_call_update"}:
            kind = {
                "in_progress": "tool_running",
                "completed": "tool_finished",
                "failed": "tool_finished",
            }.get(update.get("status"))
    if not kind:
        return None
    return SessionEvent(
        s.agent, s.session_id, s.data_root, kind, at, "log", turn, data=data
    )
