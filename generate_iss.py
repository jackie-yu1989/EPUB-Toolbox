#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动生成 setup.iss — 版本号、路径、文件名全部从单一数据源派生
使用方式：python generate_iss.py
"""

import sys
from pathlib import Path

# 添加项目根目录到路径，确保能导入 core.version
sys.path.insert(0, str(Path(__file__).parent))
from core.version import __version__, __app_name__

# ★ 与 build_folder.spec 中 COLLECT name 保持一致的命名规则
dist_folder = f"EPUB工具箱_v{__version__}"
output_filename = f"EPUB工具箱_v{__version__}_Setup"

iss_content = f"""; 自动生成，请勿手动编辑
; 生成命令: python generate_iss.py
; 数据来源: core/version.py → __version__ = "{__version__}"

[Setup]
AppName={__app_name__}
AppVersion={__version__}
AppPublisher=YQJ
DefaultDirName={{autopf}}\\{__app_name__}
DefaultGroupName={__app_name__}
OutputDir=.\\installer
OutputBaseFilename={output_filename}
Compression=lzma2/ultra64
SolidCompression=yes
UninstallDisplayIcon={{app}}\\{dist_folder}.exe
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "dist\\{dist_folder}\\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{{group}}\\{__app_name__}"; Filename: "{{app}}\\{dist_folder}.exe"
Name: "{{group}}\\卸载 {__app_name__}"; Filename: "{{uninstallexe}}"
Name: "{{commondesktop}}\\{__app_name__}"; Filename: "{{app}}\\{dist_folder}.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"

[Run]
Filename: "{{app}}\\{dist_folder}.exe"; Description: "启动 {__app_name__}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{{app}}\\*"
"""

output_path = Path(__file__).parent / "setup.iss"
output_path.write_text(iss_content, encoding="utf-8")
print(f"✅ 已生成 setup.iss (版本: {__version__})")
print(f"   输出文件: installer/{output_filename}.exe")
print(f"   源目录:   dist/{dist_folder}/")