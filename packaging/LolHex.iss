; 海克斯大亂鬥助手安裝包。先執行 packaging/build.ps1（它會呼叫本指令碼）。
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{1107079E-6C48-46FD-938D-04B1C3EA9A72}
AppName=AramHex 臺服版
AppVersion={#AppVersion}
AppPublisher=czgreat
AppPublisherURL=https://github.com/czgreat/aramhex
AppSupportURL=https://github.com/czgreat/aramhex/issues
AppUpdatesURL=https://github.com/czgreat/aramhex/releases
DefaultDirName={localappdata}\Programs\AramHexTW
DefaultGroupName=AramHex 臺服版
; 裝到使用者目錄，不需要管理員許可權；始終"只為當前使用者安裝"（解除安裝資訊寫在 HKCU），線上更新才能改「應用」列表裡的版本號
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force
OutputDir=..\build\installer
OutputBaseFilename=AramHexTW-Setup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=AramHex 臺服版
UninstallDisplayIcon={app}\AramHexTW.exe
SetupIconFile=lolhex.ico
LicenseFile=..\LICENSE

[Languages]
Name: "cht"; MessagesFile: "ChineseTraditional.isl"

[Tasks]
Name: "desktopicon"; Description: "建立桌面快捷方式"; GroupDescription: "附加任務："

[Files]
Source: "..\build\dist\AramHexTW\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; 升級時先清掉舊的程式檔案（onedir 目錄合併安裝，否則舊版本多出來的檔案會留下）
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\AramHex 臺服版"; Filename: "{app}\AramHexTW.exe"
Name: "{group}\解除安裝海克斯大亂鬥助手"; Filename: "{uninstallexe}"
Name: "{userdesktop}\AramHex 臺服版"; Filename: "{app}\AramHexTW.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AramHexTW.exe"; Description: "立即啟動"; Flags: nowait postinstall skipifsilent
; 助手裡點「立即更新」走的是 /SILENT：裝完自動重新開啟
Filename: "{app}\AramHexTW.exe"; Flags: nowait; Check: WizardSilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/c taskkill /im AramHexTW.exe /f"; Flags: runhidden; RunOnceId: "KillAramHex"
