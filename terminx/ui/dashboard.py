import queue
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..agents.base import AgentAdapter, SessionInfo
from ..config import load_config
from ..core.gitutil import git_branch
from ..core.state import load_state, save_state
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


def _limit_status(pct: float | None, hit: bool = False) -> Text:
    if hit:
        return Text("HIT", style="bold red")
    if pct is None:
        return Text(t("n/a"), style="dim")
    if pct >= 90:
        label, style = "HIT", "bold red"
    elif pct >= 80:
        label, style = "NEAR", "yellow"
    else:
        label, style = "OK", "green"
    return Text(f"{label} {pct:.0f}%", style=style)


def _usage_window_cell(win) -> Text:
    t_row = Text()
    t_row.append(f"{t(win.label)}: ")
    t_row.append(_limit_status(win.pct))
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
        self._keys: "queue.Queue[str]" = queue.Queue()
        self._last_scan: datetime | None = None
        self._errors: list[str] = []
        self._rows: list[SessionInfo] = []
        self._usage_rows: list[dict] = []
        self._pop_status: str | None = None
        self._scanning = False
        self._state = load_state()
        self._notes: dict[str, str] = self._state.setdefault("notes", {})
        self._colors: dict[str, str] = self._state.setdefault("colors", {})
        self._note_edit: str | None = None
        self._note_key: str | None = None

    def scan(self) -> None:
        rows: list[SessionInfo] = []
        usage_rows: list[dict] = []
        errors: list[str] = []

        def scan_adapter(adapter: AgentAdapter) -> tuple[list[SessionInfo], dict, list[str]]:
            try:
                sessions = adapter.sessions(self.cfg)
                for s in sessions:
                    s.branch = git_branch(Path(s.cwd)) if s.cwd else None
                quota = adapter.quota(self.cfg)
                usage_row = {
                    "agent": adapter.name,
                    "quota": quota,
                }
                live = [s for s in sessions if s.status != "offline"]
                return live, usage_row, []
            except Exception as e:
                return [], {}, [f"{adapter.name}: {e}"]

        with ThreadPoolExecutor(max_workers=len(self.adapters)) as pool:
            results = list(pool.map(scan_adapter, self.adapters))
        for live, usage_row, errs in results:
            rows.extend(live)
            if usage_row:
                usage_rows.append(usage_row)
            errors.extend(errs)
        rows.sort(key=lambda r: (r.last_activity or utcnow()), reverse=True)
        with self._lock:
            self._rows = rows
            self._usage_rows = usage_rows
            self._errors = errors
            self._last_scan = utcnow()
        self._clamp_cursor()

    def _clamp_cursor(self) -> None:
        with self._lock:
            if self.view == "usage":
                n = len(self._usage_rows)
            else:
                n = len(self._rows)
        self.cursor = max(0, min(self.cursor, n - 1)) if n else 0

    def _select(self, row_count: int, index: int) -> Text:
        prefix = "▸ " if index == self.cursor else "  "
        style = "bold" if index == self.cursor else ""
        return Text(prefix, style=style)

    def render(self) -> Group:
        if self.view == "usage":
            return self._render_usage()
        return self._render_terminals()

    def _header(self, title: str, summary: str) -> Panel:
        last_scan = self._last_scan
        keys = t("↑↓ select · ←→ view · Enter pop · n note · c color · d details · q quit")
        scan_txt = t("scanning…") if self._scanning else t(
            "scan: {time}",
            time=last_scan.strftime("%H:%M:%S") if last_scan else "—",
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
            errors = list(self._errors)

        table = Table(box=box.SIMPLE_HEAVY, expand=True, pad_edge=False, header_style="bold")
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
            if s.status == "working":
                working += 1
            elif s.status == "blocked":
                blocked += 1
            status = Text(f"{STATUS_GLYPH.get(s.status, '·')} {t(label)}", style=style)
            if s.detail:
                status.append(f" ({s.detail[:12]})", style="dim")
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
            table.add_row(self._select(len(rows), i), agent_txt, status, model, directory)

        if not rows:
            msg = (
                t("scanning for running agents…")
                if self._scanning and self._last_scan is None
                else t("open a terminal with codex / opencode / claude / kimi")
            )
            table.add_row("", "—", Text(t("no agents running"), style="dim"), "—", msg)

        total = len(rows)
        summary = t(
            "[green]{working} working[/] · [yellow]{blocked} blocked[/] · [cyan]{running} running[/]",
            working=working,
            blocked=blocked,
            running=total - working - blocked,
        )
        header = self._header(t("open terminals"), summary)
        footer = self._footer(
            t("only sessions open right now · [bold]Enter[/] = pop · [bold]n[/] = note · [bold]c[/] = color · [bold]d[/] = details")
        )
        parts: list = [header, table, footer]
        if self._note_edit is not None and rows:
            s = rows[self.cursor]
            prompt = t(
                "✎ note for [bold]{agent}[/] ({cwd}): ",
                agent=s.agent,
                cwd=s.cwd or "—",
            ) + self._note_edit + "▌"
            parts.append(
                Panel(
                    Text.from_markup(prompt),
                    title=t("enter note"),
                    border_style="yellow",
                    subtitle=t("Enter save · Esc cancel"),
                    box=box.ROUNDED,
                )
            )
        if self._pop_status:
            parts.append(Text(f"↗ {self._pop_status}", style="blue"))
        if self.detail and rows:
            s = rows[self.cursor]
            parts.append(self._session_detail_panel(s))
        for err in errors:
            parts.append(Text(f"⚠ {err}", style="red"))
        return Group(*parts)

    def _session_detail_panel(self, s: SessionInfo) -> Panel:
        lines = [
            f"{_label('agent:')}[bold]{s.agent}[/]",
            f"{_label('status:')}{t(STATUS_STYLE.get(s.status, ('white', s.status))[1])}"
            + (f" ({s.detail})" if s.detail else ""),
            f"{_label('model:')}{s.model or '—'}",
            f"{_label('provider:')}{s.provider or '—'}",
            f"{_label('directory:')}{s.cwd or '—'}",
            f"{_label('branch:')}{s.branch or '—'}",
            f"{_label('pid:')}{s.pid or '—'}",
        ]
        if s.last_activity:
            age = (utcnow() - s.last_activity).total_seconds()
            lines.append(t("last act: {age} min ago", age=f"{age / 60:.1f}"))
        lines.append(f"{_label('session:')}{s.source or '—'}")
        note = self._notes.get(self._note_key_for(s))
        if note:
            lines.append(f"{_label('note:')}{note}")
        return Panel(
            "\n".join(lines),
            title=t("session detail"),
            border_style="blue",
            box=box.ROUNDED,
        )

    def _render_usage(self) -> Group:
        with self._lock:
            usage_rows = list(self._usage_rows)
            errors = list(self._errors)

        table = Table(box=box.SIMPLE_HEAVY, expand=True, pad_edge=False, header_style="bold")
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
                for w in quota.windows:
                    limits.append(_usage_window_cell(w))
                    limits.append("\n")
                limits = Text.from_markup(limits.plain.rstrip("\n"))
            else:
                limits = Text(t("no official quota data (no subscription / api key)"), style="dim")
            plan = quota.plan if quota and quota.plan else "—"
            provider = quota.provider if quota else t("no subscription")
            cells = [
                self._select(len(usage_rows), i),
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
            t("OK <80% · NEAR 80–90% · HIT ≥90% — official provider APIs only · [bold]←[/] = terminals view")
        )
        parts: list = [header, table, footer]
        if self.detail and usage_rows:
            parts.append(self._usage_detail_panel(usage_rows[self.cursor]))
        for err in errors:
            parts.append(Text(f"⚠ {err}", style="red"))
        return Group(*parts)

    def _usage_detail_panel(self, row: dict) -> Panel:
        quota = row.get("quota")
        lines = [f"{_label('agent:')}[bold]{row['agent']}[/]"]
        if quota:
            lines.append(f"{_label('provider:')}{quota.provider}")
            if quota.plan:
                lines.append(f"{_label('plan:')}{quota.plan}")
            for w in quota.windows:
                line = f"{t(w.label):>10}:  {_limit_status(w.pct).plain}"
                if w.countdown:
                    line += f"  · {w.countdown}"
                lines.append(line)
        else:
            lines.append(f"{_label('provider:')}{t('no official subscription quota available')}")
        return Panel(
            "\n".join(lines),
            title=t("quota breakdown"),
            border_style="blue",
            box=box.ROUNDED,
        )

    def _pop_terminal(self, s: SessionInfo) -> str:
        if not s.cwd or not Path(s.cwd).exists():
            return t("no working directory — cannot open")
        try:
            from ..core.win32 import find_terminal_window, focus_window, pid_cwd_matches
        except ImportError:
            find_terminal_window = focus_window = pid_cwd_matches = None
        folder = Path(s.cwd).name
        if find_terminal_window:
            pid = s.pid if pid_cwd_matches(s.pid, s.cwd) else None
            hwnd = find_terminal_window(strong=[folder], weak=[s.agent], agent_pid=pid)
            if hwnd:
                try:
                    focus_window(hwnd)
                    return t("focused existing {agent} window ({folder})", agent=s.agent, folder=folder)
                except Exception as e:
                    return t("failed to focus window: {err}", err=e)
        wt = _find_wt()
        if not wt:
            return t("windows terminal (wt) not found")
        cmd = s.resume_cmd or [s.agent]
        try:
            subprocess.Popen(
                [wt, "-w", "new", "-d", s.cwd, *cmd],
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            return t("popped {agent} → {cwd}", agent=s.agent, cwd=s.cwd)
        except Exception as e:
            return t("failed to open terminal: {err}", err=e)

    def _note_key_for(self, s: SessionInfo) -> str:
        return f"{s.agent}::{s.cwd or ''}"

    def _start_note_edit(self) -> None:
        if self.view != "terminals" or not self._rows:
            return
        s = self._rows[self.cursor]
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
        if self.view == "terminals" and self._rows:
            agent = self._rows[self.cursor].agent
        elif self.view == "usage" and self._usage_rows:
            agent = self._usage_rows[self.cursor]["agent"]
        if not agent:
            return
        cfg_colors = self.cfg.get("colors", {}) or {}
        self._colors[agent] = cycle_color(agent, self._colors, cfg_colors)
        save_state(self._state)

    def _agent_style(self, agent: str) -> str:
        cfg_colors = self.cfg.get("colors", {}) or {}
        return agent_color(agent, self._colors, cfg_colors)

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
                        self._keys.put("up")
                    elif ext == b"P":
                        self._keys.put("down")
                    elif ext == b"K":
                        self._keys.put("left")
                    elif ext == b"M":
                        self._keys.put("right")
                elif self._note_edit is not None:
                    if ch in (b"\r", b"\n"):
                        self._keys.put("note-save")
                    elif ch in (b"\x08", b"\x7f"):
                        self._keys.put("note-bs")
                    elif ch == b"\x1b":
                        self._keys.put("note-cancel")
                    elif 32 <= ch[0] < 127:
                        self._keys.put(("note-char", chr(ch[0])))
                elif ch in (b"\r", b"\n"):
                    self._keys.put("enter")
                elif ch in (b"q", b"Q"):
                    self._stop.set()
                    return
                elif ch in (b"n", b"N"):
                    self._keys.put("note")
                elif ch in (b"c", b"C"):
                    self._keys.put("color")
                elif ch in (b"d", b"D"):
                    self._keys.put("d")
            time.sleep(0.02)

    def _handle_keys(self) -> None:
        if self.view == "usage":
            n = len(self._usage_rows)
        else:
            n = len(self._rows)
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
                continue
            if key == "up":
                self.cursor = max(0, self.cursor - 1)
            elif key == "down":
                self.cursor = min(n - 1, self.cursor + 1) if n else 0
            elif key == "left":
                self.view = "terminals"
                self.detail = False
                self.cursor = 0
            elif key == "right":
                self.view = "usage"
                self.detail = False
                self.cursor = 0
            elif key == "enter":
                if self.view == "terminals" and self._rows:
                    self._pop_status = self._pop_terminal(self._rows[self.cursor])
                else:
                    self.detail = not self.detail
            elif key == "d":
                self.detail = not self.detail
            elif key == "note":
                self._start_note_edit()
            elif key == "color":
                self._cycle_agent_color()

    def _scanner_loop(self) -> None:
        while not self._stop.is_set():
            self._scanning = True
            try:
                self.scan()
            except Exception as e:
                with self._lock:
                    self._errors = [str(e)]
            self._scanning = False
            time.sleep(self.cfg.get("refresh_sec", 3))

    def run(self) -> None:
        self._scanning = True
        scanner = threading.Thread(target=self._scanner_loop, daemon=True)
        scanner.start()
        listener = threading.Thread(target=self._key_listener, daemon=True)
        listener.start()
        with Live(self.render(), console=self.console, refresh_per_second=10) as live:
            while not self._stop.is_set():
                self._handle_keys()
                live.update(self.render())
                time.sleep(0.05)
        self.console.print(t("[dim]bye[/]"))


def run() -> None:
    cfg = load_config()
    from ..agents import ADAPTERS
    Dashboard(ADAPTERS, cfg).run()
