#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
依赖工具安装/管理向导
支持检测已安装、安装、更新
提供各工具的卸载说明
"""

import subprocess
import sys
from typing import List, Tuple, Dict

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QTextEdit, QGroupBox, QMessageBox, QGridLayout,
    QSizePolicy, QWidget
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont


# ==================== 工具定义 ====================

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
            "  PowerShell 执行：winget uninstall Pandoc\n\n"
            "方式三：\n"
            "  控制面板 → 程序和功能 → 找到 Pandoc → 卸载"
        ),
        "required": True,
    },
    "calibre": {
        "name": "Calibre",
        "icon": "📄",
        "description": "EPUB 转 PDF 转换工具",
        "winget_id": "Calibre",
        "install_cmd": "winget install --accept-source-agreements Calibre",
        "verify_cmd": "ebook-convert --version",
        "version_cmd": "ebook-convert --version",
        "uninstall_info": (
            "方式一（推荐）：\n"
            "  打开 Windows 设置 → 应用 → 已安装的应用\n"
            "  搜索 Calibre → 点击卸载\n\n"
            "方式二（命令行）：\n"
            "  PowerShell 执行：winget uninstall Calibre\n\n"
            "方式三：\n"
            "  控制面板 → 程序和功能 → 找到 Calibre → 卸载"
        ),
        "required": True,
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
            "  方式一（推荐）：Windows 设置 → 应用 → 已安装的应用\n"
            "    搜索 Node.js → 点击卸载\n"
            "  方式二（命令行）：winget uninstall OpenJS.NodeJS"
        ),
        "required": False,
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
            "命令行卸载（唯一方式）：\n"
            "  PowerShell 或 CMD 执行：\n"
            "  npm uninstall -g @mermaid-js/mermaid-cli\n\n"
            "此操作不会影响 Node.js 和其他 npm 全局包。"
        ),
        "required": False,
    },
}


# ==================== 工作线程 ====================

class ToolCheckWorker(QThread):
    """后台检测线程：检查所有工具的安装状态和版本"""
    
    status_ready = pyqtSignal(str, dict)
    all_checked = pyqtSignal()
    
    def run(self):
        for key, tool in TOOLS.items():
            installed, version = self._check_tool(tool)
            self.status_ready.emit(key, {
                "installed": installed,
                "version": version,
                "status_text": f"v{version}" if version else "未安装",
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


class InstallWorker(QThread):
    """后台安装/更新线程"""
    
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
            
            if action == "install":
                self.progress_text.emit(f"📥 正在安装 {name}...")
                success, msg = self._run_cmd(tool["install_cmd"])
                if success:
                    ok, _ = self._check_installed(tool["verify_cmd"])
                    if ok:
                        self.progress_text.emit(f"✅ {name} 安装完成")
                        results[tool_key] = (True, "安装成功")
                    else:
                        self.progress_text.emit(f"⚠️ {name} 安装完成但验证失败")
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
    """依赖工具管理对话框"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("依赖工具管理")
        self.setMinimumSize(600, 520)
        
        self.status_labels: Dict[str, QLabel] = {}
        self.action_buttons: Dict[str, QPushButton] = {}
        self.tool_status: Dict[str, dict] = {}
        
        self._setup_ui()
        self._check_tools()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # 标题
        title = QLabel("📦依赖工具管理")
        title.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # 说明
        hint = QLabel(
            "以下工具用于扩展 EPUB 工具箱的功能。\n"
            "通过 Windows 包管理器 (winget) 一键安装/更新。"
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

        tools_layout.setColumnStretch(0, 2)
        tools_layout.setColumnStretch(1, 1)
        tools_layout.setColumnStretch(2, 0)
        tools_layout.setColumnStretch(3, 0)

        for i, (key, tool) in enumerate(TOOLS.items(), 1):
            # 名称
            name_label = QLabel(f"{tool['icon']}  {tool['name']}")
            name_label.setToolTip(tool["description"])
            name_label.setFont(QFont("Microsoft YaHei", 10))
            tools_layout.addWidget(name_label, i, 0)

            # 状态
            status_label = QLabel("🔍 检测中...")
            status_label.setStyleSheet("color: #888;")
            tools_layout.addWidget(status_label, i, 1)
            self.status_labels[key] = status_label

            # 安装/更新
            btn = QPushButton("安装")
            btn.setFixedWidth(55)
            btn.setEnabled(False)
            btn.clicked.connect(lambda checked, k=key: self._on_tool_action(k))
            tools_layout.addWidget(btn, i, 2)
            self.action_buttons[key] = btn

            # 卸载说明
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

        # 进度条 — 固定高度
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumHeight(22)
        layout.addWidget(self.progress_bar)

        # 日志 — 获得窗口拉伸时的全部额外空间
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
        self.log_text.setSizePolicy(
            self.log_text.sizePolicy().horizontalPolicy(),
            QSizePolicy.Policy.Expanding
        )
        layout.addWidget(self.log_text, 1)

        # 按钮行 — 固定在底部
        btn_layout = QHBoxLayout()
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
        """显示卸载说明弹窗"""
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
        
        if status["installed"]:
            self.status_labels[key].setText(f"✅ {status['status_text']}")
            self.status_labels[key].setStyleSheet("color: #27ae60; font-weight: bold;")
            self.action_buttons[key].setText("更新")
            self.action_buttons[key].setToolTip(f"更新 {TOOLS[key]['name']} 到最新版本")
        else:
            self.status_labels[key].setText("⚠️ 未安装")
            self.status_labels[key].setStyleSheet("color: #e67e22;")
            self.action_buttons[key].setText("安装")
            self.action_buttons[key].setToolTip(f"安装 {TOOLS[key]['name']}")
        
        self.action_buttons[key].setEnabled(True)
    
    def _on_all_checked(self):
        self.log_text.append("✅ 检测完成\n")
        all_installed = all(s["installed"] for s in self.tool_status.values())
        self.install_all_btn.setText("🔄 全部更新" if all_installed else "🚀 全部安装/更新")
    
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
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(len(actions))
        self.progress_bar.setValue(0)
        self.install_all_btn.setEnabled(False)
        for btn in self.action_buttons.values():
            btn.setEnabled(False)
        
        self.worker = InstallWorker(actions)
        self.worker.progress_text.connect(self._on_progress)
        self.worker.step_completed.connect(self._on_step_completed)
        self.worker.all_done.connect(self._on_all_done)
        self.worker.start()
    
    def _on_progress(self, text: str):
        self.log_text.append(text)
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def _on_step_completed(self, key: str, success: bool, message: str):
        self.progress_bar.setValue(self.progress_bar.value() + 1)
    
    def _on_all_done(self, results: dict):
        self.progress_bar.setVisible(False)
        self.install_all_btn.setEnabled(True)
        success_count = sum(1 for ok, _ in results.values() if ok)
        self.log_text.append(f"\n操作完成: {success_count}/{len(results)} 成功")
        self.log_text.append("🔍 重新检测工具状态...")
        self._check_tools()