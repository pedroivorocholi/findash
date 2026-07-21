; Inno Setup script â€” wraps dist\aurantium.exe into aurantium-setup.exe.
; Build the exe first (see BUILD.md), then compile this with Inno Setup.

#define AppId "aurantium.terminal.desktop.1"

[Setup]
AppName=aurantium
AppVersion=1.4.3
AppPublisher=aurantium
DefaultDirName={autopf}\aurantium
DefaultGroupName=aurantium
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=aurantium-setup
SetupIconFile=aurantium.ico
UninstallDisplayIcon={app}\aurantium.exe
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern

[Files]
; One-folder build: copy dist\aurantium\ (aurantium.exe + _internal\...) into {app}.
Source: "dist\aurantium\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "aurantium.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: ".env.example"; DestDir: "{app}"; Flags: ignoreversion

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Icons]
Name: "{group}\aurantium"; Filename: "{app}\aurantium.exe"; IconFilename: "{app}\aurantium.ico"; AppUserModelID: "{#AppId}"
Name: "{group}\Uninstall aurantium"; Filename: "{uninstallexe}"
Name: "{userdesktop}\aurantium"; Filename: "{app}\aurantium.exe"; IconFilename: "{app}\aurantium.ico"; AppUserModelID: "{#AppId}"; Tasks: desktopicon

[Run]
; Interactive installs relaunch via this postinstall entry (skipped in silent).
; By the time the user reaches the Finished page the new files have settled, so
; a plain launch works. Silent auto-updates relaunch from [Code] with a delay.
Filename: "{app}\aurantium.exe"; WorkingDir: "{app}"; Description: "Launch aurantium"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  rc: Integer;
begin
  // Silent auto-updates (WinSparkle) must relaunch aurantium themselves, but the
  // relaunch has to WAIT: launched the instant the update finishes, the freshly
  // written numpy C-extension DLLs aren't fully in place yet and the app crashes
  // with "Importing the numpy C-extensions failed". A brief pause lets the file
  // replacement settle â€” a normal (slightly later) launch already works fine.
  if (CurStep = ssPostInstall) and WizardSilent() then
  begin
    Sleep(6000);
    Exec(ExpandConstant('{app}\aurantium.exe'), '', ExpandConstant('{app}'),
         SW_SHOW, ewNoWait, rc);
  end;
end;
