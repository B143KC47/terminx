import queue
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..agents.base import AgentAdapter, SessionInfo
from ..agents.quota import collect_quotas
from ..config import load_config
from ..core.events import ACTIVE, ATTENTION, LABELS
from ..core.gitutil import git_branch
from ..core.monitor import Monitor, collect_sessions
from ..core.state import load_state, save_state
from ..core.terminals import TerminalLocator
from ..core.usage import utcnow
from ..i18n import set_language, t
from .colors import agent_color, cycle_color

STATUS_STYLE = {
    "working": ("green", "working"),
    "blocked": ("yellow", "blocked"),
    "idle": ("cyan", "idle"),
    "running": ("blue", "running"),
    "offline": ("dim red", "offline"),
}

STATUS_GLYPH = {
    "working": "●",
    "blocked": "■",
    "idle": "○",
    "running": "○",
    "offline": "·",
}


STATUS_STYLE.update(
    {
        key: (
            "yellow" if key in ATTENTION else "green" if key in ACTIVE else "cyan",
            value,
        )
        for key, value in LABELS.items()
    }
)


def _limit_status(pct: float | None, hit: bool = False) -> Text:
    if hit:
        return Text("HIT", style="bold red")
    if pct is None:
        return Text(t("n/a"), style="dim")
    if pct >= 90:
        label, style = "HIGH", "bold yellow"
    elif pct >= 80:
        label, style = "NEAR", "yellow"
    else:
        label, style = "OK", "green"
    return Text(f"{label} {pct:.0f}%", style=style)


def _usage_window_cell(win, hit=False) -> Text:
    t_row = Text()
    t_row.append(f"{t(win.label)}: ")
    t_row.append(_limit_status(win.pct, hit))
    if win.countdown:
        t_row.append(f" ({win.countdown})", style="dim")
    return t_row


def _find_wt() -> str | None:
    return shutil.which("wt") or shutil.which("wt.exe")


def _label(key: str, width: int = 12) -> str:
    """Translate a ``key:``-style label and pad to a fixed display width (CJK-aware)."""
    label = t(key)
    return label + " " * max(1, width - Text(label).cell_len)


