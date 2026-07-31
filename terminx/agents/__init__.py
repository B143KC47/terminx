from .claude import ClaudeAdapter
from .codex import CodexAdapter
from .kimi import KimiAdapter
from .opencode import OpenCodeAdapter

ADAPTERS = [CodexAdapter(), ClaudeAdapter(), OpenCodeAdapter(), KimiAdapter()]
