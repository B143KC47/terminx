# termiX

termiX shows open AI CLI sessions in a Windows sidebar.
It also has a terminal dashboard.
The supported CLIs are Codex, Claude Code, Kimi Code, Grok Build, and OpenCode.
The interface has English and Simplified Chinese text.

## Install

Use Windows 10 version 1809 or later, or Windows 11, on an x64 computer.
Install each required CLI.
Sign in to each CLI before you use its account data.
Install Windows Terminal to open new sessions from termiX.

1. Open the [release page](https://github.com/B143KC47/terminx/releases/latest).
2. Download `terminx-0.3.0-windows-x64-setup.exe`.
3. Open the installation file.
4. Complete the installation procedure.
5. Open **termiX** from the Start menu.

The installer contains Python and the desktop libraries.
It installs for the current user without administrator access.
It starts termiX after Windows sign-in by default.
For the ZIP, wheel, or source package, see [Installation](docs/installation.md).

## Change start at sign-in

1. Open the sidebar menu.
2. Select **Settings and integrations**.
3. Set **Start termiX when I sign in to Windows** to the required state.
4. Select **Save**.

Windows starts the sidebar after the user signs in.
An update keeps the selected setting.
The ZIP and Python packages do not change this setting during installation.

## Use the sidebar

The sidebar starts as a small rail.
Its number shows the count of open CLI terminals.
Select the rail to open the panel.
Drag the rail or panel header to change its position.

Select a session to focus its existing terminal.
The panel closes after a successful focus action.
Select the details icon to see the session ID, folder, state, public output, and notes.
Select **New** to start a CLI in a new Windows Terminal window.

| Control | Action |
|---|---|
| Session row | Focus the existing terminal |
| Details icon | Open session details |
| `Ctrl+F` | Select the search field |
| `Ctrl+N` | Open the new session dialog |
| `Esc` | Close the panel to the rail |
| Account quota | Show account limits |
| Tray menu | Open settings or quit |

## Session evidence

Codex uses live processes, open session files, and native log events.
Codex does not need termiX hooks.
Claude, Kimi, and Grok have optional hooks in **Settings and integrations**.
OpenCode can show an open terminal without an exact native session association.

termiX uses the CLI, data home, and native session ID to identify each session.
It uses the process creation time to reject a reused process ID.
It does not select a session from its folder or a similar terminal title.
It reports unknown state when evidence is missing.
Silence does not show that a task is complete.

Account quota, session token counts, and context usage are different values.
Missing quota is not zero quota.
An unsuccessful refresh keeps the last value with a stale marker.
See [CLI integrations](docs/integrations.md) for provider limits.

## Local data

termiX stores settings and notes in the current user's data directory.
It does not send telemetry.
The event journal stores metadata, not prompts, tool arguments, or credentials.
The details view reads public output from local CLI logs.
It excludes private reasoning and tool payloads.
See [Configuration](docs/configuration.md) and [Security](SECURITY.md).

## Development

Use Python 3.11 or later for a source installation.
Use the locked Python 3.12 environment for release builds.

```powershell
git clone https://github.com/B143KC47/terminx.git
cd terminx
uv sync --locked --extra desktop --extra dev --extra package
uv run python scripts/check_docs.py
uv run ruff check terminx tests scripts packaging
uv run python -m unittest discover -s tests
```

See [Development](docs/development.md), [Architecture](docs/architecture.md), and [Release procedure](docs/release.md).
The [review record](docs/review.md) gives findings and evidence limits.
The [validation record](docs/sidebar-validation.md) gives the observed checks.

## Documentation

Project English documentation uses ASD-STE100 Issue 9 writing rules.
The [writing policy](docs/writing-policy.md) defines the terms and review procedure.
Automatic checks cover selected rules.
They do not establish full dictionary or grammar compliance.
Upstream license text keeps its original wording.

## License

The project source uses the [MIT license](LICENSE).
The Windows packages include third-party license files.
See [Third-party software](docs/third-party.md).
