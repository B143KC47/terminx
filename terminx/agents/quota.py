"""Official CLI quota surfaces with provenance, freshness and account isolation."""

import atexit
import json
import math
import queue
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from copy import deepcopy
from datetime import datetime, timezone

from .. import __version__
from ..bridge import account_fingerprint
from ..core.events import EventJournal, state_dir
from ..core.paths import configured_home
from ..core.runtime import external_popen
from ..core.usage import utcnow
from ..i18n import t
from .base import Quota, QuotaWindow

_CACHE = {}
_LOCK = threading.Lock()
_KIMI = {}
URLS = {
    "codex": "https://chatgpt.com/codex/settings/usage",
    "claude": "https://claude.ai/settings/usage",
    "kimi": "https://www.kimi.com/code/console",
    "grok": "https://grok.com",
    "opencode": "https://opencode.ai/docs/providers/",
}


def _root(agent, cfg):
    return configured_home(agent, cfg)


def _fmt_countdown(reset_after=None, reset_at=None):
    if reset_after is None and reset_at is None:
        return None
    seconds = max(
        0, int(reset_after if reset_after is not None else reset_at - time.time())
    )
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    return (
        t("resets in {days}d {hours}h", days=days, hours=hours)
        if days
        else t("resets in {hours}h {minutes}m", hours=hours, minutes=rem // 60)
    )


def make_window(label, pct, reset=None, seconds=0):
    if not isinstance(pct, (int, float)) or pct < 0 or not math.isfinite(pct):
        return None
    if isinstance(reset, str):
        try:
            reset = datetime.fromisoformat(reset.replace("Z", "+00:00")).timestamp()
        except ValueError:
            reset = None
    return QuotaWindow(
        label,
        seconds,
        used_percent=float(pct),
        reset_at=datetime.fromtimestamp(reset, timezone.utc).isoformat()
        if reset
        else None,
        countdown=_fmt_countdown(reset_at=reset),
    )


def unavailable(agent, reason, availability="unavailable"):
    return Quota(
        agent,
        availability=availability,
        reason=reason,
        official_url=URLS.get(agent, ""),
    )


class QuotaUnavailable(Exception):
    pass


def fetch_quota(agent, cfg, fetch):
    root = _root(agent, cfg)
    account = account_fingerprint(agent, root)
    key = (agent, str(root), account)
    interval = max(5, cfg.get("quota_refresh_sec", 120))
    with _LOCK:
        hit = _CACHE.get(key)
    if hit and time.monotonic() - hit[0] < interval:
        return deepcopy(hit[1])
    try:
        value = fetch(root, account)
        if not value.windows:
            value.availability = "unavailable"
            value.reason = value.reason or "No account quota reported by this CLI"
        value.account_id = account
        value.official_url = URLS[agent]
        if value.fetched_at is None and value.windows:
            value.fetched_at = utcnow()
        if (
            value.fetched_at
            and (utcnow() - value.fetched_at).total_seconds() > interval * 2
        ):
            value.availability = "stale"
            value.reason = "Waiting for a fresh CLI update"
    except Exception as exc:
        reason = (
            "Authentication required"
            if isinstance(exc, urllib.error.HTTPError) and exc.code in {401, 403}
            else str(exc)
            if isinstance(exc, QuotaUnavailable)
            else f"Quota query failed ({type(exc).__name__})"
        )
        value = (
            deepcopy(hit[1]) if hit and hit[1].windows else unavailable(agent, reason)
        )
        value.availability = "stale" if value.windows else "unavailable"
        value.reason = reason
        value.account_id = account
    with _LOCK:
        _CACHE[key] = (time.monotonic(), deepcopy(value))
    return value


def codex_rpc(root):
    exe = shutil.which("codex")
    if not exe:
        raise QuotaUnavailable("Codex CLI is not installed")
    import os

    proc = external_popen(
        [exe, "app-server", "--stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=dict(os.environ, CODEX_HOME=str(root)),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    messages = queue.Queue()

    def read():
        try:
            for line in proc.stdout:
                try:
                    messages.put(json.loads(line))
                except (ValueError, UnicodeError):
                    pass
        finally:
            messages.put(None)

    thread = threading.Thread(target=read, daemon=True)
    thread.start()

    def send(data):
        proc.stdin.write((json.dumps(data) + "\n").encode())
        proc.stdin.flush()

    def receive(identifier):
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            message = messages.get(timeout=max(0.01, deadline - time.monotonic()))
            if message is None:
                raise QuotaUnavailable("Codex app-server closed before returning quota")
            if message.get("id") == identifier:
                if "error" in message:
                    raise QuotaUnavailable(
                        "Codex did not expose account limits; check CLI login"
                    )
                return message.get("result") or {}
        raise TimeoutError()

    try:
        send(
            {
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {"name": "terminx", "version": __version__},
                    "capabilities": {},
                },
            }
        )
        receive(1)
        send({"method": "initialized"})
        send({"id": 2, "method": "account/rateLimits/read"})
        return receive(2)
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait(timeout=2)
        thread.join(timeout=1)
        proc.stdout.close()


def parse_codex(data):
    q = Quota("codex", source="account/rateLimits/read")
    buckets = data.get("rateLimitsByLimitId") or {"codex": data.get("rateLimits") or {}}
    for bucket_id, bucket in buckets.items():
        for label in ("primary", "secondary"):
            window = bucket.get(label) or {}
            seconds = int(window.get("windowDurationMins") or 0) * 60
            duration = (
                f"{seconds // 86400}d"
                if seconds >= 86400
                else f"{seconds / 3600:g}h"
                if seconds
                else label
            )
            win = make_window(
                f"{bucket_id} · {duration}",
                window.get("usedPercent"),
                window.get("resetsAt"),
                seconds,
            )
            if win:
                q.windows.append(win)
        q.limited |= bool(bucket.get("rateLimitReachedType"))
    return q


def fetch_codex_quota(cfg):
    return fetch_quota("codex", cfg, lambda root, account: parse_codex(codex_rpc(root)))


def fetch_claude_quota(cfg):
    def fetch(root, account):
        latest = None
        cursor = 0
        journal = EventJournal(state_dir(cfg))
        while True:
            batch = journal.read(cursor)
            if not batch:
                break
            for seq, event in batch:
                cursor = seq
                if (
                    event.agent == "claude"
                    and event.source == "statusline"
                    and event.data.get("account_id") == account
                ):
                    if latest is None or event.at > latest.at:
                        latest = event
        if not latest:
            raise QuotaUnavailable(
                "Enable Claude integration and wait for a statusline update"
            )
        q = Quota(
            "claude",
            source="official statusline",
            fetched_at=datetime.fromtimestamp(latest.at, timezone.utc),
        )
        for label, data in (latest.data.get("rate_limits") or {}).items():
            win = make_window(label, data.get("used_percentage"), data.get("resets_at"))
            if win:
                q.windows.append(win)
        return q

    return fetch_quota("claude", cfg, fetch)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _kimi_request(root, port, timeout=3):
    token = (root / "server.token").read_text(encoding="utf-8").strip()
    req = urllib.request.Request(
        f"http://127.0.0.1:{int(port)}/api/v1/oauth/usage",
        headers={"Authorization": f"Bearer {token}"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(req, timeout=timeout) as response:
        body = json.load(response)
    data = body.get("data") or {}
    if body.get("code") != 0 or data.get("kind") != "ok":
        raise QuotaUnavailable("Kimi account usage unavailable; check CLI login")
    return data.get("quota") or {}


def close_helpers():
    for proc, _ in list(_KIMI.values()):
        if proc and proc.poll() is None:
            try:
                import psutil

                parent = psutil.Process(proc.pid)
                for child in parent.children(recursive=True):
                    child.terminate()
                parent.terminate()
                proc.wait(timeout=3)
            except Exception:
                pass
    _KIMI.clear()


atexit.register(close_helpers)


def kimi_usage(root, cfg):
    deadline = time.monotonic() + 8
    candidates = [cfg.get("kimi_server_port", 58627)]
    own = _KIMI.get(str(root))
    if own:
        candidates.insert(0, own[1])
    for desc in (root / "server" / "instances").glob("*.json"):
        try:
            data = json.loads(desc.read_text(encoding="utf-8"))
            if isinstance(data.get("port"), int):
                candidates.append(data["port"])
        except (OSError, ValueError):
            pass
    for port in dict.fromkeys(candidates):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            return _kimi_request(root, port, timeout=min(3, remaining))
        except (OSError, ValueError):
            pass
    if not cfg.get("kimi_start_server", True) or not shutil.which("kimi"):
        raise QuotaUnavailable(
            "Kimi local service unavailable; start kimi web --no-open"
        )
    if own and own[0].poll() is None:
        raise QuotaUnavailable("Kimi local service is still starting")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    import os

    proc = external_popen(
        [
            shutil.which("kimi"),
            "web",
            "--no-open",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=dict(os.environ, KIMI_CODE_HOME=str(root)),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    _KIMI[str(root)] = (proc, port)
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        time.sleep(0.25)
        try:
            return _kimi_request(
                root, port, timeout=max(0.1, min(1, deadline - time.monotonic()))
            )
        except (OSError, ValueError):
            if proc.poll() is not None:
                break
    raise QuotaUnavailable("Kimi local service did not return quota")


def parse_kimi(data):
    q = Quota("kimi", source="local official /api/v1/oauth/usage")
    for label, entry in (data.get("usages") or {}).items():
        ratio = entry.get("usedRatio")
        win = make_window(
            label,
            ratio * 100 if isinstance(ratio, (int, float)) else None,
            entry.get("resetAt"),
        )
        if win:
            q.windows.append(win)
    return q


def fetch_kimi_quota(cfg):
    return fetch_quota(
        "kimi", cfg, lambda root, account: parse_kimi(kimi_usage(root, cfg))
    )


def collect_quotas(adapters, cfg, on_result=None):
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def fetch(adapter):
        try:
            value = adapter.quota(cfg)
            if value is None:
                value = unavailable(
                    adapter.name,
                    "Account quota interface unavailable; open the official usage view",
                )
            return {"agent": adapter.name, "quota": value}
        except Exception as exc:
            return {
                "agent": adapter.name,
                "quota": unavailable(
                    adapter.name, f"Quota query failed ({type(exc).__name__})"
                ),
            }

    with ThreadPoolExecutor(max_workers=max(1, len(adapters))) as pool:
        futures = [pool.submit(fetch, adapter) for adapter in adapters]
        rows = []
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            if on_result:
                on_result(row)
        by_agent = {row["agent"]: row for row in rows}
        return [by_agent[a.name] for a in adapters]
