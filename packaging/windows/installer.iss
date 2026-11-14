; Magpie for Windows: the installer (Inno Setup 6). Built by build_app.py on Windows:
;   ISCC /DAppVersion=x.y.z /DSourceDir=dist\Magpie installer.iss
;
; Installs for the current person only, into their own Programs folder, so it never asks for
; an administrator password. A Start menu entry, and an entry in Settings, Apps to uninstall.
; Uninstalling leaves settings and libraries alone. WinSparkle runs this same installer quietly
; to update (see rplmaker/updates.py).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\dist\Magpie"
#endif

[Setup]
; Never change AppId: it's how Windows knows a new version replaces the old one, whatever the
; app ends up being called.
AppId={{6b1f4b3e-2c7a-4f0e-9d7c-0d8e2a5b9c41}
AppName=Magpie
AppVersion={#AppVersion}
AppVerName=Magpie {#AppVersion}
AppPublisher=Matthew Whitaker
AppPublisherURL=https://github.com/Matthew2244/rpl-maker
AppSupportURL=https://github.com/Matthew2244/rpl-maker/issues
DefaultDirName={localappdata}\Programs\Magpie
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=Magpie-Setup
SetupIconFile=..\..\assets\icon.ico
UninstallDisplayIcon={app}\Magpie.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Put Magpie on the desktop"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[InstallDelete]
; A new version may drop files the old one had; start clean inside the app folder only.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\Magpie"; Filename: "{app}\Magpie.exe"
Name: "{autodesktop}\Magpie"; Filename: "{app}\Magpie.exe"; Tasks: desktopicon

[Run]
; After a normal install: offer to open it. After a quiet update (WinSparkle): open it again.
Filename: "{app}\Magpie.exe"; Description: "Open Magpie now"; Flags: nowait postinstall skipifsilent
Filename: "{app}\Magpie.exe"; Flags: nowait; Check: Relaunch

[Code]
// WinSparkle passes /relaunch=1 when it runs this quietly to update, so the app comes back by
// itself. A quiet install without it (a test machine) opens nothing.
function Relaunch(): Boolean;
begin
  Result := WizardSilent() and (ExpandConstant('{param:relaunch|0}') = '1');
end;
