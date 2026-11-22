; Build inputs are explicit: account files and user browser profiles are never packaged
[Setup]
AppId={{D584AE32-B160-4F8A-A133-8F06D18F812A}
AppName=XAnty
AppVersion={#AppVersion}
AppPublisher=XAnty
AppPublisherURL=https://github.com/mur3r/XAnty
AppUpdatesURL=https://github.com/mur3r/XAnty/releases/latest
DefaultDirName={localappdata}\Programs\XAnty
DefaultGroupName=XAnty
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
SetupIconFile=..\xgenius\web\static\assets\app.ico
UninstallDisplayIcon={app}\XAnty.exe
OutputDir={#OutputDir}
OutputBaseFilename=XAnty-Setup
Compression=lzma2
SolidCompression=yes
AppMutex=Local\XAnty.App.Running
CloseApplications=no
RestartApplications=no
UninstallDisplayName=XAnty

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "ukrainian"; MessagesFile: "compiler:Languages\Ukrainian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; Flags: unchecked

[Files]
Source: "{#AppExe}"; DestDir: "{app}"; DestName: "XAnty.exe"; Flags: ignoreversion
Source: "{#ChromeDir}\*"; DestDir: "{app}\runtime\Bro"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#DriverDir}\*"; DestDir: "{app}\runtime\Drivers"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#WebViewSetup}"; Flags: dontcopy

[Icons]
Name: "{group}\XAnty"; Filename: "{app}\XAnty.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\XAnty"; Filename: "{app}\XAnty.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\XAnty.exe"; Description: "{cm:LaunchProgram,XAnty}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\XAnty.exe.previous"
Type: files; Name: "{app}\XAnty.exe.next"

[Code]
function HasWebView2: Boolean;
var Version: String;
begin
  Result := (RegQueryStringValue(HKLM32, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version)
    and (Version <> '') and (Version <> '0.0.0.0'));
  if not Result then
    Result := (RegQueryStringValue(HKCU32, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version)
      and (Version <> '') and (Version <> '0.0.0.0'));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var ExitCode: Integer;
begin
  Result := '';
  if not HasWebView2 then begin
    ExtractTemporaryFile('MicrosoftEdgeWebview2Setup.exe');
    if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'), '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ExitCode)
      or not HasWebView2 then
      Result := 'Microsoft WebView2 could not be installed. Connect to the Internet and run Setup again.';
  end;
end;
