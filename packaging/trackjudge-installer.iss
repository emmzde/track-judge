#ifndef ProjectRoot
  #error ProjectRoot compiler define is required
#endif
#ifndef PortableRoot
  #error PortableRoot compiler define is required
#endif
#ifndef OutputRoot
  #error OutputRoot compiler define is required
#endif

#define MyAppName "TrackJudge"
#define MyAppVersion "1.2.0"
#define MyAppPublisher "emmzde"
#define MyAppURL "https://github.com/emmzde"
#define MyAppExeName "TrackJudge.exe"

[Setup]
AppId={{D43957D4-7D23-4B2D-AB0C-7F2D15A5B9A1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputRoot}
OutputBaseFilename=TrackJudge-Setup-Windows-x64
SetupIconFile={#ProjectRoot}\assets\trackjudge-v2.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
LicenseFile={#ProjectRoot}\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
WizardSizePercent=110
CloseApplications=force
RestartApplications=no
ChangesAssociations=no
ChangesEnvironment=no
UsePreviousAppDir=yes
SetupLogging=yes
VersionInfoVersion=1.2.0.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} installer
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Files]
Source: "{#PortableRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; AppUserModelID: "TrackJudge.TrackJudge"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; AppUserModelID: "TrackJudge.TrackJudge"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\TrackJudge\runtime"
Type: dirifempty; Name: "{localappdata}\TrackJudge"
