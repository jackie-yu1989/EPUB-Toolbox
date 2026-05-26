#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动生成 setup_Lite.iss — 专为 Lite 版设计
版本号、路径、文件名全部从单一数据源派生，并与 build_folder_Lite.spec 严格保持一致
使用方式：python generate_iss_Lite.py
"""
import sys
from pathlib import Path

# 添加项目根目录到路径，确保能导入 core.version
sys.path.insert(0, str(Path(__file__).parent))
from core.version import __version__, __app_name__

# ★ 关键变量定义：必须与 build_folder_Lite.spec 中的定义完全一致
# 1. COLLECT 的 name 参数决定了 dist 下的文件夹名
DIST_FOLDER_NAME = f"EPUB工具箱_Lite_v{__version__}"

# 2. EXE 的 name 参数决定了可执行文件名
# 注意：您的 spec 中写的是 name=f'EPUB工具箱_Lite'，所以这里不带版本号
EXE_FILE_NAME = "EPUB工具箱_Lite.exe"

# 3. 安装包输出文件名
INSTALLER_FILENAME = f"EPUB工具箱_Lite_v{__version__}_Setup.exe"

iss_content = f"""; 自动生成，请勿手动编辑
; 生成命令: python generate_iss_Lite.py
; 数据来源: core/version.py → __version__ = "{__version__}"
; 对应 Spec: build_folder_Lite.spec

[Setup]
AppName={__app_name__} Lite
AppVersion={__version__}
AppPublisher=YQJ
DefaultDirName={{autopf}}\\{__app_name__} Lite
DefaultGroupName={__app_name__} Lite
OutputDir=.\\installer
OutputBaseFilename=EPUB工具箱_Lite_v{__version__}_Setup
Compression=lzma2/ultra64
SolidCompression=yes
UninstallDisplayIcon={{app}}\\{EXE_FILE_NAME}
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
; 源路径必须与 DIST_FOLDER_NAME 一致
Source: "dist\\{DIST_FOLDER_NAME}\\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{{group}}\\{__app_name__} Lite"; Filename: "{{app}}\\{EXE_FILE_NAME}"
Name: "{{group}}\\卸载 {__app_name__} Lite"; Filename: "{{uninstallexe}}"
Name: "{{commondesktop}}\\{__app_name__} Lite"; Filename: "{{app}}\\{EXE_FILE_NAME}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"

[Run]
Filename: "{{app}}\\{EXE_FILE_NAME}"; Description: "启动 {__app_name__} Lite"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{{app}}\\*"
"""

output_path = Path(__file__).parent / "setup_Lite.iss"
output_path.write_text(iss_content, encoding="utf-8")

print(f"✅ 已生成 setup_Lite.iss (版本: {__version__})")
print(f"   输出安装包: installer/{INSTALLER_FILENAME}")
print(f"   源目录:     dist/{DIST_FOLDER_NAME}/")
print(f"   主程序EXE:  {EXE_FILE_NAME}")