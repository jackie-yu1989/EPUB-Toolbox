[Setup]
AppName=EPUB工具箱
AppVersion=1.14.2
AppPublisher=YQJ
DefaultDirName={autopf}\EPUB工具箱
DefaultGroupName=EPUB工具箱
OutputDir=.\installer
OutputBaseFilename=EPUB工具箱_v1.14.2_Setup
Compression=lzma2/ultra64
SolidCompression=yes
UninstallDisplayIcon={app}\EPUB工具箱.exe
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "dist\EPUB工具箱\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\EPUB工具箱"; Filename: "{app}\EPUB工具箱.exe"
Name: "{group}\卸载 EPUB工具箱"; Filename: "{uninstallexe}"
Name: "{commondesktop}\EPUB工具箱"; Filename: "{app}\EPUB工具箱.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"

[Run]
Filename: "{app}\EPUB工具箱.exe"; Description: "启动 EPUB工具箱"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\*"