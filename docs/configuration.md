# Configuration

CLI output uses UTF-8, including redirected output.

The application reads the first existing configuration file in this order.

1. `~/.config/terminx/config.json`
2. `~/.terminx.json`

See [the example file](../terminx/config.example.json).
The `TERMINX_CONFIG` environment variable can select one other configuration file.

```json
{
  "lang": "zh_CN",
  "refresh_sec": 3,
  "quota_refresh_sec": 120,
  "show_recent_hours": 24,
  "max_rows_per_agent": 100,
  "kimi_start_server": true,
  "paths": {}
}
```

| Field | Meaning |
|---|---|
| `lang` | Interface language: `auto`, `en`, or `zh_CN` |
| `refresh_sec` | Seconds between process scans |
| `quota_refresh_sec` | Minimum seconds between account quota requests |
| `show_recent_hours` | History age limit in hours |
| `max_rows_per_agent` | Maximum history rows per provider |
| `kimi_start_server` | Permission to start an owned Kimi usage helper |
| `kimi_server_port` | Port for an existing loopback usage service |
| `paths` | Provider data home overrides |
| `state_dir` | Application data directory override |

An invalid field uses its default value.
The application does not replace an invalid file.
Environment variables can also select provider data homes.
These variables are `CODEX_HOME`, `CLAUDE_CONFIG_DIR`, `KIMI_CODE_HOME`, and `GROK_HOME`.
The old Codex sessions-directory override stays valid.
The `colors` field changes provider colors in the terminal dashboard.

## Local files

The default data directory is `~/.config/terminx`.
The `state_dir` setting or `TERMINX_STATE_DIR` environment variable can change it.

| File or directory | Data |
|---|---|
| `events.sqlite3` | Session metadata and quota metadata |
| `sidebar.json` | Panel position, settings, and session notes |
| `state.json` | Terminal dashboard notes and colors |
| `integrations/` | Hook installation records and original settings backups |
| `launches/` | Metadata for terminals opened by termiX |

The journal removes events older than seven days.
Original settings backups can contain existing provider secrets.
Keep these backups local.
The start at sign-in setting uses Windows settings, not a second JSON value.
