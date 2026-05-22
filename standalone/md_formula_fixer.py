#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MD公式修复工具 独立版本
"""

import sys
import os
import re
import json
import time
import uuid
import difflib
import traceback
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Optional, Dict, Any, Set
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import Enum
from dataclasses import dataclass, field

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QListWidget, QListWidgetItem, QTextEdit,
    QProgressBar, QFileDialog, QGroupBox, QRadioButton, QCheckBox,
    QSpinBox, QComboBox, QLineEdit, QGridLayout, QMessageBox,
    QStatusBar, QFrame, QSplitter, QScrollArea, QTabWidget,
    QDialog, QDialogButtonBox, QTextBrowser, QStackedWidget,
    QButtonGroup, QMenu
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings, QUrl
from PyQt6.QtGui import (
    QFont, QColor, QTextCursor, QDragEnterEvent, QDropEvent
)


# ==================== 元信息 ====================
__author__ = "YQJ"
__version__ = "4.4.0"
__date__ = "2026.04.28"
__app_name__ = "MD公式修复工具"


# ==================== 风险等级枚举 ====================
class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def icon(self) -> str:
        return {"low": "🟢", "medium": "🟡", "high": "🔴"}[self.value]

    @property
    def color(self) -> str:
        return {"low": "#27ae60", "medium": "#e67e22", "high": "#e74c3c"}[self.value]

    @property
    def description(self) -> str:
        return {
            "low": "低风险，推荐始终开启",
            "medium": "中等风险，建议按需开启",
            "high": "高风险，可能改变原意"
        }[self.value]


# ==================== 文件状态枚举 ====================
class FileStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"

    @property
    def icon(self) -> str:
        icons = {
            FileStatus.PENDING: "⏳",
            FileStatus.PROCESSING: "🔄",
            FileStatus.SUCCESS: "✅",
            FileStatus.FAILED: "❌"
        }
        return icons.get(self, "📄")


# ==================== 数据类 ====================
@dataclass
class FormulaChange:
    original: str
    fixed: str
    changes: List[str]
    risk_level: str
    formula_type: str


@dataclass
class RepairProfile:
    """修复配置方案"""
    name: str
    description: str
    config: Dict[str, Any]

    @classmethod
    def get_builtin_profiles(cls) -> List['RepairProfile']:
        return [
            cls(
                name="🟢 安全模式",
                description="仅低风险修复：格式化、语法修正。适合重要文档",
                config={
                    'clean_extra_newlines': True,
                    'add_space_after_inline': True,
                    'subsup_fix': True,
                    'func_normalize': True,
                    'matrix_newline_remove': True,
                    'bracket_check': True,
                    'markdown_escape_inline': False,
                    'matrix_add_multiplication': False,
                    'dl_commands_to_text': False,
                    'remove_size_commands': False,
                    'bm_to_vec': False,
                    'inline_to_display': False,
                    'image_caption_enabled': False,
                    'respect_macros': True,
                    'escape_mode': 'off',
                    'fix_encoding': True,
                    'escape_isolated_dollars': True,
                    'bm_strict_mode': True,
                }
            ),
            cls(
                name="🟡 标准模式",
                description="平衡安全与效果，适合日常使用",
                config={
                    'clean_extra_newlines': True,       # 多余换行清理
                    'add_space_after_inline': True,     # 行内公式后加空格
                    'subsup_fix': True,                 # ✅ True — 修正常见错误 上下标修正
                    'func_normalize': False,            # ✅ 符合学术排版规范 函数名正体化
                    'matrix_newline_remove': True,      # ✅ 纯格式修复，零风险 矩阵末尾换行移除
                    'bracket_check': False,             # ✅ 自动补全缺失的括号 括号配对检查
                    'markdown_escape_inline': False,    # 防止 Markdown 解析器抢夺符号 Markdown符号转义
                    'matrix_add_multiplication': True,  # ✅ 纯格式修复，零风险 矩阵末尾换行移除
                    'dl_commands_to_text': True,        # ✅ 非标准命令转文本，配合 respect_macros 安全
                    'remove_size_commands': True,       # ✅ 清理复制粘贴残留，几乎无副作用 移除尺寸命令
                    'bm_to_vec': True,                  # ✅ 已开启 \bm严格模式
                    'inline_to_display': True,          # 独立行内转块级
                    'image_caption_enabled': True,      # 图片标题样式化
                    'respect_macros': True,             # 智能识别用户宏
                    'escape_mode': 'standard',          # Markdown 符号转义的模式
                    'fix_encoding': False,              # 编码修复
                    'escape_isolated_dollars': True,    # 转义模式
                    'bm_strict_mode': True,             # ✅ 已开启 \bm严格模式
                }
            ),
            cls(
                name="🟣 知乎发布",
                description="针对知乎平台优化：增强转义、添加间距",
                config={
                    'clean_extra_newlines': True,
                    'add_space_after_inline': True,
                    'subsup_fix': True,
                    'func_normalize': True,
                    'matrix_newline_remove': True,
                    'bracket_check': True,
                    'markdown_escape_inline': True,
                    'matrix_add_multiplication': True,
                    'dl_commands_to_text': True,
                    'remove_size_commands': True,
                    'bm_to_vec': False,
                    'inline_to_display': False,
                    'image_caption_enabled': False,
                    'respect_macros': True,
                    'escape_mode': 'zhihu',
                    'fix_encoding': True,
                    'escape_isolated_dollars': True,
                    'bm_strict_mode': True,
                }
            ),
            cls(
                name="🔵 学术论文",
                description="仅语法修正，保留所有数学语义",
                config={
                    'clean_extra_newlines': True,
                    'add_space_after_inline': False,
                    'subsup_fix': True,
                    'func_normalize': True,
                    'matrix_newline_remove': True,
                    'bracket_check': True,
                    'markdown_escape_inline': False,
                    'matrix_add_multiplication': False,
                    'dl_commands_to_text': False,
                    'remove_size_commands': False,
                    'bm_to_vec': False,
                    'inline_to_display': False,
                    'image_caption_enabled': False,
                    'respect_macros': True,
                    'escape_mode': 'off',
                    'fix_encoding': True,
                    'escape_isolated_dollars': False,
                    'bm_strict_mode': True,
                }
            ),
        ]


# ==================== 功能说明数据库 ====================
class FeatureHelpDatabase:
    """功能说明数据库"""

    @staticmethod
    def get_all_features() -> Dict[str, Dict[str, Any]]:
        features = {
            'clean_newlines': {
                'name': '多余换行清理', 'icon': '🧹', 'risk': 'low',
                'category': '格式与语法修复',
                'trigger': '文档中出现3个以上连续空行',
                'action': '将3个以上连续空行简化为2个空行',
                'example_before': '段落一\n\n\n\n段落二',
                'example_after': '段落一\n\n段落二',
                'why': 'Markdown中两个空行即可表示段落分隔，多余空行会让文档显得松散。',
                'problem': '几乎无风险。仅在作者故意使用多个空行表示特殊排版时有轻微影响。',
                'recommendation': '✅ 推荐始终开启',
            },
            'add_space_after_inline': {
                'name': '行内公式后添加空格', 'icon': '📏', 'risk': 'low',
                'category': '格式与语法修复',
                'trigger': '行内公式 $...$ 后紧跟中文字符',
                'action': '在公式结尾的 $ 与中文字符之间添加一个空格',
                'example_before': '$x+y$是方程的解',
                'example_after': '$x+y$ 是方程的解',
                'why': '知乎等平台的渲染器在公式后紧跟中文时可能解析失败。',
                'problem': '几乎无风险。仅在极少数情况下轻微改变排版。',
                'recommendation': '✅ 发布到知乎等内容平台时推荐开启',
            },
            'subsup_fix': {
                'name': '上下标范围修正', 'icon': '↗️', 'risk': 'low',
                'category': '格式与语法修复',
                'trigger': '公式中的上下标后跟多个字符但未用花括号包裹',
                'action': '自动添加花括号',
                'example_before': '$x^10$ → 显示为 x¹0',
                'example_after': '$x^{10}$ → 正确显示为 x¹⁰',
                'why': 'LaTeX规定上下标只作用于其后一个字符。',
                'problem': '极少数情况作者可能故意写x^2y表示x²乘以y。',
                'recommendation': '✅ 强烈推荐始终开启',
            },
            'func_normalize': {
                'name': '函数名正体化', 'icon': '📝', 'risk': 'low',
                'category': '格式与语法修复',
                'trigger': '公式中出现应使用正体的数学函数名',
                'action': '自动添加 \\ 前缀',
                'example_before': '$sin(x) + log(y)$',
                'example_after': '$\\sin(x) + \\log(y)$',
                'why': '数学排版规范要求函数名使用正体。',
                'problem': '正常使用场景风险极低。',
                'recommendation': '✅ 推荐开启，符合学术排版标准',
            },
            'matrix_newline_remove': {
                'name': '矩阵末尾换行移除', 'icon': '🧮', 'risk': 'low',
                'category': '格式与语法修复',
                'trigger': '矩阵环境最后一行后有多余的 \\\\',
                'action': '移除末尾多余的换行符',
                'example_before': '\\begin{pmatrix}\na & b \\\\\nc & d \\\\\n\\end{pmatrix}',
                'example_after': '\\begin{pmatrix}\na & b \\\\\nc & d\n\\end{pmatrix}',
                'why': '矩阵最后一行后面不应该有换行符。',
                'problem': '几乎无风险。',
                'recommendation': '✅ 推荐开启',
            },
            'bracket_check': {
                'name': '括号配对检查', 'icon': '🔍', 'risk': 'low',
                'category': '格式与语法修复',
                'trigger': '公式中存在 \\left 和 \\right 命令',
                'action': '检测括号配对，自动补全缺失的 \\right.',
                'example_before': '\\left( \\frac{1}{2}',
                'example_after': '\\left( \\frac{1}{2} \\right.',
                'why': '\\left和\\right必须成对出现。',
                'problem': '自动补全位置可能不是预期位置。',
                'recommendation': '✅ 推荐开启',
            },
            'markdown_escape_inline': {
                'name': 'Markdown符号转义', 'icon': '🛡️', 'risk': 'medium',
                'category': '语义增强',
                'trigger': '行内公式中存在 _ 或 * 等Markdown语法符号',
                'action': '添加反斜杠转义',
                'example_before': '$x_i$（可能被识别为斜体）',
                'example_after': '$x\\_i$ 或 $x_{i}$',
                'why': 'Markdown解析器会抢夺公式里的特殊符号。',
                'problem': '在已正确使用花括号的公式中转义是多余的。',
                'recommendation': '⚠️ 在知乎等内容平台发布时推荐开启',
            },
            'matrix_add_multiplication': {
                'name': '矩阵间自动添加乘号', 'icon': '✖️', 'risk': 'medium',
                'category': '语义增强',
                'trigger': '两个矩阵环境之间直接相邻',
                'action': '插入 \\times 符号',
                'example_before': '\\end{pmatrix}\\begin{pmatrix}',
                'example_after': '\\end{pmatrix} \\times \\begin{pmatrix}',
                'why': '两个矩阵相邻通常表示矩阵乘法。',
                'problem': '如果作者故意表示拼接或其他非乘法操作，会误加乘号。',
                'recommendation': '⚠️ 建议预览确认后再应用',
            },
            'dl_commands_to_text': {
                'name': '深度学习命令转文本', 'icon': '🤖', 'risk': 'medium',
                'category': '安全保护',
                'trigger': '公式中包含自定义命令（如\\ReLU、\\Softmax等）',
                'action': '转换为\\text{命令名}形式',
                'example_before': '$\\ReLU(x)$',
                'example_after': '$\\text{ReLU}(x)$',
                'why': '这些命令不是标准LaTeX命令。',
                'problem': '如果作者已定义这些命令，转换后会失效。建议配合「智能识别用户自定义命令」使用。',
                'recommendation': '⚠️ 建议开启。如果文档中使用了 \\newcommand 等自定义命令，强烈建议同时开启「智能识别用户自定义命令」。',
            },
            'remove_size_commands': {
                'name': '移除尺寸命令', 'icon': '📐', 'risk': 'medium',
                'category': '语义增强',
                'trigger': '公式中存在\\large、\\Large、\\small等',
                'action': '移除字号命令',
                'example_before': '$\\large (x + y)$',
                'example_after': '$(x + y)$',
                'why': '通常来自复制粘贴时的残留。',
                'problem': '如果作者故意使用会被误移除。',
                'recommendation': '⚠️ 建议预览确认后再应用',
            },
            'bm_to_vec': {
                'name': '\\bm → \\vec 转换', 'icon': '🔄', 'risk': 'high',
                'category': '高级转换',
                'trigger': '公式中包含\\bm{...}命令',
                'action': '智能判断后转换为\\vec{...}（矩阵环境中的\\bm不会被转换）',
                'example_before': '$\\bm{x}$（非矩阵环境）',
                'example_after': '$\\vec{x}$',
                'why': '部分文档用\\bm表示向量。',
                'problem': '🔴 <b>高风险！</b>\\bm表示粗体，\\vec表示向量箭头，语义不同。开启严格模式后仅在非矩阵环境且上下文为向量运算时转换。',
                'recommendation': '🔴 <b>非必要不开启</b>。开启后建议使用严格模式',
            },
            'inline_to_display': {
                'name': '独立行内公式转块级', 'icon': '📦', 'risk': 'high',
                'category': '高级转换',
                'trigger': '行内公式$...$单独占一行',
                'action': '转换为块级$$...$$',
                'example_before': '文字\n\n$E = mc^2$\n\n继续',
                'example_after': '文字\n\n$$E = mc^2$$\n\n继续',
                'why': '单独成行的公式通常应该块级显示。',
                'problem': '🔴 <b>高风险！</b>可能改变段落结构和排版意图。',
                'recommendation': '🔴 <b>非必要不开启</b>',
            },
            'image_caption': {
                'name': '图片标题样式化', 'icon': '🖼️', 'risk': 'high',
                'category': '用户定制',
                'trigger': '图片Markdown语法下方的*斜体文字*',
                'action': '转换为居中HTML样式标题',
                'example_before': '![图片](image.png)\n\n*这是标题*',
                'example_after': '![图片](image.png)\n<p style="...">这是标题</p>',
                'why': '纯Markdown的图片标题样式有限，使用HTML可以实现更丰富的样式效果。',
                'problem': '🔴 <b>高风险！</b>将纯Markdown替换为HTML，<b>不可逆</b>。HTML可能不被所有平台支持。',
                'recommendation': '🔴 <b>默认关闭，谨慎使用</b>。仅适合发布到支持HTML的平台。',
            },
            'respect_macros': {
                'name': '智能识别用户自定义命令',
                'icon': '🧠',
                'risk': 'low',
                'category': '安全保护',
                'trigger': '处理开始前自动扫描文档',
                'action': '扫描文档中的 \\newcommand、\\renewcommand、\\def 等定义。如果发现用户已定义了某个命令，后续处理中跳过该命令，保留原样。',
                'example_before': '用户定义 \\newcommand{\\ReLU}{...} 后，工具准备将 \\ReLU 转为 \\text{ReLU}',
                'example_after': '检测到用户已定义 \\ReLU，跳过转换，保留用户原有定义',
                'why': '避免覆盖用户的自定义宏定义。例如用户在文档中定义了 \\ReLU 命令，如果工具将其转为 \\text{ReLU}，会导致渲染结果不符合预期。',
                'problem': '扫描范围有限（仅扫描文件前 64KB），如果宏定义在文档很后面的位置可能扫描不到。',
                'recommendation': '✅ 推荐始终开启。如果文档中使用了 \\newcommand 等自定义命令，强烈建议开启。',
            },
            'fix_encoding': {
                'name': '编码问题修复',
                'icon': '🔤',
                'risk': 'low',
                'category': '格式与语法修复',
                'trigger': '公式中存在 \\x0a、\\x0d 等编码转义序列',
                'action': '修复编码问题，如将 \\x0a 转义为正确的形式',
                'example_before': '公式中出现 \\x0a 导致渲染异常',
                'example_after': '修复为 \\\\x0a 避免被误解析',
                'why': '某些编辑器或复制粘贴过程会产生编码问题，导致LaTeX渲染失败。',
                'problem': '正常使用场景风险极低。',
                'recommendation': '✅ 推荐始终开启',
            },
            'escape_isolated_dollars': {
                'name': '非公式美元符号转义',
                'icon': '💲',
                'risk': 'low',
                'category': '安全保护',
                'trigger': '文本中出现非公式内容的 $ 符号（如价格 $100）',
                'action': '检测并转义非公式内容的孤立 $ 符号',
                'example_before': '价格是 $100，不是公式',
                'example_after': '价格是 \\$100，不是公式',
                'why': '不必要的 $ 符号可能被Markdown解析器识别为公式边界，导致格式错乱。',
                'problem': '极少数情况下可能误转义合法的公式符号。',
                'recommendation': '✅ 推荐开启',
            },
        }
        return features

# ==================== 可拖拽文件列表（增强版） ====================
class DropFileListWidget(QListWidget):
    files_added = pyqtSignal(list)
    preview_requested = pyqtSignal(list)
    remove_requested = pyqtSignal()      # 新增信号
    clear_requested = pyqtSignal()       # 新增信号

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.file_paths: Dict[int, Path] = {}
        self.file_status: Dict[int, FileStatus] = {}
        self.completed_files: Set[str] = set()
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def _show_context_menu(self, position):
        menu = QMenu(self)
        
        # ★ 新增：打开所在文件夹
        open_folder_action = menu.addAction("📂 打开所在文件夹")
        open_folder_action.setToolTip("在文件管理器中打开所选文件所在目录")
        
        menu.addSeparator()
        
        preview_action = menu.addAction("🔍 预检预览")
        preview_action.setToolTip("预览所选文件的修复变更\n支持并排对比查看差异\n快捷键: Ctrl+P")
        preview_action.setShortcut("Ctrl+P")
        
        menu.addSeparator()
        
        remove_action = menu.addAction("❌ 移除选中")
        remove_action.setToolTip("从列表中移除所选文件\n快捷键: Delete")
        remove_action.setShortcut("Delete")
        
        menu.addSeparator()
        
        clear_action = menu.addAction("🗑️ 清空列表")
        clear_action.setToolTip("清空所有文件")
        
        selected_files = self._get_selected_files()
        
        if not selected_files:
            open_folder_action.setEnabled(False)
            preview_action.setEnabled(False)
            remove_action.setEnabled(False)
        
        if self.count() == 0:
            clear_action.setEnabled(False)
        
        action = menu.exec(self.mapToGlobal(position))
        
        if action == open_folder_action and selected_files:
            self._open_folder_for_selected(selected_files[0])
        elif action == preview_action and selected_files:
            self.preview_requested.emit(selected_files)
        elif action == remove_action:
            self.remove_requested.emit()
        elif action == clear_action:
            self.clear_requested.emit()

    def _get_selected_files(self) -> List[Path]:
        selected = []
        for item in self.selectedItems():
            row = self.row(item)
            if row in self.file_paths:
                selected.append(self.file_paths[row])
        return selected

    def _open_folder_for_selected(self, file_path: Path):
        """在文件管理器中打开文件所在位置"""
        import subprocess
        folder = str(file_path.parent)
        if sys.platform == 'win32':
            subprocess.run(['explorer', folder], shell=True)
        elif sys.platform == 'darwin':
            subprocess.run(['open', folder])
        else:
            subprocess.run(['xdg-open', folder])

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        md_files = []
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if not path.exists():
                continue
            if path.is_file() and path.suffix.lower() == '.md':
                md_files.append(path)
            elif path.is_dir():
                for ext in ['.md', '.MD']:
                    for fp in path.rglob(f"*{ext}"):
                        md_files.append(fp)
        if md_files:
            md_files = list(dict.fromkeys(md_files))
            self.files_added.emit(md_files)
            event.acceptProposedAction()
        else:
            event.ignore()

    def add_file(self, file_path: Path) -> bool:
        if file_path in self.file_paths.values():
            return False
        index = self.count()
        self.file_paths[index] = file_path
        self.file_status[index] = FileStatus.PENDING
        item = QListWidgetItem(f"{FileStatus.PENDING.icon} {file_path.name}")
        item.setToolTip(str(file_path))
        self.addItem(item)
        return True

    def add_files(self, files: List[Path]) -> int:
        added = 0
        for f in files:
            if str(f.absolute()) in self.completed_files: 
                continue
            if self.add_file(f):
                added += 1
        return added

    def remove_selected(self) -> List[Path]:
        removed = []
        for item in sorted(self.selectedItems(), key=lambda x: self.row(x), reverse=True):
            row = self.row(item)
            if row in self.file_paths:
                removed.append(self.file_paths[row])
                self.completed_files.discard(str(self.file_paths[row].absolute()))
                del self.file_paths[row]
                del self.file_status[row]
            self.takeItem(row)
        self._reindex()
        return removed

    def clear_all(self):
        self.clear()
        self.file_paths.clear()
        self.file_status.clear()
        self.completed_files.clear()

    def update_status(self, file_path: Path, status: FileStatus):
        colors = {
            FileStatus.SUCCESS: QColor(39, 174, 96),
            FileStatus.FAILED: QColor(231, 76, 60),
            FileStatus.PROCESSING: QColor(52, 152, 219),
            FileStatus.PENDING: QColor(128, 128, 128)
        }
        for index, path in self.file_paths.items():
            if path == file_path:
                self.file_status[index] = status
                if status == FileStatus.SUCCESS:
                    self.completed_files.add(str(file_path.absolute()))
                item = self.item(index)
                if item:
                    base_name = file_path.name
                    for old_icon in ["⏳", "🔄", "✅", "❌"]:
                        base_name = base_name.replace(f"{old_icon} ", "")
                    item.setText(f"{status.icon} {base_name}")
                    item.setForeground(colors.get(status, QColor(0, 0, 0)))
                break

    def get_all_files(self) -> List[Path]:
        return list(self.file_paths.values())

    def get_pending_files(self) -> List[Path]:
        return [path for idx, path in self.file_paths.items()
                if self.file_status[idx] == FileStatus.PENDING]

    def get_files_by_status(self, status: FileStatus) -> List[Path]:
        return [path for idx, path in self.file_paths.items()
                if self.file_status.get(idx) == status]

    def reset_all_status(self):
        for path in self.file_paths.values():
            self.update_status(path, FileStatus.PENDING)

    def _reindex(self):
        new_paths, new_status = {}, {}
        for i in range(self.count()):
            item = self.item(i)
            item_text = item.text()
            for idx, path in self.file_paths.items():
                if path.name in item_text:
                    new_paths[i] = path
                    new_status[i] = self.file_status[idx]
                    break
        self.file_paths = new_paths
        self.file_status = new_status


# ==================== 上下文相关类 ====================
class MacroScanner:
    """预扫描用户自定义宏定义"""
    NEWCOMMAND_PATTERN = (
        r'\\(?:newcommand|renewcommand|def|DeclareMathOperator)'
        r'\{?\\([a-zA-Z]+)\}?'
    )
    PROVIDECOMMAND_PATTERN = r'\\providecommand\{?\\([a-zA-Z]+)\}?'

    def __init__(self):
        self._cache: Dict[str, List[str]] = {}

    def scan_file(self, file_path: Path) -> List[str]:
        key = str(file_path.absolute())
        if key in self._cache:
            return self._cache[key]
        commands = []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read(65536)
            for match in re.finditer(self.NEWCOMMAND_PATTERN, content):
                cmd = match.group(1)
                if cmd not in commands:
                    commands.append(cmd)
            for match in re.finditer(self.PROVIDECOMMAND_PATTERN, content):
                cmd = match.group(1)
                if cmd not in commands:
                    commands.append(cmd)
        except Exception:
            pass
        self._cache[key] = commands
        return commands


class FormulaContext:
    """公式上下文信息"""
    def __init__(self):
        self.contains_matrix = False
        self.contains_sum = False
        self.contains_integral = False
        self.matrix_row_count = 0
        self.surrounding_text = ""
        self.is_standalone = False

    @classmethod
    def from_formula(cls, formula: str, surrounding_text: str = "") -> 'FormulaContext':
        ctx = cls()
        matrix_envs = ['matrix', 'pmatrix', 'bmatrix', 'Bmatrix',
                       'vmatrix', 'Vmatrix', 'smallmatrix']
        for env in matrix_envs:
            if f'\\begin{{{env}}}' in formula:
                ctx.contains_matrix = True
                rows = len(re.findall(r'\\\\', formula))
                ctx.matrix_row_count = rows + 1 if rows > 0 else 1
                break
        ctx.contains_sum = bool(re.search(
            r'\\(sum|prod|bigcup|bigcap|bigoplus|bigotimes)', formula))
        ctx.contains_integral = bool(re.search(
            r'\\(int|iint|iiint|oint)', formula))
        if surrounding_text:
            ctx.surrounding_text = surrounding_text
            stripped = surrounding_text.strip()
            if not stripped or '\n' not in stripped:
                ctx.is_standalone = True
        return ctx


# ==================== 核心处理模块 ====================

# --- 编码问题修复器 ---
class FormulaEncodingFixer:
    """修复公式中的编码问题"""
    
    ENCODING_FIXES = {
        r'\\(?=x[0-9a-fA-F]{2})': r'\\\\',
    }
    
    SPECIAL_CHAR_FIXES = {
        '\x00': '',
        '\r\n': '\n',
        '\r': '\n',
    }
    
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
    
    def fix_encoding(self, formula: str) -> Tuple[str, int]:
        if not self.enabled:
            return formula, 0
        
        fixed_formula = formula
        fix_count = 0
        
        for char, replacement in self.SPECIAL_CHAR_FIXES.items():
            if char in fixed_formula:
                old = fixed_formula
                fixed_formula = fixed_formula.replace(char, replacement)
                if old != fixed_formula:
                    fix_count += 1
        
        def fix_hex_escape(match):
            nonlocal fix_count
            fix_count += 1
            return '\\\\' + match.group(0).lstrip('\\')
        
        fixed_formula = re.sub(r'(?<!\\)\\x[0-9a-fA-F]{2}', fix_hex_escape, fixed_formula)
        
        return fixed_formula, fix_count
    
    def fix_text(self, text: str) -> Tuple[str, int]:
        if not self.enabled:
            return text, 0
        
        formulas = []
        def save_formula(m):
            formulas.append(m.group(0))
            return f'__FORMULA_{len(formulas)-1}__'
        
        text = re.sub(r'\$\$.*?\$\$', save_formula, text, flags=re.DOTALL)
        text = re.sub(r'\$[^$\n]+?\$', save_formula, text)
        
        total_fixes = 0
        for char, replacement in self.SPECIAL_CHAR_FIXES.items():
            if char in text:
                old = text
                text = text.replace(char, replacement)
                if old != text:
                    total_fixes += 1
        
        for i, formula in enumerate(formulas):
            text = text.replace(f'__FORMULA_{i}__', formula)
        
        return text, total_fixes


# --- 非公式美元符号转义器 ---
class DollarSignEscaper:
    """检测并转义非公式内容的孤立 $ 符号"""
    
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
    
    def escape(self, text: str) -> Tuple[str, int]:
        if not self.enabled:
            return text, 0
        
        protected_formulas = []
        protected_blocks = []
        escape_count = 0
        
        # 步骤0: 处理表格行（在保护前处理其中的 $）
        table_pattern = re.compile(r'^\|.+\|$', re.MULTILINE)
        
        def fix_table_row(m):
            nonlocal escape_count
            row = m.group(0)
            
            # 保护表格行中的内联公式
            table_formulas = []
            def save_tf(fm):
                table_formulas.append(fm.group(0))
                return f'__TF_{len(table_formulas)-1}__'
            row = re.sub(r'\$[^$\n\|]+?\$', save_tf, row)
            
            # 转义表格行中孤立的 $
            new_row = []
            for ch in row:
                if ch == '$':
                    new_row.append(r'\$')
                    escape_count += 1
                else:
                    new_row.append(ch)
            row = ''.join(new_row)
            
            # 恢复表格行内的公式
            for i, fm in enumerate(table_formulas):
                row = row.replace(f'__TF_{i}__', fm)
            
            protected_blocks.append(row)
            return f'__TABLE_ROW_{len(protected_blocks)-1}__'
        
        text = table_pattern.sub(fix_table_row, text)
        
        # 步骤1: 保护块级公式
        def save_display(m):
            protected_formulas.append(m.group(0))
            return f'__DISPLAY_FORMULA_{len(protected_formulas)-1}__'
        text = re.sub(r'\$\$.*?\$\$', save_display, text, flags=re.DOTALL)
        
        # 步骤2: 保护行内公式
        def save_inline(m):
            protected_formulas.append(m.group(0))
            return f'__INLINE_FORMULA_{len(protected_formulas)-1}__'
        text = re.sub(r'\$[^$\n]+?\$', save_inline, text)
        
        # 步骤3: 保护代码块
        def save_code(m):
            protected_blocks.append(m.group(0))
            return f'__CODE_BLOCK_{len(protected_blocks)-1}__'
        text = re.sub(r'```.*?```', save_code, text, flags=re.DOTALL)
        text = re.sub(r'`[^`\n]+`', save_code, text)
        
        # 步骤4: 处理剩余文本中的孤立 $
        lines = text.split('\n')
        new_lines = []
        
        for line in lines:
            # 跳过已保护的表格行和代码块
            if re.match(r'^__(?:TABLE_ROW|CODE_BLOCK)_\d+__$', line):
                new_lines.append(line)
                continue
            
            # 转义孤立的 $
            new_line = []
            for i, ch in enumerate(line):
                if ch == '$':
                    # 检查是否是孤立美元符号
                    if self._is_truly_isolated(line, i):
                        new_line.append(r'\$')
                        escape_count += 1
                    else:
                        new_line.append(ch)
                else:
                    new_line.append(ch)
            
            new_lines.append(''.join(new_line))
        
        text = '\n'.join(new_lines)
        
        # 步骤5: 恢复所有保护的内容
        for i, formula in enumerate(protected_formulas):
            text = text.replace(f'__DISPLAY_FORMULA_{i}__', formula)
            text = text.replace(f'__INLINE_FORMULA_{i}__', formula)
        
        for i, block in enumerate(protected_blocks):
            text = text.replace(f'__TABLE_ROW_{i}__', block)
            text = text.replace(f'__CODE_BLOCK_{i}__', block)
        
        return text, escape_count
    
    def _is_truly_isolated(self, line: str, pos: int) -> bool:
        """判断 $ 是否真正孤立（不是公式的一部分）"""
        # 已经转义的跳过
        if pos > 0 and line[pos-1] == '\\':
            return False
        
        # 查找行中所有 $ 的位置
        all_positions = [i for i, ch in enumerate(line) if ch == '$' and (i == 0 or line[i-1] != '\\')]
        
        # 如果 $ 数量 >= 2 且 pos 在成对位置中，不是孤立的
        if len(all_positions) >= 2 and pos in all_positions:
            idx = all_positions.index(pos)
            if idx % 2 == 0 and idx + 1 < len(all_positions):
                # 是开始 $，检查中间内容
                next_pos = all_positions[idx + 1]
                content = line[pos+1:next_pos]
                if self._is_formula_content(content):
                    return False
            elif idx % 2 == 1:
                # 是结束 $
                return False
        
        # 孤立的 $（如 "价格是 $100"）
        return True
    
    def _is_formula_content(self, content: str) -> bool:
        """判断内容是否像数学公式"""
        if not content.strip():
            return False
        # 纯数字不是公式
        if re.match(r'^\d+(\.\d+)?$', content.strip()):
            return False
        
        math_indicators = [
            '\\', '^', '_', '{', '}',
            '+', '-', '*', '/', '=',
            '\\sin', '\\cos', '\\log',
            '\\frac', '\\sum', '\\int',
            '\\alpha', '\\beta',
        ]
        return any(ind in content for ind in math_indicators)

# --- Markdown符号转义器 ---
class MarkdownEscaper:
    STANDARD_MAP = {'_': r'\_', '*': r'\*'}
    ZHIHU_MAP = {'_': r'\_', '*': r'\*', '#': r'\#', '~': r'\textasciitilde{}', '&': r'\&'}

    def __init__(self, mode: str = 'standard'):
        self.mode = mode
        if mode == 'zhihu':
            self.escape_map = self.ZHIHU_MAP
        elif mode == 'standard':
            self.escape_map = self.STANDARD_MAP
        else:
            self.escape_map = {}

    @property
    def enabled(self) -> bool:
        return self.mode != 'off' and len(self.escape_map) > 0

    def escape_formula(self, formula: str) -> Tuple[str, int]:
        if not self.enabled:
            return formula, 0
        count = 0
        command_pattern = r'\\(?:[a-zA-Z]+|.)'
        protected_ranges = []
        for m in re.finditer(command_pattern, formula):
            protected_ranges.append((m.start(), m.end()))
        brace_depth = 0
        brace_start = -1
        for i, ch in enumerate(formula):
            if ch == '{' and (i == 0 or formula[i-1] != '\\'):
                if brace_depth == 0:
                    if i > 0 and formula[i-1] in '_^':
                        brace_start = i - 1
                    else:
                        brace_start = i
                brace_depth += 1
            elif ch == '}' and (i == 0 or formula[i-1] != '\\'):
                brace_depth -= 1
                if brace_depth == 0 and brace_start >= 0:
                    protected_ranges.append((brace_start, i + 1))
                    brace_start = -1
        protected_ranges.sort()
        merged = []
        for start, end in protected_ranges:
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        new_chars = []
        i = 0
        for start, end in merged:
            while i < start:
                if formula[i] in self.escape_map:
                    new_chars.append(self.escape_map[formula[i]])
                    count += 1
                else:
                    new_chars.append(formula[i])
                i += 1
            new_chars.append(formula[start:end])
            i = end
        while i < len(formula):
            if formula[i] in self.escape_map:
                new_chars.append(self.escape_map[formula[i]])
                count += 1
            else:
                new_chars.append(formula[i])
            i += 1
        return ''.join(new_chars), count


class FunctionNameNormalizer:
    STANDARD_FUNCTIONS = {
        'sin', 'cos', 'tan', 'cot', 'sec', 'csc',
        'arcsin', 'arccos', 'arctan', 'arccot', 'arcsec', 'arccsc',
        'sinh', 'cosh', 'tanh', 'coth', 'sech', 'csch',
        'exp', 'log', 'ln', 'lg', 'det', 'gcd', 'lcm',
        'lim', 'limsup', 'liminf', 'sup', 'inf',
        'max', 'min', 'argmax', 'argmin',
        'dim', 'ker', 'deg', 'hom', 'Pr', 'arg', 'Re', 'Im',
        'mod', 'bmod', 'pmod', 'binom',
    }

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def normalize(self, formula: str) -> Tuple[str, int]:
        if not self.enabled:
            return formula, 0
        count = 0
        for func in sorted(self.STANDARD_FUNCTIONS, key=len, reverse=True):
            pattern = rf'(?<!\\)\b{re.escape(func)}\b'
            replacement = rf'\\{func}'
            new_formula, n = re.subn(pattern, replacement, formula)
            if n > 0:
                formula = new_formula
                count += n
        return formula, count


class SubSupFixer:
    SEPARATORS = re.compile(r'[,;:=<>+\-*/\\\(\)\[\]\|&!\^\{\}]')
    ALPHANUM = re.compile(r'^[a-zA-Z0-9]+$')

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def fix(self, formula: str) -> Tuple[str, int]:
        if not self.enabled:
            return formula, 0
        count = 0
        protected_brackets = []
        def save_bracket(m):
            protected_brackets.append(m.group(0))
            return f'__BRACKET_{len(protected_brackets) - 1}__'
        formula = re.sub(r'\{[^{}]*\}', save_bracket, formula)

        def fix_sup(match):
            nonlocal count
            prefix, sup_content = match.group(1), match.group(2)
            if self.SEPARATORS.search(sup_content):
                return match.group(0)
            if len(sup_content) == 1 or sup_content.startswith('\\'):
                return match.group(0)
            if self.ALPHANUM.match(sup_content) and len(sup_content) > 1:
                # 检查上标后是否紧跟字母（如 a^2b，可能是 a^2 * b）
                end_pos = match.end()
                # 需要从公式中获取后续字符
                # 简单处理：如果是数字+字母组合，且数字在前，字母在后，只取数字部分
                if re.match(r'^\d+[a-zA-Z]', sup_content):
                    # 分离数字和字母部分
                    digits = re.match(r'^(\d+)', sup_content).group(1)
                    letters = sup_content[len(digits):]
                    # 这里无法简单处理，因为需要修改公式结构
                    # 保守处理：只包裹数字部分
                    count += 1
                    return f'{prefix}^{{{digits}}}{letters}'
                count += 1
                return f'{prefix}^{{{sup_content}}}'
            return match.group(0)

        formula = re.sub(r'(\S)\^([^\s{]+)', fix_sup, formula)

        def fix_sub(match):
            nonlocal count
            prefix, sub_content = match.group(1), match.group(2)
            if self.SEPARATORS.search(sub_content):
                return match.group(0)
            if len(sub_content) == 1 or sub_content.startswith('\\'):
                return match.group(0)
            if self.ALPHANUM.match(sub_content) and len(sub_content) > 1:
                count += 1
                return f'{prefix}_{{{sub_content}}}'
            return match.group(0)

        formula = re.sub(r'(\S)_([^\s{]+)', fix_sub, formula)
        for i, bracket in enumerate(protected_brackets):
            formula = formula.replace(f'__BRACKET_{i}__', bracket)
        return formula, count


class BracketChecker:
    LEFT_PATTERNS = [r'\\left\(', r'\\left\[', r'\\left\\\{', r'\\left\.', r'\\left\|']
    RIGHT_PATTERNS = [r'\\right\)', r'\\right\]', r'\\right\\\}', r'\\right\.', r'\\right\|']

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def check_and_fix(self, formula: str) -> Tuple[str, List[str]]:
        if not self.enabled:
            return formula, []
        logs = []
        formula, log = self._fix_left_right(formula)
        if log:
            logs.append(log)
        formula, log = self._fix_braces(formula)
        if log:
            logs.append(log)
        return formula, logs

    def _fix_left_right(self, formula: str) -> Tuple[str, List[str]]:
        left_count = sum(len(re.findall(pat, formula)) for pat in self.LEFT_PATTERNS)
        right_count = sum(len(re.findall(pat, formula)) for pat in self.RIGHT_PATTERNS)
        if left_count > right_count:
            formula = formula.rstrip() + ' \\right.'
            return formula, [f"补全缺失的\\right. (left:{left_count}, right:{right_count})"]
        elif right_count > left_count:
            return formula, [f"检测到{right_count - left_count}处多余的\\right，请手动检查"]
        return formula, []

    def _fix_braces(self, formula: str) -> Tuple[str, List[str]]:
        stack = []
        for i, ch in enumerate(formula):
            if ch == '{' and (i == 0 or formula[i - 1] != '\\'):
                stack.append(i)
            elif ch == '}' and (i == 0 or formula[i - 1] != '\\'):
                if stack:
                    stack.pop()
                else:
                    return formula, [f"检测到多余的右花括号在位置{i}"]
        if stack:
            return formula, [f"检测到{len(stack)}个未闭合的左花括号"]
        return formula, []


class ImageCaptionOptimizer:
    COLOR_SCHEMES = {
        'purple': '#9b59b6', 'blue': "#4181ab", 'red': '#e74c3c',
        'green': '#27ae60', 'orange': '#e67e22', 'black': '#000000',
        'dark_purple': '#800080', 'medium_purple': '#9370DB',
        'light_purple': '#c39bd3', 'teal': '#1abc9c', 'navy': '#2c3e50'
    }

    def __init__(self, color_scheme: str = 'purple', enabled: bool = True):
        self.enabled = enabled
        self.color_code = self.COLOR_SCHEMES.get(color_scheme, '#9b59b6')
        self.image_pattern = re.compile(r'!\[[^\]]*\]\([^)]+\)')

    def optimize(self, text: str) -> Tuple[str, int]:
        if not self.enabled:
            return text, 0
        lines = text.split('\n')
        new_lines = []
        i = 0
        count = 0
        while i < len(lines):
            current_line = lines[i]
            if self.image_pattern.search(current_line):
                j = i + 1
                while j < len(lines) and lines[j].strip() == '':
                    j += 1
                if j < len(lines):
                    next_line = lines[j].strip()
                    caption_match = re.match(r'^\*([^*]+)\*$', next_line)
                    if caption_match:
                        caption = caption_match.group(1).strip()
                        new_lines.append(current_line)
                        new_lines.append(
                            f'<p style="text-align: center; '
                            f'margin-top: 0.5em; margin-bottom: 1em;">'
                            f'<strong style="color: {self.color_code};">'
                            f'{caption}</strong></p>'
                        )
                        i = j + 1
                        count += 1
                        continue
            new_lines.append(current_line)
            i += 1
        return '\n'.join(new_lines), count


class ConfigurableFormulaFixer:
    """可配置的公式修复器 - 增强版"""
    DEFAULT_DL_COMMANDS = [
        'LayerNorm', 'Linear', 'ReLU', 'GELU', 'SiLU', 'Swish',
        'Softmax', 'Sigmoid', 'Tanh', 'Dropout', 'BatchNorm',
        'InstanceNorm', 'GroupNorm', 'RMSNorm', 'LSTM', 'GRU',
        'Attention', 'MultiHeadAttention', 'Transformer',
        'Encoder', 'Decoder', 'Embedding', 'PositionalEncoding',
        'MLP', 'CNN', 'RNN', 'FFN', 'MHA', 'MSE', 'MAE',
        'CrossEntropy', 'BCE', 'Adam', 'SGD', 'AdamW'
    ]
    MATRIX_ENVS = ['matrix', 'pmatrix', 'bmatrix', 'Bmatrix',
                   'vmatrix', 'Vmatrix', 'smallmatrix']

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or self.get_default_config()
        escape_mode = self.config.get('escape_mode', 'standard')
        self.escaper = MarkdownEscaper(mode=escape_mode)
        self.normalizer = FunctionNameNormalizer(enabled=self.config.get('func_normalize', True))
        self.subsup_fixer = SubSupFixer(enabled=self.config.get('subsup_fix', True))
        self.bracket_checker = BracketChecker(enabled=self.config.get('bracket_check', True))
        self.macro_scanner = MacroScanner()
        self.encoding_fixer = FormulaEncodingFixer(enabled=self.config.get('fix_encoding', True))

    @staticmethod
    def get_default_config() -> Dict[str, Any]:
        return {
            'bm_to_vec': True,                  # 🔴 高风险，保持关闭 \bm→\vec 转换
            'remove_size_commands': True,       # ✅ 清理复制粘贴残留，几乎无副作用 移除尺寸命令
            'matrix_newline_remove': True,      # ✅ 纯格式修复，零风险 矩阵末尾换行移除
            'matrix_add_multiplication': True,  # ✅ 语义明确（矩阵相邻=乘法）矩阵间添加乘号
            'dl_commands_to_text': True,        # ✅ 非标准命令转文本，配合 respect_macros 安全
            'dl_commands_list': ConfigurableFormulaFixer.DEFAULT_DL_COMMANDS[:],

            'markdown_escape_inline': False,    # ✅ 防止 Markdown 解析器抢夺符号 Markdown符号转义
            'escape_mode': 'standard',          # ✅ Markdown 符号转义的模式

            'func_normalize': False,            # ✅ 符合学术排版规范 函数名正体化
            'subsup_fix': False,                # ✅ True — 修正常见错误 上下标修正
            'bracket_check': False,             # ✅ 自动补全缺失的括号 括号配对检查
            'respect_macros': True,             # ✅ 已开启 智能识别用户宏

            'bm_strict_mode': True,             # ✅ 已开启 \bm严格模式
        }

    def _smart_bm_to_vec(self, formula: str, context: FormulaContext = None) -> Tuple[str, int]:
        """智能 \bm 转 \vec，考虑上下文"""
        if not self.config.get('bm_to_vec') or '\\bm' not in formula:
            return formula, 0
        
        if context and context.contains_matrix:
            return formula, 0
        
        bm_contents = re.findall(r'\\bm\{([^}]*?)\}', formula)
        bm_single = re.findall(r'\\bm\s+([a-zA-Z])', formula)
        bm_single2 = re.findall(r'\\bm([a-zA-Z])', formula)
        
        all_bm_targets = bm_contents + bm_single + bm_single2
        
        if not all_bm_targets:
            return self._apply_bm_to_vec(formula)
        
        vector_indicators = [
            '\\vec', '\\cdot', '\\times', '\\sum', '\\int', '\\partial',
            '\\nabla', '\\mathbf', '\\hat', '\\bar', '\\tilde',
        ]
        
        all_single_letter = all(
            len(t.strip()) <= 1 and (t.strip().isalpha() if t.strip() else False) 
            for t in all_bm_targets
        )
        
        has_vector_context = any(ind in formula for ind in vector_indicators)
        
        # 决定是否转换的逻辑
        should_convert = False
        if has_vector_context and all_single_letter:
            should_convert = True
        elif all_single_letter and len(all_bm_targets) == 1:
            should_convert = True
        elif has_vector_context and not self.config.get('bm_strict_mode', True):
            should_convert = True
        
        if should_convert:
            return self._apply_bm_to_vec(formula)
        return formula, 0

    def _apply_bm_to_vec(self, formula: str) -> Tuple[str, int]:
        """执行 \\bm 到 \\vec 的实际替换"""
        count_before = len(re.findall(r'\\bm', formula))
        formula = re.sub(r'\\bm\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}', r'\\vec{\1}', formula)
        formula = re.sub(r'\\bm\{([^}]*?)\}', r'\\vec{\1}', formula, flags=re.DOTALL)
        formula = re.sub(r'\\bm\s+([a-zA-Z])', r'\\vec{\1}', formula)
        formula = re.sub(r'\\bm([a-zA-Z])', r'\\vec{\1}', formula)
        count_after = len(re.findall(r'\\bm', formula))
        return formula, count_before - count_after

    def fix_formula(self, formula: str, is_display: bool = False,
                    context=None, user_macros: List[str] = None) -> Tuple[str, List[str]]:
        logs = []
        if user_macros is None:
            user_macros = []

        # 0. 编码问题修复（最高优先级）
        formula, cnt = self.encoding_fixer.fix_encoding(formula)
        if cnt > 0:
            logs.append(f"编码修复: {cnt}处")

        formula, bracket_logs = self.bracket_checker.check_and_fix(formula)
        logs.extend(bracket_logs)

        formula, cnt = self.subsup_fixer.fix(formula)
        if cnt > 0:
            logs.append(f"上下标修正: {cnt}处")

        formula, cnt = self.normalizer.normalize(formula)
        if cnt > 0:
            logs.append(f"函数名正体化: {cnt}处")

        if not is_display and self.config.get('markdown_escape_inline', False):
            formula, cnt = self.escaper.escape_formula(formula)
            if cnt > 0:
                mode_label = {'standard': '标准', 'zhihu': '知乎增强', 'off': '关闭'}.get(
                    self.config.get('escape_mode', 'standard'), '标准')
                logs.append(f"Markdown转义({mode_label}): {cnt}处")

        # 3. \bm 转 \vec（智能版）
        formula, cnt = self._smart_bm_to_vec(formula, context)
        if cnt > 0:
            logs.append(f"\\bm→\\vec: {cnt}处")

        if self.config.get('remove_size_commands'):
            for cmd in ['\\large', '\\Large', '\\small', '\\footnotesize', '\\tiny']:
                if cmd in formula:
                    formula = re.sub(rf'{re.escape(cmd)}\s*\(', '(', formula)
                    formula = re.sub(rf'{re.escape(cmd)}\b', '', formula)
                    logs.append(f"移除: {cmd}")

        if self.config.get('matrix_newline_remove') and any(env in formula for env in self.MATRIX_ENVS):
            old = formula
            formula = re.sub(r'\\\\+(\s*\\\])', r'\1', formula)
            formula = re.sub(r'\\\\+(\s*\$\$)', r'\1', formula)
            for env in self.MATRIX_ENVS:
                formula = re.sub(rf'\\\\+(\s*\\end{{{env}}})', r'\1', formula)
            formula = re.sub(r'\\\\+\s*$', '', formula)
            if formula != old:
                logs.append("移除矩阵末尾换行")

        if self.config.get('matrix_add_multiplication') and any(env in formula for env in self.MATRIX_ENVS):
            begin_p = r'\\begin\{(?:' + '|'.join(self.MATRIX_ENVS) + r')\}'
            end_p = r'\\end\{(?:' + '|'.join(self.MATRIX_ENVS) + r')\}'
            pattern = r'(' + end_p + r')\s+(' + begin_p + r')'
            cnt = [0]
            def add_times(m):
                if r'\times' not in m.group(0):
                    cnt[0] += 1
                    return m.group(1) + r' \times ' + m.group(2)
                return m.group(0)
            formula = re.sub(pattern, add_times, formula)
            if cnt[0] > 0:
                logs.append(f"添加矩阵乘号: {cnt[0]}处")

        if self.config.get('dl_commands_to_text'):
            dl_list = self.config.get('dl_commands_list', self.DEFAULT_DL_COMMANDS)
            for cmd in dl_list:
                if self.config.get('respect_macros', True) and cmd in user_macros:
                    continue
                pattern = rf'\\{cmd}\b(?!\w)'
                if re.search(pattern, formula):
                    formula = re.sub(pattern, rf'\\text{{{cmd}}}', formula)
                    logs.append(f"{cmd}→\\text")

        formula = re.sub(r'[ \t]+', ' ', formula)
        formula = re.sub(r'[ \t]+\n', '\n', formula)
        formula = re.sub(r'\n[ \t]+', '\n', formula)
        formula = formula.strip()
        return formula, logs


class FormulaPreviewer:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.fixer = ConfigurableFormulaFixer(config.get('formula_config', {}))
        self.macro_scanner = MacroScanner()

    def preview(self, text: str, file_path: Path = None) -> List[FormulaChange]:
        changes = []
        user_macros = []
        if file_path and self.config.get('formula_config', {}).get('respect_macros', True):
            user_macros = self.macro_scanner.scan_file(file_path)
        for m in re.finditer(r'\$\$(.*?)\$\$', text, re.DOTALL):
            original = m.group(1).strip()
            context = FormulaContext.from_formula(original, '')
            fixed, logs = self.fixer.fix_formula(original, is_display=True, context=context, user_macros=user_macros)
            if original != fixed:
                changes.append(FormulaChange(original=original, fixed=fixed, changes=logs,
                    risk_level=self._assess_risk(logs), formula_type='display'))
        for m in re.finditer(r'(?<!\$)\$(?!\$)(.*?)(?<!\$)\$(?!\$)', text, re.DOTALL):
            original = m.group(1).strip()
            context = FormulaContext.from_formula(original, '')
            fixed, logs = self.fixer.fix_formula(original, is_display=False, context=context, user_macros=user_macros)
            if original != fixed:
                changes.append(FormulaChange(original=original, fixed=fixed, changes=logs,
                    risk_level=self._assess_risk(logs), formula_type='inline'))
        return changes

    def _assess_risk(self, logs: List[str]) -> str:
        high_risk_kw = ['\\bm→\\vec', '转块级']
        medium_risk_kw = ['乘号', '\\text', '移除尺寸', 'Markdown转义', '知乎增强']
        for log in logs:
            for kw in high_risk_kw:
                if kw in log:
                    return 'high'
        for log in logs:
            for kw in medium_risk_kw:
                if kw in log:
                    return 'medium'
        return 'low'


class MarkdownFormulaProcessor:
    """Markdown公式处理器 - 增强版"""
    def __init__(self, input_file: Path, output_dir: Path = None, config: Dict[str, Any] = None):
        self.input_file = input_file
        self.output_dir = output_dir or input_file.parent
        self.config = config or {}
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.caption_optimizer = ImageCaptionOptimizer(
            color_scheme=self.config.get('image_caption_color', 'purple'),
            enabled=self.config.get('image_caption_enabled', True))
        self.formula_fixer = ConfigurableFormulaFixer(self.config.get('formula_config', {}))
        self.dollar_escaper = DollarSignEscaper(
            enabled=self.config.get('escape_isolated_dollars', True))
        self.encoding_fixer = FormulaEncodingFixer(
            enabled=self.config.get('fix_encoding', True))
        self.stats = {
            'total_formulas': 0, 'fixed_formulas': 0,
            'inline_formulas': 0, 'display_formulas': 0,
            'converted_to_display': 0, 'matrix_formulas': 0,
            'image_captions_fixed': 0, 'func_normalized': 0,
            'subsup_fixed': 0, 'markdown_escaped': 0,
            'bracket_fixed': 0, 'bm_converted': 0,
            'encoding_fixed': 0, 'dollar_escaped': 0,
            'fix_logs': []
        }

    def process(self, output_filename: str = None) -> Tuple[str, Path]:
        with open(self.input_file, 'r', encoding='utf-8') as f:
            text = f.read()
        if not text:
            raise ValueError(f"文件为空: {self.input_file}")
        if self._is_all_disabled():
            if not output_filename:
                output_filename = f"{self.input_file.stem}_fixed.md"
            output_path = self.output_dir / output_filename
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(text)
            return text, output_path
        
        # 编码修复
        try:
            text, encoding_count = self.encoding_fixer.fix_text(text)
            if encoding_count > 0:
                self.stats['encoding_fixed'] += encoding_count
        except Exception as e:
            print(f"编码修复失败: {e}")
        
        # 转义孤立美元符号
        try:
            text, dollar_count = self.dollar_escaper.escape(text)
            if dollar_count > 0:
                self.stats['dollar_escaped'] += dollar_count
        except Exception as e:
            print(f"美元符号转义失败: {e}")
        
        try:
            text, caption_count = self.caption_optimizer.optimize(text)
            self.stats['image_captions_fixed'] = caption_count
        except Exception as e:
            print(f"图片标题优化失败: {e}")
        try:
            text = self._process_formulas(text)
        except Exception as e:
            print(f"公式处理失败: {e}")
            traceback.print_exc()
        if text is None:
            raise ValueError("处理后的文本为None，处理失败")
        if not output_filename:
            output_filename = f"{self.input_file.stem}_fixed.md"
        output_path = self.output_dir / output_filename
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(text)
        return text, output_path

    def _is_all_disabled(self) -> bool:
        fc = self.config.get('formula_config', {})
        return (
            not self.config.get('image_caption_enabled', False) and
            not self.config.get('clean_extra_newlines', False) and
            not self.config.get('add_space_after_inline', False) and
            not self.config.get('inline_to_display', False) and
            not self.config.get('escape_isolated_dollars', False) and
            not self.config.get('fix_encoding', False) and
            not fc.get('bm_to_vec', False) and
            not fc.get('remove_size_commands', False) and
            not fc.get('matrix_newline_remove', False) and
            not fc.get('matrix_add_multiplication', False) and
            not fc.get('dl_commands_to_text', False) and
            not fc.get('markdown_escape_inline', False) and
            not fc.get('func_normalize', False) and
            not fc.get('subsup_fix', False) and
            not fc.get('bracket_check', False)
        )

    def _protect_blocks(self, text: str) -> Tuple[str, List[str]]:
        protected = []
        text = self._protect_fenced_blocks(text, protected)
        text = self._protect_inline_codes(text, protected)
        return text, protected

    def _protect_fenced_blocks(self, text: str, protected: List[str]) -> str:
        fence_positions = []
        pattern = re.compile(r'(?:^|\n)```')
        for m in pattern.finditer(text):
            pos = m.start()
            if text[pos] == '\n':
                pos += 1
            fence_positions.append(pos)
        if len(fence_positions) < 2:
            return text
        i = 0
        while i + 1 < len(fence_positions):
            start = fence_positions[i]
            end_line_start = fence_positions[i + 1]
            end_line = text.find('\n', end_line_start)
            if end_line == -1:
                end_line = len(text)
            between = text[start:end_line_start]
            if '\n' not in between.strip():
                i += 1
                continue
            full_block = text[start:end_line]
            protected.append(full_block)
            placeholder = f'__PROTECTED_{len(protected) - 1}__'
            text = text[:start] + placeholder + text[end_line:]
            offset = len(placeholder) - len(full_block)
            for j in range(i + 2, len(fence_positions)):
                fence_positions[j] += offset
            i += 2
        return text

    def _protect_inline_codes(self, text: str, protected: List[str]) -> str:
        lines = text.split('\n')
        new_lines = []
        for line in lines:
            new_line = re.sub(r'`([^`\n]+)`', lambda m: self._save_inline(m.group(0), protected), line)
            new_lines.append(new_line)
        return '\n'.join(new_lines)

    def _save_inline(self, code: str, protected: List[str]) -> str:
        if re.match(r'^__PROTECTED_\d+__$', code):
            return code
        if len(code) <= 2:
            return code
        if code in protected:
            return f'__PROTECTED_{protected.index(code)}__'
        protected.append(code)
        return f'__PROTECTED_{len(protected) - 1}__'

    def _restore_blocks(self, text: str, protected: List[str]) -> str:
        if not protected:
            return text
        for i in range(len(protected) - 1, -1, -1):
            text = text.replace(f'__PROTECTED_{i}__', protected[i])
        return text

    def _is_protected_placeholder(self, content: str) -> bool:
        return bool(re.match(r'^__PROTECTED_\d+__$', content.strip()))

    def _process_formulas(self, text: str) -> str:
        if not text:
            return text
        user_macros = []
        if self.config.get('respect_macros', True):
            user_macros = self.formula_fixer.macro_scanner.scan_file(self.input_file)
        text, protected_blocks = self._protect_blocks(text)

        def safe_process_display(m):
            try:
                content = m.group(1)
                if not content or not content.strip():
                    return m.group(0)
                stripped = content.strip()
                if self._is_protected_placeholder(stripped):
                    return m.group(0)
                self.stats['total_formulas'] += 1
                self.stats['display_formulas'] += 1
                if any(env in stripped for env in ConfigurableFormulaFixer.MATRIX_ENVS):
                    self.stats['matrix_formulas'] += 1
                context = FormulaContext.from_formula(stripped, '')
                fixed, logs = self.formula_fixer.fix_formula(
                    stripped, is_display=True, context=context, user_macros=user_macros)
                if fixed != stripped and logs:
                    self.stats['fixed_formulas'] += 1
                    self.stats['fix_logs'].append({'type': 'display', 'logs': logs})
                    self._update_stats(logs)
                return f'$$\n{fixed.strip()}\n$$'
            except Exception as e:
                return m.group(0)

        text = re.sub(r'\$\$(.*?)\$\$', safe_process_display, text, flags=re.DOTALL)
        lines = text.split('\n')
        new_lines = []
        for line in lines:
            if re.match(r'^\s*__PROTECTED_\d+__\s*$', line):
                new_lines.append(line)
                continue
            processed_line = self._process_inline_formulas_in_line(line, user_macros)
            new_lines.append(processed_line)
        text = '\n'.join(new_lines)
        text = self._restore_blocks(text, protected_blocks)
        if self.config.get('clean_extra_newlines', True):
            text = re.sub(r'\n{3,}', '\n\n', text)
        return text

    def _process_inline_formulas_in_line(self, line: str, user_macros: List[str]) -> str:
        def safe_process_inline(m):
            try:
                content = m.group(1)
                if not content or not content.strip():
                    return m.group(0)
                stripped = content.strip()
                if self._is_protected_placeholder(stripped):
                    return m.group(0)
                self.stats['total_formulas'] += 1
                if any(env in stripped for env in ConfigurableFormulaFixer.MATRIX_ENVS):
                    self.stats['matrix_formulas'] += 1
                context = FormulaContext.from_formula(stripped, line)
                fixed, logs = self.formula_fixer.fix_formula(
                    stripped, is_display=False, context=context, user_macros=user_macros)
                if fixed != stripped and logs:
                    self.stats['fixed_formulas'] += 1
                    self.stats['fix_logs'].append({'type': 'inline', 'logs': logs})
                    self._update_stats(logs)
                self.stats['inline_formulas'] += 1
                result = f'${fixed}$'
                if self.config.get('add_space_after_inline', False):
                    end_pos = m.end()
                    if end_pos < len(line) and re.match(r'[\u4e00-\u9fff]', line[end_pos]):
                        result += ' '
                return result
            except Exception as e:
                return m.group(0)

        line = re.sub(r'(?<!\$)\$(?!\$)([^$\n]+?)(?<!\$)\$(?!\$)', safe_process_inline, line)
        return line

    def _update_stats(self, logs: List[str]):
        for log in logs:
            if '上下标修正' in log:
                self.stats['subsup_fixed'] += 1
            elif '函数名正体化' in log:
                self.stats['func_normalized'] += 1
            elif 'Markdown转义' in log:
                self.stats['markdown_escaped'] += 1
            elif '括号' in log:
                self.stats['bracket_fixed'] += 1
            elif '\\bm→\\vec' in log:
                self.stats['bm_converted'] += 1


class MarkdownTitleExtractor:
    ILLEGAL_CHARS = r'[<>:"/\\|?*\x00-\x1f]'

    def extract_title(self, md_file: Path, fields: List[str] = None) -> Optional[str]:
        if fields is None:
            fields = ['title', '标题', 'name', 'slug', '文件名']
        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                content = f.read(16384)
            match = re.search(r'^[-+]{3}\s*\n(.*?)\n[-+]{3}\s*\n', content, re.DOTALL)
            if not match:
                return None
            yaml_content = match.group(1)
            for field in fields:
                pattern = rf'^{re.escape(field)}:\s*["\'\u201c\u201d\u2018\u2019]?(.+?)["\'\u201c\u201d\u2018\u2019]?\s*$'
                m = re.search(pattern, yaml_content, re.MULTILINE | re.IGNORECASE)
                if m:
                    return m.group(1).strip()
            return None
        except Exception:
            return None

    def sanitize(self, title: str, max_length: int = 100) -> str:
        if not title:
            return "untitled"
        safe = re.sub(self.ILLEGAL_CHARS, '_', title).strip('. _-')
        safe = re.sub(r'[\s_]+', '_', safe)
        if len(safe) > max_length:
            safe = safe[:max_length].rstrip('._-')
        return safe or "untitled"

    def get_unique_name(self, directory: Path, base: str, ext: str = '.md') -> str:
        name = f"{base}{ext}"
        if not (directory / name).exists():
            return name
        counter = 1
        while True:
            name = f"{base}_{counter}{ext}"
            if not (directory / name).exists():
                return name
            counter += 1

    def generate_name(self, md_file: Path, output_dir: Path, fields: List[str] = None) -> Tuple[str, bool, Optional[str]]:
        title = self.extract_title(md_file, fields)
        if title:
            safe = self.sanitize(title)
            if safe and safe != "untitled":
                name = self.get_unique_name(output_dir, safe)
                return name, True, title
        return f"{md_file.stem}_fixed.md", False, None


# ==================== 工作线程 ====================
class RepairWorker(QThread):
    progress_updated = pyqtSignal(int, str, int, int)
    file_status_signal = pyqtSignal(Path, str)
    log_message = pyqtSignal(str, str)
    finished_all = pyqtSignal(list)

    def __init__(self, files: List[Path], output_mode: str, output_dir: Path = None,
                 max_workers: int = 4, config: Dict[str, Any] = None,
                 rename_by_title: bool = False, auto_open: bool = False):
        super().__init__()
        self.files = files
        self.output_mode = output_mode
        self.output_dir = output_dir
        self.max_workers = max_workers
        self.config = config or {}
        self.rename_by_title = rename_by_title
        self.auto_open = auto_open
        self._is_running = True
        self.results = []
        self.title_extractor = MarkdownTitleExtractor() if rename_by_title else None

    def stop(self):
        self._is_running = False

    def run(self):
        total = len(self.files)
        self.results = []
        self.log_message.emit(f"开始处理 {total} 个文件，并行数: {self.max_workers}", "INFO")
        if self.rename_by_title:
            self.log_message.emit("🔍 YAML标题重命名已启用", "INFO")

        file_output_map = {}
        rename_count = 0
        for f in self.files:
            out_dir = self.output_dir if self.output_mode == "custom" else f.parent
            out_dir.mkdir(parents=True, exist_ok=True)
            if self.rename_by_title and self.title_extractor:
                name, title_used, extracted = self.title_extractor.generate_name(f, out_dir)
                if title_used:
                    rename_count += 1
                    self.log_message.emit(f"📝 将重命名: {f.name} → {name}（标题: {extracted}）", "INFO")
            else:
                name = f"{f.stem}_fixed.md"
                title_used, extracted = False, None
            output_path = out_dir / name
            output_path = self._get_unique_path(output_path)
            file_output_map[f] = (output_path, title_used, extracted)

        if self.rename_by_title:
            self.log_message.emit(f"📊 共 {rename_count}/{total} 个文件将使用YAML标题", "INFO")

        start = time.time()
        completed = 0
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {}
            for f in self.files:
                if not self._is_running:
                    break
                self.file_status_signal.emit(f, 'processing')
                output_path, _, _ = file_output_map[f]
                future = executor.submit(self._process_file, f, output_path)
                futures[future] = f
            for future in as_completed(futures):
                if not self._is_running:
                    break
                f = futures[future]
                completed += 1
                try:
                    result = future.result(timeout=300)
                    self.results.append(result)
                    output_path, title_used, extracted = file_output_map[f]
                    result.update({'title_used': title_used, 'extracted_title': extracted,
                                   'original_name': f.name, 'new_name': output_path.name})
                    progress = int(completed / total * 100)
                    if result['status'] == 'success':
                        self.file_status_signal.emit(f, 'success')
                        stats = result.get('stats', {})
                        msg = f"✅ [{completed}/{total}] {f.name} → {output_path.name}"
                        if stats.get('total_formulas', 0) > 0:
                            msg += f": 公式{stats['total_formulas']}个，修复{stats['fixed_formulas']}个"
                        for key, label in [('func_normalized', '函数名'), ('subsup_fixed', '上下标'),
                                           ('bracket_fixed', '括号'), ('markdown_escaped', '转义'),
                                           ('image_captions_fixed', '图片标题'),
                                           ('encoding_fixed', '编码修复'),
                                           ('dollar_escaped', '美元转义')]:
                            if stats.get(key, 0) > 0:
                                msg += f"，{label}{stats[key]}个"
                        if title_used:
                            msg += f"\n   📝 已重命名（标题: {extracted}）"
                        self.log_message.emit(msg, "SUCCESS")
                    else:
                        self.file_status_signal.emit(f, 'failed')
                        self.log_message.emit(f"❌ [{completed}/{total}] {f.name}: {result.get('error')}", "ERROR")
                except Exception as e:
                    self.file_status_signal.emit(f, 'failed')
                    self.log_message.emit(f"❌ {f.name}: {e}", "ERROR")
                    self.results.append({'file': str(f), 'status': 'failed', 'error': str(e)})
                self.progress_updated.emit(progress, f"处理中... {completed}/{total}", completed, total)

        elapsed = time.time() - start
        self.log_message.emit(f"总耗时: {elapsed:.1f}秒", "INFO")
        if self._is_running and self.auto_open:
            self._smart_open()
        self.finished_all.emit(self.results)

    def _process_file(self, input_file: Path, output_file: Path) -> dict:
        try:
            processor = MarkdownFormulaProcessor(input_file, output_file.parent, self.config)
            text, actual = processor.process(output_filename=output_file.name)
            if text is None:
                return {'file': str(input_file), 'output': '', 'status': 'failed',
                        'error': '处理后的文本为空', 'stats': processor.stats}
            return {'file': str(input_file), 'output': str(actual), 'status': 'success',
                    'stats': processor.stats, 'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')}
        except Exception as e:
            traceback.print_exc()
            return {'file': str(input_file), 'status': 'failed', 'error': f'{type(e).__name__}: {str(e)}'}

    def _get_unique_path(self, path: Path) -> Path:
        if not path.exists():
            return path
        parent, stem, suffix = path.parent, path.stem, path.suffix
        counter = 1
        while counter <= 100:
            new = parent / f"{stem}_{counter}{suffix}"
            if not new.exists():
                return new
            counter += 1
        return parent / f"{stem}_{uuid.uuid4().hex[:8]}{suffix}"

    def _smart_open(self):
        dirs = set(Path(r['output']).parent for r in self.results if r.get('output'))
        lst = list(dirs)
        if len(lst) == 1:
            self._open_folder(lst[0])
        elif len(lst) <= 3:
            for d in lst:
                self._open_folder(d)

    def _open_folder(self, folder: Path):
        if sys.platform == 'win32':
            os.startfile(str(folder))
        elif sys.platform == 'darwin':
            import subprocess
            subprocess.run(['open', str(folder)])
        else:
            import subprocess
            subprocess.run(['xdg-open', str(folder)])


# ==================== 功能说明弹窗 ====================
class FeatureHelpDialog(QDialog):
    def __init__(self, feature_key: str, parent=None):
        super().__init__(parent)
        self.feature_key = feature_key
        self.info = FeatureHelpDatabase.get_all_features().get(feature_key, {})
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle(f"📖 功能说明 - {self.info.get('name', '未知功能')}")
        self.setMinimumWidth(520)
        self.setMaximumWidth(600)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        if not self.info:
            layout.addWidget(QLabel("⚠️ 该功能的详细说明暂未收录"))
            close_btn = QPushButton("关闭")
            close_btn.clicked.connect(self.accept)
            layout.addWidget(close_btn)
            return
        title_row = QHBoxLayout()
        icon_label = QLabel(self.info.get('icon', '📌'))
        icon_label.setFont(QFont("Segoe UI Emoji", 20))
        title_row.addWidget(icon_label)
        name_label = QLabel(self.info.get('name', ''))
        name_label.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        title_row.addWidget(name_label)
        title_row.addStretch()
        risk = self.info.get('risk', 'low')
        risk_labels = {'low': '🟢 低风险', 'medium': '🟡 中风险', 'high': '🔴 高风险'}
        risk_label = QLabel(risk_labels.get(risk, ''))
        risk_label.setStyleSheet(f"color: {RiskLevel(risk).color}; font-weight: bold; font-size: 12px;")
        title_row.addWidget(risk_label)
        layout.addLayout(title_row)
        category_label = QLabel(f"📂 分类: {self.info.get('category', '')}")
        category_label.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(category_label)
        detail_tabs = QTabWidget()
        overview_tab = QWidget()
        overview_layout = QVBoxLayout(overview_tab)
        overview_text = QTextBrowser()
        overview_text.setHtml(f"""
        <style>
            body {{ font-family: 'Microsoft YaHei', sans-serif; font-size: 13px; line-height: 1.6; }}
            h3 {{ color: #2c3e50; margin-top: 12px; margin-bottom: 6px; }}
            .highlight {{ background: #fff3cd; padding: 8px; border-radius: 4px; border-left: 3px solid #ffc107; }}
        </style>
        <h3>🎯 触发条件</h3><div class="highlight">{self.info.get('trigger', '')}</div>
        <h3>⚡ 执行操作</h3><p>{self.info.get('action', '')}</p>
        <h3>💡 为什么要修改</h3><p>{self.info.get('why', '')}</p>
        <h3>⚠️ 潜在问题</h3><p>{self.info.get('problem', '')}</p>
        <h3>📋 使用建议</h3><p><b>{self.info.get('recommendation', '')}</b></p>
        """)
        overview_layout.addWidget(overview_text)
        detail_tabs.addTab(overview_tab, "📋 概述")
        example_tab = QWidget()
        example_layout = QVBoxLayout(example_tab)
        example_text = QTextBrowser()
        example_text.setHtml(f"""
        <style>
            body {{ font-family: 'Consolas', 'Microsoft YaHei', monospace; font-size: 13px; }}
            .before {{ background: #fff3cd; padding: 10px; border-radius: 4px; margin: 8px 0; }}
            .after {{ background: #d4edda; padding: 10px; border-radius: 4px; margin: 8px 0; }}
            .label {{ font-weight: bold; margin-top: 10px; }}
        </style>
        <p class="label">📄 修改前:</p>
        <div class="before"><code>{self._escape_html(self.info.get('example_before', ''))}</code></div>
        <p class="label">✅ 修改后:</p>
        <div class="after"><code>{self._escape_html(self.info.get('example_after', ''))}</code></div>
        """)
        example_layout.addWidget(example_text)
        detail_tabs.addTab(example_tab, "💻 示例")
        layout.addWidget(detail_tabs)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        close_btn.setStyleSheet("padding: 6px 20px;")
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)

    def _escape_html(self, text: str) -> str:
        return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


# ==================== 并排对比预览对话框 ====================
class SideBySidePreviewDialog(QDialog):
    def __init__(self, changes: List[FormulaChange], parent=None, file_name: str = ""):
        super().__init__(parent)
        self.changes = changes
        self.file_name = file_name
        self._setup_ui()

    def _setup_ui(self):
        title = "🔍 修复预览"
        if self.file_name:
            title += f" - {self.file_name}"
        title += f" ({len(self.changes)}处变更)"
        self.setWindowTitle(title)
        self.setMinimumSize(1000, 600)
        self.resize(1100, 650)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        stats_layout = self._create_stats_bar()
        layout.addLayout(stats_layout)
        if len(self.changes) > 20:
            hint = QLabel(f"💡 变更较多（{len(self.changes)}处），建议逐处检查后再决定是否应用")
            hint.setStyleSheet("color: #e67e22; font-size: 12px; padding: 2px 0;")
            layout.addWidget(hint)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_header = QLabel("📄 原始公式")
        left_header.setStyleSheet("background: #f8d7da; padding: 6px; font-weight: bold; border-radius: 4px;")
        left_layout.addWidget(left_header)
        self.original_view = QTextEdit()
        self.original_view.setReadOnly(True)
        self.original_view.setFont(QFont("Consolas", 11))
        left_layout.addWidget(self.original_view)
        splitter.addWidget(left_widget)
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_header = QLabel("✅ 修复后")
        right_header.setStyleSheet("background: #d4edda; padding: 6px; font-weight: bold; border-radius: 4px;")
        right_layout.addWidget(right_header)
        self.fixed_view = QTextEdit()
        self.fixed_view.setReadOnly(True)
        self.fixed_view.setFont(QFont("Consolas", 11))
        right_layout.addWidget(self.fixed_view)
        splitter.addWidget(right_widget)
        splitter.setSizes([500, 500])
        layout.addWidget(splitter, 1)
        self.original_view.verticalScrollBar().valueChanged.connect(self.fixed_view.verticalScrollBar().setValue)
        self.fixed_view.verticalScrollBar().valueChanged.connect(self.original_view.verticalScrollBar().setValue)
        log_group = QGroupBox("📝 修改详情")
        log_layout = QVBoxLayout(log_group)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 10))
        self.log_text.setMaximumHeight(120)
        log_layout.addWidget(self.log_text)
        layout.addWidget(log_group)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        close_btn.setStyleSheet("padding: 6px 20px;")
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)
        self.current_index = -1
        if self.changes:
            self._show_change(0)

    def _create_stats_bar(self) -> QHBoxLayout:
        stats_layout = QHBoxLayout()
        risk_counts = {'low': 0, 'medium': 0, 'high': 0}
        type_counts = {'inline': 0, 'display': 0}
        for c in self.changes:
            risk_counts[c.risk_level] = risk_counts.get(c.risk_level, 0) + 1
            type_counts[c.formula_type] = type_counts.get(c.formula_type, 0) + 1
        summary_parts = [f"共 {len(self.changes)} 处变更"]
        for level in ['high', 'medium', 'low']:
            if risk_counts[level] > 0:
                rl = RiskLevel(level)
                summary_parts.append(f"{rl.icon}{risk_counts[level]}")
        summary_parts.append(f"| 行内:{type_counts['inline']} 块级:{type_counts['display']}")
        stats_label = QLabel("  ".join(summary_parts))
        stats_label.setStyleSheet("font-size: 13px;")
        stats_layout.addWidget(stats_label)
        stats_layout.addStretch()
        self.prev_btn = QPushButton("⬆ 上一处")
        self.next_btn = QPushButton("⬇ 下一处")
        self.prev_btn.clicked.connect(lambda: self._navigate(-1))
        self.next_btn.clicked.connect(lambda: self._navigate(1))
        self.prev_btn.setFixedWidth(90)
        self.next_btn.setFixedWidth(90)
        stats_layout.addWidget(self.prev_btn)
        stats_layout.addWidget(self.next_btn)
        return stats_layout

    def _show_change(self, index: int):
        if index < 0 or index >= len(self.changes):
            return
        self.current_index = index
        change = self.changes[index]
        rl = RiskLevel(change.risk_level)
        self.setWindowTitle(f"🔍 修复预览 [{index + 1}/{len(self.changes)}] - {rl.icon} {rl.description}"
                            + (f" - {self.file_name}" if self.file_name else ""))
        original_html, fixed_html = self._compute_diff(change.original, change.fixed)
        self.original_view.setHtml(original_html)
        self.fixed_view.setHtml(fixed_html)
        log_html = "<ul style='margin:4px;'>"
        for log in change.changes:
            log_html += f"<li>{log}</li>"
        log_html += "</ul>"
        self.log_text.setHtml(log_html)
        self.prev_btn.setEnabled(index > 0)
        self.next_btn.setEnabled(index < len(self.changes) - 1)

    def _navigate(self, direction: int):
        new_index = self.current_index + direction
        if 0 <= new_index < len(self.changes):
            self._show_change(new_index)

    def _compute_diff(self, original: str, fixed: str) -> Tuple[str, str]:
        matcher = difflib.SequenceMatcher(None, original, fixed)
        original_parts, fixed_parts = [], []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            orig_segment = self._escape_html(original[i1:i2])
            fixed_segment = self._escape_html(fixed[j1:j2])
            if tag == 'equal':
                original_parts.append(orig_segment)
                fixed_parts.append(fixed_segment)
            elif tag == 'replace':
                original_parts.append(f'<span style="background-color:#ffcccc;text-decoration:line-through;border-radius:2px;padding:0 1px;">{orig_segment}</span>')
                fixed_parts.append(f'<span style="background-color:#ccffcc;border-radius:2px;padding:0 1px;">{fixed_segment}</span>')
            elif tag == 'delete':
                original_parts.append(f'<span style="background-color:#ffcccc;text-decoration:line-through;border-radius:2px;padding:0 1px;">{orig_segment}</span>')
            elif tag == 'insert':
                fixed_parts.append(f'<span style="background-color:#ccffcc;border-radius:2px;padding:0 1px;">{fixed_segment}</span>')
        return (
            '<pre style="white-space:pre-wrap;font-family:Consolas,monospace;font-size:12px;line-height:1.6;margin:4px;">' + ''.join(original_parts) + '</pre>',
            '<pre style="white-space:pre-wrap;font-family:Consolas,monospace;font-size:12px;line-height:1.6;margin:4px;">' + ''.join(fixed_parts) + '</pre>'
        )

    def _escape_html(self, text: str) -> str:
        return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


# ==================== 高级设置对话框 ====================
class AdvancedSettingsDialog(QDialog):
    """高级修复选项弹窗"""
    def __init__(self, config: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔧 高级修复选项")
        self.setMinimumWidth(580)
        self.config = config.copy()
        self.checkboxes: Dict[str, QCheckBox] = {}
        self.selected_profile_name: str = ""
        self._setup_ui()
        self._load_config()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ====== 预设方案按钮组 ======
        profile_layout = QHBoxLayout()
        profile_layout.addWidget(QLabel("📋 预设方案:"))

        self.profile_group = QButtonGroup(self)
        self.profile_group.setExclusive(True)

        self.profile_buttons = []
        profiles = RepairProfile.get_builtin_profiles()
        for i, p in enumerate(profiles):
            btn = QPushButton(p.name)
            btn.setCheckable(True)
            btn.setToolTip(p.description)
            btn.setStyleSheet("""
                QPushButton {
                    padding: 6px 12px;
                    border: 2px solid #ddd;
                    border-radius: 4px;
                    background: #fafafa;
                    font-size: 12px;
                }
                QPushButton:hover {
                    border-color: #3498db;
                    background: #e8f4fd;
                }
                QPushButton:checked {
                    border-color: #3498db;
                    background: #d4e9fc;
                    font-weight: bold;
                }
            """)
            btn.clicked.connect(lambda checked, idx=i: self._on_profile_button_clicked(idx))
            self.profile_group.addButton(btn, i)
            self.profile_buttons.append(btn)
            profile_layout.addWidget(btn)

        profile_layout.addStretch()
        layout.addLayout(profile_layout)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

        hint = QLabel("💡 修改复选框将自动取消方案选择，切换为「自定义」。点击每个选项旁的 ⓘ 查看详细说明")
        hint.setStyleSheet("color: #666; padding: 4px; background: #f0f0f0; border-radius: 4px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(10)
        scroll_layout.addWidget(self._create_section("🟢 格式与语法修复",
            ['clean_newlines', 'add_space_after_inline', 'subsup_fix',
             'func_normalize', 'matrix_newline_remove', 'bracket_check',
             'fix_encoding', 'escape_isolated_dollars']))
        scroll_layout.addWidget(self._create_section("🟡 语义增强",
            ['markdown_escape_inline', 'matrix_add_multiplication', 'remove_size_commands']))
        scroll_layout.addWidget(self._create_section("🛡️ 安全保护",
            ['respect_macros', 'dl_commands_to_text']))
        scroll_layout.addWidget(self._create_section("🔴 高级转换",
            ['bm_to_vec', 'inline_to_display']))
        scroll_layout.addWidget(self._create_section("🖼️ 用户定制",
            ['image_caption']))
        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll, 1)

        color_layout = QHBoxLayout()
        color_layout.addWidget(QLabel("🖼️ 图片标题颜色:"))
        self.color_combo = QComboBox()
        self.color_combo.addItems(list(ImageCaptionOptimizer.COLOR_SCHEMES.keys()))
        self.color_combo.setCurrentText('purple')
        color_layout.addWidget(self.color_combo)
        color_layout.addStretch()
        layout.addLayout(color_layout)

        btn_layout = QHBoxLayout()
        reset_btn = QPushButton("🔄 恢复默认")
        reset_btn.clicked.connect(self._reset_default)
        btn_layout.addWidget(reset_btn)
        
        select_all_btn = QPushButton("☑️ 全部选择")
        select_all_btn.setToolTip("勾选所有修复功能")
        select_all_btn.clicked.connect(self._select_all)
        btn_layout.addWidget(select_all_btn)
        
        deselect_all_btn = QPushButton("☐ 全部取消")
        deselect_all_btn.setToolTip("取消所有修复功能")
        deselect_all_btn.clicked.connect(self._deselect_all)
        btn_layout.addWidget(deselect_all_btn)
        
        btn_layout.addStretch()

        ok_btn = QPushButton("✅ 确定")
        ok_btn.clicked.connect(self._on_ok)
        ok_btn.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold; padding: 8px 20px; border-radius: 4px;")
        btn_layout.addWidget(ok_btn)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _on_profile_button_clicked(self, index: int):
        profiles = RepairProfile.get_builtin_profiles()
        profile = profiles[index]
        self.selected_profile_name = profile.name
        self._apply_profile(profile)

    def _apply_profile(self, profile: RepairProfile):
        config = profile.config

        for cb in self.checkboxes.values():
            cb.blockSignals(True)

        checkbox_map = {
            'clean_newlines': config.get('clean_extra_newlines', True),
            'add_space_after_inline': config.get('add_space_after_inline', True),
            'subsup_fix': config.get('subsup_fix', True),
            'func_normalize': config.get('func_normalize', True),
            'matrix_newline_remove': config.get('matrix_newline_remove', True),
            'bracket_check': config.get('bracket_check', True),
            'markdown_escape_inline': config.get('markdown_escape_inline', True),
            'matrix_add_multiplication': config.get('matrix_add_multiplication', True),
            'dl_commands_to_text': config.get('dl_commands_to_text', True),
            'remove_size_commands': config.get('remove_size_commands', True),
            'bm_to_vec': config.get('bm_to_vec', False),
            'inline_to_display': config.get('inline_to_display', False),
            'image_caption': config.get('image_caption_enabled', True),
            'respect_macros': config.get('respect_macros', True),
            'fix_encoding': config.get('fix_encoding', True),
            'escape_isolated_dollars': config.get('escape_isolated_dollars', True),
        }
        for var_name, value in checkbox_map.items():
            cb = self.checkboxes.get(var_name)
            if cb:
                cb.setChecked(value)

        self.color_combo.setCurrentText(config.get('image_caption_color', 'purple'))

        # ★ 同步顶层字段
        self.config['clean_extra_newlines'] = config.get('clean_extra_newlines', True)
        self.config['add_space_after_inline'] = config.get('add_space_after_inline', True)
        self.config['inline_to_display'] = config.get('inline_to_display', False)
        self.config['image_caption_enabled'] = config.get('image_caption_enabled', True)
        self.config['escape_isolated_dollars'] = config.get('escape_isolated_dollars', True)
        self.config['fix_encoding'] = config.get('fix_encoding', True)

        # ★ 同步 formula_config 中的字段
        if 'formula_config' not in self.config:
            self.config['formula_config'] = {}
        fc = self.config['formula_config']
        fc['subsup_fix'] = config.get('subsup_fix', True)
        fc['func_normalize'] = config.get('func_normalize', True)
        fc['matrix_newline_remove'] = config.get('matrix_newline_remove', True)
        fc['bracket_check'] = config.get('bracket_check', True)
        fc['markdown_escape_inline'] = config.get('markdown_escape_inline', True)
        fc['matrix_add_multiplication'] = config.get('matrix_add_multiplication', True)
        fc['dl_commands_to_text'] = config.get('dl_commands_to_text', True)
        fc['remove_size_commands'] = config.get('remove_size_commands', True)
        fc['bm_to_vec'] = config.get('bm_to_vec', False)
        fc['respect_macros'] = config.get('respect_macros', True)
        fc['escape_mode'] = config.get('escape_mode', 'standard')
        fc['bm_strict_mode'] = config.get('bm_strict_mode', True)
        fc['fix_encoding'] = config.get('fix_encoding', True)
        self.config['image_caption_color'] = config.get('image_caption_color', 'purple')

        for cb in self.checkboxes.values():
            cb.blockSignals(False)


    def _on_checkbox_changed(self):
        self.profile_group.setExclusive(False)
        for btn in self.profile_buttons:
            btn.setChecked(False)
        self.profile_group.setExclusive(True)
        self.selected_profile_name = ""

    def _select_all(self):
        """勾选所有修复功能"""
        self.profile_group.setExclusive(False)
        for btn in self.profile_buttons:
            btn.setChecked(False)
        self.profile_group.setExclusive(True)
        self.selected_profile_name = ""
        
        for cb in self.checkboxes.values():
            cb.setChecked(True)
    
    def _deselect_all(self):
        """取消所有修复功能"""
        self.profile_group.setExclusive(False)
        for btn in self.profile_buttons:
            btn.setChecked(False)
        self.profile_group.setExclusive(True)
        self.selected_profile_name = ""
        
        for cb in self.checkboxes.values():
            cb.setChecked(False)

    def _create_section(self, title: str, feature_keys: List[str]) -> QGroupBox:
        group = QGroupBox(title)
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(6)
        help_db = FeatureHelpDatabase.get_all_features()
        for key in feature_keys:
            info = help_db.get(key, {})
            if not info:
                continue
            row = QHBoxLayout()
            row.setSpacing(4)
            cb = QCheckBox(f"{info.get('icon', '')} {info.get('name', key)}")
            cb.setToolTip(info.get('trigger', ''))
            cb.toggled.connect(self._on_checkbox_changed)
            row.addWidget(cb, 1)
            self.checkboxes[key] = cb
            risk = info.get('risk', 'low')
            risk_icons = {'low': '🟢', 'medium': '🟡', 'high': '🔴'}
            risk_label = QLabel(risk_icons.get(risk, ''))
            risk_label.setToolTip({'low': '低风险', 'medium': '中风险', 'high': '高风险'}.get(risk, ''))
            risk_label.setFixedWidth(24)
            row.addWidget(risk_label)
            help_btn = QPushButton("ⓘ")
            help_btn.setFixedSize(20, 20)
            help_btn.setToolTip(f"查看「{info.get('name', '')}」的详细说明")
            help_btn.setStyleSheet("QPushButton { border: none; background: transparent; color: #888; font-size: 14px; padding: 0px; } QPushButton:hover { color: #3498db; }")
            help_btn.clicked.connect(lambda checked, k=key: self._show_feature_help(k))
            row.addWidget(help_btn)
            group_layout.addLayout(row)
        return group

    def _show_feature_help(self, feature_key: str):
        dialog = FeatureHelpDialog(feature_key, self)
        dialog.exec()

    def _load_config(self):
        fc = self.config.get('formula_config', {})

        for cb in self.checkboxes.values():
            cb.blockSignals(True)

        matched = self._match_profile()

        # QMessageBox.information(None, "DEBUG", 
        #     f"fix_encoding={self.config.get('fix_encoding')}\n"
        #     f"clean_extra_newlines={self.config.get('clean_extra_newlines')}\n"
        #     f"matched={matched}")

        if matched:
            btn_index = matched - 1
            if btn_index < len(self.profile_buttons):
                self.profile_buttons[btn_index].setChecked(True)
                self.selected_profile_name = self.profile_buttons[btn_index].text()
                # ★ 手动应用匹配到的方案
                profiles = RepairProfile.get_builtin_profiles()
                self._apply_profile(profiles[btn_index])



        else:
            self.profile_group.setExclusive(False)
            for btn in self.profile_buttons:
                btn.setChecked(False)
            self.profile_group.setExclusive(True)
            self.selected_profile_name = ""
            mapping = {
                'clean_newlines': self.config.get('clean_extra_newlines', True),
                'add_space_after_inline': self.config.get('add_space_after_inline', True),
                'subsup_fix': fc.get('subsup_fix', True),
                'func_normalize': fc.get('func_normalize', True),
                'matrix_newline_remove': fc.get('matrix_newline_remove', True),
                'bracket_check': fc.get('bracket_check', True),
                'markdown_escape_inline': fc.get('markdown_escape_inline', True),
                'matrix_add_multiplication': fc.get('matrix_add_multiplication', True),
                'dl_commands_to_text': fc.get('dl_commands_to_text', True),
                'remove_size_commands': fc.get('remove_size_commands', True),
                'bm_to_vec': fc.get('bm_to_vec', False),
                'inline_to_display': self.config.get('inline_to_display', False),
                'image_caption': self.config.get('image_caption_enabled', True),
                'respect_macros': fc.get('respect_macros', True),
                'fix_encoding': self.config.get('fix_encoding', True),
                'escape_isolated_dollars': self.config.get('escape_isolated_dollars', True),
            }
            for var_name, cb in self.checkboxes.items():
                cb.setChecked(mapping.get(var_name, False))

        self.color_combo.setCurrentText(self.config.get('image_caption_color', 'purple'))

        for cb in self.checkboxes.values():
            cb.blockSignals(False)

    def _match_profile(self) -> int:
        profiles = RepairProfile.get_builtin_profiles()
        fc = self.config.get('formula_config', {})
        for idx, profile in enumerate(profiles):
            pc = profile.config
            if (self.config.get('clean_extra_newlines') != pc.get('clean_extra_newlines') or
                self.config.get('add_space_after_inline') != pc.get('add_space_after_inline') or
                self.config.get('inline_to_display') != pc.get('inline_to_display') or
                self.config.get('image_caption_enabled') != pc.get('image_caption_enabled') or
                self.config.get('escape_isolated_dollars') != pc.get('escape_isolated_dollars') or
                self.config.get('fix_encoding') != pc.get('fix_encoding')):
                continue
            formula_keys = ['subsup_fix', 'func_normalize', 'matrix_newline_remove',
                           'bracket_check', 'markdown_escape_inline', 'matrix_add_multiplication',
                           'dl_commands_to_text', 'remove_size_commands', 'bm_to_vec',
                           'escape_mode', 'respect_macros', 'bm_strict_mode']
            match = True
            for key in formula_keys:
                if fc.get(key) != pc.get(key):
                    match = False
                    break
            if match:
                return idx + 1
        return 0

    def _reset_default(self):
        default_config = ConfigurableFormulaFixer.get_default_config()
        default_full = {
            'clean_extra_newlines': True, 
            'add_space_after_inline': False,
            'inline_to_display': True, 
            'image_caption_enabled': True,
            'image_caption_color': 'purple', 
            'escape_isolated_dollars': False,
            'formula_config': default_config,
        }
        self.config = default_full
        self.profile_group.setExclusive(False)
        for btn in self.profile_buttons:
            btn.setChecked(False)
        self.profile_group.setExclusive(True)
        self.selected_profile_name = ""
        self._load_config()

    def _on_ok(self):
        if 'formula_config' not in self.config:
            self.config['formula_config'] = {}
        fc = self.config['formula_config']
        
        self.config['clean_extra_newlines'] = self.checkboxes['clean_newlines'].isChecked()
        self.config['add_space_after_inline'] = self.checkboxes['add_space_after_inline'].isChecked()
        self.config['inline_to_display'] = self.checkboxes['inline_to_display'].isChecked()
        self.config['image_caption_enabled'] = self.checkboxes['image_caption'].isChecked()
        self.config['escape_isolated_dollars'] = self.checkboxes['escape_isolated_dollars'].isChecked()
        self.config['fix_encoding'] = self.checkboxes['fix_encoding'].isChecked()
        
        fc['subsup_fix'] = self.checkboxes['subsup_fix'].isChecked()
        fc['func_normalize'] = self.checkboxes['func_normalize'].isChecked()
        fc['matrix_newline_remove'] = self.checkboxes['matrix_newline_remove'].isChecked()
        fc['bracket_check'] = self.checkboxes['bracket_check'].isChecked()
        fc['markdown_escape_inline'] = self.checkboxes['markdown_escape_inline'].isChecked()
        fc['matrix_add_multiplication'] = self.checkboxes['matrix_add_multiplication'].isChecked()
        fc['dl_commands_to_text'] = self.checkboxes['dl_commands_to_text'].isChecked()
        fc['remove_size_commands'] = self.checkboxes['remove_size_commands'].isChecked()
        fc['bm_to_vec'] = self.checkboxes['bm_to_vec'].isChecked()
        fc['respect_macros'] = self.checkboxes['respect_macros'].isChecked()
        
        fc.setdefault('escape_mode', 'standard')
        fc.setdefault('bm_strict_mode', True)
        
        self.config['image_caption_color'] = self.color_combo.currentText()
        
        self.accept()

    def get_config(self) -> Dict[str, Any]:
        return self.config


# ==================== 主窗口 ====================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{__app_name__} v{__version__}")
        self.setMinimumSize(950, 650)
        self.resize(1000, 700)
        self.settings = QSettings("MDFormulaFixer", "SettingsV8")
        self.output_dir: Optional[Path] = None
        self.worker: Optional[RepairWorker] = None
        self.last_config = self._load_config()
        self._setup_ui()
        self._load_config_to_ui()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        left_panel = QWidget()
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        left_scroll.setWidget(left_panel)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setSpacing(10)
        left_layout.setContentsMargins(10, 10, 10, 10)

        # 1. 高级设置按钮
        advanced_row = QHBoxLayout()
        self.advanced_btn = QPushButton("🔧 高级设置")
        self.advanced_btn.clicked.connect(self._open_advanced_settings)
        self.advanced_btn.setToolTip(
            "打开高级修复选项\n可选择预设方案或自定义每个修复功能的开关\n每个选项旁有 ⓘ 可查看详细说明")
        self.advanced_btn.setStyleSheet(
            "QPushButton { padding: 8px 16px; font-size: 13px; font-weight: bold; "
            "color: #ffffff; background-color: #3498db; "
            "border: 1px solid #2980b9; border-radius: 4px; }"
            "QPushButton:hover { background-color: #2980b9; border-color: #1c6ea4; }"
            "QPushButton:pressed { background-color: #2471a3; }")
        advanced_row.addWidget(self.advanced_btn)
        advanced_row.addStretch()
        left_layout.addLayout(advanced_row)

        # 2. 文件列表
        file_group = QGroupBox("📁 Markdown文件 (支持拖拽，右键预览)")
        file_layout = QVBoxLayout(file_group)
        self.file_list = DropFileListWidget()
        self.file_list.setMinimumHeight(80)
        self.file_list.setMaximumHeight(120)
        self.file_list.files_added.connect(self._on_files_added)
        self.file_list.preview_requested.connect(self._preview_files)
        self.file_list.remove_requested.connect(self._remove_selected)
        self.file_list.clear_requested.connect(self._clear_all)
        file_layout.addWidget(self.file_list)
        
        btn_layout = QHBoxLayout()
        for text, slot in [("➕ 添加文件", self._add_files), ("📂 添加文件夹", self._add_folder),
                           ("❌ 移除选中", self._remove_selected), ("🗑️ 清空", self._clear_all)]:
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            btn_layout.addWidget(btn)
        
        self.cb_force_reprocess = QCheckBox("忽略状态")
        self.cb_force_reprocess.setChecked(False)
        self.cb_force_reprocess.setToolTip(
            "默认情况下，已经处理过的文件不会再次处理。\n勾选此项后，将重新处理列表中的所有文件。\n\n"
            "适用场景：\n• 修改了修复配置后想重新处理\n• 之前处理失败的文件想再次尝试\n• 需要覆盖之前的输出文件")
        btn_layout.addWidget(self.cb_force_reprocess)
        
        btn_layout.addStretch()
        file_layout.addLayout(btn_layout)
        left_layout.addWidget(file_group)

        # 3. 输出设置
        out_group = QGroupBox("📂 输出设置")
        out_layout = QVBoxLayout(out_group)
        mode_layout = QHBoxLayout()
        self.out_source = QRadioButton("与源文件同目录")
        self.out_custom = QRadioButton("统一输出到:")
        self.out_source.setChecked(True)
        mode_layout.addWidget(self.out_source)
        mode_layout.addWidget(self.out_custom)
        mode_layout.addStretch()
        out_layout.addLayout(mode_layout)
        dir_layout = QHBoxLayout()
        self.out_dir_edit = QLineEdit()
        self.out_dir_edit.setEnabled(False)
        self.out_dir_edit.setPlaceholderText("请选择输出目录")
        dir_layout.addWidget(self.out_dir_edit)
        browse_btn = QPushButton("浏览...")
        browse_btn.setEnabled(False)
        browse_btn.clicked.connect(self._select_output_dir)
        dir_layout.addWidget(browse_btn)
        out_layout.addLayout(dir_layout)
        self.out_custom.toggled.connect(lambda c: (self.out_dir_edit.setEnabled(c), browse_btn.setEnabled(c)))
        left_layout.addWidget(out_group)

        # 4. 执行选项
        exec_group = QGroupBox("⚙️ 执行选项")
        exec_layout = QVBoxLayout(exec_group)
        exec_layout.setSpacing(6)
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("并行线程:"))
        self.worker_spin = QSpinBox()
        self.worker_spin.setRange(1, 16)
        self.worker_spin.setValue(min(os.cpu_count() or 4, 8))
        self.worker_spin.setFixedWidth(70)
        row1.addWidget(self.worker_spin)
        row1.addStretch()
        exec_layout.addLayout(row1)
        self.cb_auto_open = QCheckBox("完成后自动打开输出目录")
        exec_layout.addWidget(self.cb_auto_open)
        self.cb_rename_title = QCheckBox("使用YAML标题重命名")
        exec_layout.addWidget(self.cb_rename_title)
        left_layout.addWidget(exec_group)

        # 5. 操作按钮（居中）
        ctrl_layout = QHBoxLayout()
        ctrl_layout.addStretch()
        
        self.process_btn = QPushButton("🚀 开始处理")
        self.process_btn.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold; padding: 10px 30px; border-radius: 6px;")
        self.process_btn.clicked.connect(self._start_processing)
        ctrl_layout.addWidget(self.process_btn)
        
        self.stop_btn = QPushButton("⏹️ 停止处理")
        self.stop_btn.setStyleSheet("background-color: #e74c3c; color: white; font-weight: bold; padding: 10px 30px; border-radius: 6px;")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_processing)
        ctrl_layout.addWidget(self.stop_btn)
        
        ctrl_layout.addStretch()
        left_layout.addLayout(ctrl_layout)

        # 6. 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumHeight(22)
        self.progress_bar.setTextVisible(True)
        left_layout.addWidget(self.progress_bar)

        # 右侧日志面板
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(5, 5, 5, 5)
        log_header = QLabel("📋 处理日志")
        log_header.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        right_layout.addWidget(log_header)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 10))
        right_layout.addWidget(self.log_text)
        log_toolbar = QHBoxLayout()
        clear_log_btn = QPushButton("🗑️ 清空")
        clear_log_btn.clicked.connect(lambda: self.log_text.clear())
        log_toolbar.addWidget(clear_log_btn)
        save_log_btn = QPushButton("💾 保存")
        save_log_btn.clicked.connect(self._save_log)
        log_toolbar.addWidget(save_log_btn)
        log_toolbar.addStretch()
        right_layout.addLayout(log_toolbar)
        main_splitter.addWidget(left_scroll)
        main_splitter.addWidget(right_panel)
        main_splitter.setSizes([520, 480])
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(main_splitter)
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_label = QLabel("就绪")
        self.status_bar.addWidget(self.status_label)
        self.file_count_label = QLabel("已选择 0 个文件")
        self.status_bar.addPermanentWidget(self.file_count_label)

    def _get_current_config(self) -> Dict[str, Any]:
        fc = self.last_config.get('formula_config', {})
        return {
            'image_caption_enabled': self.last_config.get('image_caption_enabled', False),
            'image_caption_color': self.last_config.get('image_caption_color', 'purple'),
            'escape_isolated_dollars': self.last_config.get('escape_isolated_dollars', True),
            'formula_config': fc,
            'inline_to_display': self.last_config.get('inline_to_display', False),
            'clean_extra_newlines': self.last_config.get('clean_extra_newlines', True),
            'add_space_after_inline': self.last_config.get('add_space_after_inline', True),
            'fix_encoding': self.last_config.get('fix_encoding', True),
        }

    def _load_config(self) -> Dict[str, Any]:
        defaults = {
            'image_caption_enabled': True,
            'image_caption_color': 'purple',
            'escape_isolated_dollars': False,
            'formula_config': ConfigurableFormulaFixer.get_default_config(),
            'inline_to_display': True,
            'clean_extra_newlines': True,
            'add_space_after_inline': False,
            'fix_encoding': False,
        }
        saved = self.settings.value("repair_config_v8")
        if saved and isinstance(saved, dict):
            defaults.update(saved)
        if 'formula_config' not in defaults:
            defaults['formula_config'] = ConfigurableFormulaFixer.get_default_config()
        return defaults

    def _save_config(self):
        self.settings.setValue("repair_config_v8", self.last_config)

    def _load_config_to_ui(self):
        pass

    def _open_advanced_settings(self):
        dialog = AdvancedSettingsDialog(self.last_config.copy(), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.last_config = dialog.get_config()
            profile_name = dialog.selected_profile_name
            if profile_name:
                self.advanced_btn.setText(f"🔧 高级设置 ({profile_name})")
            else:
                self.advanced_btn.setText("🔧 高级设置 (自定义)")
            self._log("✅ 已更新修复配置", "INFO")

    def _preview_files(self, files: List[Path] = None):
        if files is None:
            all_files = self.file_list.get_all_files()
            if not all_files:
                QMessageBox.warning(self, "警告", "请先添加文件")
                return
            test_file = self._get_selected_file()
            if test_file is None:
                test_file = all_files[0]
                if len(all_files) > 1:
                    self._log(f"💡 提示：列表中有 {len(all_files)} 个文件，当前预览「{test_file.name}」。\n    可选中其他文件后右键预览", "INFO")
            files = [test_file]
        
        if not files:
            QMessageBox.warning(self, "警告", "请先选择文件")
            return
        
        test_file = files[0]
        
        try:
            with open(test_file, 'r', encoding='utf-8') as f:
                text = f.read()
        except Exception as e:
            QMessageBox.warning(self, "错误", f"无法读取文件: {e}")
            return
        
        config = self._get_current_config()
        previewer = FormulaPreviewer(config)
        try:
            changes = previewer.preview(text, test_file)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"预检处理失败: {e}")
            return
        
        if not changes:
            QMessageBox.information(self, "预检结果", f"✅ 文件「{test_file.name}」\n未检测到需要修改的内容。")
            return
        
        dialog = SideBySidePreviewDialog(changes, self, file_name=test_file.name)
        dialog.exec()

    def _get_selected_file(self) -> Optional[Path]:
        selected_items = self.file_list.selectedItems()
        if not selected_items:
            return None
        for item in selected_items:
            row = self.file_list.row(item)
            if row in self.file_list.file_paths:
                return self.file_list.file_paths[row]
        return None

    def _on_files_added(self, files: List[Path]):
        added = self.file_list.add_files(files)
        if added > 0:
            self._log(f"📁 添加了 {added} 个文件")
        self._update_file_count()

    def _add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "选择Markdown文件", "", "Markdown文件 (*.md);;所有文件 (*.*)")
        if files:
            added = self.file_list.add_files([Path(f) for f in files])
            self._log(f"📁 添加了 {added} 个文件")
            self._update_file_count()

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择包含Markdown文件的文件夹")
        if folder:
            path = Path(folder)
            md_files = list(path.rglob("*.md")) + list(path.rglob("*.MD"))
            added = self.file_list.add_files(md_files)
            self._log(f"📁 从文件夹添加了 {added} 个文件")
            self._update_file_count()

    def _remove_selected(self):
        removed = self.file_list.remove_selected()
        if removed:
            self._log(f"🗑️ 移除了 {len(removed)} 个文件")
        self._update_file_count()

    def _clear_all(self):
        self.file_list.clear_all()
        self._log("🗑️ 已清空文件列表")
        self._update_file_count()

    def _update_file_count(self):
        total = self.file_list.count()
        pending = len(self.file_list.get_pending_files())
        success = len(self.file_list.get_files_by_status(FileStatus.SUCCESS))
        failed = len(self.file_list.get_files_by_status(FileStatus.FAILED))
        parts = [f"已选择 {total} 个文件"]
        if pending > 0:
            parts.append(f"待处理: {pending}")
        if success > 0:
            parts.append(f"已完成: {success}")
        if failed > 0:
            parts.append(f"失败: {failed}")
        self.file_count_label.setText(" | ".join(parts))

    def _select_output_dir(self):
        directory = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if directory:
            self.output_dir = Path(directory)
            self.out_dir_edit.setText(str(self.output_dir))

    def _start_processing(self):
        if self.cb_force_reprocess.isChecked():
            all_files = self.file_list.get_all_files()
            if not all_files:
                QMessageBox.warning(self, "警告", "请先添加文件")
                return
            self.file_list.reset_all_status()
            files = self.file_list.get_all_files()
            self._log(f"🔄 强制重新处理模式：将重新处理全部 {len(files)} 个文件", "INFO")
        else:
            files = self.file_list.get_pending_files()
            if not files:
                all_files = self.file_list.get_all_files()
                if all_files:
                    failed = self.file_list.get_files_by_status(FileStatus.FAILED)
                    if failed:
                        reply = QMessageBox.question(self, "提示",
                            f"有 {len(failed)} 个文件处理失败，是否重试？\n\n提示：也可以勾选「忽略状态」来处理所有文件。",
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                        if reply == QMessageBox.StandardButton.Yes:
                            for f in failed:
                                self.file_list.update_status(f, FileStatus.PENDING)
                            files = failed
                        else:
                            return
                    else:
                        QMessageBox.information(self, "提示", "所有文件都已处理完成！\n\n如需重新处理，请勾选「忽略状态」选项。")
                        return
                else:
                    QMessageBox.warning(self, "警告", "请先添加文件")
                    return
        if self.out_custom.isChecked() and not self.output_dir:
            QMessageBox.warning(self, "警告", "请选择输出目录")
            return
        fc = self.last_config.get('formula_config', {})
        high_risk = []
        if fc.get('bm_to_vec'):
            high_risk.append("\\bm→\\vec 转换")
        if self.last_config.get('inline_to_display'):
            high_risk.append("独立行内转块级")
        if high_risk:
            reply = QMessageBox.question(self, "⚠️ 高风险功能提醒",
                "以下高风险功能已启用：\n\n" + "\n".join(f"  • {f}" for f in high_risk) +
                "\n\n建议先用「🔍 预检预览」查看变更。\n是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return
        reply = QMessageBox.question(self, "确认", f"即将处理 {len(files)} 个文件，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._save_config()
        self.process_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        config = self._get_current_config()
        output_mode = "custom" if self.out_custom.isChecked() else "source"
        output_dir = self.output_dir if output_mode == "custom" else None
        self.worker = RepairWorker(files=files, output_mode=output_mode, output_dir=output_dir,
            max_workers=self.worker_spin.value(), config=config,
            rename_by_title=self.cb_rename_title.isChecked(), auto_open=self.cb_auto_open.isChecked())
        self.worker.progress_updated.connect(self._on_progress)
        self.worker.file_status_signal.connect(self._on_file_status)
        self.worker.log_message.connect(self._log)
        self.worker.finished_all.connect(self._on_finished)
        self.worker.start()

    def _stop_processing(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self._log("⚠️ 正在停止处理...", "WARNING")
            self.stop_btn.setEnabled(False)

    def _on_progress(self, value, msg, completed, total):
        self.progress_bar.setValue(value)
        self.status_label.setText(f"{msg} - {completed}/{total}")

    def _on_file_status(self, file_path, status):
        status_map = {'processing': FileStatus.PROCESSING, 'success': FileStatus.SUCCESS,
                      'failed': FileStatus.FAILED, 'pending': FileStatus.PENDING}
        self.file_list.update_status(file_path, status_map.get(status, FileStatus.PENDING))

    def _on_finished(self, results):
        self.process_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setValue(100)
        success = sum(1 for r in results if r['status'] == 'success')
        failed = len(results) - success
        self._log("")
        self._log(f"📊 处理完成！成功: {success}, 失败: {failed}", "SUCCESS" if failed == 0 else "WARNING")
        if self.cb_rename_title.isChecked():
            renamed = sum(1 for r in results if r.get('title_used'))
            if renamed > 0:
                self._log(f"📝 YAML重命名: {renamed} 个", "INFO")
        self.status_label.setText(f"完成 - 成功: {success}, 失败: {failed}")
        if self.cb_force_reprocess.isChecked():
            self.cb_force_reprocess.setChecked(False)
        QMessageBox.information(self, "完成", f"处理任务已完成！\n\n✅ 成功: {success} 个\n❌ 失败: {failed} 个")

    def _log(self, msg: str, level: str = "INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        icons = {"INFO": "ℹ️", "SUCCESS": "✅", "WARNING": "⚠️", "ERROR": "❌"}
        icon = icons.get(level, "📝")
        colors = {"INFO": "#2c3e50", "SUCCESS": "#27ae60", "WARNING": "#e67e22", "ERROR": "#e74c3c"}
        self.log_text.setTextColor(QColor(colors.get(level, "#2c3e50")))
        self.log_text.append(f"[{timestamp}] {icon} {msg}")
        self.log_text.moveCursor(QTextCursor.MoveOperation.End)

    def _save_log(self):
        text = self.log_text.toPlainText()
        if not text:
            QMessageBox.information(self, "提示", "没有日志内容")
            return
        name = f"md_fixer_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        path, _ = QFileDialog.getSaveFileName(self, "保存日志", name, "文本文件 (*.txt)")
        if path:
            Path(path).write_text(text, encoding='utf-8')
            self._log(f"💾 日志已保存: {path}", "SUCCESS")


# ==================== 主入口 ====================
def main():
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setApplicationVersion(__version__)
    app.setStyle('Fusion')
    app.setStyleSheet("""
        QGroupBox { font-weight: bold; padding-top: 10px; }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
        QCheckBox { spacing: 6px; padding: 2px 0; }
        QCheckBox::indicator { width: 16px; height: 16px; }
        QPushButton { padding: 4px 12px; }
    """)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()