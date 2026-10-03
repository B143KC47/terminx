"""Bounded public user/assistant messages for an explicitly opened session view."""

import json
from pathlib import Path


def text_content(value):
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    return "\n".join(
        str(p["text"])
        for p in value
        if isinstance(p, dict)
        and p.get("type") in {"text", "input_text", "output_text", "Text"}
        and isinstance(p.get("text"), str)
    )


def public_message(agent, obj):
    payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
    if agent == "codex":
        kind = obj.get("type")
        if kind == "event_msg":
            event = payload.get("type")
            if event in {"agent_message", "user_message"}:
                return (
                    "assistant" if event == "agent_message" else "user",
                    text_content(payload.get("message")),
                )
            item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
            if (
                event == "item_completed"
                and item.get("type") == "AgentMessage"
                and item.get("phase") not in {"analysis", "reasoning"}
            ):
                return "assistant", text_content(item.get("content"))
        elif (
            kind == "response_item"
            and payload.get("type") == "message"
            and payload.get("role") in {"user", "assistant"}
        ):
            if payload.get("phase") not in {"analysis", "reasoning"} and payload.get(
                "channel"
            ) not in {"analysis", "reasoning"}:
                return payload["role"], text_content(payload.get("content"))
    elif (
        agent == "claude"
        and not obj.get("isSidechain")
        and obj.get("type") in {"user", "assistant"}
    ):
        message = obj.get("message") if isinstance(obj.get("message"), dict) else {}
        return obj["type"], text_content(message.get("content"))
    elif agent == "kimi":
        if obj.get("type") in {"context.append", "context.append_message"}:
            message = obj.get("message") if isinstance(obj.get("message"), dict) else {}
            if message.get("role") in {"user", "assistant"}:
                return message["role"], text_content(message.get("content"))
        event = obj.get("event") if isinstance(obj.get("event"), dict) else {}
        if (
            obj.get("type") == "context.append_loop_event"
            and event.get("type") == "content.part"
        ):
            part = event.get("part") if isinstance(event.get("part"), dict) else {}
            if part.get("type") == "text":
                return "assistant", str(part.get("text") or "")
    elif agent == "grok":
        params = obj.get("params") if isinstance(obj.get("params"), dict) else {}
        update = params.get("update") if isinstance(params.get("update"), dict) else {}
        kind = update.get("sessionUpdate")
        if kind in {"agent_message_chunk", "user_message_chunk"}:
            return (
                "assistant" if kind == "agent_message_chunk" else "user",
                text_content([update.get("content")]),
            )
    return None


def read_preview(session, limit=12, byte_limit=160_000):
    if not session.activity_path:
        return []
    try:
        with Path(session.activity_path).open("rb") as stream:
            size = stream.seek(0, 2)
            offset = max(0, size - byte_limit)
            stream.seek(offset)
            if offset:
                stream.readline()
            lines = stream.read(byte_limit).splitlines()
    except OSError:
        return []
    messages = []
    for line in lines:
        try:
            obj = json.loads(line)
            message = (
                public_message(session.agent, obj) if isinstance(obj, dict) else None
            )
            if (
                message
                and message[1].strip()
                and (not messages or message != messages[-1])
            ):
                messages.append((message[0], message[1][-8000:]))
        except (ValueError, TypeError, AttributeError):
            continue
    return messages[-limit:]
