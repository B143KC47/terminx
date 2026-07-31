import json
import time
import urllib.request
from pathlib import Path

from .base import Quota, QuotaWindow

_CACHE: dict[str, tuple[float, Quota | None]] = {}
_TTL = 120.0


def _cached(key: str, fetch):
    now = time.monotonic()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    try:
        quota = fetch()
    except Exception:
        quota = None
    _CACHE[key] = (now, quota)
    return quota


def _http_json(url: str, headers: dict, timeout: int = 15) -> dict | None:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "ignore"))


def _fmt_countdown(reset_after: int | None, reset_at: int | None) -> str | None:
    if reset_after is not None:
        seconds = int(reset_after)
    elif reset_at is not None:
        seconds = int(reset_at) - int(time.time())
    else:
        return None
    if seconds <= 0:
        return "resets now"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"resets in {days}d {hours}h"
    if hours:
        return f"resets in {hours}h {minutes}m"
    return f"resets in {minutes}m"


# ---------------------------------------------------------------------------
# Codex / ChatGPT Plus — https://chatgpt.com/backend-api/wham/usage
# ---------------------------------------------------------------------------


def fetch_codex_quota(cfg: dict) -> Quota | None:
    def fetch() -> Quota:
        auth_file = Path.home() / ".codex" / "auth.json"
        if not auth_file.exists():
            raise RuntimeError("no codex auth")
        auth = json.loads(auth_file.read_text(encoding="utf-8"))
        tokens = auth.get("tokens") or {}
        access_token = tokens.get("access_token")
        account_id = tokens.get("account_id")
        if not access_token or not account_id:
            raise RuntimeError("codex auth missing token")
        base = cfg.get("codex_usage_url", "https://chatgpt.com/backend-api")
        data = _http_json(
            f"{base}/wham/usage",
            {
                "Authorization": f"Bearer {access_token}",
                "ChatGPT-Account-Id": account_id,
            },
        )
        plan = (data.get("plan_type") or "").capitalize() or None
        q = Quota(provider="codex (chatgpt)", plan=plan)
        rl = data.get("rate_limit") or {}
        primary = rl.get("primary_window") or {}
        secondary = rl.get("secondary_window") or {}

        def add_window(win: dict, label: str):
            if not isinstance(win, dict):
                return
            seconds = win.get("limit_window_seconds") or 0
            used_pct = win.get("used_percent")
            q.windows.append(
                QuotaWindow(
                    label=label,
                    seconds=int(seconds),
                    used_percent=float(used_pct) if used_pct is not None else None,
                    reset_at=None,
                    countdown=_fmt_countdown(
                        win.get("reset_after_seconds"), win.get("reset_at")
                    ),
                )
            )

        if primary:
            label = "weekly" if (primary.get("limit_window_seconds") or 0) >= 604800 else "5h"
            add_window(primary, label)
        if secondary:
            add_window(secondary, "5h")
        for entry in data.get("additional_rate_limits") or []:
            name = entry.get("limit_name") or ""
            if "codex" not in name.lower():
                continue
            rl2 = entry.get("rate_limit") or {}
            w = rl2.get("primary_window") or {}
            if w:
                add_window(w, name)
        return q

    return _cached("codex", fetch)


# ---------------------------------------------------------------------------
# Claude Code (subscription via OAuth) — https://api.anthropic.com/api/oauth/usage
# ---------------------------------------------------------------------------


def fetch_claude_quota(cfg: dict) -> Quota | None:
    def fetch() -> Quota:
        creds_file = Path.home() / ".claude" / ".credentials.json"
        if not creds_file.exists():
            raise RuntimeError("no claude credentials")
        creds = json.loads(creds_file.read_text(encoding="utf-8"))
        oauth = creds.get("claudeAiOauth") or {}
        token = oauth.get("accessToken") if isinstance(oauth, dict) else oauth
        if not token:
            raise RuntimeError("claude oauth token empty (routed/proxy setup)")
        data = _http_json(
            "https://api.anthropic.com/api/oauth/usage",
            {
                "Authorization": f"Bearer {token}",
                "anthropic-beta": "oauth-2025-04-20",
            },
        )
        q = Quota(provider="claude subscription")
        q.plan = creds.get("subscriptionType") if isinstance(creds, dict) else None
        for key, label in (
            ("five_hour", "5h"),
            ("seven_day", "7d"),
            ("seven_day_sonnet", "7d sonnet"),
            ("seven_day_opus", "7d opus"),
        ):
            win = data.get(key)
            if isinstance(win, dict) and win.get("utilization") is not None:
                q.windows.append(
                    QuotaWindow(
                        label=label,
                        seconds=5 * 3600 if key == "five_hour" else 7 * 86400,
                        used_percent=float(win["utilization"]) * 100,
                        countdown=None,
                    )
                )
        return q

    return _cached("claude", fetch)


# ---------------------------------------------------------------------------
# Kimi Code — https://api.kimi.com/coding/v1/usages (needs sk-kimi- console key)
# ---------------------------------------------------------------------------


def fetch_kimi_quota(cfg: dict) -> Quota | None:
    def fetch() -> Quota:
        api_key = cfg.get("kimi_api_key") or ""
        if not api_key:
            raise RuntimeError("no kimi console api key in config")
        base = cfg.get("kimi_usage_url", "https://api.kimi.com/coding/v1")
        data = _http_json(
            f"{base}/usages",
            {
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "KimiCLI/1.6",
            },
        )
        q = Quota(provider="kimi code")
        rows = data.get("data") if isinstance(data.get("data"), list) else []
        for item in rows:
            if not isinstance(item, dict):
                continue
            label = "weekly" if item.get("model_name") == "all" else "limit"
            used = item.get("used") or item.get("used_amount")
            limit = item.get("limit") or item.get("limit_amount")
            countdown = _fmt_countdown(
                item.get("reset_in"),
                None,
            )
            if used is None and limit is None:
                continue
            q.windows.append(
                QuotaWindow(
                    label=label,
                    seconds=7 * 86400 if label == "weekly" else 5 * 3600,
                    used=int(used or 0),
                    limit=int(limit) if limit is not None else None,
                    countdown=countdown,
                )
            )
        return q

    return _cached("kimi", fetch)
