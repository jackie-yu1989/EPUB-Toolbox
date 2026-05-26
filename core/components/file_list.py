#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
统一文件列表组件 - 增强版（修复同名文件索引问题）
"""

import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from enum import Enum

from PyQt6.QtWidgets import (
    QListWidget, QListWidgetItem, QMenu, QApplication
)
from PyQt6.QtCore import (
    Qt, pyqtSignal, QUrl
)
from PyQt6.QtGui import (
    QDragEnterEvent, QDropEvent, QColor, QAction
)

from core.utils import open_file_location

class FileStatus(Enum):
    """文件处理状态"""
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
    
    @property
    def display_name(self) -> str:
        names = {
            FileStatus.PENDING: "等待中",
            FileStatus.PROCESSING: "处理中",
            FileStatus.SUCCESS: "成功",
            FileStatus.FAILED: "失败"
        }
        return names.get(self, "未知")


class UnifiedFileListWidget(QListWidget):
    """统一的文件列表控件 - 增强版（修复同名文件索引问题）"""
    
    files_added = pyqtSignal(list)
    files_removed = pyqtSignal(list)
    selection_changed = pyqtSignal(int)
    
    def __init__(self, accepted_extensions: List[str] = None, parent=None):
        super().__init__(parent)
        self.accepted_extensions = [ext.lower() for ext in (accepted_extensions or [])]
        self.setAcceptDrops(True)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.setDragEnabled(False)
        
        self.file_paths: Dict[int, Path] = {}
        self.file_status: Dict[int, FileStatus] = {}
        self.file_output_paths: Dict[int, Path] = {}
        self.completed_files: set = set()
        
        self.itemSelectionChanged.connect(self._on_selection_changed)
    
    def set_accepted_extensions(self, extensions: List[str]):
        self.accepted_extensions = [ext.lower() for ext in extensions]
    
    def _is_accepted_file(self, file_path: Path) -> bool:
        if not self.accepted_extensions:
            return True
        return file_path.suffix.lower() in self.accepted_extensions
    
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            event.setDropAction(Qt.DropAction.CopyAction)
        else:
            event.ignore()
    
    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            event.setDropAction(Qt.DropAction.CopyAction)
        else:
            event.ignore()
    
    def dropEvent(self, event: QDropEvent):
        accepted_files = []
        
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            
            if not path.exists():
                continue
                
            if path.is_file() and self._is_accepted_file(path):
                accepted_files.append(path)
            elif path.is_dir():
                for ext in self.accepted_extensions:
                    for file_path in path.rglob(f"*{ext}"):
                        accepted_files.append(file_path)
                    for file_path in path.rglob(f"*{ext.upper()}"):
                        accepted_files.append(file_path)
        
        if accepted_files:
            accepted_files = list(dict.fromkeys(accepted_files))
            event.acceptProposedAction()
            self.files_added.emit(accepted_files)
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
    
    def add_files(self, files: List[Path], skip_completed: bool = False) -> int:
        """批量添加文件"""
        added_count = 0
        
        for f in files:
            if skip_completed and str(f.absolute()) in self.completed_files:
                continue
            
            if self.add_file(f):
                added_count += 1
        
        return added_count
    
    def remove_selected(self) -> List[Path]:
        removed = []
        for item in sorted(self.selectedItems(), key=lambda x: self.row(x), reverse=True):
            row = self.row(item)
            if row in self.file_paths:
                file_path = self.file_paths[row]
                removed.append(file_path)
                self.completed_files.discard(str(file_path.absolute()))
                del self.file_paths[row]
                del self.file_status[row]
                if row in self.file_output_paths:
                    del self.file_output_paths[row]
            self.takeItem(row)
        
        self._reindex()
        
        if removed:
            self.files_removed.emit(removed)
        
        return removed
    
    def clear_all(self):
        count = self.count()
        if count > 0:
            removed = list(self.file_paths.values())
            self.clear()
            self.file_paths.clear()
            self.file_status.clear()
            self.file_output_paths.clear()
            self.completed_files.clear()
            self.files_removed.emit(removed)
    
    def update_status(self, file_path: Path, status: FileStatus, output_path: Path = None):
        colors = {
            FileStatus.SUCCESS: QColor(39, 174, 96),
            FileStatus.FAILED: QColor(231, 76, 60),
            FileStatus.PROCESSING: QColor(52, 152, 219),
            FileStatus.PENDING: QColor(128, 128, 128)
        }
        
        for index, path in self.file_paths.items():
            if path == file_path:
                self.file_status[index] = status
                
                if output_path:
                    self.file_output_paths[index] = output_path
                
                if status == FileStatus.SUCCESS:
                    self.completed_files.add(str(file_path.absolute()))
                
                item = self.item(index)
                if item:
                    base_name = file_path.name
                    for old_icon in ["⏳", "🔄", "✅", "❌", "📄"]:
                        base_name = base_name.replace(f"{old_icon} ", "")
                    item.setText(f"{status.icon} {base_name}")
                    item.setForeground(colors.get(status, QColor(0, 0, 0)))
                    
                    if output_path:
                        item.setToolTip(f"源文件: {file_path}\n输出文件: {output_path}")
                    else:
                        item.setToolTip(str(file_path))
                break
    
    def reset_all_status(self):
        for file_path in self.file_paths.values():
            self.update_status(file_path, FileStatus.PENDING)
    
    def get_all_files(self) -> List[Path]:
        return list(self.file_paths.values())
    
    def get_pending_files(self) -> List[Path]:
        pending = []
        for index, path in self.file_paths.items():
            if self.file_status[index] == FileStatus.PENDING:
                pending.append(path)
        return pending
    
    def get_files_by_status(self, status: FileStatus) -> List[Path]:
        return [path for idx, path in self.file_paths.items() 
                if self.file_status.get(idx) == status]
    
    def get_statistics(self) -> Dict[str, int]:
        stats = {
            'total': len(self.file_paths),
            'pending': 0,
            'processing': 0,
            'success': 0,
            'failed': 0
        }
        for status in self.file_status.values():
            stats[status.value] = stats.get(status.value, 0) + 1
        return stats
    
    def _reindex(self):
        """重新索引文件 - 修复同名文件匹配问题"""
        new_paths = {}
        new_status = {}
        new_outputs = {}
        
        # 创建已使用索引的集合
        used_indices = set()
        
        for i in range(self.count()):
            item = self.item(i)
            item_text = item.text()
            item_tooltip = item.toolTip()
            
            # 清理显示文本，获取纯文件名
            clean_name = item_text
            for icon in ["⏳ ", "🔄 ", "✅ ", "❌ "]:
                clean_name = clean_name.replace(icon, "")
            
            best_match = None
            
            # 第一轮：精确匹配（通过工具提示中的完整路径）
            for idx, path in self.file_paths.items():
                if idx in used_indices:
                    continue
                if str(path) in item_tooltip:
                    best_match = idx
                    break
            
            # 第二轮：如果没找到，通过文件名匹配
            if best_match is None:
                for idx, path in self.file_paths.items():
                    if idx in used_indices:
                        continue
                    if path.name == clean_name:
                        best_match = idx
                        break
            
            if best_match is not None:
                used_indices.add(best_match)
                new_paths[i] = self.file_paths[best_match]
                new_status[i] = self.file_status[best_match]
                if best_match in self.file_output_paths:
                    new_outputs[i] = self.file_output_paths[best_match]
        
        self.file_paths = new_paths
        self.file_status = new_status
        self.file_output_paths = new_outputs
    
    def keyPressEvent(self, event):
        """捕获 Ctrl+V 粘贴事件，从剪贴板提取文件路径"""
        # 检测 Ctrl+V
        if event.key() == Qt.Key.Key_V and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            clipboard = QApplication.clipboard()
            
            # 尝试从剪贴板获取文本
            text = clipboard.text()
            if text:
                files = self._parse_clipboard_text(text)
                if files:
                    self.files_added.emit(files)
                    return  # 已处理，不调用父类
            
            # 如果文本解析没找到文件，尝试从剪贴板获取 URL 列表（兼容部分文件管理器复制）
            mime = clipboard.mimeData()
            if mime.hasUrls():
                files = self._extract_files_from_urls(mime.urls())
                if files:
                    self.files_added.emit(files)
                    return

        # ★ 新增：Delete 键删除选中文件
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if self.selectedItems():
                self.remove_selected()
                return

        # 非粘贴事件，交给父类处理
        super().keyPressEvent(event)
    
    def _parse_clipboard_text(self, text: str) -> List[Path]:
        """解析剪贴板文本，提取符合扩展名的文件路径
        
        支持格式：
        - 单行：C:\path\to\file.md
        - 多行（每行一个路径）
        - 混合：文件路径 + 文件夹路径
        - Unix 路径：/home/user/file.md
        - 带引号的路径（路径含空格时常见）
        """
        found_files = []
        
        # 按换行分割
        raw_lines = text.strip().splitlines()
        
        for line in raw_lines:
            line = line.strip()
            if not line:
                continue
            
            # 移除首尾引号（Windows 复制含空格的路径时会带引号）
            line = line.strip('"').strip("'")
            
            # 尝试作为路径处理
            try:
                path = Path(line)
            except Exception:
                # 不是合法路径，尝试识别路径模式
                # 处理 "file1.md file2.md" 这种空格分隔的情况
                # 如果当前行没有换行但包含多个文件，且看起来像是被空格分隔的路径
                # 这里不做太复杂的解析，因为大多数文件管理器复制时会换行
                continue
            
            # ★ 如果路径不存在，尝试拼接前缀（处理只粘贴文件名的场景）
            if not path.exists() and not path.is_absolute():
                # 如果只是纯文件名，当前工作目录下查找
                cwd_path = Path.cwd() / path
                if cwd_path.exists():
                    path = cwd_path
            
            if not path.exists():
                continue
            
            if path.is_file() and self._is_accepted_file(path):
                found_files.append(path)
            elif path.is_dir():
                # 递归收集文件夹内符合扩展名的文件
                for ext in self.accepted_extensions:
                    for file_path in path.rglob(f"*{ext}"):
                        found_files.append(file_path)
                    for file_path in path.rglob(f"*{ext.upper()}"):
                        found_files.append(file_path)
        
        # 去重并保持顺序
        seen = set()
        unique_files = []
        for f in found_files:
            f_abs = str(f.absolute())
            if f_abs not in seen:
                seen.add(f_abs)
                unique_files.append(f)
        
        return unique_files
    
    def _extract_files_from_urls(self, urls: list) -> List[Path]:
        """从剪贴板 URL 列表中提取符合扩展名的文件（复用 dropEvent 逻辑）"""
        accepted_files = []
        
        for url in urls:
            path = Path(url.toLocalFile())
            
            if not path.exists():
                continue
            
            if path.is_file() and self._is_accepted_file(path):
                accepted_files.append(path)
            elif path.is_dir():
                for ext in self.accepted_extensions:
                    for file_path in path.rglob(f"*{ext}"):
                        accepted_files.append(file_path)
                    for file_path in path.rglob(f"*{ext.upper()}"):
                        accepted_files.append(file_path)
        
        # 去重
        seen = set()
        unique_files = []
        for f in accepted_files:
            f_abs = str(f.absolute())
            if f_abs not in seen:
                seen.add(f_abs)
                unique_files.append(f)
        
        return unique_files


    def _on_selection_changed(self):
        self.selection_changed.emit(len(self.selectedItems()))
    
    def contextMenuEvent(self, event):
        menu = QMenu(self)
        
        open_folder_action = QAction("📂 打开所在文件夹", self)
        open_folder_action.triggered.connect(lambda: self._open_folder_for_selected())
        
        remove_action = QAction("❌ 移除选中", self)
        remove_action.triggered.connect(self.remove_selected)
        
        clear_all_action = QAction("🗑️ 清空全部", self)
        clear_all_action.triggered.connect(self.clear_all)
        
        menu.addAction(open_folder_action)
        menu.addSeparator()
        menu.addAction(remove_action)
        menu.addAction(clear_all_action)
        
        if not self.selectedItems():
            open_folder_action.setEnabled(False)
            remove_action.setEnabled(False)
        
        menu.exec(event.globalPos())
    
    def _open_folder_for_selected(self):
        selected = self.selectedItems()
        if selected:
            item = selected[0]
            row = self.row(item)
            if row in self.file_paths:
                file_path = self.file_paths[row]
                self._open_folder(file_path)
    
    def _open_folder(self, file_path: Path):
        """打开文件所在文件夹（使用统一工具函数）"""
        open_file_location(file_path)  # 复用 core.utils 中的函数

class DropHotzoneMixin:
    """拖放热区 Mixin
    
    为任意 QWidget 提供拖放文件到 UnifiedFileListWidget 的能力。
    使用方式：
        widget = QGroupBox(...)
        DropHotzoneMixin.install(widget, file_list, accepted_extensions)
    """
    
    @staticmethod
    def install(widget, file_list, accepted_extensions: List[str]):
        """安装拖放热区到指定控件
        
        Args:
            widget: 要安装热区的控件（如 QGroupBox）
            file_list: 目标 UnifiedFileListWidget
            accepted_extensions: 接受的文件扩展名列表
        """
        widget.setAcceptDrops(True)
        widget._dh_file_list = file_list
        widget._dh_extensions = [ext.lower() for ext in accepted_extensions]
        
        original_drag_enter = widget.dragEnterEvent
        original_drag_move = widget.dragMoveEvent
        original_drop = widget.dropEvent
        
        def dragEnterEvent(event):
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
                event.setDropAction(Qt.DropAction.CopyAction)
            else:
                event.ignore()
        
        def dragMoveEvent(event):
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
                event.setDropAction(Qt.DropAction.CopyAction)
            else:
                event.ignore()
        
        def dropEvent(event):
            accepted_files = []
            for url in event.mimeData().urls():
                path = Path(url.toLocalFile())
                if not path.exists():
                    continue
                ext = path.suffix.lower()
                if path.is_file() and ext in widget._dh_extensions:
                    accepted_files.append(path)
                elif path.is_dir():
                    for e in widget._dh_extensions:
                        for fp in path.rglob(f"*{e}"):
                            accepted_files.append(fp)
                        for fp in path.rglob(f"*{e.upper()}"):
                            accepted_files.append(fp)
            
            if accepted_files:
                seen = set()
                unique = []
                for f in accepted_files:
                    fa = str(f.absolute())
                    if fa not in seen:
                        seen.add(fa)
                        unique.append(f)
                event.acceptProposedAction()
                widget._dh_file_list.files_added.emit(unique)
            else:
                event.ignore()
        
        widget.dragEnterEvent = dragEnterEvent
        widget.dragMoveEvent = dragMoveEvent
        widget.dropEvent = dropEvent