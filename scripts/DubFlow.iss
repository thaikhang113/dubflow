#define AppName "DubFlow"
#define AppPublisher "DubFlow contributors"
#define AppExeName "DubFlow.exe"

#ifndef AppVersion
  #define AppVersion "3.0.3"
#endif

[Setup]
AppId={{B7B3B9D8-7D94-4B52-9F35-8A2E2A4B2B10}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\DubFlow
DefaultGroupName=DubFlow
OutputDir=..\dist
OutputBaseFilename=DubFlow-v{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#AppExeName}
SetupIconFile=..\logo.ico
WizardStyle=modern

[Files]
Source: "..\dist\DubFlow\*"; DestDir: "{app}"; Excludes: ".env,smoke_test_result.json,smoke_startup_trace.txt"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\DubFlow"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\DubFlow"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch DubFlow"; Flags: nowait postinstall skipifsilent
