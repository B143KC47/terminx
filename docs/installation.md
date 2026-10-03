# Installation

## Windows installer

Use the x64 installer on Windows 10 version 1809 or later, or Windows 11.
The desktop package includes Python, Qt, and the application libraries.
The desktop package does not include provider CLIs.

1. Download the setup EXE from the [release page](https://github.com/B143KC47/terminx/releases/latest).
2. Compare its SHA-256 value with `SHA256SUMS.txt`.
3. Open the setup EXE.
4. Select the installation folder.
5. Set the start at sign-in option as required.
6. Complete the installation.

The default folder is `%LOCALAPPDATA%\Programs\termiX`.
The installer does not request administrator access.
An update keeps the current start at sign-in setting.
The installer does not sign in to a provider account.

## Portable ZIP

1. Download the portable ZIP from the release page.
2. Extract the complete `terminx` folder.
3. Open `terminx-sidebar.exe`.

Keep the EXE files and `_internal` folder together.
The ZIP uses the same user data directory as the installer.
The ZIP does not enable start at sign-in by itself.
If you enable that setting, keep the folder at the same location.
Before you move or delete that folder, disable start at sign-in.
Before you delete a package with hooks, run `terminx.exe --cleanup`.

## Python wheel

Use Python 3.11 or later.
The desktop extra installs Qt.

```powershell
python -m pip install "terminx-0.3.0-py3-none-any.whl[desktop]"
terminx-sidebar
```

For the terminal dashboard, install the wheel without the desktop extra.

```powershell
python -m pip install terminx-0.3.0-py3-none-any.whl
terminx --once
terminx
```

## Source package

```powershell
python -m pip install "terminx-0.3.0.tar.gz[desktop]"
terminx-sidebar
```

The source package also contains the tests and release scripts.
The desktop sidebar and exact terminal focus require Windows.
The terminal dashboard has limited process support on other systems.
The release does not provide macOS or Linux desktop installers.

## Remove the installation

1. Quit termiX from its tray menu.
2. Open **Installed apps** in Windows Settings.
3. Select **termiX**.
4. Select **Uninstall**.

The uninstaller removes the program, shortcuts, start at sign-in entry, and termiX hooks.
It keeps notes and local data.
It keeps other provider hooks and later user edits.
For a Python installation, run `terminx --cleanup` before `python -m pip uninstall terminx`.

## Start after sign-in

The installer enables start at sign-in on the first installation unless you clear its option.
The application starts as a rail after user sign-in.
It does not run as a system service before sign-in.
Windows can delay startup applications.

Use **Settings and integrations** to change the setting.
The setting uses only the current user's `Run` registry value named `termiX`.
The application reads that value each time the settings dialog opens.
See the [Windows reference](https://learn.microsoft.com/en-us/windows/win32/setupapi/run-and-runonce-registry-keys).
