<div align="center">

# 🖥️ termiX

**One terminal to watch them all.**

A live dashboard for your CLI coding agents — **Codex, OpenCode, Claude Code, Kimi** — showing what every agent is doing right now, in one terminal.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/platform-Windows-blueviolet)
![License](https://img.shields.io/badge/license-MIT-green)
![Version](https://img.shields.io/badge/version-0.1.0-orange)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ termiX — open terminals  1 working · 0 blocked · 2 running                  │
└─ scan: 15:43:07 · refresh 3s · ↑↓ select · ←→ view · Enter pop · n note · c ─┘
                                                                               
        agent      status                 model              directory        
 ───────────────────────────────────────────────────────────────────────────── 
 ▸      opencode   ● working              deepseek-v4-flas   C:\Users\you  \…
        codex      ■ blocked (waiting     gpt-5.6-sol        …\diffusion_rese…
                   423s)                                                       
        kimi       ○ idle                 kimi-k2-0711       …\site_rebuild    
```

</div>

---

## ✨ Features

- **Live terminal overview** — every agent session currently open on your machine:
  status (`● working` / `■ blocked` / `○ idle`), model in use, working directory, git branch
- **Pop into the real terminal** — `Enter` brings the selected session's terminal
  window to the foreground (Windows Terminal), resuming the exact same conversation
- **Account quota at a glance** — official subscription limits (5h / weekly / monthly)
  straight from the provider APIs: `OK` / `NEAR` / `HIT` + reset countdown
- **Per-terminal notes** — jot down what each agent is working on; notes persist
- **Per-agent colors** — auto-assigned palette, or cycle with `c` and save
- **Internationalized** — English & 简体中文 built in; language auto-detected from
  your system locale, override anytime in the config
- **Pluggable adapters** — adding a new CLI agent is ~30 lines

## 📦 Requirements

- Windows (Windows Terminal recommended) — macOS/Linux: status detection works,
  "pop into terminal" falls back to spawning a new window
- Python 3.10+
- One or more of: [Codex](https://github.com/openai/codex),
  [OpenCode](https://opencode.ai), [Claude Code](https://docs.claude.com),
  [Kimi Code](https://www.kimi.com/code)

## 🚀 Install

```powershell
pip install rich
git clone https://github.com/B143KC47/terminx.git
cd terminx
pip install -e .
```

Then run from anywhere:

```powershell
terminx              # live dashboard (q to quit)
terminx --once       # render a single frame and exit
```

## 🎮 Controls

| Key | Action |
|---|---|
| `↑` / `↓` | move cursor between sessions |
| `←` / `→` | switch between **terminals** view and **account usage** view |
| `Enter` | pop the selected terminal to the foreground (focus existing window, or open + resume a new one) |
| `n` | write a note for the selected terminal (Enter save · Esc cancel) |
| `c` | cycle the selected agent's color |
| `d` | toggle details panel |
| `q` | quit |

## 📊 What each view shows

### Open terminals

Only sessions that are **actually running right now** — stale session files are
filtered out by matching each session's working directory against live processes.

| column | meaning |
|---|---|
| agent | name, colored per agent; `✎` = has a note |
| status | `● working` (session file updated recently) · `■ blocked` (running, waiting on you — includes permission prompts) · `○ idle` |
| model | parsed from the agent's own session files |
| directory | working directory (+ git branch in magenta) |

### Account usage

Official subscription quota **only** — no local estimation, and your local model
configuration (e.g. a router/proxy setup) has no influence.

| status | meaning |
|---|---|
| `OK` | under 80% of the window |
| `NEAR` | 80–90% |
| `HIT` | ≥90% (you'll be cut off until reset) |

Sources per agent:

| agent | source | extra setup |
|---|---|---|
| codex | `chatgpt.com/backend-api/wham/usage` (reads `~/.codex/auth.json`) | none — works after `codex login` |
| claude | `api.anthropic.com/api/oauth/usage` | only when logged in via OAuth (`claude login`); proxied/router setups show "no official quota data" |
| kimi | `api.kimi.com/coding/v1/usages` | set `kimi_api_key` (create at [Kimi Code console](https://www.kimi.com/code/console) → API Keys) |
| opencode | none (BYO provider key) | — |

## ⚙️ Configuration

Create `~/.terminx.json` (or `~/.config/terminx/config.json`). Full example:
`terminx/config.example.json`.

```json
{
  "lang": "auto",
  "refresh_sec": 3,
  "working_threshold_sec": 60,
  "blocked_threshold_sec": 600,
  "show_recent_hours": 24,
  "max_rows_per_agent": 6,
  "colors": { "codex": "yellow", "claude": "magenta" },
  "kimi_api_key": "sk-kimi-...",
  "paths": {}
}
```

- `lang` — UI language: `"auto"` (detect from system locale) · `"en"` · `"zh_CN"`.
  You can also force it per-run: `set LANG=en_US && terminx`
- `colors` — fixed per-agent colors (otherwise auto-assigned; `c` cycles live)
- `kimi_api_key` — optional, enables official Kimi quota
- `paths` — override an agent's data directory, e.g. `{"codex": "D:/codex-data"}`

## 🌐 Adding a language

Translations live in `terminx/locales/<code>.json` as simple key→text maps, where
the key is the original English string. To add a language:

1. Copy `terminx/locales/zh_CN.json` to `terminx/locales/<code>.json`
2. Translate the values (keep `{placeholders}` and rich markup like `[bold]…[/]` intact)
3. Add the code to `SUPPORTED` in `terminx/i18n.py`
4. Set `"lang": "<code>"` in your config to try it

## 🔐 Privacy

- API tokens are read from your local auth files and used **only inside HTTP
  headers** — never printed, logged, displayed, or stored by termiX
- Notes and color choices are saved to `~/.config/terminx/state.json`
- No telemetry, no network calls except the official quota endpoints you enable

## 🧩 Adding a new agent (developers)

Create `terminx/agents/<name>.py` with an `AgentAdapter` subclass:

```python
from .base import AgentAdapter, SessionInfo, Quota

class MyAgent(AgentAdapter):
    name = "myagent"
    process_names = ["myagent"]

    def find_sessions(self, cfg) -> list[SessionInfo]:
        ...  # -> sessions with cwd, model, last_activity, resume_cmd

    def usage_records(self, since, cfg) -> list:
        ...  # optional, not used for quota display anymore

    def quota(self, cfg) -> Quota | None:
        ...  # optional — official quota from the provider's API
```

Register it in `terminx/agents/__init__.py`. Status detection, git branch, PID
resolution, and quota caching come free from the base class.

## 🏗️ Architecture

```
terminx/
├── agents/            # one adapter per CLI agent (codex, claude, opencode, kimi)
│   ├── base.py        # AgentAdapter ABC: sessions, status, resolve_pid
│   └── quota.py       # official quota fetchers (cached 120s)
├── core/              # processes (tasklist), git branch, win32 window-focus, state
├── i18n.py            # language detection + catalog loader
├── locales/           # translation catalogs (zh_CN.json; English is embedded)
└── ui/
    ├── dashboard.py   # rich Live TUI: key handling, views, notes, colors
    └── colors.py      # per-agent palette
```

Key design points:

- **Status truth** — a session is shown only when a live process exists in its
  exact working directory (`pid ↔ cwd` matching), so the count always equals
  what `tasklist` says
- **Responsive UI** — scanning runs in a background thread; keystrokes are
  handled every 50ms, so the UI never blocks on disk/network scans
- **Quota = official only** — provider APIs are the single source of truth

## 🧪 Development

```powershell
pip install -e . pyflakes
python -m pyflakes terminx   # lint
python -m unittest discover -s tests   # i18n sanity tests
python -m terminx --once     # smoke test
```

## 📄 License

[MIT](LICENSE)
