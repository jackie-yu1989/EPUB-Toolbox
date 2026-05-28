#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动生成 setup.iss — 标准版（完整版）安装包配置
版本号、路径、文件名全部从单一数据源派生，并与 build_folder.spec 严格保持一致
使用方式：python generate_iss.py

"""
import sys
from pathlib import Path

# 添加项目根目录到路径，确保能导入 core.version
sys.path.insert(0, str(Path(__file__).parent))

# ==================== Import 容错机制 ====================
try:
    from core.version import __version__, __app_name__, __author__
except ImportError:
    # 兜底机制：防止在打包环境或路径异常时脚本崩溃
    __version__ = "1.17.1"
    __app_name__ = "EPUB工具箱"
    __author__ = "YQJ"


# ==================== 1. 集中配置区 ====================
CONFIG = {
    # 应用后缀标识（标准版无后缀，Lite 版可改为 "_Lite"）
    'app_suffix': '',
    
    # 发布者名称（从 version.py 动态导入）
    'publisher': __author__,
    
    # 安装包输出目录（相对于脚本所在目录）
    'output_installer_dir': 'installer',
    
    # ★ 卸载行为配置
    #   dirifempty   = 卸载时仅删除空目录（安全，不删除用户数据）
    #   filesandordirs = 卸载时删除整个目录（危险，不推荐）
    'uninstall_delete': 'dirifempty',
    
    # 功能开关（True/False）
    'create_desktop_icon': True,   # 是否创建桌面快捷方式
    'run_after_install': True,     # 是否在安装完成后启动程序
}


# ==================== 2. 动态生成名称 ====================
# 例: EPUB工具箱
EXE_BASE_NAME = f"{__app_name__}{CONFIG['app_suffix']}"

# 例: EPUB工具箱.exe
EXE_FILE_NAME = f"{EXE_BASE_NAME}.exe"

# 例: EPUB工具箱_v1.17.1
DIST_FOLDER_NAME = f"{EXE_BASE_NAME}_v{__version__}"

# 例: EPUB工具箱_v1.17.1_Setup
INSTALLER_BASENAME = f"{EXE_BASE_NAME}_v{__version__}_Setup"


# ==================== 3. 生成 ISS 内容 ====================
iss_parts = []

# --- [Setup] ---
iss_parts.append(f"""; 自动生成，请勿手动编辑
; 生成命令: python generate_iss.py
; 数据来源: core/version.py → __version__ = "{__version__}"
; 对应 Spec: build_folder.spec

[Setup]
AppName={__app_name__}
AppVersion={__version__}
AppPublisher={CONFIG['publisher']}
DefaultDirName={{autopf}}\\{__app_name__}
DefaultGroupName={__app_name__}
OutputDir=.\\{CONFIG['output_installer_dir']}
OutputBaseFilename={INSTALLER_BASENAME}
Compression=lzma2/ultra64
SolidCompression=yes
UninstallDisplayIcon={{app}}\\{EXE_FILE_NAME}
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "dist\\{DIST_FOLDER_NAME}\\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{{group}}\\{__app_name__}"; Filename: "{{app}}\\{EXE_FILE_NAME}"
Name: "{{group}}\\卸载 {__app_name__}"; Filename: "{{uninstallexe}}"
""")

# --- 桌面快捷方式（可选插入） ---
if CONFIG['create_desktop_icon']:
    iss_parts.append(f'Name: "{{commondesktop}}\\{__app_name__}"; Filename: "{{app}}\\{EXE_FILE_NAME}"; Tasks: desktopicon\n')

# --- [Tasks] ---
if CONFIG['create_desktop_icon']:
    iss_parts.append(f"""[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"
""")
else:
    iss_parts.append("\n; [Tasks] 已禁用\n")

# --- [Run] ---
if CONFIG['run_after_install']:
    iss_parts.append(f"""[Run]
Filename: "{{app}}\\{EXE_FILE_NAME}"; Description: "启动 {__app_name__}"; Flags: nowait postinstall skipifsilent
""")
else:
    iss_parts.append("\n[Run]\n; 安装完成后不启动程序 (已禁用)\n")

# --- [UninstallDelete]（安全修复） ---
iss_parts.append(f"""[UninstallDelete]
Type: {CONFIG['uninstall_delete']}; Name: "{{app}}"
""")

# 拼接所有部分
iss_content = ''.join(iss_parts)


# ==================== 4. 写入文件 ====================
output_path = Path(__file__).parent / "setup.iss"
output_path.write_text(iss_content, encoding="utf-8")


# ==================== 5. 打印配置信息 ====================
print(f"""
╔═══════════════════════════════════════════════════════════════════╗
║                      setup.iss 生成成功                            ║
╠═══════════════════════════════════════════════════════════════════╣
║  应用名称:   {__app_name__}
║  版本号:     {__version__}
║  发布者:     {CONFIG['publisher']}
║  安装包:     {CONFIG['output_installer_dir']}/{INSTALLER_BASENAME}.exe
║  源目录:     dist/{DIST_FOLDER_NAME}/
║  主程序:     {EXE_FILE_NAME}
╠═══════════════════════════════════════════════════════════════════╣
║  桌面快捷方式: {'是' if CONFIG['create_desktop_icon'] else '否'}
║  安装后启动:   {'是' if CONFIG['run_after_install'] else '否'}
║  卸载行为:     {CONFIG['uninstall_delete']}（安全模式）
╚═══════════════════════════════════════════════════════════════════╝
""")