# Release procedure

## Acceptance conditions

The release needs passing tests, static checks, document checks, and package checks.
The release needs a reviewed source diff and a change record.
The release needs installer, ZIP, wheel, source package, component record, and SHA-256 values.
It also includes matching third-party source archives and original license notices.
GitHub CI must pass for the published source commit.
The maintainer uses their own Git author identity.

## Build the Windows assets

Use 64-bit CPython 3.12 on Windows.
Install the official [Inno Setup compiler](https://jrsoftware.org/isdl.php).
The build script needs its `ISCC.exe` path.

```powershell
uv sync --locked --extra desktop --extra dev --extra package
uv run python scripts/package_windows.py --iscc "C:/Tools/Inno Setup/ISCC.exe"
```

The default output directory is `dist/release`.
Use an empty output directory for each build.
The build refuses to mix assets from different attempts.
The program version comes from `terminx/__init__.py`.
The build record gives the Python and package versions.

## Check the package

1. Extract the portable ZIP into a directory with spaces.
2. Run the console EXE with `--version` and `--once`.
3. Open the sidebar EXE without a local Python dependency.
4. Check the internal console helper.
5. Install the setup EXE for the current user.
6. Check the Start menu shortcut and registry command.
7. Disable start at sign-in in the settings dialog.
8. Install the update and check that startup stays disabled.
9. Enable start at sign-in in the settings dialog.
10. Remove the installation.
11. Check that program files and the startup entry are absent.
12. Check that notes and unrelated registry entries stay.

The package check preserves pre-existing local registry values.
The check uses a different application data directory.
Use a clean Windows machine for a full reboot acceptance check.

## Publish

1. Confirm the Git author name and email.
2. Commit the reviewed files.
3. Push the source commit to GitHub.
4. Wait for CI to finish.
5. Create a release tag for that commit.
6. Upload the verified assets and release notes.
7. Download the published checksum file.
8. Compare the uploaded asset sizes and hashes.

The release workflow prepares the assets when a version tag arrives.
Publishing an approved local build can use the same asset set.
Do not claim a package is tested when only its compilation completed.
