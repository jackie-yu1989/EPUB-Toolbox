#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
依赖工具安装/管理向导
支持离线安装包（优先使用本地 resources/dependencies/ 目录）
支持后台运行模式（安装任务在后台执行，完成后系统托盘通知）
支持快捷键 Ctrl+W / Esc 关闭对话框，Ctrl+Q 清空日志，F5 刷新
"""

import subprocess
import sys
from pathlib import Path
from typing import List, Tuple, Dict, Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QTextEdit, QGroupBox, QMessageBox, QGridLayout,
    QCheckBox, QSystemTrayIcon
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QShortcut, QKeySequence


# ==================== 工具定义 ====================

def get_resources_dir() -> Path:
    """获取资源目录路径（兼容开发环境和打包后）"""
    if getattr(sys, 'frozen', False):
        base_path = Path(sys._MEIPASS)
    else:
        base_path = Path(__file__).parent.parent.parent
    
    return base_path / 'resources'


def get_dependencies_dir() -> Path:
    """获取依赖工具离线安装包目录"""
    return get_resources_dir() / 'dependencies'


def get_offline_installer_path(tool_key: str) -> Optional[Path]:
    """获取离线安装包路径"""
    tools_dir = get_dependencies_dir()
    if not tools_dir.exists():
        return None
    
    file_patterns = {
        'pandoc': ['pandoc-*.msi', 'pandoc-*.exe'],
        'calibre': ['calibre-*.msi', 'calibre-*.exe'],
        'nodejs': ['node-*.msi', 'node-*.exe'],
        'mermaid': ['mermaid-*.tgz'],
    }
    
    patterns = file_patterns.get(tool_key, [])
    for pattern in patterns:
        matches = list(tools_dir.glob(pattern))
        if matches:
            matches.sort(reverse=True)
            return matches[0]
    
    return None


TOOLS = {
    "pandoc": {
        "name": "Pandoc",
        "icon": "📖",
        "description": "MD 转 EPUB 核心引擎",
        "winget_id": "Pandoc",
        "install_cmd": "winget install --accept-source-agreements Pandoc",
        "verify_cmd": "pandoc --version",
        "version_cmd": "pandoc --version | findstr /b pandoc",
        "uninstall_info": (
            "方式一（推荐）：\n"
            "  打开 Windows 设置 → 应用 → 已安装的应用\n"
            "  搜索 Pandoc → 点击卸载\n\n"
            "方式二（命令行）：\n"
            "  PowerShell 执行：winget uninstall Pandoc"
        ),
        "required": True,
        "offline_installer": True,
    },
    "calibre": {
        "name": "Calibre",
        "icon": "📄",
        "description": "EPUB 转 PDF/Word 转换工具",
        "winget_id": "Calibre",
        "install_cmd": "winget install --accept-source-agreements Calibre",
        "verify_cmd": "ebook-convert --version",
        "version_cmd": "ebook-convert --version",
        "uninstall_info": (
            "方式一（推荐）：\n"
            "  打开 Windows 设置 → 应用 → 已安装的应用\n"
            "  搜索 Calibre → 点击卸载\n\n"
            "方式二（命令行）：\n"
            "  PowerShell 执行：winget uninstall Calibre"
        ),
        "required": True,
        "offline_installer": True,
    },
    "nodejs": {
        "name": "Node.js",
        "icon": "🧩",
        "description": "Mermaid CLI 运行环境",
        "winget_id": "OpenJS.NodeJS",
        "install_cmd": "winget install --accept-source-agreements OpenJS.NodeJS",
        "verify_cmd": "node --version",
        "version_cmd": "node --version",
        "uninstall_info": (
            "⚠️ 注意：卸载 Node.js 前，建议先卸载 Mermaid CLI。\n\n"
            "先卸载 Mermaid CLI：\n"
            "  PowerShell 执行：npm uninstall -g @mermaid-js/mermaid-cli\n\n"
            "再卸载 Node.js：\n"
            "  方式一：Windows 设置 → 应用 → 已安装的应用\n"
            "  方式二：winget uninstall OpenJS.NodeJS"
        ),
        "required": False,
        "offline_installer": True,
    },
    "mermaid": {
        "name": "Mermaid CLI",
        "icon": "📊",
        "description": "Mermaid 图表渲染工具",
        "winget_id": None,
        "install_cmd": "npm install -g @mermaid-js/mermaid-cli",
        "verify_cmd": "mmdc --version",
        "version_cmd": "mmdc --version 2>&1",
        "uninstall_info": (
            "命令行卸载：\n"
            "  npm uninstall -g @mermaid-js/mermaid-cli"
        ),
        "required": False,
        "offline_installer": False,
    },
}


# ==================== 工具检查工作线程 ====================

class ToolCheckWorker(QThread):
    """后台检测线程：检查所有工具的安装状态和版本"""
    
    status_ready = pyqtSignal(str, dict)
    all_checked = pyqtSignal()
    
    def run(self):
        for key, tool in TOOLS.items():
            installed, version = self._check_tool(tool)
            
            offline_path = get_offline_installer_path(key)
            has_offline = offline_path is not None
            
            self.status_ready.emit(key, {
                "installed": installed,
                "version": version,
                "status_text": f"v{version}" if version else "未安装",
                "has_offline": has_offline,
                "offline_hint": f"（离线包可用）" if has_offline else "",
            })
        self.all_checked.emit()
    
    def _check_tool(self, tool: dict) -> Tuple[bool, str]:
        try:
            result = subprocess.run(
                tool["version_cmd"], shell=True, capture_output=True,
                text=True, timeout=10,
                startupinfo=self._get_startupinfo()
            )
            if result.returncode == 0 and result.stdout.strip():
                import re
                version = result.stdout.strip().split("\n")[0]
                match = re.search(r'(\d+\.\d+\.\d+)', version)
                if match:
                    return True, match.group(1)
                return True, version[:30]
            return False, ""
        except Exception:
            return False, ""
    
    @staticmethod
    def _get_startupinfo():
        if sys.platform == 'win32':
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
            return si
        return None


# ==================== 后台安装工作线程 ====================

class BackgroundInstallWorker(QThread):
    """后台安装工作线程（支持进度通知）"""
    
    progress_updated = pyqtSignal(int, str)
    task_completed = pyqtSignal(str, bool, str)
    all_completed = pyqtSignal(dict)
    
    def __init__(self, actions: List[Tuple[str, str]]):
        super().__init__()
        self.actions = actions
        self._is_cancelled = False
    
    def cancel(self):
        self._is_cancelled = True
    
    def run(self):
        total = len(self.actions)
        results = {}
        
        for i, (tool_key, action) in enumerate(self.actions):
            if self._is_cancelled:
                break
            
            tool = TOOLS[tool_key]
            name = tool["name"]
            
            progress = int((i / total) * 100) if total > 0 else 0
            self.progress_updated.emit(progress, f"正在安装 {name}...")
            
            # 优先离线安装
            offline_path = get_offline_installer_path(tool_key)
            
            if action == "install" and offline_path:
                success, msg = self._run_msi_install(offline_path)
                if success:
                    results[tool_key] = (True, "离线安装成功")
                    self.task_completed.emit(name, True, "安装完成")
                    continue
                else:
                    self.progress_updated.emit(progress, f"离线安装失败，尝试网络安装 {name}...")
            
            # 网络安装
            if action == "install":
                success, msg = self._run_cmd(tool["install_cmd"])
                if success:
                    results[tool_key] = (True, "安装成功")
                    self.task_completed.emit(name, True, "安装完成")
                else:
                    results[tool_key] = (False, msg)
                    self.task_completed.emit(name, False, f"安装失败: {msg}")
            
            elif action == "update":
                cmd = f"winget upgrade {tool['winget_id']}" if tool.get("winget_id") else tool["install_cmd"]
                success, msg = self._run_cmd(cmd)
                if success:
                    results[tool_key] = (True, "更新成功")
                    self.task_completed.emit(name, True, "更新完成")
                else:
                    results[tool_key] = (False, msg)
                    self.task_completed.emit(name, False, f"更新失败: {msg}")
        
        self.progress_updated.emit(100, "安装完成")
        self.all_completed.emit(results)
    
    def _run_msi_install(self, installer_path: Path) -> Tuple[bool, str]:
        try:
            cmd = ['msiexec', '/i', str(installer_path), '/passive', '/norestart']
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=600, startupinfo=self._get_startupinfo()
            )
            if result.returncode == 0:
                return True, "安装成功"
            return False, f"安装返回码: {result.returncode}"
        except subprocess.TimeoutExpired:
            return False, "安装超时（10分钟）"
        except Exception as e:
            return False, str(e)
    
    def _run_cmd(self, cmd: str) -> Tuple[bool, str]:
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True,
                text=True, timeout=300,
                startupinfo=self._get_startupinfo()
            )
            if result.returncode == 0:
                return True, ""
            return False, (result.stderr + result.stdout)[:200]
        except subprocess.TimeoutExpired:
            return False, "操作超时（5分钟）"
        except Exception as e:
            return False, str(e)
    
    @staticmethod
    def _get_startupinfo():
        if sys.platform == 'win32':
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
            return si
        return None


# ==================== 前台安装工作线程 ====================

class ForegroundInstallWorker(QThread):
    """前台安装工作线程（显示详细日志）"""
    
    progress_text = pyqtSignal(str)
    step_completed = pyqtSignal(str, bool, str)
    all_done = pyqtSignal(dict)
    
    def __init__(self, actions: List[Tuple[str, str]]):
        super().__init__()
        self.actions = actions
    
    def run(self):
        results = {}
        
        for tool_key, action in self.actions:
            tool = TOOLS[tool_key]
            name = tool["name"]
            
            offline_path = get_offline_installer_path(tool_key)
            
            if action == "install" and offline_path:
                self.progress_text.emit(f"📦 使用离线包安装 {name}...")
                success, msg = self._run_msi_install(offline_path)
                if success:
                    self.progress_text.emit(f"✅ {name} 离线安装完成")
                    results[tool_key] = (True, "离线安装成功")
                    self.step_completed.emit(tool_key, True, msg)
                    continue
                else:
                    self.progress_text.emit(f"⚠️ 离线安装失败，尝试网络安装...")
            
            if action == "install":
                self.progress_text.emit(f"📥 正在安装 {name}...")
                success, msg = self._run_cmd(tool["install_cmd"])
                if success:
                    ok, _ = self._check_installed(tool["verify_cmd"])
                    if ok:
                        self.progress_text.emit(f"✅ {name} 安装完成")
                        results[tool_key] = (True, "安装成功")
                    else:
                        results[tool_key] = (True, "安装完成（需重启后验证）")
                else:
                    self.progress_text.emit(f"❌ {name} 安装失败: {msg}")
                    results[tool_key] = (False, msg)
            
            elif action == "update":
                self.progress_text.emit(f"🔄 正在更新 {name}...")
                cmd = f"winget upgrade {tool['winget_id']}" if tool.get("winget_id") else tool["install_cmd"]
                success, msg = self._run_cmd(cmd)
                if success:
                    self.progress_text.emit(f"✅ {name} 更新完成")
                    results[tool_key] = (True, "更新成功")
                else:
                    self.progress_text.emit(f"⚠️ {name} 更新失败: {msg}")
                    results[tool_key] = (False, msg)
            
            self.step_completed.emit(tool_key, results[tool_key][0], results[tool_key][1])
        
        self.all_done.emit(results)
    
    def _run_msi_install(self, installer_path: Path) -> Tuple[bool, str]:
        try:
            cmd = ['msiexec', '/i', str(installer_path), '/passive', '/norestart']
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=600, startupinfo=self._get_startupinfo()
            )
            if result.returncode == 0:
                return True, "安装成功"
            return False, f"安装返回码: {result.returncode}"
        except subprocess.TimeoutExpired:
            return False, "安装超时（10分钟）"
        except Exception as e:
            return False, str(e)
    
    def _run_cmd(self, cmd: str) -> Tuple[bool, str]:
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True,
                text=True, timeout=300,
                startupinfo=self._get_startupinfo()
            )
            if result.returncode == 0:
                return True, ""
            return False, (result.stderr + result.stdout)[:200]
        except subprocess.TimeoutExpired:
            return False, "操作超时（5分钟）"
        except Exception as e:
            return False, str(e)
    
    def _check_installed(self, verify_cmd: str) -> Tuple[bool, str]:
        try:
            result = subprocess.run(
                verify_cmd, shell=True, capture_output=True,
                text=True, timeout=10,
                startupinfo=self._get_startupinfo()
            )
            return result.returncode == 0, result.stdout.strip()[:50]
        except Exception:
            return False, ""
    
    @staticmethod
    def _get_startupinfo():
        if sys.platform == 'win32':
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
            return si
        return None


# ==================== 对话框 ====================

class DependencyInstallerDialog(QDialog):
    """依赖工具管理对话框（支持前台/后台两种模式）"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("依赖工具管理")
        self.setMinimumSize(650, 600)
        
        self.status_labels: Dict[str, QLabel] = {}
        self.action_buttons: Dict[str, QPushButton] = {}
        self.tool_status: Dict[str, dict] = {}
        self.bg_worker: Optional[BackgroundInstallWorker] = None
        self.parent_window = parent
        
        self._setup_ui()
        self._check_tools()
        
        # ★ 快捷键支持
        # Ctrl+W 关闭对话框
        close_shortcut = QShortcut(QKeySequence("Ctrl+W"), self)
        close_shortcut.activated.connect(self.close)
        
        # Esc 关闭对话框
        esc_shortcut = QShortcut(QKeySequence("Esc"), self)
        esc_shortcut.activated.connect(self.reject)
        
        # Ctrl+Q 清空日志
        clear_log_shortcut = QShortcut(QKeySequence("Ctrl+Q"), self)
        clear_log_shortcut.activated.connect(self._clear_log)
        
        # F5 刷新
        f5_shortcut = QShortcut(QKeySequence("F5"), self)
        f5_shortcut.activated.connect(self._refresh_tools)
    
    def _clear_log(self):
        """清空日志"""
        self.log_text.clear()
        self.log_text.append("🗑 日志已清空")
    
    def _refresh_tools(self):
        """刷新工具状态（重新检测）"""
        self.log_text.append("🔄 手动刷新，重新检测工具状态...")
        
        # 重置状态
        for key in self.status_labels:
            self.status_labels[key].setText("🔍 检测中...")
            self.status_labels[key].setStyleSheet("color: #888;")
            self.action_buttons[key].setEnabled(False)
        
        self.install_all_btn.setEnabled(False)
        
        # 重新检测
        self._check_tools()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # 标题
        title = QLabel("📦 依赖工具管理")
        title.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # 说明
        offline_info = ""
        tools_dir = get_dependencies_dir()
        if tools_dir.exists() and any(tools_dir.glob("*.msi")):
            offline_info = "\n✅ 检测到离线安装包，将优先使用本地安装（无需网络）"
        
        hint = QLabel(
            f"以下工具用于扩展 EPUB 工具箱的功能。\n"
            f"支持离线安装包（将 .msi 文件放入 resources/dependencies/ 目录）{offline_info}"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(hint)

        # 工具状态表格
        tools_group = QGroupBox("工具状态")
        tools_layout = QGridLayout(tools_group)
        tools_layout.setSpacing(6)
        tools_layout.setContentsMargins(12, 16, 12, 12)

        # 表头
        tools_layout.addWidget(QLabel("<b>工具</b>"), 0, 0)
        tools_layout.addWidget(QLabel("<b>状态</b>"), 0, 1)
        tools_layout.addWidget(QLabel("<b>操作</b>"), 0, 2)
        tools_layout.addWidget(QLabel("<b>卸载</b>"), 0, 3)

        for i, (key, tool) in enumerate(TOOLS.items(), 1):
            name_label = QLabel(f"{tool['icon']}  {tool['name']}")
            name_label.setToolTip(tool["description"])
            tools_layout.addWidget(name_label, i, 0)

            status_label = QLabel("🔍 检测中...")
            status_label.setStyleSheet("color: #888;")
            tools_layout.addWidget(status_label, i, 1)
            self.status_labels[key] = status_label

            btn = QPushButton("安装")
            btn.setFixedWidth(55)
            btn.setEnabled(False)
            btn.clicked.connect(lambda checked, k=key: self._on_tool_action(k))
            tools_layout.addWidget(btn, i, 2)
            self.action_buttons[key] = btn

            uninstall_btn = QPushButton("卸载说明")
            uninstall_btn.setFixedWidth(72)
            uninstall_btn.setStyleSheet("""
                QPushButton {
                    padding: 3px 6px;
                    background-color: transparent;
                    color: #888;
                    border: 1px solid #ccc;
                    border-radius: 3px;
                    font-size: 10px;
                }
                QPushButton:hover {
                    background-color: #f0f0f0;
                    color: #e74c3c;
                }
            """)
            uninstall_btn.clicked.connect(lambda checked, k=key: self._show_uninstall_info(k))
            tools_layout.addWidget(uninstall_btn, i, 3)

        layout.addWidget(tools_group)

        # 后台运行复选框
        self.background_checkbox = QCheckBox("后台运行（安装任务在后台执行，完成后系统托盘通知）")
        self.background_checkbox.setChecked(False)
        self.background_checkbox.setToolTip(
            "勾选后，安装任务将在后台执行，您可以关闭此对话框继续使用软件。\n"
            "安装完成后会通过系统托盘通知您。\n"
            "（需要系统托盘图标支持）"
        )
        layout.addWidget(self.background_checkbox)

        # 进度条（前台模式使用）
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumHeight(22)
        layout.addWidget(self.progress_bar)

        # 日志区域（前台模式使用）
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 8px;
            }
        """)
        layout.addWidget(self.log_text, 1)

        # 底部按钮行
        btn_layout = QHBoxLayout()
        
        # ★ 刷新按钮
        self.refresh_btn = QPushButton("🔄 刷新")
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                padding: 8px 16px;
                background-color: #3498db;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #2980b9; }
        """)
        self.refresh_btn.setToolTip("重新检测工具安装状态 (F5)")
        self.refresh_btn.clicked.connect(self._refresh_tools)
        btn_layout.addWidget(self.refresh_btn)
        
        btn_layout.addStretch()
        
        self.install_all_btn = QPushButton("🚀 全部安装/更新")
        self.install_all_btn.setStyleSheet("""
            QPushButton {
                padding: 8px 20px;
                background-color: #27ae60;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                font-size: 12pt;
            }
            QPushButton:hover { background-color: #219a52; }
            QPushButton:disabled { background-color: #bdc3c7; }
        """)
        self.install_all_btn.clicked.connect(self._on_install_all)
        btn_layout.addWidget(self.install_all_btn)

        layout.addLayout(btn_layout)
    
    def _show_uninstall_info(self, key: str):
        tool = TOOLS[key]
        QMessageBox.information(
            self,
            f"卸载说明 — {tool['name']}",
            tool["uninstall_info"]
        )
    
    def _check_tools(self):
        self.log_text.append("🔍 正在检测已安装的工具...")
        self.check_worker = ToolCheckWorker()
        self.check_worker.status_ready.connect(self._on_tool_status)
        self.check_worker.all_checked.connect(self._on_all_checked)
        self.check_worker.start()
    
    def _on_tool_status(self, key: str, status: dict):
        self.tool_status[key] = status
        
        offline_hint = status.get("offline_hint", "")
        
        if status["installed"]:
            self.status_labels[key].setText(f"✅ {status['status_text']} {offline_hint}")
            self.status_labels[key].setStyleSheet("color: #27ae60; font-weight: bold;")
            self.action_buttons[key].setText("更新")
            self.action_buttons[key].setToolTip(f"更新 {TOOLS[key]['name']} 到最新版本")
        else:
            self.status_labels[key].setText(f"⚠️ 未安装 {offline_hint}")
            self.status_labels[key].setStyleSheet("color: #e67e22;")
            self.action_buttons[key].setText("安装")
            self.action_buttons[key].setToolTip(f"安装 {TOOLS[key]['name']}")
        
        self.action_buttons[key].setEnabled(True)
    
    def _on_all_checked(self):
        self.log_text.append("✅ 检测完成\n")
        all_installed = all(s["installed"] for s in self.tool_status.values())
        self.install_all_btn.setText("🔄 全部更新" if all_installed else "🚀 全部安装/更新")
        self.install_all_btn.setEnabled(True)
    
    def _on_tool_action(self, key: str):
        status = self.tool_status.get(key, {})
        action = "update" if status.get("installed") else "install"
        self.log_text.append(f"{'🔄 更新' if action == 'update' else '📥 安装'} {TOOLS[key]['name']}...")
        self._run_actions([(key, action)])
    
    def _on_install_all(self):
        actions = []
        for key in ["pandoc", "calibre", "nodejs", "mermaid"]:
            if key in self.tool_status:
                action = "update" if self.tool_status[key].get("installed") else "install"
                actions.append((key, action))
        self.log_text.append("🚀 开始批量安装/更新...")
        self._run_actions(actions)
    
    def _run_actions(self, actions: list):
        if self.background_checkbox.isChecked():
            self._run_background(actions)
        else:
            self._run_foreground(actions)
    
    def _run_foreground(self, actions: list):
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(len(actions))
        self.progress_bar.setValue(0)
        self.install_all_btn.setEnabled(False)
        for btn in self.action_buttons.values():
            btn.setEnabled(False)
        
        self.worker = ForegroundInstallWorker(actions)
        self.worker.progress_text.connect(self._on_progress)
        self.worker.step_completed.connect(self._on_step_completed)
        self.worker.all_done.connect(self._on_all_done_foreground)
        self.worker.start()
    
    def _run_background(self, actions: list):
        self.hide()
        
        self._show_tray_message(
            "📦 依赖工具安装",
            f"正在后台安装 {len(actions)} 个依赖工具...",
            is_info=True
        )
        
        self.bg_worker = BackgroundInstallWorker(actions)
        self.bg_worker.progress_updated.connect(self._on_bg_progress)
        self.bg_worker.task_completed.connect(self._on_bg_task_completed)
        self.bg_worker.all_completed.connect(self._on_bg_all_completed)
        self.bg_worker.start()
    
    def _on_progress(self, text: str):
        self.log_text.append(text)
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def _on_step_completed(self, key: str, success: bool, message: str):
        self.progress_bar.setValue(self.progress_bar.value() + 1)
    
    def _on_all_done_foreground(self, results: dict):
        self.progress_bar.setVisible(False)
        self.install_all_btn.setEnabled(True)
        success_count = sum(1 for ok, _ in results.values() if ok)
        self.log_text.append(f"\n操作完成: {success_count}/{len(results)} 成功")
        self.log_text.append("🔍 重新检测工具状态...")
        self._check_tools()
    
    def _on_bg_progress(self, percent: int, message: str):
        self._update_tray_tooltip(f"EPUB工具箱\n{message} ({percent}%)")
    
    def _on_bg_task_completed(self, name: str, success: bool, msg: str):
        if success:
            self._show_tray_message(f"✅ {name} 安装完成", msg, is_success=True)
    
    def _on_bg_all_completed(self, results: dict):
        success_count = sum(1 for ok, _ in results.values() if ok)
        failed_count = len(results) - success_count
        
        self._update_tray_tooltip("EPUB工具箱")
        
        if failed_count == 0:
            self._show_tray_message(
                "✅ 依赖工具安装完成",
                f"成功安装 {success_count} 个工具",
                is_success=True
            )
        else:
            self._show_tray_message(
                "⚠️ 部分工具安装失败",
                f"成功: {success_count}, 失败: {failed_count}",
                is_error=True
            )
        
        reply = QMessageBox.question(
            None, "安装完成",
            f"依赖工具安装完成！\n\n✅ 成功: {success_count}\n❌ 失败: {failed_count}\n\n是否查看详细信息？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.show()
            self._check_tools()
        else:
            self._check_tools()
    
    def _show_tray_message(self, title: str, message: str, is_success=False, is_error=False, is_info=False):
        tray_icon = self._get_tray_icon()
        if tray_icon is None:
            return
        
        if is_error:
            icon = QSystemTrayIcon.MessageIcon.Critical
        else:
            icon = QSystemTrayIcon.MessageIcon.Information
        
        tray_icon.showMessage(title, message, icon, 5000)
    
    def _update_tray_tooltip(self, tooltip: str):
        tray_icon = self._get_tray_icon()
        if tray_icon:
            tray_icon.setToolTip(tooltip)
    
    def _get_tray_icon(self):
        if self.parent_window and hasattr(self.parent_window, 'tray_icon'):
            return self.parent_window.tray_icon
        
        from PyQt6.QtWidgets import QApplication
        for widget in QApplication.topLevelWidgets():
            if hasattr(widget, 'tray_icon') and widget.tray_icon:
                return widget.tray_icon
        return None
    
    def closeEvent(self, event):
        if self.bg_worker and self.bg_worker.isRunning():
            reply = QMessageBox.question(
                self, "确认关闭",
                "后台安装任务正在执行中，关闭对话框不会停止安装。\n\n"
                "确定要关闭吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        
        event.accept()


# ==================== 元信息 ====================
__author__ = "YQJ"
__version__ = "1.5.0"
__date__ = "2026.05.29"