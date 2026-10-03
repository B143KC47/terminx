#ifndef AppVersion
  #define AppVersion "0.3.0"
#endif
#ifndef BundleDir
  #define BundleDir "..\dist\terminx"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

[Setup]
AppId={{DD4547AB-C77B-47F6-A668-D089BB6BE3D3}
AppName=termiX
AppVersion={#AppVersion}
AppPublisher=BlackCat
AppPublisherURL=https://github.com/B143KC47/terminx
AppSupportURL=https://github.com/B143KC47/terminx/issues
AppUpdatesURL=https://github.com/B143KC47/terminx/releases
DefaultDirName={localappdata}\Programs\termiX
DefaultGroupName=termiX
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#OutputDir}
OutputBaseFilename=terminx-{#AppVersion}-windows-x64-setup
LicenseFile=..\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\terminx-sidebar.exe
UsePreviousTasks=no
DisableProgramGroupPage=yes

[Tasks]
Name: "startup"; Description: "Start termiX when I sign in to Windows"
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\termiX"; Filename: "{app}\terminx-sidebar.exe"
Name: "{autodesktop}\termiX"; Filename: "{app}\terminx-sidebar.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\termiX"; ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"; Flags: uninsdeletekeyifempty uninsdeletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "termiX"; ValueData: """{app}\terminx-sidebar.exe"" --startup"; Flags: uninsdeletevalue; Check: StartAtSignIn
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "termiX"; Flags: deletevalue; Check: DoNotStartAtSignIn

[Run]
Filename: "{app}\terminx-sidebar.exe"; Description: "Open termiX"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\terminx-sidebar.exe"; Parameters: "--quit"; Flags: runhidden; RunOnceId: "CloseSidebar"

[Code]
var
  WasInstalled: Boolean;
  WasStartupEnabled: Boolean;

function InitializeSetup(): Boolean;
begin
  WasInstalled := RegValueExists(HKCU, 'Software\termiX', 'InstallPath');
  WasStartupEnabled := RegValueExists(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'termiX');
  Result := True;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpSelectTasks) and WasInstalled then
    WizardForm.TasksList.Checked[0] := WasStartupEnabled;
end;

function StartAtSignIn(): Boolean;
begin
  if WizardSilent and WasInstalled then
    Result := WasStartupEnabled
  else
    Result := WizardIsTaskSelected('startup');
end;

function DoNotStartAtSignIn(): Boolean;
begin
  Result := not StartAtSignIn;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    if not Exec(ExpandConstant('{app}\terminx.exe'), '--cleanup', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      RaiseException('Cannot start termiX hook removal. Keep the program files and retry.');
    if ResultCode <> 0 then
      RaiseException('Cannot remove termiX hooks. Correct the provider configuration and retry.');
  end;
end;
