#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
通用对话框组件
提供确认、关于、依赖检查和处理结果等可复用对话框
"""

import logging
from typing import List, Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QTextBrowser, QGroupBox, QDialogButtonBox, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

# ★ 从统一版本模块导入
from core.version import __version__ as APP_VERSION, __date__ as APP_DATE, __author__ as APP_AUTHOR


# 模块级日志记录器
logger = logging.getLogger(__name__)


class ConfirmDialog(QDialog):
    """通用确认对话框
    
    显示标题、消息和可选的详细信息，提供确认/取消按钮。
    
    Usage:
        dialog = ConfirmDialog("确认删除", "确定要删除这些文件吗？", "file1.md\nfile2.md")
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # 用户点击了确认
    """
    
    def __init__(self, title: str, message: str, details: str = "", parent=None):
        """初始化确认对话框
        
        Args:
            title: 对话框标题
            message: 主要提示消息
            details: 可选的详细信息（显示在可折叠的文本区域）
            parent: 父级窗口
        """
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(500, 350)
        self._setup_ui(message, details)
    
    def _setup_ui(self, message: str, details: str):
        """构建对话框 UI 布局"""
        layout = QVBoxLayout(self)
        
        # 标题
        title_label = QLabel("📋 确认操作")
        title_font = QFont("Microsoft YaHei", 14, QFont.Weight.Bold)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)
        
        # 主要消息
        msg_label = QLabel(message)
        msg_label.setWordWrap(True)
        msg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(msg_label)
        
        # 详细信息（可选）
        if details:
            details_group = QGroupBox("详细信息")
            details_layout = QVBoxLayout(details_group)
            details_text = QTextEdit()
            details_text.setPlainText(details)
            details_text.setReadOnly(True)
            details_text.setMaximumHeight(200)
            details_layout.addWidget(details_text)
            layout.addWidget(details_group)
        
        layout.addStretch()
        
        # 按钮
        button_box = QDialogButtonBox()
        ok_button = button_box.addButton("✅ 确认", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_button = button_box.addButton("❌ 取消", QDialogButtonBox.ButtonRole.RejectRole)
        
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)


class AboutDialog(QMessageBox):
    """关于对话框
    
    显示应用版本、作者、功能模块和技术栈信息。
    
    Usage:
        AboutDialog().exec()
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("关于 EPUB 工具箱")
        self.setIcon(QMessageBox.Icon.Information)
        
        self.setText(
            f"<h2>📚 EPUB 工具箱</h2>"
            f"<p><b>版本:</b> {APP_VERSION}</p>"
            f"<p><b>作者:</b> {APP_AUTHOR}</p>"
            f"<p><b>更新日期:</b> {APP_DATE}</p>"
        )
        
        self.setInformativeText(
            "<p>集成 MD公式修复、MD转EPUB、EPUB转PDF、EPUB转Word 和组合工作流"
            "五大功能的综合性电子书处理工具。</p>"
            "<p><b>功能模块:</b></p>"
            "<ul>"
            "<li>🔄 <b>组合工作流</b> — 5种模式，流水线并行，📊可视化监视面板</li>"
            "<li>📝 <b>MD公式修复</b> — 16项可配置修复，批量预检摘要，并排对比预览</li>"
            "<li>📖 <b>MD转EPUB</b> — 外部CSS自动发现，10种主题颜色，Mermaid图表</li>"
            "<li>📄 <b>EPUB转Word</b> — 软回车修复，5种排版预设（学术/书籍/商务/技术）</li>"
            "<li>📕 <b>EPUB转PDF</b> — 4种页边距预设，可选页码，多线程并行</li>"
            "</ul>"
            "<p><b>工具链:</b> 帮助菜单 → 依赖工具管理 → 一键安装 Pandoc/Calibre/Node.js/Mermaid CLI</p>"
            "<p><b>全局:</b> 6套主题，拖拽+粘贴导入，系统托盘，全局热键唤醒</p>"
            "<p><b>技术栈:</b> PyQt6 + Pandoc + Calibre + MathJax v3 + python-docx</p>"
            "<p><b>许可证:</b> MIT</p>"
        )


class DependencyDialog(QMessageBox):
    """依赖检查对话框
    
    当模块依赖未安装时显示，提示用户安装缺失的依赖。
    
    Usage:
        dialog = DependencyDialog("MD转EPUB", ["Pandoc"])
        dialog.exec()
    """
    
    def __init__(self, module_name: str, missing_deps: List[str], parent=None):
        """初始化依赖检查对话框
        
        Args:
            module_name: 模块名称
            missing_deps: 缺失的依赖列表
            parent: 父级窗口
        """
        super().__init__(parent)
        self.setWindowTitle(f"{module_name} - 依赖缺失")
        self.setIcon(QMessageBox.Icon.Warning)
        
        self.setText(f"<h3>⚠️ {module_name} 模块缺少必要依赖</h3>")
        
        deps_text = "<br>".join([f"• {dep}" for dep in missing_deps])
        self.setInformativeText(
            f"<p>以下依赖未安装:</p>"
            f"<p>{deps_text}</p>"
            f"<p>请安装相应依赖后重试。</p>"
        )
        
        self.setStandardButtons(QMessageBox.StandardButton.Ok)


