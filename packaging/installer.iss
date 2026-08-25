; Inno Setup script for the JARVIS Windows installer.
; Compiled by .github/workflows/build-windows.yml on a windows runner.
;
; Installs per-user into %LOCALAPPDATA%\Programs\JARVIS. That is deliberate:
; a per-user install needs no administrator rights, which means no UAC prompt
; on an unsigned build, and it keeps the app's own data directory writable.

#define AppName "JARVIS"
#define AppPublisher "JARVIS"
#define AppExeName "JARVIS.exe"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{8F3C1A72-4E5D-4B7A-9C21-2D6E8B4F1A93}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=no
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputBaseFilename=JARVIS-Setup-{#AppVersion}
SetupIconFile=..\assets\jarvis.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "startupicon"; Description: "Start JARVIS when I sign in"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
Source: "..\dist\JARVIS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{#AppName} diagnostics"; Filename: "{app}\JARVIS-console.exe"; Parameters: "doctor"; Comment: "Check every subsystem and print what is missing"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: startupicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Start {#AppName} now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; The models and logs JARVIS downloads after install; leaving them behind after
; an uninstall would strand a few hundred megabytes in AppData.
Type: filesandordirs; Name: "{userappdata}\JARVIS\models"
Type: filesandordirs; Name: "{userappdata}\JARVIS\logs"

[Code]
// Config, the API key and remembered facts are deliberately NOT removed above.
// Ask, so a reinstall doesn't silently lose someone's settings.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataPath: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataPath := ExpandConstant('{userappdata}\JARVIS');
    if DirExists(DataPath) then
    begin
      if MsgBox('Also remove your JARVIS settings, API key and remembered notes?'#13#10#13#10
                + 'Choose No to keep them for a future reinstall.',
                mbConfirmation, MB_YESNO) = IDYES then
        DelTree(DataPath, True, True, True);
    end;
  end;
end;
