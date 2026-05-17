#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
统一日志面板组件
支持彩色日志、日志级别过滤、日志保存
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit,
    QPushButton, QComboBox, QLabel, QFileDialog, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QTextCursor


class LogPanel(QWidget):
    """统一的日志面板
    
    特性：
    - 彩色日志显示
    - 日志级别过滤
    - 日志保存
    - 日志清空
    """
    
    log_cleared = pyqtSignal()
    log_saved = pyqtSignal(str)  # 保存路径
    
    # 日志级别配置
    LEVELS = {
        "INFO": {"icon": "ℹ️", "color": "#2c3e50", "dark_color": "#e0e0e0"},
        "SUCCESS": {"icon": "✅", "color": "#27ae60", "dark_color": "#27ae60"},
        "WARNING": {"icon": "⚠️", "color": "#e67e22", "dark_color": "#f39c12"},
        "ERROR": {"icon": "❌", "color": "#e74c3c", "dark_color": "#e74c3c"},
        "DEBUG": {"icon": "🔍", "color": "#7f8c8d", "dark_color": "#95a5a6"}
    }
    
    def __init__(self, parent=None, show_toolbar: bool = True):
        super().__init__(parent)
        self.show_toolbar = show_toolbar
        self.is_dark_theme = False
        self.current_filter = "ALL"
        self._all_logs = []  # 存储所有日志用于过滤
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 工具栏
        if self.show_toolbar:
            toolbar = QHBoxLayout()
            
            # 过滤器标签
            filter_label = QLabel("级别过滤:")
            toolbar.addWidget(filter_label)
            
            # 级别过滤器
            self.filter_combo = QComboBox()
            self.filter_combo.addItem("全部", "ALL")
            for level in self.LEVELS.keys():
                self.filter_combo.addItem(f"{self.LEVELS[level]['icon']} {level}", level)
            self.filter_combo.currentIndexChanged.connect(self._on_filter_changed)
            toolbar.addWidget(self.filter_combo)
            
            toolbar.addStretch()
            
            # 清空按钮
            self.clear_btn = QPushButton("🗑️ 清空")
            self.clear_btn.clicked.connect(self.clear)
            toolbar.addWidget(self.clear_btn)
            
            # 保存按钮
            self.save_btn = QPushButton("💾 保存")
            self.save_btn.clicked.connect(self.save_log)
            toolbar.addWidget(self.save_btn)
            
            layout.addLayout(toolbar)
        
        # 日志文本框
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 10))
        self.log_text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(self.log_text)
    
    def set_dark_theme(self, is_dark: bool):
        """设置深色主题模式"""
        self.is_dark_theme = is_dark
        self._refresh_display()
    
    def log(self, message: str, level: str = "INFO"):
        """添加日志
        
        Args:
            message: 日志消息
            level: 日志级别 (INFO, SUCCESS, WARNING, ERROR, DEBUG)
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        level_config = self.LEVELS.get(level.upper(), self.LEVELS["INFO"])
        icon = level_config["icon"]
        
        log_entry = {
            "timestamp": timestamp,
            "level": level.upper(),
            "icon": icon,
            "message": message,
            "formatted": f"[{timestamp}] {icon} {message}"
        }
        
        self._all_logs.append(log_entry)
        
        # 如果符合当前过滤器，显示
        if self._should_display(level):
            self._append_log(log_entry)
    
    def _should_display(self, level: str) -> bool:
        """检查日志是否应该显示"""
        if self.current_filter == "ALL":
            return True
        return level.upper() == self.current_filter
    
    def _append_log(self, log_entry: dict):
        """追加日志到显示区域"""
        level = log_entry["level"]
        level_config = self.LEVELS.get(level, self.LEVELS["INFO"])
        
        # 选择颜色
        if self.is_dark_theme:
            color = QColor(level_config["dark_color"])
        else:
            color = QColor(level_config["color"])
        
        self.log_text.setTextColor(color)
        self.log_text.append(log_entry["formatted"])
        self.log_text.moveCursor(QTextCursor.MoveOperation.End)
    
    def _refresh_display(self):
        """刷新显示（用于过滤器变化或主题变化）"""
        self.log_text.clear()
        
        for log_entry in self._all_logs:
            if self._should_display(log_entry["level"]):
                self._append_log(log_entry)
    
    def _on_filter_changed(self, index: int):
        """过滤器变化回调"""
        self.current_filter = self.filter_combo.currentData()
        self._refresh_display()
    
    def clear(self):
        """清空日志"""
        self.log_text.clear()
        self._all_logs.clear()
        self.log_cleared.emit()
    
    def save_log(self):
        """保存日志到文件"""
        if not self._all_logs:
            QMessageBox.information(self, "提示", "没有日志内容可保存")
            return
        
        default_name = f"epub_toolbox_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存日志", default_name, "文本文件 (*.txt);;所有文件 (*.*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    for log in self._all_logs:
                        f.write(f"[{log['timestamp']}] [{log['level']}] {log['message']}\n")
                
                self.log_saved.emit(file_path)
                self.log(f"日志已保存到: {file_path}", "SUCCESS")
                QMessageBox.information(self, "成功", f"日志已保存到:\n{file_path}")
            except Exception as e:
                self.log(f"保存日志失败: {e}", "ERROR")
                QMessageBox.critical(self, "错误", f"保存失败: {e}")
    
    def get_log_text(self) -> str:
        """获取纯文本格式的日志"""
        lines = []
        for log in self._all_logs:
            lines.append(f"[{log['timestamp']}] [{log['level']}] {log['message']}")
        return "\n".join(lines)
    
    def add_separator(self, char: str = "=", length: int = 60):
        """添加分隔线"""
        self.log(char * length, "INFO")