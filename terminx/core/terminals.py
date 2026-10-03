"""Fail-closed terminal navigation. A title resembling a directory is not identity."""

import json
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

import psutil

from .events import EventJournal, state_dir
from .integrations import atomic_write
from .monitor import runtime_alive
from .paths import configured_home
from .processes import normalize_path
from .runtime import external_popen, external_run, module_command


@dataclass
class FocusResult:
    status: str
    message: str


class TerminalLocator:
    def __init__(self, cfg=None):
        self.cfg = cfg or {}

    def focus(self, session):
        if os.name != "nt":
            return FocusResult("unsupported", "Terminal navigation requires Windows")
        binding = session.runtime
        if not binding:
            return FocusResult(
                "unsupported", "This terminal layout cannot be identified automatically"
            )
        if not runtime_alive(binding):
            return FocusResult("exited", "Session process has exited")
        if binding.launch_id and re.fullmatch(r"[a-f0-9]{32}", binding.launch_id):
            try:
                record = json.loads(
                    (
                        state_dir(self.cfg) / "launches" / f"{binding.launch_id}.json"
                    ).read_text(encoding="utf-8")
                )
                if record.get("agent") != session.agent or normalize_path(
                    record.get("data_root", "")
                ) != normalize_path(session.data_root):
                    return FocusResult(
                        "unsupported", "Terminal registration is unavailable"
                    )
                process = psutil.Process(binding.pid)
                chain = [process, *process.parents()]
                owner = next((p for p in chain if p.pid == record.get("pid")), None)
                if (
                    owner is None
                    or abs(owner.create_time() - record.get("created_at", 0)) >= 0.01
                ):
                    return FocusResult(
                        "unsupported", "Session is multiplexed inside another CLI"
                    )
                if (
                    record.get("session_id")
                    and record["session_id"] != session.session_id
                ):
                    return FocusResult(
                        "unsupported", "Session is multiplexed inside another CLI"
                    )
                journal = EventJournal(state_dir(self.cfg))
                if journal.path.exists():
                    with journal.connect() as db:
                        ids = db.execute(
                            "SELECT DISTINCT json_extract(body,'$.session_id') FROM events WHERE json_extract(body,'$.data.launch_id')=?",
                            (binding.launch_id,),
                        ).fetchall()
                    if ids and (len(ids) != 1 or ids[0][0] != session.session_id):
                        return FocusResult(
                            "unsupported", "Session is multiplexed inside another CLI"
                        )
                return self._focus_tag(binding.launch_id)
            except (OSError, ValueError, TypeError, psutil.Error):
                return FocusResult(
                    "unsupported", "Terminal registration is unavailable"
                )
        if binding.console_hwnd:
            from . import win32

            # Only traditional console windows. WT's hidden pseudo-window is not a tab.
            hwnd = binding.console_hwnd
            if win32.native_console_for_pid(hwnd, binding.pid):
                if win32.focus_window(hwnd):
                    return FocusResult("focused", "Focused existing terminal")
                return FocusResult("failed", "Windows did not grant foreground focus")
            owner = win32.pseudo_console_owner(hwnd, binding.pid)
            if owner:
                result = self._focus_owner(owner)
                if result.status == "identity_required":
                    from .console_identity import title_challenge

                    try:
                        with title_challenge(binding) as marker:
                            if marker:
                                result = self._focus_owner(owner, marker)
                    except (OSError, ValueError, subprocess.TimeoutExpired):
                        result = FocusResult(
                            "failed", "Terminal registration is unavailable"
                        )
                if not runtime_alive(binding):
                    return FocusResult("exited", "Session process has exited")
                return (
                    result
                    if result.status != "identity_required"
                    else FocusResult(
                        "unsupported",
                        "This terminal layout cannot be identified automatically",
                    )
                )
        return FocusResult(
            "unsupported",
            "Existing Windows Terminal tabs and panes require a verified automatic identity",
        )

    def _focus_owner(self, owner, marker=""):
        script = _UIA_OWNER_FOCUS.replace("__OWNER__", str(int(owner))).replace(
            "__MARKER__", marker
        )
        try:
            result = external_run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            code = (
                result.stdout.strip().splitlines()[-1]
                if result.stdout.strip()
                else "unsupported"
            )
        except (OSError, subprocess.TimeoutExpired):
            code = "failed"
        if code not in {
            "focused",
            "identity_required",
            "unsupported",
            "ambiguous",
            "failed",
        }:
            code = "failed"
        return FocusResult(
            code,
            "Focused existing terminal"
            if code == "focused"
            else "Windows did not grant foreground focus"
            if code == "failed"
            else "This terminal layout cannot be identified automatically",
        )

    def _focus_tag(self, launch_id):
        # Identity is generated at launch and pinned as the starting title. No directory/title guessing.
        script = _UIA_FOCUS.replace("__TAG__", "[tx:" + launch_id + "]")
        try:
            result = external_run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.TimeoutExpired):
            return FocusResult("failed", "Terminal registration is unavailable")
        code = (
            result.stdout.strip().splitlines()[-1]
            if result.stdout.strip()
            else "unsupported"
        )
        return FocusResult(
            code if code in {"focused", "ambiguous", "failed"} else "unsupported",
            "Focused existing terminal"
            if code == "focused"
            else "Target could not be uniquely verified; no duplicate session opened",
        )


