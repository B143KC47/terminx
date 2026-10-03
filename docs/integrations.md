# CLI integrations

## Evidence sources

| CLI | Session state source | Account quota source |
|---|---|---|
| Codex | Live process, exact open session file, native log events | `account/rateLimits/read` |
| Claude Code | Optional hooks and transcript completion events | Official statusline `rate_limits` |
| Kimi Code | Optional hooks and wire events | Local `/api/v1/oauth/usage` |
| Grok Build | Optional hooks and ACP events | Official CLI `/usage` command |
| OpenCode | Local logs and live process evidence | Configured provider |

Grok does not supply an external quota interface to termiX.
OpenCode does not supply one common quota interface for all providers.
Some CLI versions omit state events or quota fields.
The interface marks missing data as unknown or unavailable.

## Install optional hooks

1. Open **Settings and integrations**.
2. Select **Enable** beside Claude, Kimi, or Grok.
3. Restart that CLI.

The hooks collect metadata only.
The installer saves the original configuration and a removal record.
An existing Claude statusline keeps its command output.
Select **Remove** to remove only termiX entries.
Codex hook installation is disabled.
Old termiX Codex hook records can still use the removal procedure.

## Kimi usage helper

Kimi quota collection can start `kimi web --no-open` on a loopback address.
The helper does not open a browser or resume a session.
Set `kimi_start_server` to `false` to prevent this helper.
The application stops only helpers it started.
The local bearer goes only to the loopback service.
The HTTP client disables proxies and redirects for this request.

## Session and focus limits

Two sessions in the same folder stay different.
An unmatched terminal shows **Session association pending**.
It does not use the newest session file as an identity guess.

New terminals have a unique termiX marker.
Existing Windows Terminal panes use a temporary console title check.
The check restores the original title after it selects the pane.
Duplicate markers, protected terminals, and unsupported layouts stop the focus action.
A failed focus action does not open a replacement session.

The resume action requires a valid native session ID.
An already live session cannot use this action to start a duplicate.
Prompts, approvals, and interrupts stay controls in the official CLI.
