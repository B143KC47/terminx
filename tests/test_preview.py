import json
import tempfile
import unittest
from pathlib import Path

from terminx.agents.base import SessionInfo
from terminx.core.preview import read_preview


class PreviewTests(unittest.TestCase):
    def test_codex_public_output_excludes_reasoning_and_tool_content(self):
        records = [
            {
                "type": "event_msg",
                "payload": {
                    "type": "item_completed",
                    "item": {"type": "Reasoning", "raw_content": "PRIVATE"},
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "item_completed",
                    "item": {
                        "type": "AgentMessage",
                        "phase": "analysis",
                        "content": "PRIVATE",
                    },
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "channel": "analysis",
                    "content": "PRIVATE",
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "item_completed",
                    "item": {
                        "type": "AgentMessage",
                        "phase": "commentary",
                        "content": [{"type": "Text", "text": "Working on it"}],
                    },
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "item_completed",
                    "item": {"type": "CommandExecution", "stdout": "PRIVATE"},
                },
            },
        ]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            path.write_text("\n".join(json.dumps(row) for row in records) + "\n")
            messages = read_preview(SessionInfo("codex", activity_path=str(path)))
            self.assertEqual(messages, [("assistant", "Working on it")])

    def test_claude_thinking_sidechain_and_tools_are_not_public_messages(self):
        records = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "thinking", "thinking": "PRIVATE"},
                        {"type": "text", "text": "Done"},
                    ]
                },
            },
            {
                "type": "assistant",
                "isSidechain": True,
                "message": {"content": [{"type": "text", "text": "PRIVATE"}]},
            },
            {
                "type": "user",
                "message": {"content": [{"type": "tool_result", "content": "PRIVATE"}]},
            },
        ]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            path.write_text("\n".join(json.dumps(row) for row in records))
            self.assertEqual(
                read_preview(SessionInfo("claude", activity_path=str(path))),
                [("assistant", "Done")],
            )

    def test_bounded_tail_tolerates_malformed_records_and_keeps_latest(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            path.write_text(
                "bad\n"
                + "\n".join(
                    json.dumps(
                        {
                            "type": "event_msg",
                            "payload": {"type": "agent_message", "message": str(i)},
                        }
                    )
                    for i in range(100)
                )
            )
            rows = read_preview(
                SessionInfo("codex", activity_path=str(path)), limit=3, byte_limit=600
            )
            self.assertEqual([text for _, text in rows], ["97", "98", "99"])

    def test_missing_log_does_not_crash_details(self):
        self.assertEqual(
            read_preview(SessionInfo("kimi", activity_path="missing-log.jsonl")), []
        )


if __name__ == "__main__":
    unittest.main()
