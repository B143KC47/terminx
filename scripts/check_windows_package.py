"""Check a real Windows installer with isolated application data."""

import argparse
import json
import os
import subprocess
import tempfile
import time
import uuid
import zipfile
from contextlib import nullcontext
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
INSTALL_KEY = r"Software\termiX"

UI_SETTINGS = r"""
Add-Type -AssemblyName UIAutomationClient,UIAutomationTypes
$applicationProcessId = PID_VALUE
$desired = DESIRED_VALUE
$root = [System.Windows.Automation.AutomationElement]::RootElement
$processCondition = [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::ProcessIdProperty,$applicationProcessId)
$checkboxCondition = [System.Windows.Automation.AndCondition]::new($processCondition,[System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::NameProperty,'Start termiX when I sign in to Windows'))
$checkbox = $null
for ($attempt = 0; $attempt -lt 40; $attempt++) {
  $checkbox = $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants,$checkboxCondition)
  if ($null -ne $checkbox) { break }
  Start-Sleep -Milliseconds 250
}
if ($null -eq $checkbox) { throw 'The installed startup control is absent' }
$toggle = $checkbox.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
$before = $toggle.Current.ToggleState -eq [System.Windows.Automation.ToggleState]::On
if ($before -ne $desired) { $toggle.Toggle() }
$saveCondition = [System.Windows.Automation.AndCondition]::new($processCondition,[System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::Button))
$save = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants,$saveCondition) | Where-Object { $_.Current.Name -match '^&?Save$' } | Select-Object -First 1
if ($null -eq $save) { throw 'The installed Save control is absent' }
$save.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
@{previous=$before;requested=$desired;settingsControl=$true} | ConvertTo-Json -Compress
"""


def registry_value(key, name):
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
            return winreg.QueryValueEx(handle, name)
    except FileNotFoundError:
        return None


def set_registry_value(key, name, value):
    import winreg

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE
    ) as handle:
        if value is None:
            try:
                winreg.DeleteValue(handle, name)
            except FileNotFoundError:
                pass
        else:
            winreg.SetValueEx(handle, name, 0, value[1], value[0])


def run(command, env, timeout=90):
    result = subprocess.run(
        command,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode:
        raise RuntimeError(
            f"Command failed: {command!r}\n{result.stdout}\n{result.stderr}"
        )
    return result


def close_sidebar(executable, env, process):
    run([str(executable), "--quit"], env)
    try:
        process.wait(timeout=35)
    except subprocess.TimeoutExpired:
        process.terminate()
        process.wait(timeout=10)
        raise


def settings(executable, env, enabled):
    process = subprocess.Popen(
        [str(executable), "--settings", "--exit-after", "35"], env=env
    )
    try:
        script = UI_SETTINGS.replace("PID_VALUE", str(process.pid)).replace(
            "DESIRED_VALUE", "$true" if enabled else "$false"
        )
        result = run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            env,
            timeout=30,
        )
        receipt = json.loads(result.stdout)
        time.sleep(0.3)
        return receipt
    finally:
        close_sidebar(executable, env, process)


