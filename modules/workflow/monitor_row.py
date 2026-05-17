#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
监视面板 - 单文件流水线行组件
包含 StepBarWidget（单步骤状态条）和 FilePipelineRow（单文件行）
"""

from pathlib import Path
from typing import List, Dict, Optional
from enum import Enum

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QMenu, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QColor


# ==================== 状态枚举 ====================

class StepStatus(Enum):
    """步骤状态枚举"""
    WAITING = "waiting"
    PROCESSING = "processing"
    COMPLETED = "completed"
    COMPLETED_CLEANED = "completed_cleaned"
    FAILED = "failed"
    SKIPPED = "skipped"

    @property
    def icon(self) -> str:
        icons = {
            StepStatus.WAITING: "⏳",
            StepStatus.PROCESSING: "🔄",
            StepStatus.COMPLETED: "✅",
            StepStatus.FAILED: "❌",
            StepStatus.SKIPPED: "⏭️",
        }
        return icons.get(self, "")


class StepType(Enum):
    """步骤类型枚举"""
    REPAIR = "repair"
    MD2EPUB = "md2epub"
    EPUB2PDF = "epub2pdf"

    @property
    def display_name(self) -> str:
        names = {
            StepType.REPAIR: "MD修复",
            StepType.MD2EPUB: "MD转EPUB",
            StepType.EPUB2PDF: "EPUB转PDF",
        }
        return names.get(self, "")


# ==================== 步骤状态条组件 ====================

class StepBarWidget(QWidget):
    """单个步骤的状态条组件

    显示彩色进度条（含产物名） + 操作按钮。
    右键点击进度条 → 打开产物所在文件夹。
    """

    preview_requested = pyqtSignal()
    rollback_requested = pyqtSignal()
    retry_requested = pyqtSignal()
    open_folder_requested = pyqtSignal(str)

    COLORS = {
        StepStatus.WAITING:    ("#bdc3c7", "#e8e8e8"),
        StepStatus.PROCESSING: ("#f39c12", "#fdebd0"),
        StepStatus.COMPLETED:  ("#27ae60", "#d5f5e3"),
        StepStatus.COMPLETED_CLEANED: ("#82e0aa", "#eafaf1"),
        StepStatus.FAILED:     ("#e74c3c", "#fadbd8"),
        StepStatus.SKIPPED:    ("#f1c40f", "#fef9e7"),
    }

    def __init__(self, step_type: StepType, parent=None):
        super().__init__(parent)
        self.step_type = step_type
        self.status = StepStatus.WAITING
        self.progress = 0
        self.output_path = ""
        self.error_message = ""

        self._setup_ui()
        self._apply_status(StepStatus.WAITING)

    def _setup_ui(self):
        """构建 UI 布局 — 操作按钮在标题右侧"""
        # ★ 移除宽度限制，让列自适应
        self.setMinimumWidth(80)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(0)

        # ★ 标题行：步骤名 + 操作按钮
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 1, 0, 1)
        title_row.setSpacing(2)

        self.name_label = QLabel(self.step_type.display_name)
        self.name_label.setStyleSheet(
            "font-size: 10px; color: #7f8c8d; font-weight: bold;"
        )
        title_row.addWidget(self.name_label)

        title_row.addStretch()

        # 操作按钮（放在标题右侧）
        self.preview_btn = QPushButton("👁")
        self.preview_btn.setFixedSize(18, 18)
        self.preview_btn.setToolTip("预览产物")
        self.preview_btn.setStyleSheet(
            "QPushButton { border: none; background: transparent; font-size: 10px; }"
            "QPushButton:hover { background: #e8e8e8; border-radius: 3px; }"
        )
        self.preview_btn.clicked.connect(self.preview_requested.emit)
        self.preview_btn.setVisible(False)
        title_row.addWidget(self.preview_btn)

        self.rollback_btn = QPushButton("🗑")
        self.rollback_btn.setFixedSize(18, 18)
        self.rollback_btn.setToolTip("回滚（删除产物）")
        self.rollback_btn.setStyleSheet(
            "QPushButton { border: none; background: transparent; font-size: 10px; }"
            "QPushButton:hover { background: #fadbd8; border-radius: 3px; }"
        )
        self.rollback_btn.clicked.connect(self.rollback_requested.emit)
        self.rollback_btn.setVisible(False)
        title_row.addWidget(self.rollback_btn)

        self.retry_btn = QPushButton("🔄")
        self.retry_btn.setFixedSize(18, 18)
        self.retry_btn.setToolTip("重试此步骤")
        self.retry_btn.setStyleSheet(
            "QPushButton { border: none; background: transparent; font-size: 10px; }"
            "QPushButton:hover { background: #d5f5e3; border-radius: 3px; }"
        )
        self.retry_btn.clicked.connect(self.retry_requested.emit)
        self.retry_btn.setVisible(False)
        title_row.addWidget(self.retry_btn)

        layout.addLayout(title_row)

        # 进度条（显示产物名或状态文本）
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimumHeight(22)
        self.progress_bar.setMaximumHeight(22)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("等待")
        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.progress_bar.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self.progress_bar)

    def set_status(self, status: StepStatus, progress: int = 0,
                   output_path: str = "", error: str = "", elapsed: float = 0):
        """更新步骤状态"""
        self.status = status
        self.progress = progress
        self.output_path = output_path
        self.error_message = error

        self._apply_status(status)

        if status == StepStatus.PROCESSING:
            self.progress_bar.setValue(progress)
            self.progress_bar.setFormat(f"处理中 {progress}%")

        elif status == StepStatus.COMPLETED:
            self.progress_bar.setValue(100)
            file_name = Path(output_path).name if output_path else ""
            # ★ 产物名称显示在进度条上
            if elapsed > 0:
                self.progress_bar.setFormat(f"{file_name}")
            else:
                self.progress_bar.setFormat(f"{file_name}")
            self.progress_bar.setToolTip(
                f"产物: {output_path}\n耗时: {elapsed:.1f}s\n双击打开文件夹"
            )
            self._set_buttons(show_preview=True, show_rollback=True, show_retry=False)

        elif status == StepStatus.COMPLETED_CLEANED:
            self.progress_bar.setValue(100)
            file_name = Path(output_path).name if output_path else ""
            self.progress_bar.setFormat(f"已清理: {file_name}")
            self.progress_bar.setToolTip(
                f"产物已被清理: {output_path}\n工作流完成后自动删除"
            )
            self._set_buttons(show_preview=False, show_rollback=False, show_retry=False)

        elif status == StepStatus.FAILED:
            self.progress_bar.setValue(0)
            short_error = error[:25] + "..." if len(error) > 25 else error
            self.progress_bar.setFormat(f"❌ {short_error}")
            self.progress_bar.setToolTip(error)
            self._set_buttons(show_preview=False, show_rollback=True, show_retry=True)

        elif status == StepStatus.SKIPPED:
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("已跳过")
            self._set_buttons(show_preview=False, show_rollback=False, show_retry=False)

        elif status == StepStatus.WAITING:
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("等待")
            self._set_buttons(show_preview=False, show_rollback=False, show_retry=False)

    def _apply_status(self, status: StepStatus):
        """应用状态颜色样式"""
        main_color, bg_color = self.COLORS[status]

        if status == StepStatus.SKIPPED:
            self.progress_bar.setStyleSheet(f"""
                QProgressBar {{
                    border: 2px dashed {main_color};
                    border-radius: 3px;
                    background-color: transparent;
                    text-align: center;
                    font-size: 10px;
                }}
                QProgressBar::chunk {{ background-color: transparent; }}
            """)
        else:
            self.progress_bar.setStyleSheet(f"""
                QProgressBar {{
                    border: 1px solid {main_color};
                    border-radius: 3px;
                    background-color: {bg_color};
                    text-align: center;
                    font-size: 10px;
                    font-weight: bold;
                }}
                QProgressBar::chunk {{ background-color: {main_color}; border-radius: 2px; }}
            """)

    def _set_buttons(self, show_preview: bool, show_rollback: bool, show_retry: bool):
        """设置操作按钮可见性"""
        self.preview_btn.setVisible(show_preview)
        self.rollback_btn.setVisible(show_rollback)
        self.retry_btn.setVisible(show_retry)

    def _on_context_menu(self, pos):
        """右键菜单：打开产物所在文件夹"""
        if not self.output_path or self.status != StepStatus.COMPLETED:
            return

        output = Path(self.output_path)
        if not output.exists():
            return

        menu = QMenu(self)
        open_action = menu.addAction("📂 打开产物所在文件夹")
        action = menu.exec(self.progress_bar.mapToGlobal(pos))

        if action == open_action:
            self.open_folder_requested.emit(self.output_path)

    def mouseDoubleClickEvent(self, event):
        """双击进度条：打开产物文件夹"""
        if self.output_path and self.status == StepStatus.COMPLETED:
            from core.utils import open_file_location
            open_file_location(Path(self.output_path))
        super().mouseDoubleClickEvent(event)


# ==================== 单文件流水线行组件 ====================

# monitor_row.py — FilePipelineRow 类中添加信号和右键菜单

class FilePipelineRow(QWidget):
    """单文件流水线行组件"""

    preview_requested = pyqtSignal(Path, StepType)
    repair_preview_requested = pyqtSignal(Path)  # ★ 右键修复预览（直接进入配置调试）
    rollback_requested = pyqtSignal(Path, StepType)
    retry_requested = pyqtSignal(Path, StepType)
    config_requested = pyqtSignal(Path)
    remove_requested = pyqtSignal(Path)

    def __init__(self, file_path: Path, steps: List[StepType], 
                 row_index: int = 0, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.row_index = row_index
        self.step_widgets: Dict[StepType, StepBarWidget] = {}

        self._setup_ui(steps)
        self.setMinimumHeight(55)
        
        # ★ 启用右键菜单
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

        self._is_selected = False

    def _on_context_menu(self, pos):
        """右键菜单：修复预览 / 删除文件 / 打开所在文件夹"""
        menu = QMenu(self)
        
        # ★ 新增：修复预览
        preview_action = menu.addAction("🔍 修复预览")
        menu.addSeparator()
        remove_action = menu.addAction("❌ 从列表移除")
        menu.addSeparator()
        open_folder_action = menu.addAction("📂 打开所在文件夹")
        
        action = menu.exec(self.mapToGlobal(pos))
        
        if action == preview_action:
            self.repair_preview_requested.emit(self.file_path)
        elif action == remove_action:
            self.remove_requested.emit(self.file_path)
        elif action == open_folder_action:
            from core.utils import open_file_location
            open_file_location(self.file_path)

    def _setup_ui(self, steps: List[StepType]):
        """构建行布局 — 序号 + 文件名 + 配置 + 步骤条"""
        self.setStyleSheet("""
            FilePipelineRow {
                background-color: #fafafa;
                border-bottom: 1px solid #e8e8e8;
            }
            FilePipelineRow:hover {
                background-color: #f0f4f8;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(6)

        # ★ 序号
        index_label = QLabel(f"{self.row_index}")
        index_label.setFixedWidth(36)
        index_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        index_label.setStyleSheet("""
            font-size: 12px; 
            font-weight: bold; 
            color: #888;
            background: #f0f0f0;
            border-radius: 10px;
            padding: 2px 4px;
        """)
        layout.addWidget(index_label)

        # ★ 文件名（固定宽度，单行省略）
        file_name = self.file_path.name
        file_label = QLabel()
        file_label.setMinimumWidth(120)
        file_label.setMaximumWidth(250)
        file_label.setFixedWidth(200)  # 默认 200px 宽
        file_label.setFont(QFont("Microsoft YaHei", 10))
        file_label.setToolTip(f"完整路径: {self.file_path}")
        file_label.setTextFormat(Qt.TextFormat.PlainText)
        file_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        metrics = file_label.fontMetrics()
        elided = metrics.elidedText(file_name, Qt.TextElideMode.ElideMiddle, 142)
        file_label.setText(f"📄 {elided}")
        layout.addWidget(file_label)

        # 配置按钮 ⚙️
        config_btn = QPushButton("⚙")
        config_btn.setFixedSize(22, 22)
        config_btn.setToolTip(
            f"打开 {self.file_path.name} 的独立修复设置\n"
            f"覆盖全局配置，仅对该文件生效"
        )
        config_btn.setStyleSheet("""
            QPushButton {
                border: 1px solid #ddd;
                border-radius: 3px;
                background: #fff;
                font-size: 12px;
            }
            QPushButton:hover {
                border-color: #3498db;
                background: #eaf2f8;
            }
        """)
        config_btn.clicked.connect(lambda: self.config_requested.emit(self.file_path))
        layout.addWidget(config_btn)

        # ★ 添加分隔线，固定宽度保证列对齐
        spacer = QWidget()
        spacer.setFixedWidth(6)
        layout.addWidget(spacer)

        # 各步骤状态条
        for step in steps:
            step_bar = StepBarWidget(step)
            self.step_widgets[step] = step_bar

            step_bar.preview_requested.connect(
                lambda s=step: self.preview_requested.emit(self.file_path, s))
            step_bar.rollback_requested.connect(
                lambda s=step: self.rollback_requested.emit(self.file_path, s))
            step_bar.retry_requested.connect(
                lambda s=step: self.retry_requested.emit(self.file_path, s))
            step_bar.open_folder_requested.connect(self._on_open_step_folder)

            layout.addWidget(step_bar, 1)

        self.setMinimumHeight(55)

    row_clicked = pyqtSignal(object, bool)  # row实例, ctrl_pressed

    def mousePressEvent(self, event):
        ctrl = event.modifiers() == Qt.KeyboardModifier.ControlModifier
        self.row_clicked.emit(self, ctrl)

    def _set_selected(self, selected: bool):
        self._is_selected = selected
        if selected:
            p = self.palette()
            p.setColor(self.backgroundRole(), QColor("#d4e6f1"))
            self.setPalette(p)
            self.setAutoFillBackground(True)
        else:
            self.setAutoFillBackground(False)
            self.setPalette(self.style().standardPalette())
            self.setStyleSheet("""
                FilePipelineRow {
                    background-color: #fafafa;
                    border-bottom: 1px solid #e8e8e8;
                }
                FilePipelineRow:hover {
                    background-color: #f0f4f8;
                }
            """)    

    def update_step(self, step: StepType, status: StepStatus,
                    progress: int = 0, output_path: str = "",
                    error: str = "", elapsed: float = 0):
        widget = self.step_widgets.get(step)
        if widget:
            widget.set_status(status, progress, output_path, error, elapsed)

    def set_all_waiting(self):
        for widget in self.step_widgets.values():
            widget.set_status(StepStatus.WAITING)

    def set_config_indicator(self, has_custom_config: bool):
        """设置配置按钮样式"""
        layout = self.layout()
        for i in range(layout.count()):
            item = layout.itemAt(i)
            widget = item.widget()
            if isinstance(widget, QPushButton) and widget.text() == "⚙":
                if has_custom_config:
                    widget.setStyleSheet("""
                        QPushButton {
                            border: 2px solid #e67e22;
                            border-radius: 3px;
                            background: #fef5e7;
                            font-size: 12px;
                        }
                        QPushButton:hover {
                            border-color: #e74c3c;
                            background: #fdebd0;
                        }
                    """)
                else:
                    widget.setStyleSheet("""
                        QPushButton {
                            border: 1px solid #ddd;
                            border-radius: 3px;
                            background: #fff;
                            font-size: 12px;
                        }
                        QPushButton:hover {
                            border-color: #3498db;
                            background: #eaf2f8;
                        }
                    """)
                break
            
    def _on_open_step_folder(self, output_path: str):
        """打开产物所在文件夹"""
        from core.utils import open_file_location
        p = Path(output_path)
        if p.exists():
            open_file_location(p)            


# ==================== 元信息 ====================
__author__ = "YQJ"
__version__ = "1.1.0"
__date__ = "2026.05.09"