class ProcessingResultDialog(QMessageBox):
    """处理结果对话框
    
    显示文件处理的结果摘要（成功/失败数量，详细列表）。
    失败数 > 0 时图标为警告，全部成功时图标为信息，全部失败时图标为错误。
    
    Usage:
        dialog = ProcessingResultDialog(8, 2, ["file1.md: 成功", "file2.md: 失败 - 编码错误"])
        dialog.exec()
    """
    
    # 详细信息最大显示条数
    MAX_DETAIL_ITEMS = 10
    
    def __init__(self, success_count: int, failed_count: int, 
                 details: Optional[List[str]] = None, parent=None):
        """初始化处理结果对话框
        
        Args:
            success_count: 成功处理的文件数
            failed_count: 处理失败的文件数
            details: 可选的详细结果列表
            parent: 父级窗口
        """
        super().__init__(parent)
        self.setWindowTitle("处理完成")
        
        # 根据失败数量选择图标和标题
        if failed_count == 0:
            self.setIcon(QMessageBox.Icon.Information)
            self.setText("<h3>✅ 处理完成！</h3>")
        elif success_count == 0:
            self.setIcon(QMessageBox.Icon.Critical)
            self.setText("<h3>❌ 处理失败</h3>")
        else:
            self.setIcon(QMessageBox.Icon.Warning)
            self.setText("<h3>⚠️ 处理完成（部分失败）</h3>")
        
        # 结果摘要
        summary_parts = [f"成功: {success_count} 个"]
        if failed_count > 0:
            summary_parts.append(f"失败: {failed_count} 个")
        self.setInformativeText(f"<p>{'<br>'.join(summary_parts)}</p>")
        
        # 详细列表（截断显示）
        if details:
            detail_text = "<br>".join(details[:self.MAX_DETAIL_ITEMS])
            if len(details) > self.MAX_DETAIL_ITEMS:
                detail_text += f"<br>... 还有 {len(details) - self.MAX_DETAIL_ITEMS} 条"
            self.setDetailedText(detail_text)
        
        self.setStandardButtons(QMessageBox.StandardButton.Ok)

class ShortcutDialog(QDialog):
    """快捷键一览对话框"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⌨️ 快捷键一览")
        self.setMinimumSize(600, 480)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        # 说明
        hint = QLabel("以下是 EPUB 工具箱的全部快捷键，按作用域分类展示。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666; font-size: 11px; padding: 0 4px;")
        layout.addWidget(hint)
        
        # 表格
        table = QTextBrowser()
        table.setFont(QFont("Consolas", 11))
        table.setStyleSheet("""
            QTextBrowser {
                background-color: #fafafa;
                border: 1px solid #dee2e6;
                border-radius: 4px;
                padding: 10px;
            }
        """)
        
        shortcuts = [
            # (快捷键, 功能, 作用域)
            ("Ctrl+0/1/2/3/4",  "切换到工作流/MD修复/MD转EPUB/EPUB转Word/EPUB转PDF", "主窗口"),
            ("Ctrl+Shift+D",    "开始处理（当前模块）",                               "主窗口"),
            ("Ctrl+Shift+L",    "预检预览（默认第一个文件）",                          "主窗口"),
            ("Ctrl+Shift+M",    "打开监视面板（工作流模块）",                          "主窗口"),
            ("Ctrl+L",          "显示/隐藏日志面板",                                  "主窗口/面板"),
            ("Ctrl+Q",          "清空当前窗口日志（主窗口/监视面板）",                 "主窗口/面板"),
            ("Ctrl+Shift+Q",    "清空当前模块文件列表",                               "主窗口"),
            ("Ctrl+K",          "切换托盘模式",                                      "主窗口"),
            ("Ctrl+Shift+K",    "从系统托盘唤醒窗口并强制置顶",                        "全局"),
            ("Ctrl+W",          "退出软件 / 关闭修复预览 / 关闭监视面板",              "全局"),
            ("Ctrl+Left",       "预览中查看上一处变更",                               "预览"),
            ("Ctrl+Right",      "预览中查看下一处变更",                               "预览"),
            ("Esc",             "关闭修复预览并激活主窗口 / 关闭监视面板",             "预览/面板"),
            ("Delete",          "删除文件列表中选中的文件 / 删除选中行",               "主窗口/面板"),
            ("Ctrl+V",          "粘贴文件到监视面板",                                 "监视面板"),
            ("双击托盘图标",    "从系统托盘唤醒窗口",                                 "托盘"),
        ]
        
        # 构建 HTML 表格
        html = '<table cellpadding="4" cellspacing="0" style="font-size:12px; width:100%;">'
        html += '<tr style="background-color:#e9ecef; font-weight:bold;">'
        html += '<td style="width:140px;">快捷键</td>'
        html += '<td>功能</td>'
        html += '<td style="width:70px; text-align:center;">作用域</td>'
        html += '</tr>'
        
        for i, (key, func, scope) in enumerate(shortcuts):
            bg = '#ffffff' if i % 2 == 0 else '#f8f9fa'
            scope_color = {
                "主窗口": "#3498db",
                "全局": "#e67e22",
                "预览": "#27ae60",
                "面板": "#9b59b6",
                "主窗口/面板": "#16a085",
                "托盘": "#8e44ad",
            }.get(scope, "#333")
            
            html += f'<tr style="background-color:{bg};">'
            html += f'<td><code style="font-weight:bold;">{key}</code></td>'
            html += f'<td>{func}</td>'
            html += f'<td style="text-align:center; color:{scope_color}; font-weight:bold;">{scope}</td>'
            html += '</tr>'
        
        html += '</table>'
        table.setHtml(html)
        layout.addWidget(table)
        
        # 关闭按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        close_btn.setStyleSheet("padding: 6px 20px;")
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)


# ==================== 元信息 ====================
__author__ = "YQJ"
__version__ = "1.3.0"
__date__ = "2026.05.25"