_UIA_OWNER_FOCUS = r"""
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public class TxOwner { [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h); [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h,int n); [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow(); }'
$handle = [IntPtr]__OWNER__
$marker = '__MARKER__'
$root = [System.Windows.Automation.AutomationElement]::FromHandle($handle)
if ($null -eq $root -or $root.Current.ClassName -ne 'CASCADIA_HOSTING_WINDOW_CLASS') { Write-Output 'unsupported'; exit }
$tabCondition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::TabItem)
$paneCondition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ClassNameProperty,'TermControl')
$tabs = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants,$tabCondition)
$panes = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants,$paneCondition)
$target = $null
$original = $null
foreach ($tab in $tabs) {
  if ($tab.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Current.IsSelected) { $original = $tab }
}
if ($marker -eq '') {
  if ($tabs.Count -ne 1 -or $panes.Count -ne 1) { Write-Output 'identity_required'; exit }
  $target = $panes[0]
} else {
  $matches = @($panes | Where-Object { $_.Current.HelpText.Contains($marker) -or $_.Current.Name.Contains($marker) })
  if ($matches.Count -gt 1) { Write-Output 'ambiguous'; exit }
  if ($matches.Count -eq 1) { $target = $matches[0] }
  if ($null -eq $target -and $tabs.Count -le 24) {
    foreach ($tab in $tabs) {
      $tab.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select()
      Start-Sleep -Milliseconds 35
      $panes = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants,$paneCondition)
      $matches = @($panes | Where-Object { $_.Current.HelpText.Contains($marker) -or $_.Current.Name.Contains($marker) })
      if ($matches.Count -gt 1) {
        if ($null -ne $original) { $original.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select() }
        Write-Output 'ambiguous'; exit
      }
      if ($matches.Count -eq 1) { $target = $matches[0]; break }
    }
  }
  if ($null -eq $target) {
    if ($null -ne $original) { $original.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select() }
    Write-Output 'unsupported'; exit
  }
}
[void][TxOwner]::ShowWindow($handle,9)
[void][TxOwner]::SetForegroundWindow($handle)
$target.SetFocus()
for ($attempt = 0; $attempt -lt 12; $attempt++) {
  $focused = [System.Windows.Automation.AutomationElement]::FocusedElement
  if (([TxOwner]::GetForegroundWindow() -eq $handle) -and (($focused.GetRuntimeId() -join '.') -eq ($target.GetRuntimeId() -join '.'))) { Write-Output 'focused'; exit }
  Start-Sleep -Milliseconds 40
}
Write-Output 'failed'
"""


