#ifndef AppVersion
  #define AppVersion "0.7.0"
#endif
#ifndef SourceExe
  #define SourceExe "dist\PianoShadow-v0.7.0-Windows-x64.exe"
#endif

#define AppName "Piano Shadow"
#define AppPublisher "Piano Shadow"
#define AppExeName "PianoShadow.exe"

[Setup]
AppId={{4E81C643-274F-4C73-93AD-A726096180E1}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\PianoShadow
DefaultGroupName={#AppName}
DisableDirPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=dist
OutputBaseFilename=PianoShadow-Setup-v{#AppVersion}-Windows-x64
SetupIconFile=assets\piano-shadow.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#AppVersion}.0
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}

[Languages]
Name: "chinesesimp"; MessagesFile: "localization\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: unchecked
Name: "startup"; Description: "登录 Windows 后自动启动"; GroupDescription: "启动选项："; Flags: unchecked

[Files]
Source: "{#SourceExe}"; DestDir: "{app}"; DestName: "{#AppExeName}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: startup

[Run]
Filename: "{app}\{#AppExeName}"; Description: "启动 {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Deliberately preserve %LOCALAPPDATA%\PianoShadow: downloaded models and user data
; survive upgrades and uninstall/reinstall cycles.
Type: filesandordirs; Name: "{localappdata}\PianoShadow\logs"
