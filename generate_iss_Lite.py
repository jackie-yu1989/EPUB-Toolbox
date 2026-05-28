#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动生成 setup_Lite.iss — 专为 Lite 版设计
版本号、路径、文件名全部从单一数据源派生，并与 build_folder_Lite.spec 严格保持一致

"""
import sys
from pathlib import Path

# 添加项目根目录到路径，确保能导入 core.version
sys.path.insert(0, str(Path(__file__).parent))
from core.version import __version__, __app_name__, __author__


# ==================== 1. 集中配置（与 build_folder_Lite.spec 保持同源逻辑） ====================
CONFIG = {
    # 应用后缀标识（必须与 spec 文件中的 CONFIG['app_suffix'] 保持一致）
    'app_suffix': '_Lite',
    
    # 发布者名称（从 version.py 动态导入，避免硬编码）
    'publisher': __author__,
    
    # 安装包输出目录（相对于项目根目录）
    'output_installer_dir': 'installer',
    
    # ★ 卸载行为：dirifempty = 仅删除空目录（安全，不删除用户数据）
    #   filesandordirs = 删除整个目录（危险，会删除用户配置文件/缓存，不推荐）
    'uninstall_delete': 'dirifempty',
    
    # 是否创建桌面快捷方式（True/False）
    'create_desktop_icon': True,
    
    # 是否在安装完成后启动程序（True/False）
    'run_after_install': True,
}


# ==================== 2. 动态生成名称（与 spec 文件派生逻辑完全一致） ====================
# 例: EPUB工具箱_Lite
EXE_BASE_NAME = f"{__app_name__}{CONFIG['app_suffix']}"

# 例: EPUB工具箱_Lite_v1.17.1
DIST_FOLDER_NAME = f"{EXE_BASE_NAME}_v{__version__}"

# 例: EPUB工具箱_Lite_v1.17.1_Setup
INSTALLER_BASENAME = f"{EXE_BASE_NAME}_v{__version__}_Setup"


# ==================== 3. 构建 ISS 内容 ====================
iss_content = f"""; 自动生成，请勿手动编辑
; 生成命令: python generate_iss_Lite.py
; 数据来源: core/version.py → __version__ = "{__version__}"
; 对应 Spec: build_folder_Lite.spec
;
; 修改记录:
;   - 卸载行为改为 dirifempty（仅删除空目录，不删除用户数据）
;   - AppPublisher 从 version.py 动态导入
;   - 配置集中管理，支持功能开关

[Setup]
AppName={__app_name__} Lite
AppVersion={__version__}
AppPublisher={CONFIG['publisher']}
DefaultDirName={{autopf}}\\{__app_name__} Lite
DefaultGroupName={__app_name__} Lite
OutputDir=.\\{CONFIG['output_installer_dir']}
OutputBaseFilename={INSTALLER_BASENAME}
Compression=lzma2/ultra64
SolidCompression=yes
UninstallDisplayIcon={{app}}\\{EXE_BASE_NAME}.exe
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
; 源路径必须与 DIST_FOLDER_NAME 一致
Source: "dist\\{DIST_FOLDER_NAME}\\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{{group}}\\{__app_name__} Lite"; Filename: "{{app}}\\{EXE_BASE_NAME}.exe"
Name: "{{group}}\\卸载 {__app_name__} Lite"; Filename: "{{uninstallexe}}"
"""

# 条件添加桌面快捷方式
if CONFIG['create_desktop_icon']:
    iss_content += f'\nName: "{{commondesktop}}\\{__app_name__} Lite"; Filename: "{{app}}\\{EXE_BASE_NAME}.exe"; Tasks: desktopicon\n'
else:
    iss_content += '\n; 桌面快捷方式已禁用（CONFIG["create_desktop_icon"] = False）\n'

iss_content += f"""
[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"
"""

# 条件添加安装完成后启动程序
if CONFIG['run_after_install']:
    iss_content += f"""
[Run]
Filename: "{{app}}\\{EXE_BASE_NAME}.exe"; Description: "启动 {__app_name__} Lite"; Flags: nowait postinstall skipifsilent
"""
else:
    iss_content += """
[Run]
; 安装完成后不自动启动程序（CONFIG["run_after_install"] = False）
"""

# 卸载行为配置
iss_content += f"""
[UninstallDelete]
; ★ 安全修复：使用 dirifempty 而非 filesandordirs
;   dirifempty   = 卸载时仅删除空目录（安全，不删除用户数据）
;   filesandordirs = 卸载时删除整个目录（危险，会删除用户配置文件/缓存）
; 当前配置：{CONFIG['uninstall_delete']}
Type: {CONFIG['uninstall_delete']}; Name: "{{app}}"
"""


# ==================== 4. 写入文件 ====================
output_path = Path(__file__).parent / "setup_Lite.iss"
output_path.write_text(iss_content, encoding="utf-8")


# ==================== 5. 打印配置摘要（便于 CI/CD 日志审计） ====================
print(f"""
╔═══════════════════════════════════════════════════════════════════╗
║                    setup_Lite.iss 生成成功                         ║
╠═══════════════════════════════════════════════════════════════════╣
║  应用名称:   {__app_name__} Lite
║  版本号:     {__version__}
║  发布者:     {CONFIG['publisher']}
║  安装包:     {CONFIG['output_installer_dir']}/{INSTALLER_BASENAME}.exe
║  源目录:     dist/{DIST_FOLDER_NAME}/
║  主程序:     {EXE_BASE_NAME}.exe
╠═══════════════════════════════════════════════════════════════════╣
║  桌面快捷方式: {'是' if CONFIG['create_desktop_icon'] else '否'}
║  安装后启动:   {'是' if CONFIG['run_after_install'] else '否'}
║  卸载行为:     {CONFIG['uninstall_delete']}（安全模式）
╚═══════════════════════════════════════════════════════════════════╝
""")