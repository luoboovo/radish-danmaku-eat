; 萝卜弹幕吃吃吃 Windows 安装程序（Inno Setup 6）
; 构建示例：ISCC.exe /DAppVersion=1.4.0 installer.iss

#ifndef AppVersion
  #define AppVersion "1.4.0"
#endif

#define AppName "萝卜弹幕吃吃吃"
#define AppPublisher "luoboovo"
#define AppUrl "https://github.com/luoboovo/radish-danmaku-eat"
#define PortableExe "radish-danmaku-eat-v" + AppVersion + "-windows.exe"
#define InstalledExe "萝卜弹幕吃吃吃.exe"

[Setup]
AppId={{D7AE06D0-C5EE-4B6A-95D7-866B02C987AD}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl + "/issues"}
AppUpdatesURL={#AppUrl + "/releases"}
DefaultDirName={localappdata}\Programs\RadishDanmakuEat
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=LICENSE
OutputDir=dist
OutputBaseFilename=radish-danmaku-eat-v{#AppVersion}-setup
SetupIconFile=cake.ico
UninstallDisplayIcon={app}\{#InstalledExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
SetupLogging=yes

[Languages]
Name: "chinesesimplified"; MessagesFile: "installer\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加选项："; Flags: unchecked

[Files]
Source: "dist\{#PortableExe}"; DestDir: "{app}"; DestName: "{#InstalledExe}"; Flags: ignoreversion
Source: "LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#InstalledExe}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#InstalledExe}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#InstalledExe}"; Description: "启动 {#AppName}"; Flags: nowait postinstall skipifsilent
