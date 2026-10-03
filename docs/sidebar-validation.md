# Windows validation record

## Previous checks

The previous local validation date was 2026-10-02.
It used Windows Terminal 1.24.11911.0 and PySide6 6.9.2.
It used Codex 0.160.0 and Claude Code 2.1.286.
It also used Kimi Code 0.38.0 and Grok Build 1.0.46.

The previous test suite contained 103 tests.
The previous native checks covered single windows, inactive tabs, split panes, and duplicate markers.
Duplicate markers caused the focus action to stop without a success claim.
The previous desktop checks covered scale factors 1.0, 1.5, 1.875, and 2.0.

## Current checks

The release validation date is 2026-10-03.
The release uses a different CPython environment.
The release checks include the test suite, static checks, document checks, and package checks.
The release assets contain SHA-256 values and a software component record.
The [review record](review.md) gives the current results.
The local suite passed 132 tests without skipped desktop tests.
The package check used the real Windows desktop and its UI Automation interface.
It executed the registered sign-in command without a Python directory on PATH.
It changed startup through the installed Settings controls.
It checked updates with startup disabled and enabled.
It checked removal while preserving notes and other registry entries.

## Native checks

`tests/native_acceptance.py` opens dedicated Windows Terminal probe sessions.
`tests/native_existing_acceptance.py` checks exact pane focus for tabs and split panes.
`tests/sidebar_native_controls.py` checks panel controls with native mouse input.
`tests/sidebar_visual.py` saves native Qt images from fixture data.
These checks do not run paid model inference.
The probe checks stop only their own processes.

## Evidence limits

Fixture tests verify the inspected log formats.
They do not prove compatibility with every future CLI version.
Windows can reject a background focus request.
Protected or elevated terminals can prevent process or UI access.
The application reports these failures in the panel.
The build does not include code signing.
Windows can show a publisher warning for the installer.
