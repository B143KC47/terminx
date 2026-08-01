"""Lightweight internationalization.

English strings in the code double as translation keys; optional JSON catalogs
in ``locales/`` provide localized text (e.g. ``zh_CN.json``). Language is picked
from the ``lang`` config key ("auto" | "en" | "zh_CN"), falling back to the
system locale, then English.
"""

import json
import os
from pathlib import Path

try:
    import locale as _locale
except ImportError:  # pragma: no cover
    _locale = None

LOCALES_DIR = Path(__file__).parent / "locales"

SUPPORTED = ("en", "zh_CN")

_catalog: dict[str, str] = {}
_lang = "en"


def detect_language() -> str:
    """Best-effort detection: ``LANG``-style env vars win, then system locale."""
    for var in ("LANG", "LC_ALL", "LC_MESSAGES"):
        env = os.environ.get(var)
        if env:
            code = env.split(".")[0].split("@")[0].replace("-", "_").lower()
            return "zh_CN" if code.startswith("zh") else "en"
    if _locale is not None:
        try:
            code = _locale.getdefaultlocale()[0] or ""
        except (ValueError, TypeError):
            code = ""
        if code.lower().startswith("zh"):
            return "zh_CN"
    return "en"


def set_language(lang: str = "auto") -> str:
    """Activate a catalog. Unknown codes fall back to English. Returns the active language."""
    global _catalog, _lang
    _lang = lang if lang in SUPPORTED else detect_language()
    _catalog = _load_catalog(_lang) if _lang != "en" else {}
    return _lang


def _load_catalog(name: str) -> dict[str, str]:
    path = LOCALES_DIR / f"{name}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def t(key: str, **kwargs) -> str:
    """Translate ``key`` (the English source string), formatting ``{name}`` placeholders."""
    text = _catalog.get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text