_UIA_FOCUS = r"""
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public class TxFocus { [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h); [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h,int n); [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow(); }'
$tag = '__TAG__'
$targets = @()
$topWindows = [System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children,[System.Windows.Automation.Condition]::TrueCondition)
foreach ($window in $topWindows) {
  if ($window.Current.ClassName -ne 'CASCADIA_HOSTING_WINDOW_CLASS') { continue }
  $condition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::TabItem)
  $tabs = $window.FindAll([System.Windows.Automation.TreeScope]::Descendants,$condition)
  foreach ($tab in $tabs) {
    if ($tab.Current.Name.Contains($tag)) { $targets += @{Window=$window; Tab=$tab; Handle=$window.Current.NativeWindowHandle} }
  }
}
if ($targets.Count -ne 1) { Write-Output 'ambiguous'; exit }
$target = $targets[0]
$pattern = $target.Tab.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern)
$pattern.Select()
$condition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ClassNameProperty,'TermControl')
$panes = $target.Window.FindAll([System.Windows.Automation.TreeScope]::Descendants,$condition)
$matches = @($panes | Where-Object { $_.Current.Name.Contains($tag) })
if ($matches.Count -ne 1) { Write-Output 'unsupported'; exit }
[void][TxFocus]::ShowWindow($target.Handle,9)
[void][TxFocus]::SetForegroundWindow($target.Handle)
$matches[0].SetFocus()
# UIA focus and compositor foreground updates can complete on the next message turn.
for ($attempt = 0; $attempt -lt 12; $attempt++) {
  $focused = [System.Windows.Automation.AutomationElement]::FocusedElement
  if (([TxFocus]::GetForegroundWindow() -eq $target.Handle) -and (($focused.GetRuntimeId() -join '.') -eq ($matches[0].GetRuntimeId() -join '.'))) { Write-Output 'focused'; exit }
  Start-Sleep -Milliseconds 40
}
Write-Output 'failed'
"""


def launch_session(agent, cwd, cfg=None, session=None):
    if os.name != "nt" or not shutil.which("wt"):
        raise RuntimeError("Windows Terminal is not installed")
    if agent not in {"codex", "claude", "kimi", "grok", "opencode"} or not shutil.which(
        agent
    ):
        raise RuntimeError("CLI is not installed")
    folder = Path(cwd).resolve(strict=True)
    if not folder.is_dir():
        raise ValueError("Select a working directory")
    if session and session.runtime and runtime_alive(session.runtime):
        raise RuntimeError(
            "Session is already running; resume would create a duplicate"
        )
    command = [agent]
    if session:
        if not session.session_id or not re.fullmatch(
            r"[A-Za-z0-9_-]+", session.session_id
        ):
            raise ValueError("A valid native session ID is required")
        flag = {
            "codex": "resume",
            "claude": "--resume",
            "kimi": "--session",
            "grok": "--resume",
            "opencode": "--session",
        }[agent]
        command.extend([flag, session.session_id])
    identifier = uuid.uuid4().hex
    directory = state_dir(cfg)
    root = (
        session.data_root
        if session and session.data_root
        else str(configured_home(agent, cfg))
    )
    record = {
        "agent": agent,
        "cwd": str(folder),
        "command": command,
        "data_root": root,
        "session_id": session.session_id if session else "",
    }
    atomic_write(directory / "launches" / f"{identifier}.json", json.dumps(record))
    title = f"{agent} · {folder.name} [tx:{identifier}]"
    external_popen(
        [
            shutil.which("wt"),
            "-w",
            "new",
            "new-tab",
            "--title",
            title,
            "--suppressApplicationTitle",
            "--startingDirectory",
            str(folder),
            *module_command("terminx.launch", identifier, str(directory)),
        ],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return identifier