def check(assets, ui):
    import winreg

    if registry_value(INSTALL_KEY, "InstallPath") is not None:
        raise RuntimeError(
            "An existing termiX installation prevents an isolated install check"
        )
    installers = list(assets.glob("*-windows-x64-setup.exe"))
    portable = list(assets.glob("*-windows-x64-portable.zip"))
    if len(installers) != 1 or len(portable) != 1:
        raise RuntimeError("The release needs one installer and one portable ZIP")
    old_startup = registry_value(RUN_KEY, "termiX")
    witness_name = "termiX-check-" + uuid.uuid4().hex
    witness = ("unrelated entry", winreg.REG_SZ)
    set_registry_value(RUN_KEY, witness_name, witness)
    results = {}
    uninstaller = None
    environment = None
    try:
        with nullcontext(
            tempfile.mkdtemp(prefix="package check ", dir=ROOT / "_artifacts")
        ) as directory:
            work = Path(directory).resolve()
            if not work.is_relative_to(ROOT / "_artifacts"):
                raise RuntimeError("The check directory is outside the workspace")
            state = work / "state"
            state.mkdir()
            config = work / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "lang": "en",
                        "kimi_start_server": False,
                        "paths": {
                            name: str(work / "providers" / name)
                            for name in ("codex", "claude", "kimi", "grok", "opencode")
                        },
                    }
                ),
                encoding="utf-8",
            )
            environment = dict(
                os.environ, TERMINX_STATE_DIR=str(state), TERMINX_CONFIG=str(config)
            )
            environment["PATH"] = (
                str(Path(os.environ["SystemRoot"]) / "System32")
                + os.pathsep
                + os.environ["SystemRoot"]
            )
            if ui:
                environment.pop("QT_QPA_PLATFORM", None)
            else:
                environment["QT_QPA_PLATFORM"] = "offscreen"
            extracted = work / "portable folder"
            with zipfile.ZipFile(portable[0]) as archive:
                for entry in archive.infolist():
                    if (
                        not (extracted / entry.filename)
                        .resolve()
                        .is_relative_to(extracted.resolve())
                    ):
                        raise RuntimeError(
                            "An archive entry leaves the extraction directory"
                        )
                archive.extractall(extracted)
            program = extracted / "terminx"
            version = run(
                [str(program / "terminx.exe"), "--version"], environment
            ).stdout.strip()
            results["version"] = version
            run([str(program / "terminx.exe"), "--once"], environment)
            results["portable_console_without_python_path"] = True
            handle = run(
                [
                    str(program / "terminx.exe"),
                    "--internal",
                    "terminx.core.runtime",
                    str(os.getpid()),
                ],
                environment,
            ).stdout.strip()
            int(handle)
            results["frozen_console_helper"] = True
            screenshot = work / "sidebar.png"
            run(
                [
                    str(program / "terminx-sidebar.exe"),
                    "--expanded",
                    "--screenshot",
                    str(screenshot),
                    "--exit-after",
                    "9",
                ],
                environment,
                timeout=45,
            )
            if not screenshot.exists() or screenshot.stat().st_size < 100:
                raise RuntimeError("The portable sidebar did not save a rendered image")
            results["portable_gui"] = True
            results["native_desktop"] = ui
            notes = state / "sidebar.json"
            saved = json.loads(notes.read_text(encoding="utf-8"))
            saved.setdefault("notes", {})["synthetic-note"] = "keep after uninstall"
            notes.write_text(json.dumps(saved), encoding="utf-8")
            installed = work / "installed folder"
            install_command = [
                str(installers[0]),
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                "/SP-",
                f"/DIR={installed}",
            ]
            run(install_command, environment)
            uninstaller = installed / "unins000.exe"
            executable = installed / "terminx.exe"
            sidebar = installed / "terminx-sidebar.exe"
            if not sidebar.is_file() or not uninstaller.is_file():
                raise RuntimeError("The installation files are incomplete")
            results["installed"] = True
            command = registry_value(RUN_KEY, "termiX")
            expected = f'"{sidebar}" --startup'
            if command is None or command[0] != expected:
                raise RuntimeError(
                    "The installer did not register the exact sidebar command"
                )
            if (
                run(
                    [str(executable), "--startup", "status"], environment
                ).stdout.strip()
                != "enabled"
            ):
                raise RuntimeError(
                    "The installed application disagrees with Windows startup state"
                )
            results["default_startup_enabled"] = True
            process = subprocess.Popen(command[0], env=environment)
            time.sleep(2)
            if process.poll() is not None:
                raise RuntimeError("The registered startup command exited unexpectedly")
            close_sidebar(sidebar, environment, process)
            results["registered_command_runs"] = True
            if ui:
                results["settings_disable"] = settings(sidebar, environment, False)
            else:
                run([str(executable), "--startup", "disable"], environment)
            if registry_value(RUN_KEY, "termiX") is not None:
                raise RuntimeError("Disable did not remove the startup value")
            run(install_command, environment)
            if registry_value(RUN_KEY, "termiX") is not None:
                raise RuntimeError("The update re-enabled startup")
            results["update_preserves_disabled"] = True
            if ui:
                results["settings_enable"] = settings(sidebar, environment, True)
            else:
                run([str(executable), "--startup", "enable"], environment)
            if registry_value(RUN_KEY, "termiX") is None:
                raise RuntimeError("Enable did not register the startup command")
            run(install_command, environment)
            if registry_value(RUN_KEY, "termiX")[0] != expected:
                raise RuntimeError("The update changed the enabled startup command")
            results["update_preserves_enabled"] = True
            run(
                [str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                environment,
            )
            uninstaller = None
            if (
                sidebar.exists()
                or executable.exists()
                or registry_value(RUN_KEY, "termiX") is not None
            ):
                raise RuntimeError(
                    "Uninstall left program files or startup registration"
                )
            results["uninstall_removes_program_and_startup"] = True
            if (
                json.loads(notes.read_text(encoding="utf-8"))["notes"]["synthetic-note"]
                != "keep after uninstall"
            ):
                raise RuntimeError("Uninstall changed user notes")
            results["notes_preserved"] = True
            if registry_value(RUN_KEY, witness_name) != witness:
                raise RuntimeError("An unrelated registry value changed")
            results["unrelated_registry_value_preserved"] = True
    finally:
        try:
            if uninstaller and uninstaller.exists():
                run(
                    [
                        str(uninstaller),
                        "/VERYSILENT",
                        "/SUPPRESSMSGBOXES",
                        "/NORESTART",
                    ],
                    environment,
                )
        finally:
            set_registry_value(RUN_KEY, "termiX", old_startup)
            set_registry_value(RUN_KEY, witness_name, None)
    (assets / f"terminx-{results['version']}-acceptance.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(results, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", required=True, type=Path)
    parser.add_argument(
        "--ui",
        action="store_true",
        help="Check settings through native Windows UI Automation",
    )
    args = parser.parse_args()
    if os.name != "nt":
        raise SystemExit("Windows is required")
    (ROOT / "_artifacts").mkdir(exist_ok=True)
    check(args.assets.resolve(), args.ui)


if __name__ == "__main__":
    main()
