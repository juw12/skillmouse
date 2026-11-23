; SkillMouse for Windows - per-user installer (no admin rights). build.py compiles it with:
;   iscc /DAppVersion=1.0.0 /DSourceDir=<dist\SkillMouse> /DOutputDir=<dist> /DIconFile=<build\skillmouse.ico> skillmouse.iss
; Installs to %LOCALAPPDATA%\Programs\SkillMouse, adds SkillMouse to the Start menu (and optionally the desktop) and lists it
; in Settings > Apps. The window keeps its data (what you saved in it) in %LOCALAPPDATA%\SkillMouse, which
; uninstalling leaves in place so a reinstall finds it again.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "dist\SkillMouse"
#endif
#ifndef OutputDir
  #define OutputDir "dist"
#endif
#ifndef IconFile
  #define IconFile "build\skillmouse.ico"
#endif

[Setup]
AppId={{E81247BA-698B-569E-A6DE-E1E1C366EEFB}
AppName=SkillMouse
AppVersion={#AppVersion}
AppVerName=SkillMouse {#AppVersion}
AppPublisher=Juwen Lie
AppPublisherURL=https://juw12.github.io/skillmouse/
AppSupportURL=https://github.com/juw12/skillmouse
DefaultDirName={autopf}\SkillMouse
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=SkillMouse-Windows-Setup
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\SkillMouse.exe
UninstallDisplayName=SkillMouse
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=no
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\SkillMouse"; Filename: "{app}\SkillMouse.exe"; Comment: "Use Claude Code, Codex and OpenCode skills with any model"
Name: "{userdesktop}\SkillMouse"; Filename: "{app}\SkillMouse.exe"; Comment: "Use Claude Code, Codex and OpenCode skills with any model"; Tasks: desktopicon

[Run]
Filename: "{app}\SkillMouse.exe"; Description: "{cm:LaunchProgram,SkillMouse}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\SkillMouse.exe"; Parameters: "--stop"; Flags: runhidden waituntilterminated; RunOnceId: "StopSkillMouse"

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Result := '';
  { Updating: close an open SkillMouse window first so its files can be replaced. }
  if FileExists(ExpandConstant('{app}\SkillMouse.exe')) then
    Exec(ExpandConstant('{app}\SkillMouse.exe'), '--stop', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;
