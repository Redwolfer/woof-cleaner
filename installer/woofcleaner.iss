; Inno Setup script for Woof Cleaner. Build with build.ps1, or:
;   ISCC.exe /DAppVersion=0.2.0 installer\woofcleaner.iss
; Expects dist\WoofCleaner.exe and dist\woof.exe (PyInstaller one-file builds) to exist.

#ifndef AppVersion
  #define AppVersion "0.2.0"
#endif
#define AppName "Woof Cleaner"
#define AppExe "WoofCleaner.exe"

[Setup]
; Never change AppId: upgrades and uninstall find the existing install through it.
AppId={{66FCCD7A-65DC-4EB1-A271-5AF7EB1CD1DE}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Woof Cleaner
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} Setup
DefaultDirName={autopf}\Woof Cleaner
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Per-user install by default (no admin needed); the wizard offers "install for all users" too.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
SetupIconFile=..\assets\woof.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/ultra64
SolidCompression=yes
OutputDir=..\dist
OutputBaseFilename=WoofCleaner-Setup-{#AppVersion}
ChangesEnvironment=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "addtopath"; Description: "Add the 'woof' command-line tool to PATH"; GroupDescription: "Command line:"; Flags: unchecked

[Files]
Source: "..\dist\WoofCleaner.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\woof.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme
Source: "..\data\rules.ini"; DestDir: "{app}"; DestName: "rules.example.ini"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
; In-app updates run setup with /SILENT /RELAUNCH=1: start the new version again afterwards (never elevated).
Filename: "{app}\{#AppExe}"; Flags: nowait runasoriginaluser; Check: IsRelaunch

[UninstallRun]
; Remove the scheduled-clean tasks / sign-in entry the app created, so nothing points at a deleted exe.
Filename: "{app}\woof.exe"; Parameters: "schedule --remove-all"; Flags: runhidden; RunOnceId: "RemoveSchedules"

[UninstallDelete]
; Created by the app at runtime next to the exe (optional overrides). User backups in %LOCALAPPDATA% are kept.
Type: files; Name: "{app}\rules.ini"

[Code]
const
  EnvUser = 'Environment';
  EnvMachine = 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment';

function PathRoot: Integer;
begin
  if IsAdminInstallMode then Result := HKEY_LOCAL_MACHINE else Result := HKEY_CURRENT_USER;
end;

function PathKey: String;
begin
  if IsAdminInstallMode then Result := EnvMachine else Result := EnvUser;
end;

procedure AddToPath(Dir: String);
var Paths: String;
begin
  if not RegQueryStringValue(PathRoot, PathKey, 'Path', Paths) then Paths := '';
  if Pos(';' + Uppercase(Dir) + ';', ';' + Uppercase(Paths) + ';') > 0 then Exit;
  if (Paths <> '') and (Copy(Paths, Length(Paths), 1) <> ';') then Paths := Paths + ';';
  RegWriteExpandStringValue(PathRoot, PathKey, 'Path', Paths + Dir);
end;

procedure RemoveFromPath(Dir: String);
var Paths: String; P: Integer;
begin
  if not RegQueryStringValue(PathRoot, PathKey, 'Path', Paths) then Exit;
  Paths := ';' + Paths + ';';
  P := Pos(';' + Uppercase(Dir) + ';', Uppercase(Paths));
  if P = 0 then Exit;
  Delete(Paths, P, Length(Dir) + 1);
  Paths := Copy(Paths, 2, Length(Paths) - 2);
  RegWriteExpandStringValue(PathRoot, PathKey, 'Path', Paths);
end;

// PyInstaller one-file apps run as a window-less launcher plus a child, so Restart Manager
// cannot close them gracefully and the locked exe would survive. Stop them explicitly.
procedure StopRunningApp;
var Code: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM WoofCleaner.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM woof.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Sleep(500);
end;

function IsRelaunch: Boolean;
begin
  Result := ExpandConstant('{param:RELAUNCH|0}') = '1';
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopRunningApp;
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('addtopath') then
    AddToPath(ExpandConstant('{app}'));
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  // usUninstall runs after the user confirmed, right before files are removed.
  if CurUninstallStep = usUninstall then
    StopRunningApp;
  if CurUninstallStep = usPostUninstall then
    RemoveFromPath(ExpandConstant('{app}'));
end;
