from .claude import ClaudeAdapter
from .codex import CodexAdapter
from .grok import GrokAdapter
from .kimi import KimiAdapter
from .opencode import OpenCodeAdapter

ADAPTERS = [
    CodexAdapter(),
    ClaudeAdapter(),
    KimiAdapter(),
    GrokAdapter(),
    OpenCodeAdapter(),
]