class Dashboard:
    def __init__(self, adapters: list[AgentAdapter], cfg: dict):
        self.adapters = adapters
        self.cfg = cfg
        set_language(cfg.get("lang", "auto"))
        self.console = Console()
        self.view = "terminals"
        self.cursor = 0
        self.detail = False
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._render_needed = threading.Event()
        self._keys: "queue.Queue[str]" = queue.Queue()
        self._last_scan: datetime | None = None
        self._last_usage_scan: datetime | None = None
        self._session_errors: list[str] = []
        self._usage_errors: list[str] = []
        self._rows: list[SessionInfo] = []
        self._usage_rows: list[dict] = []
        self._pop_status: str | None = None
        self._scanning = False
        self._state = load_state()
        self._notes: dict[str, str] = self._state.setdefault("notes", {})
        self._colors: dict[str, str] = self._state.setdefault("colors", {})
        self._note_edit: str | None = None
        self._note_key: str | None = None
        self._render_needed.set()
        self._monitor = (
            Monitor(adapters, cfg)
            if all(isinstance(a, AgentAdapter) for a in adapters)
            else None
        )

    def scan(self) -> None:
        with ThreadPoolExecutor(max_workers=2) as pool:
            sessions = pool.submit(self.scan_sessions)
            usage = pool.submit(self.scan_usage)
            sessions.result()
            usage.result()

    @staticmethod
    def _session_key(session: SessionInfo) -> tuple:
        return session.key

    def scan_sessions(self) -> None:
        rows, errors = (
            self._monitor.scan()
            if self._monitor
            else collect_sessions(self.adapters, self.cfg)
        )
        for row in rows:
            row.branch = git_branch(Path(row.cwd)) if row.cwd else None
        rows.sort(key=lambda r: r.last_activity or utcnow(), reverse=True)
        with self._lock:
            selected = None
            if self.view == "terminals" and self._rows:
                index = min(self.cursor, len(self._rows) - 1)
                selected = self._session_key(self._rows[index])
            self._rows = rows
            self._session_errors = errors
            self._last_scan = utcnow()
            if self.view == "terminals":
                if selected is not None:
                    self.cursor = next(
                        (
                            i
                            for i, row in enumerate(rows)
                            if self._session_key(row) == selected
                        ),
                        self.cursor,
                    )
                self.cursor = max(0, min(self.cursor, len(rows) - 1)) if rows else 0
        self._render_needed.set()

    def scan_usage(self) -> None:
        usage_rows = collect_quotas(self.adapters, self.cfg)
        errors = []
        with self._lock:
            selected = None
            if self.view == "usage" and self._usage_rows:
                index = min(self.cursor, len(self._usage_rows) - 1)
                selected = self._usage_rows[index]["agent"]
            self._usage_rows = usage_rows
            self._usage_errors = errors
            self._last_usage_scan = utcnow()
            if self.view == "usage":
                if selected is not None:
                    self.cursor = next(
                        (
                            i
                            for i, row in enumerate(usage_rows)
                            if row["agent"] == selected
                        ),
                        self.cursor,
                    )
                self.cursor = (
                    max(0, min(self.cursor, len(usage_rows) - 1)) if usage_rows else 0
                )
        self._render_needed.set()

    def _clamp_cursor(self) -> None:
        with self._lock:
            if self.view == "usage":
                n = len(self._usage_rows)
            else:
                n = len(self._rows)
            self.cursor = max(0, min(self.cursor, n - 1)) if n else 0

    def _select(self, index: int, cursor: int) -> Text:
        prefix = "▸ " if index == cursor else "  "
        style = "bold" if index == cursor else ""
        return Text(prefix, style=style)

    def render(self) -> Group:
        if self.view == "usage":
            return self._render_usage()
        return self._render_terminals()

    def _header(self, title: str, summary: str) -> Panel:
        last_scan = self._last_scan
        keys = t("↑↓ · b blocked · ←→ · Enter · q")
        scan_txt = (
            t("scanning…")
            if self._scanning
            else t(
                "scan: {time}",
                time=last_scan.strftime("%H:%M:%S") if last_scan else "—",
            )
        )
        return Panel(
            t("[bold]termiX[/] — {title}  {summary}", title=title, summary=summary),
            box=box.ROUNDED,
            subtitle=f"{scan_txt} · {t('refresh {sec}s', sec=self.cfg.get('refresh_sec', 3))} · {keys}",
        )

    def _footer(self, note: str) -> Panel:
        return Panel(Text.from_markup(note, style="dim"), box=box.SIMPLE)

    def _render_terminals(self) -> Group:
        with self._lock:
            rows = list(self._rows)
            errors = list(self._session_errors + self._usage_errors)
            cursor = min(self.cursor, len(rows) - 1) if rows else 0

        table = Table(
            box=box.SIMPLE_HEAVY, expand=True, pad_edge=False, header_style="bold"
        )
        for col, min_w, wrap in [
            ("", 3, False),
            (t("agent"), 6, False),
            (t("status"), 10, False),
            (t("model"), 8, False),
            (t("directory"), 16, True),
        ]:
            table.add_column(
                col,
                justify="left",
                min_width=min_w,
                no_wrap=not wrap,
                overflow="fold",
            )

        working = blocked = 0
        for i, s in enumerate(rows):
            style, label = STATUS_STYLE.get(s.status, ("white", s.status))
            if s.status in ACTIVE and s.presence == "live":
                working += 1
            elif s.status in ATTENTION and s.presence == "live":
                blocked += 1
            status = Text(f"{STATUS_GLYPH.get(s.status, '·')} {t(label)}", style=style)
            if s.detail:
                status.append(f" ({s.detail[:12]})", style="dim")
            if s.presence == "unverified":
                status.append(" · " + t("Runtime association unverified"), style="dim")
            model = (s.model or "—")[:16]
            dir_txt = s.cwd or "—"
            if len(dir_txt) > 56:
                dir_txt = "…" + dir_txt[-55:]
            directory = Text(dir_txt, style="cyan")
            if s.branch:
                directory.append(f" [{s.branch}]", style="magenta")
            agent_txt = Text(s.agent, style=self._agent_style(s.agent))
            if self._notes.get(self._note_key_for(s)):
                agent_txt.append(" ✎", style="yellow")
            table.add_row(self._select(i, cursor), agent_txt, status, model, directory)

        if not rows:
            msg = (
                t("scanning for running agents…")
                if self._scanning and self._last_scan is None
                else t("open a terminal with codex / opencode / claude / kimi")
            )
            table.add_row("", "—", Text(t("no agents running"), style="dim"), "—", msg)

        total = len(rows)
        summary = t(
            "{working} active · {blocked} need you · {running} other recent",
            working=working,
            blocked=blocked,
            running=total - working - blocked,
        )
        header = self._header(t("open terminals"), summary)
        footer = self._footer(
            t(
                "Recent sessions · Enter locate · b attention · n note · c color · d details"
            )
        )
        parts: list = [header, table, footer]
        if self._note_edit is not None and rows:
            s = rows[cursor]
            prompt = Text.from_markup(
                t(
                    "✎ note for [bold]{agent}[/] ({cwd}): ",
                    agent=escape(s.agent),
                    cwd=escape(s.cwd or "—"),
                )
            )
            prompt.append(self._note_edit + "▌")
            parts.append(
                Panel(
                    prompt,
                    title=t("enter note"),
                    border_style="yellow",
                    subtitle=t("Enter save · Esc cancel"),
                    box=box.ROUNDED,
                )
            )
        if self._pop_status:
            parts.append(Text(f"↗ {self._pop_status}", style="blue"))
        if self.detail and rows:
            s = rows[cursor]
            parts.append(self._session_detail_panel(s))
        for err in errors:
            parts.append(Text(f"⚠ {err}", style="red"))
        return Group(*parts)

    def _session_detail_panel(self, s: SessionInfo) -> Panel:
        lines = [
            f"{_label('agent:')}[bold]{escape(s.agent)}[/]",
            f"{_label('status:')}{t(STATUS_STYLE.get(s.status, ('white', s.status))[1])}"
            + (f" ({escape(s.detail)})" if s.detail else ""),
            f"{_label('model:')}{escape(s.model) if s.model else '—'}",
            f"{_label('provider:')}{escape(s.provider) if s.provider else '—'}",
            f"{_label('directory:')}{escape(s.cwd) if s.cwd else '—'}",
            f"{_label('branch:')}{escape(s.branch) if s.branch else '—'}",
            f"{_label('pid:')}{s.pid or '—'}",
        ]
        if s.last_activity:
            age = (utcnow() - s.last_activity).total_seconds()
            lines.append(t("last act: {age} min ago", age=f"{age / 60:.1f}"))
        lines.append(f"{_label('session:')}{escape(s.source) if s.source else '—'}")
        note = self._notes.get(self._note_key_for(s))
        if note:
            lines.append(f"{_label('note:')}{escape(note)}")
        return Panel(
            "\n".join(lines),
            title=t("session detail"),
            border_style="blue",
            box=box.ROUNDED,
        )

    def _render_usage(self) -> Group:
        with self._lock:
            usage_rows = list(self._usage_rows)
            errors = list(self._session_errors + self._usage_errors)
            cursor = min(self.cursor, len(usage_rows) - 1) if usage_rows else 0

        table = Table(
            box=box.SIMPLE_HEAVY, expand=True, pad_edge=False, header_style="bold"
        )
        for col, min_w in [
            ("", 3),
            (t("agent"), 8),
            (t("provider"), 18),
            (t("plan"), 10),
            (t("limits"), 34),
        ]:
            table.add_column(
                col,
                justify="left" if col not in ("limits",) else "left",
                min_width=min_w,
                no_wrap=True,
                overflow="fold",
            )

        for i, row in enumerate(usage_rows):
            quota = row.get("quota")
            limits = Text()
            if quota and quota.windows:
                for wi, w in enumerate(quota.windows):
                    if wi:
                        limits.append("\n")
                    limits.append(_usage_window_cell(w, quota.limited))
            else:
                limits = Text(
                    t(quota.reason) if quota and quota.reason else t("Unavailable"),
                    style="dim",
                )
            if quota and quota.availability == "stale":
                limits.append(" · " + t("Stale"), style="yellow")
            plan = quota.plan if quota and quota.plan else "—"
            provider = quota.provider if quota else t("no subscription")
            cells = [
                self._select(i, cursor),
                Text(row["agent"], style=self._agent_style(row["agent"])),
                Text(provider, style="dim"),
                plan,
                limits,
            ]
            table.add_row(*cells)

        header = self._header(
            t("account usage"),
            t("official subscription quota per account — 5h / weekly / monthly"),
        )
        footer = self._footer(
            t(
                "80% / 90% are warning thresholds, not proof of a rate limit · ← sessions"
            )
        )
        parts: list = [header, table, footer]
        if self.detail and usage_rows:
            parts.append(self._usage_detail_panel(usage_rows[cursor]))
        for err in errors:
            parts.append(Text(f"⚠ {err}", style="red"))
        return Group(*parts)

    def _usage_detail_panel(self, row: dict) -> Panel:
        quota = row.get("quota")
        lines = [f"{_label('agent:')}[bold]{escape(row['agent'])}[/]"]
        if quota:
            lines.append(f"{_label('provider:')}{escape(quota.provider)}")
            if quota.plan:
                lines.append(f"{_label('plan:')}{escape(quota.plan)}")
            for w in quota.windows:
                line = f"{t(w.label):>10}:  {_limit_status(w.pct).plain}"
                if w.countdown:
                    line += f"  · {w.countdown}"
                lines.append(line)
        else:
            lines.append(
                f"{_label('provider:')}{t('no official subscription quota available')}"
            )
        return Panel(
            "\n".join(lines),
            title=t("quota breakdown"),
            border_style="blue",
            box=box.ROUNDED,
        )

    def _pop_terminal(self, s: SessionInfo) -> str:
        try:
            return t(TerminalLocator(self.cfg).focus(s).message)
        except Exception as exc:
            return t("failed to focus window: {err}", err=type(exc).__name__)

    def _note_key_for(self, s: SessionInfo) -> str:
        import json

        key = json.dumps(s.key, ensure_ascii=False)
        legacy = f"{s.agent}::{s.cwd or ''}"
        if key not in self._notes and legacy in self._notes:
            self._notes[key] = self._notes[legacy]
        return key

    def _start_note_edit(self) -> None:
        with self._lock:
            if self.view != "terminals" or not self._rows:
                return
            s = self._rows[min(self.cursor, len(self._rows) - 1)]
        self._note_key = self._note_key_for(s)
        self._note_edit = self._notes.get(self._note_key, "")

    def _save_note(self) -> None:
        if self._note_key is None:
            self._note_edit = None
            return
        text = (self._note_edit or "").strip()
        if text:
            self._notes[self._note_key] = text
        else:
            self._notes.pop(self._note_key, None)
        self._note_edit = None
        self._note_key = None
        save_state(self._state)

    def _cancel_note_edit(self) -> None:
        self._note_edit = None
        self._note_key = None

    def _cycle_agent_color(self) -> None:
        agent = None
        with self._lock:
            if self.view == "terminals" and self._rows:
                agent = self._rows[min(self.cursor, len(self._rows) - 1)].agent
            elif self.view == "usage" and self._usage_rows:
                index = min(self.cursor, len(self._usage_rows) - 1)
                agent = self._usage_rows[index]["agent"]
        if not agent:
            return
        cfg_colors = self.cfg.get("colors", {}) or {}
        self._colors[agent] = cycle_color(agent, self._colors, cfg_colors)
        save_state(self._state)

    def _agent_style(self, agent: str) -> str:
        cfg_colors = self.cfg.get("colors", {}) or {}
        return agent_color(agent, self._colors, cfg_colors)

    def _put_key(self, key) -> None:
        self._keys.put(key)
        self._render_needed.set()

    def _key_listener(self) -> None:
        try:
            import msvcrt
        except ImportError:
            return
        while not self._stop.is_set():
            if msvcrt.kbhit():
                ch = msvcrt.getch()
                if ch in (b"\x00", b"\xe0"):
                    ext = msvcrt.getch()
                    if self._note_edit is not None:
                        continue
                    if ext == b"H":
                        self._put_key("up")
                    elif ext == b"P":
                        self._put_key("down")
                    elif ext == b"K":
                        self._put_key("left")
                    elif ext == b"M":
                        self._put_key("right")
                elif self._note_edit is not None:
                    if ch in (b"\r", b"\n"):
                        self._put_key("note-save")
                    elif ch in (b"\x08", b"\x7f"):
                        self._put_key("note-bs")
                    elif ch == b"\x1b":
                        self._put_key("note-cancel")
                    elif 32 <= ch[0] < 127:
                        self._put_key(("note-char", chr(ch[0])))
                elif ch in (b"\r", b"\n"):
                    self._put_key("enter")
                elif ch in (b"q", b"Q"):
                    self._stop.set()
                    self._render_needed.set()
                    return
                elif ch in (b"n", b"N"):
                    self._put_key("note")
                elif ch in (b"c", b"C"):
                    self._put_key("color")
                elif ch in (b"d", b"D"):
                    self._put_key("d")
                elif ch in (b"b", b"B"):
                    self._put_key("blocked")
            time.sleep(0.02)

    def _handle_keys(self) -> bool:
        changed = False
        while True:
            try:
                key = self._keys.get_nowait()
            except queue.Empty:
                break
            if self._note_edit is not None:
                if key == "note-save":
                    self._save_note()
                elif key == "note-cancel":
                    self._cancel_note_edit()
                elif key == "note-bs":
                    self._note_edit = self._note_edit[:-1]
                elif isinstance(key, tuple) and key[0] == "note-char":
                    self._note_edit += key[1]
                changed = True
                continue
            if key == "up":
                with self._lock:
                    self.cursor = max(0, self.cursor - 1)
                changed = True
            elif key == "down":
                with self._lock:
                    n = (
                        len(self._usage_rows)
                        if self.view == "usage"
                        else len(self._rows)
                    )
                    self.cursor = min(n - 1, self.cursor + 1) if n else 0
                changed = True
            elif key == "left":
                with self._lock:
                    self.view = "terminals"
                    self.detail = False
                    self.cursor = 0
                changed = True
            elif key == "right":
                with self._lock:
                    self.view = "usage"
                    self.detail = False
                    self.cursor = 0
                changed = True
            elif key == "enter":
                with self._lock:
                    rows = list(self._rows)
                if self.view == "terminals" and rows:
                    self._pop_status = self._pop_terminal(
                        rows[min(self.cursor, len(rows) - 1)]
                    )
                else:
                    self.detail = not self.detail
                changed = True
            elif key == "d":
                self.detail = not self.detail
                changed = True
            elif key == "note":
                self._start_note_edit()
                changed = True
            elif key == "color":
                self._cycle_agent_color()
                changed = True
            elif key == "blocked" and self.view == "terminals":
                with self._lock:
                    blocked = [
                        i
                        for i, row in enumerate(self._rows)
                        if row.status == "blocked"
                        or (row.status in ATTENTION and row.presence == "live")
                    ]
                    if blocked:
                        self.cursor = next(
                            (i for i in blocked if i > self.cursor), blocked[0]
                        )
                        changed = True
        return changed

    def _scanner_loop(self) -> None:
        while not self._stop.is_set():
            self._scanning = True
            self._render_needed.set()
            try:
                self.scan_sessions()
            except Exception as e:
                with self._lock:
                    self._session_errors = [str(e)]
            self._scanning = False
            self._render_needed.set()
            try:
                interval = max(0.1, float(self.cfg.get("refresh_sec", 3)))
            except (TypeError, ValueError):
                interval = 3.0
            self._stop.wait(interval)

    def _quota_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.scan_usage()
            except Exception as e:
                with self._lock:
                    self._usage_errors = [str(e)]
                self._render_needed.set()
            try:
                interval = max(1.0, float(self.cfg.get("quota_refresh_sec", 120)))
            except (TypeError, ValueError):
                interval = 120.0
            self._stop.wait(interval)

    def run(self) -> None:
        self._scanning = True
        scanner = threading.Thread(target=self._scanner_loop, daemon=True)
        scanner.start()
        quota_scanner = threading.Thread(target=self._quota_loop, daemon=True)
        quota_scanner.start()
        listener = threading.Thread(target=self._key_listener, daemon=True)
        listener.start()
        with Live(self.render(), console=self.console, auto_refresh=False) as live:
            while not self._stop.is_set():
                signaled = self._render_needed.wait(0.05)
                if signaled:
                    self._render_needed.clear()
                changed = self._handle_keys()
                if signaled or changed:
                    live.update(self.render(), refresh=True)
        self.console.print(t("[dim]bye[/]"))


def run() -> None:
    cfg = load_config()
    from ..agents import ADAPTERS

    Dashboard(ADAPTERS, cfg).run()
