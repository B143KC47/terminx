# Windows interface demo

## Watch

[Download the MP4 video](https://github.com/B143KC47/terminx/releases/download/v0.3.0/terminx-0.3.0-demo.mp4).
[Download the English subtitles](https://github.com/B143KC47/terminx/releases/download/v0.3.0/terminx-0.3.0-demo.srt).
[Read the recording record](https://github.com/B143KC47/terminx/releases/download/v0.3.0/terminx-0.3.0-demo-recording.json).

The video includes these actions:

1. Open the rail.
2. Read session states.
3. Search for a session.
4. Read session details and public messages.
5. Save a local note.
6. Read account quota details.
7. Open the Windows startup setting.
8. View the terminal image from a successful focus check.

The subtitles also appear in the video image.
The MP4 uses H.264 at 1920 by 1080 pixels.

## Scope

The video captures live application widgets on Windows 11.
Session states, messages, token counts, and quotas use sample data.
The recording uses an independent local state directory.
It starts no provider workers and makes no model requests.

The terminal is a dedicated Windows Terminal window.
It runs a local demonstration process.
The sidebar uses its real process identity to focus that window.
A different UI Automation check reads the selected terminal text to verify the result.
The capture includes only this demonstration window and the application widgets.
The video joins recorded widget interactions with a still image from the successful focus check.
The recording record identifies each source and its validation scope.

The startup control reads the installed application's Windows setting.
The recording restores the control before it saves settings.
The actual startup setting stays enabled.

The recording environment has no available Windows Sandbox or Windows VM manager.
This video is a native Windows recording with sample data.
Windows VM acceptance remains untested.

## Record again

Use Windows, Windows Terminal, FFmpeg, and the installed termiX package.
Run from the source directory.
The script requires the desktop dependencies.

```powershell
uv sync --locked --extra desktop --extra dev
uv run python scripts/record_demo.py --output _artifacts/demo --installed-console "$env:LOCALAPPDATA\Programs\termiX\terminx.exe" --features-only
```

Select an empty output directory.
The script records the MP4, subtitles, preview image, and action record.
It closes its demonstration terminal after the recording.
It restores the mouse pointer.

To check terminal focus and capture first, add `--focus-only`.
To check the widget layout, add `--preview-only`.
Use `--ffmpeg` to select a different FFmpeg executable.
Windows can refuse foreground focus during automation.
The script reports that refusal as a failed check.
