#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
监视面板 - 主对话框
工作流可视化追踪界面，提供文件流水线行列表、总体进度、日志查看
"""

import os
import sys
import time
from pathlib import Path
from typing import List, Dict, Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QScrollArea, QWidget, QFrame, QGroupBox,
    QTextEdit, QMessageBox, QComboBox, QSplitter
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QColor

from core.utils import open_file_location
from modules.workflow.module import WORKFLOW_MODES

# ★ 导入常量化配置键及工作流专用常量
from core.config_keys import MDRepairKey
from .constants import StepKey, ModeKey
from .monitor_row import FilePipelineRow, StepStatus, StepType
from .monitor_worker import MonitorWorkflowWorker, MonitorWorkerSignals
from .monitor_row_config import RowRepairConfigDialog
from modules.workflow.pipeline_state import make_pipeline_key

# ==================== 状态映射 ====================

# ★ 步骤名到 StepType 的映射，键名使用常量
STEP_NAME_TO_TYPE = {
    StepKey.REPAIR: StepType.REPAIR,
    StepKey.MD2EPUB: StepType.MD2EPUB,
    StepKey.EPUB2PDF: StepType.EPUB2PDF,
    StepKey.EPUB2DOCX: StepType.EPUB2DOCX,
}

# ★ 模式对应的步骤列表，键名使用常量
MODE_STEPS = {
    ModeKey.REPAIR_TO_EPUB: [StepType.REPAIR, StepType.MD2EPUB],
    ModeKey.MD_TO_PDF: [StepType.MD2EPUB, StepType.EPUB2PDF],
    ModeKey.MD_TO_DOCX: [StepType.MD2EPUB, StepType.EPUB2DOCX],
    ModeKey.FULL_TO_PDF: [StepType.REPAIR, StepType.MD2EPUB, StepType.EPUB2PDF],
    ModeKey.FULL_TO_DOCX: [StepType.REPAIR, StepType.MD2EPUB, StepType.EPUB2DOCX],
}


# ==================== 主对话框 ====================

class MonitorPanelDialog(QDialog):
    """工作流监视面板 — 主对话框
    
    功能：
        - 展示每个文件的流水线状态（3 个步骤状态条）
        - 支持行独立修复配置（⚙️ 按钮）
        - 预览产物（👁️）、回滚步骤（🗑️）、重试失败步骤（🔄）
        - 总体进度条 + 预估剩余时间
        - 可折叠日志面板
        - 右键打开产物文件夹
        - 全部开始 / 全部暂停

    使用方式：
        dialog = MonitorPanelDialog(parent=None, workflow_module=workflow_module)
        dialog.exec()
    """

    def __init__(self, parent=None, workflow_module=None):
        """初始化监视面板
        
        Args:
            parent: 父级窗口
            workflow_module: WorkflowModule 实例（用于获取配置和文件列表）
        """
        
        super().__init__(parent)
        self._last_worker_id = None    # ★ 提前初始化
        self._synced_main_results = False  # ★ 防止重复同步 all_results
        self.workflow_module = workflow_module

        # ★ 支持键盘 Delete 删除选中的行
        self._selected_rows: set = set()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # 流水线状态
        self.row_widgets: Dict[Path, FilePipelineRow] = {}

        # Worker
        self.monitor_worker: Optional[MonitorWorkflowWorker] = None
        self._is_running = False
        self._start_time = 0.0

        # 统计
        self._total_steps = 0
        self._completed_steps = 0
        self._completed_files = 0

        # 日志缓存（用于刷新）
        
        self.setWindowTitle("监视面板 🔄 组合工作流")
        self.setMinimumSize(1100, 680)
        self.resize(1200, 780)
        self.setWindowFlags(
            self.windowFlags() |
            Qt.WindowType.WindowMaximizeButtonHint |
            Qt.WindowType.WindowMinimizeButtonHint
        )

        self._setup_ui()
        self._populate_rows()

        # 定时刷新日志（每 500ms）
        self._log_timer = QTimer(self)
        self._log_timer.timeout.connect(self._flush_logs)
        self._log_timer.start(500)

        from PyQt6.QtGui import QShortcut, QKeySequence
        close_shortcut = QShortcut(QKeySequence("Ctrl+W"), self)
        close_shortcut.activated.connect(self.reject)

        toggle_log_shortcut = QShortcut(QKeySequence("Ctrl+L"), self)
        toggle_log_shortcut.activated.connect(self._toggle_log_panel)

        self.setAcceptDrops(True)
        self._empty_label = None  # 空状态提示 label 引用

        # ★ 定时检查主界面 Worker 变化
        self._sync_timer = QTimer(self)
        self._sync_timer.timeout.connect(self._check_main_worker)
        self._sync_timer.start(250)  # ★ 从 1000ms 改为 250ms

    @property
    def pipeline_states(self) -> Dict:
        """统一流水线状态 → 从 workflow_module 读取"""
        if self.workflow_module:
            return self.workflow_module.pipeline_states
        return {}

    @property
    def row_configs(self) -> Dict:
        """独立配置 → 从 workflow_module 读取（兼容旧代码）"""
        if self.workflow_module:
            return self.workflow_module.panel_get_all_row_configs()
        return {}

    @property
    def _log_cache(self) -> List:
        """日志缓存 → 从 workflow_module 读取（兼容旧代码）"""
        if self.workflow_module:
            return self.workflow_module.panel_log_cache
        return []

    # ==================== UI 构建 ====================

    def _setup_ui(self):
        """构建整体 UI 布局 — 左侧流水线 + 右侧日志（可拖拽分割）"""
        main_layout = QHBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # ====== 使用 QSplitter 让左右可拖拽 ======
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)

        # ====== 左侧：流水线区域 ======
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setSpacing(8)
        left_layout.setContentsMargins(0, 0, 8, 0)

        left_layout.addWidget(self._create_toolbar())
        left_layout.addWidget(self._create_header())

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: #dee2e6;")
        left_layout.addWidget(line)

        self.pipeline_scroll = QScrollArea()
        self.pipeline_scroll.setWidgetResizable(True)
        self.pipeline_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.pipeline_scroll.setStyleSheet("QScrollArea { background: #ffffff; }")

        self.pipeline_container = QWidget()
        self.pipeline_layout = QVBoxLayout(self.pipeline_container)
        self.pipeline_layout.setSpacing(0)
        self.pipeline_layout.setContentsMargins(0, 0, 0, 0)
        self.pipeline_layout.addStretch()

        self.pipeline_scroll.setWidget(self.pipeline_container)
        left_layout.addWidget(self.pipeline_scroll, 1)

        left_layout.addWidget(self._create_overall_progress())

        self.main_splitter.addWidget(left_widget)

        # ====== 右侧：日志面板 ======
        self.log_panel_container = self._create_log_panel_sidebar()
        self.main_splitter.addWidget(self.log_panel_container)

        # 默认比例：左侧占 70%，右侧占 30%
        self.main_splitter.setSizes([700, 300])
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 0)

        main_layout.addWidget(self.main_splitter)

    def _create_toolbar(self) -> QWidget:
        """创建顶部工具栏"""
        toolbar = QWidget()
        toolbar.setFixedHeight(44)
        toolbar.setStyleSheet("""
            QWidget {
                background-color: #f8f9fa;
                border-bottom: 1px solid #dee2e6;
                border-radius: 4px;
            }
        """)

        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        # 模式显示
        mode_key = self._get_mode_key()
        # ★ 使用常量获取模式信息
        mode_info = WORKFLOW_MODES.get(mode_key, WORKFLOW_MODES[ModeKey.FULL_TO_PDF])
        self.mode_label = QLabel(f"模式: {mode_info['icon']} {mode_info['name']}")
        self.mode_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #2c3e50;")
        layout.addWidget(self.mode_label)

        layout.addStretch()

        # 全部开始
        self.start_all_btn = QPushButton("▶ 全部开始")
        self.start_all_btn.setStyleSheet("""
            QPushButton {
                padding: 6px 16px;
                background-color: #27ae60;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #219a52; }
            QPushButton:disabled { background-color: #bdc3c7; }
        """)
        self.start_all_btn.clicked.connect(self._on_start_all)
        layout.addWidget(self.start_all_btn)

        # 停止处理
        self.pause_all_btn = QPushButton("⏹ 停止")
        self.pause_all_btn.setEnabled(False)
        self.pause_all_btn.setStyleSheet("""
            QPushButton {
                padding: 6px 16px;
                background-color: #e67e22;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #d35400; }
            QPushButton:disabled { background-color: #bdc3c7; }
        """)
        self.pause_all_btn.clicked.connect(self._on_pause_all)
        layout.addWidget(self.pause_all_btn)

        # 全部回滚
        self.rollback_all_btn = QPushButton("🗑 全部回滚")
        self.rollback_all_btn.setStyleSheet("""
            QPushButton {
                padding: 6px 16px;
                background-color: #c0392b;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #a93226; }
            QPushButton:disabled { background-color: #bdc3c7; }
        """)
        self.rollback_all_btn.setToolTip("清除所有中间产物和结果文件，重置所有步骤状态")
        self.rollback_all_btn.clicked.connect(self._on_rollback_all)
        layout.addWidget(self.rollback_all_btn)

        # 清理中间文件
        self.clean_intermediate_btn = QPushButton("🧹 清理中间文件")
        self.clean_intermediate_btn.setStyleSheet("""
            QPushButton {
                padding: 6px 14px;
                background-color: #8e44ad;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #7d3c98; }
        """)
        self.clean_intermediate_btn.setToolTip(
            "删除所有中间产物（_fixed.md / .epub），只保留最终结果"
        )
        self.clean_intermediate_btn.clicked.connect(self._on_clean_intermediate)
        layout.addWidget(self.clean_intermediate_btn)

        # 返回主界面
        back_btn = QPushButton("◀ 返回主界面")
        back_btn.setStyleSheet("""
            QPushButton {
                padding: 5px 14px;
                border: 1px solid #ccc;
                border-radius: 4px;
                background: #fff;
                font-weight: bold;
            }
            QPushButton:hover { background: #e8e8e8; }
        """)
        back_btn.clicked.connect(self._on_back)
        layout.addWidget(back_btn)

        # ★ 显示日志按钮（放在返回主界面右边）
        self.show_log_btn = QPushButton("📋")
        self.show_log_btn.setFixedSize(30, 30)
        self.show_log_btn.setToolTip("显示日志面板 (Ctrl+L)")
        self.show_log_btn.setStyleSheet(
            "QPushButton { border: 1px solid #ccc; border-radius: 3px; background: #fff; font-size: 14px; }"
            "QPushButton:hover { background: #e8e8e8; }"
        )
        self.show_log_btn.clicked.connect(self._show_log_panel)
        self.show_log_btn.setVisible(False)
        layout.addWidget(self.show_log_btn)

        return toolbar

    def _create_header(self) -> QWidget:
        header = QWidget()
        header.setFixedHeight(28)
        header.setStyleSheet("background-color: #e9ecef; border-radius: 4px;")

        layout = QHBoxLayout(header)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        # ★ 序号列 — 宽度与行序号一致
        idx_label = QLabel("<b>序号</b>")
        idx_label.setFixedWidth(36)
        idx_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(idx_label)

        # ★ 文件列 — 固定宽度，左对齐
        file_label = QLabel("<b>文件</b>")
        file_label.setFixedWidth(200)
        file_label.setAlignment(Qt.AlignmentFlag.AlignCenter)  # ★ 改为居中
        layout.addWidget(file_label)

        # ★ ⚙️ 列 — 固定宽度
        config_label = QLabel("")
        config_label.setFixedWidth(22)
        layout.addWidget(config_label)

        spacer = QWidget()
        spacer.setFixedWidth(6)
        layout.addWidget(spacer)

        # 步骤标题
        mode_key = self._get_mode_key()
        # ★ 使用常量获取步骤列表
        steps = MODE_STEPS.get(mode_key, [StepType.REPAIR, StepType.MD2EPUB, StepType.EPUB2PDF])
        for step in steps:
            label = QLabel(f"<b>{step.display_name}</b>")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(label, 1)

        return header

    def _create_overall_progress(self) -> QWidget:
        """创建总体进度区域"""
        widget = QWidget()
        widget.setStyleSheet("background-color: #f8f9fa; border-radius: 4px; padding: 4px;")
        layout = QVBoxLayout(widget)
        layout.setSpacing(4)
        layout.setContentsMargins(10, 6, 10, 6)

        # 进度条
        self.overall_bar = QProgressBar()
        self.overall_bar.setMinimumHeight(20)
        self.overall_bar.setTextVisible(True)
        self.overall_bar.setFormat("准备就绪")
        self.overall_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #ccc;
                border-radius: 4px;
                background-color: #e9ecef;
                text-align: center;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #27ae60;
                border-radius: 3px;
            }
        """)
        layout.addWidget(self.overall_bar)

        # 统计文本
        self.stats_label = QLabel("等待开始...")
        self.stats_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stats_label.setStyleSheet("font-size: 12px; color: #555;")
        layout.addWidget(self.stats_label)

        self.scope_hint = QLabel(
            "📌 步骤状态在面板关闭后会被保留，下次打开时可恢复。\n"
            "   日志仅反映当前会话操作，建议及时保存重要日志。"
        )
        self.scope_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scope_hint.setStyleSheet(
            "font-size: 10px; color: #999; padding: 2px;  "
            "background: transparent;"
        )
        self.scope_hint.setWordWrap(True)
        layout.addWidget(self.scope_hint)

        return widget

    def _create_log_panel_sidebar(self) -> QWidget:
        """创建右侧日志面板（可折叠/固定，支持拉伸）"""
        container = QWidget()
        container.setObjectName("logSidebar")
        container.setStyleSheet("""
            QWidget#logSidebar {
                background-color: #f8f9fa;
                border-left: 1px solid #dee2e6;
            }
        """)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ---- 日志标题栏 ----
        log_header = QWidget()
        log_header.setFixedHeight(44)
        log_header.setStyleSheet("""
            background-color: #f8f9fa;
            border-bottom: 1px solid #dee2e6;
        """)
        header_layout = QHBoxLayout(log_header)
        header_layout.setContentsMargins(8, 0, 4, 0)

        log_title = QLabel("📋 详细日志")
        log_title.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        header_layout.addWidget(log_title)
        header_layout.addStretch()

        # 固定按钮
        self.log_pin_btn = QPushButton("📍")  # ★ 默认非固定图标
        self.log_pin_btn.setCheckable(True)
        self.log_pin_btn.setChecked(False)    # ★ 默认不固定，可隐藏
        self.log_pin_btn.setToolTip("取消固定（可隐藏）")
        self.log_pin_btn.setStyleSheet(
            "QPushButton { border: none; background: transparent; font-size: 14px; }"
            "QPushButton:hover { background: #e8e8e8; border-radius: 3px; }"
            "QPushButton:checked { background: #d4e6f1; border-radius: 3px; }"
        )
        self.log_pin_btn.clicked.connect(self._on_log_pin_toggled)
        header_layout.addWidget(self.log_pin_btn)

        # 保存日志按钮
        self.log_save_btn = QPushButton("💾")
        self.log_save_btn.setFixedSize(26, 26)
        self.log_save_btn.setToolTip("保存日志")
        self.log_save_btn.setStyleSheet(
            "QPushButton { border: none; background: transparent; font-size: 14px; }"
            "QPushButton:hover { background: #d5f5e3; border-radius: 3px; }"
        )
        self.log_save_btn.clicked.connect(self._on_save_log)
        header_layout.addWidget(self.log_save_btn)

        # 清空日志按钮
        self.log_clear_btn = QPushButton("🗑")
        self.log_clear_btn.setFixedSize(26, 26)
        self.log_clear_btn.setToolTip("清空日志")
        self.log_clear_btn.setStyleSheet(
            "QPushButton { border: none; background: transparent; font-size: 14px; }"
            "QPushButton:hover { background: #fadbd8; border-radius: 3px; }"
        )
        self.log_clear_btn.clicked.connect(self._on_clear_log)
        header_layout.addWidget(self.log_clear_btn)

        # 隐藏按钮
        self.log_hide_btn = QPushButton("✕")
        self.log_hide_btn.setFixedSize(26, 26)
        self.log_hide_btn.setToolTip("隐藏日志面板")
        self.log_hide_btn.setStyleSheet(
            "QPushButton { border: none; background: transparent; font-size: 14px; }"
            "QPushButton:hover { background: #fadbd8; border-radius: 3px; }"
        )
        self.log_hide_btn.clicked.connect(self._on_log_hide)
        header_layout.addWidget(self.log_hide_btn)

        layout.addWidget(log_header)

        # ---- 日志内容 ----
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: none;
                border-radius: 0;
                padding: 6px;
            }
        """)
        layout.addWidget(self.log_text, 1)

        # ---- 日志底部状态 ----
        self.log_status_label = QLabel("")
        self.log_status_label.setFixedHeight(22)
        self.log_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.log_status_label.setStyleSheet(
            "font-size: 9px; color: #888; background-color: #f0f0f0; border-top: 1px solid #e0e0e0;"
        )
        layout.addWidget(self.log_status_label)

        return container

    # ==================== 行填充 ====================

    def _populate_rows(self):
        """从工作流模块的文件列表填充行"""
        if not self.workflow_module:
            return

        file_list = self.workflow_module.file_list
        files = file_list.get_all_files()

        if not files:
            self._empty_label = QLabel(
                "📭 请先在主界面添加 Markdown 文件\n\n"
                "或直接拖放 .md 文件到此处"
            )
            self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._empty_label.setStyleSheet(
                "color: #999; padding: 40px; font-size: 14px;"
            )
            insert_idx = self.pipeline_layout.count() - 1
            self.pipeline_layout.insertWidget(insert_idx, self._empty_label)
            return

        mode_key = self._get_mode_key()
        # ★ 使用常量获取步骤列表
        steps = MODE_STEPS.get(mode_key, [StepType.REPAIR, StepType.MD2EPUB, StepType.EPUB2PDF])

        self._total_steps = len(files) * len(steps)

        # ★ 改用文件名作为 key，避免 Path 对象比较问题
        self.row_widgets.clear()

        for i, file_path in enumerate(files, 1):
            row = FilePipelineRow(file_path, steps, row_index=i)
            row.row_clicked.connect(self._on_row_clicked)
            row.config_requested.connect(self._on_row_config)
            row.preview_requested.connect(self._on_preview_step)
            row.repair_preview_requested.connect(self._on_preview_repair)
            row.rollback_requested.connect(self._on_rollback_step)
            row.retry_requested.connect(self._on_retry_step)
            row.remove_requested.connect(self._on_remove_file)

            insert_idx = self.pipeline_layout.count() - 1
            self.pipeline_layout.insertWidget(insert_idx, row)

            unique_key = make_pipeline_key(file_path)
            self.row_widgets[unique_key] = row

            if self.workflow_module:
                if unique_key not in self.workflow_module.pipeline_states:
                    self.workflow_module.pipeline_states[unique_key] = {
                        'file': file_path,
                        'steps': {},
                    }

        self._update_overall_progress(0, self._total_steps, 0, 0)

        # ★ 从统一流水线状态恢复 UI
        self._restore_ui_from_pipeline()

        self._connect_to_main_worker()

    def _connect_to_main_worker(self):
        """面板打开时立即检查一次主界面 Worker 状态"""
        self._check_main_worker()

    def _on_main_worker_finished(self, results: list, is_final: bool = True):
        """主界面 Worker 完成/中间结果同步
        
        Args:
            results: 结果列表 [{'file': ..., 'outputs': {step: path}}]
            is_final: True=任务完成（改UI状态），False=中间同步（不改UI状态）
        """
        if is_final:
            self._is_running = False
            self.start_all_btn.setEnabled(True)
            self.start_all_btn.setText("▶ 全部开始")
        # 否则保持 UI 状态不变

        for r in results:
            file_path_str = r.get('file', '')
            file_path = Path(file_path_str)
            unique_key = make_pipeline_key(file_path)
            outputs = r.get('outputs', {})
            state = self.pipeline_states.get(unique_key)
            row = self.row_widgets.get(unique_key)
            if not state or not row:
                continue

            for step_name, output_path in outputs.items():
                step_type = STEP_NAME_TO_TYPE.get(step_name)
                if not step_type:
                    continue
                
                file_exists = output_path and Path(output_path).exists()
                status = StepStatus.COMPLETED if file_exists else StepStatus.COMPLETED_CLEANED
                
                state['steps'][step_type] = {
                    'status': 'completed',
                    'output_path': output_path,
                    'elapsed': 0,
                    'cleaned': not file_exists,
                }
                row.update_step(step_type, status, output_path=output_path)

        if is_final:
            self._append_log("📡 主界面工作流已完成，状态已同步", "INFO")

    def _on_row_clicked(self, row, ctrl_pressed: bool):
        if not row:
            return
        
        # ★ 检查 row 是否已被删除
        try:
            _ = row.isVisible()
        except RuntimeError:
            self._selected_rows.discard(row)
            return
        
        if ctrl_pressed:
            if row in self._selected_rows:
                row._set_selected(False)
                self._selected_rows.discard(row)
            else:
                row._set_selected(True)
                self._selected_rows.add(row)
        else:
            for r in list(self._selected_rows):
                r._set_selected(False)
            self._selected_rows.clear()
            row._set_selected(True)
            self._selected_rows.add(row)

    def _get_mode_key(self) -> str:
        """获取当前选中的工作流模式"""
        if self.workflow_module:
            return self.workflow_module._get_selected_mode()
        # ★ 返回常量
        return ModeKey.FULL_TO_PDF

    def _restore_ui_from_pipeline(self):
        """从 pipeline_states 恢复行状态和底部进度"""
        if not self.workflow_module:
            return
        
        # 恢复行状态
        for unique_key, row in self.row_widgets.items():
            state = self.pipeline_states.get(unique_key)
            if not state:
                continue
            steps = state.get('steps', {})
            for step_type_key, step_state in steps.items():
                if isinstance(step_type_key, StepType):
                    step_type = step_type_key
                else:
                    step_type = STEP_NAME_TO_TYPE.get(step_type_key)
                if not step_type:
                    continue
                
                status_str = step_state.get('status', '')
                if status_str == 'completed':
                    output_path = step_state.get('output_path', '')
                    file_exists = output_path and Path(output_path).exists()
                    status = StepStatus.COMPLETED if file_exists else StepStatus.COMPLETED_CLEANED
                    row.update_step(step_type, status, output_path=output_path,
                                 elapsed=step_state.get('elapsed', 0))
                elif status_str == 'failed':
                    row.update_step(step_type, StepStatus.FAILED,
                                 error=step_state.get('error_message', ''))
        
        # 恢复进度统计
        completed_steps = 0
        completed_files = 0
        mode_key = self._get_mode_key()
        required_steps = MODE_STEPS.get(mode_key, [])
        total_steps = len(self.row_widgets) * len(required_steps)

        if required_steps:
            for unique_key, row in self.row_widgets.items():
                state = self.pipeline_states.get(unique_key)  # ✅ 直接用 key
                if not state:
                    continue
                file_all_done = True
                for step_type in required_steps:
                    steps_dict = state.get('steps', {})
                    step_state = steps_dict.get(step_type) or steps_dict.get(step_type.value, {})
                    if step_state.get('status') == 'completed' and not step_state.get('cleaned', False):
                        completed_steps += 1
                    else:
                        file_all_done = False
                if file_all_done:
                    completed_files += 1

        self._completed_steps = completed_steps
        self._completed_files = completed_files
        self._total_steps = total_steps
        self._update_overall_progress(completed_steps, total_steps, completed_files, 0)

    def _bring_main_to_front(self):
        """强制将工作流模块主界面置于最前"""
        from PyQt6.QtWidgets import QApplication
        for widget in QApplication.topLevelWidgets():
            from PyQt6.QtWidgets import QMainWindow
            if isinstance(widget, QMainWindow):
                if widget.isMinimized():
                    widget.showNormal()
                widget.setWindowState(
                    widget.windowState()  & ~Qt.WindowState.WindowMinimized
                )
                widget.show()
                widget.activateWindow()
                widget.raise_()
                break

    # ==================== 工具栏事件 ====================

    def _on_back(self):
        """返回主界面"""
        # ★ 只停止监视面板自己启动的 Worker，不影响主界面正在运行的任务
        if self.monitor_worker and self.monitor_worker.isRunning():
            reply = QMessageBox.question(
                self, "确认返回",
                "监视面板有正在执行的任务，返回将停止该任务。\n"
                "（主界面的任务不受影响）\n确定要返回吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            self._stop_worker()
        self._synced_main_results = False
        self._log_timer.stop()
        self._bring_main_to_front()
        self.accept()
        if self.workflow_module:
            self.workflow_module.log("📊 监视面板已关闭", "INFO")

    def _on_start_all(self):
        """开始/继续所有处理 — 跳过已全部完成的文件"""
        if self._is_running:
            return

        # ★ 收集未完成的文件（跳过所有步骤均已完成的文件）
        file_paths = []
        skipped = 0
        mode_key = self._get_mode_key()
        required_steps = MODE_STEPS.get(mode_key, [])
        
        for unique_key, state in self.pipeline_states.items():
            f = state.get('file')
            if f is None:
                continue
            
            # 检查是否所有步骤都已完成且产物仍存在
            all_still_there = True
            for step_type in required_steps:
                step_state = state.get('steps', {}).get(step_type, {})
                if step_state.get('status') != 'completed' or step_state.get('cleaned', False):
                    all_still_there = False
                    break

            if all_still_there and required_steps:
                skipped += 1
                continue
            
            if isinstance(f, Path):
                file_paths.append(f)
            else:
                file_paths.append(Path(f))

        if skipped > 0:
            self._append_log(f"⏭️ 跳过 {skipped} 个已完成的文件", "INFO")

        if not file_paths:
            QMessageBox.information(self, "提示", "所有文件都已完成，无需处理")
            return

        self._start_workflow(file_paths)

    def _on_pause_all(self):
        """停止处理"""
        if not self._is_running:
            return

        self._stop_worker()
        self.start_all_btn.setText("▶ 全部开始")
        self.pause_all_btn.setEnabled(False)
        self._append_log("⏹ 已停止处理", "WARNING")

    # ==================== 行事件处理 ====================

    def _on_row_config(self, file_path: Path):
        global_config = self._get_global_repair_config()
        existing_row_config = self.workflow_module.panel_get_row_config(file_path) if self.workflow_module else {}

        dialog = RowRepairConfigDialog(
            file_path, global_config, self,
            existing_row_config=existing_row_config
        )

        if dialog.exec() == QDialog.DialogCode.Accepted:
            config = dialog.get_config()
            key = make_pipeline_key(file_path)  # ✅ 使用统一 key
            if self.workflow_module:
                self.workflow_module.panel_set_row_config(file_path, config)
                if config:
                    self._append_log(f"⚙️ {file_path.name}: 已设置独立修复配置", "INFO")
                else:
                    self._append_log(f"🔄 {file_path.name}: 已恢复为全局配置", "INFO")

            row = self.row_widgets.get(key)
            if row:
                has_config = self.workflow_module.panel_has_row_config(file_path) if self.workflow_module else False
                row.set_config_indicator(has_config)

    def _on_preview_step(self, file_path: Path, step_type: StepType):
        key = make_pipeline_key(file_path)  # ✅ 使用统一 key
        
        # ★ 如果是修复步骤 → 智能路由
        if step_type == StepType.REPAIR:
            state = self.pipeline_states.get(key, {})
            steps = state.get('steps', {})
            step_state = steps.get(StepType.REPAIR) or steps.get('repair', {})

            output_path = step_state.get('output_path', '')
            
            # 产物存在 → 用系统默认应用打开 _fixed.md
            if output_path:
                p = Path(output_path)
                if p.exists():
                    if sys.platform == 'win32':
                        os.startfile(str(p))
                    elif sys.platform == 'darwin':
                        import subprocess
                        subprocess.run(['open', str(p)])
                    else:
                        import subprocess
                        subprocess.run(['xdg-open', str(p)])
                    return
            
            # 产物不存在 → 进入修复预览（配置调试模式）
            self._on_preview_repair(file_path)
            return
        
        state = self.pipeline_states.get(key, {})
        steps = state.get('steps', {})
        step_state = steps.get(step_type) or steps.get(step_type.value, {})

        if not step_state or not step_state.get('output_path'):
            QMessageBox.warning(self, "提示", "该步骤没有可预览的产物")
            return

        output = Path(step_state['output_path'])
        
        if not output.exists():
            QMessageBox.information(
                self, "产物已清理",
                f"该步骤产物已被工作流自动清理：\n{output}\n\n"
                f"如需保留中间文件，请在主界面勾选「保留中间文件」选项。"
            )
            return

        if step_type == StepType.MD2EPUB:
            self._preview_epub(output)
        elif step_type == StepType.EPUB2PDF:
            self._preview_pdf(output)
        # ★ 处理 Word 步骤预览
        elif step_type == StepType.EPUB2DOCX:
            self._preview_docx(output)

    def _on_rollback_step(self, file_path: Path, step_type: StepType):
        """回滚某步骤：仅删除该步骤产物，只重置该步骤状态"""
        key = make_pipeline_key(file_path)
        state = self.pipeline_states.get(key, {})
        step_state = state.get('steps', {}).get(step_type)

        if not step_state:
            return

        step_name = step_type.display_name
        output_path = step_state.get('output_path', '')
        
        if not output_path:
            QMessageBox.warning(self, "提示", "该步骤没有可回滚的产物")
            return

        reply = QMessageBox.question(
            self, "确认回滚",
            f"将删除 {file_path.name} 的「{step_name}」产物:\n{output_path}\n\n"
            f"注意：只删除该步骤产物，不影响下游文件。\n此操作不可撤销。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # 删除产物
        p = Path(output_path)
        if p.exists():
            p.unlink()
            self._append_log(f"🗑️ 已删除: {output_path}", "INFO")

        # ★ 只重置当前步骤，不触动下游
        state['steps'][step_type] = {}
        row = self.row_widgets.get(key)
        if row:
            row.update_step(step_type, StepStatus.WAITING)

        self._append_log(
            f"🗑️ {file_path.name}: 已回滚「{step_name}」（下游未受影响）", "INFO")

    def _on_retry_step(self, file_path: Path, step_type: StepType):
        """重试失败的步骤"""
        key = make_pipeline_key(file_path)
        state = self.pipeline_states.get(key, {})
        step_state = state.get('steps', {}).get(step_type)
        if not step_state or step_state.get('status') != 'failed':
            return

        row = self.row_widgets.get(key)  # ★ 用文件名匹配
        if row:
            row.update_step(step_type, StepStatus.WAITING)

        if step_type in state.get('steps', {}):
            state['steps'][step_type] = {}

        self._append_log(
            f"🔄 {file_path.name}: 准备重试「{step_type.display_name}」", "INFO")

        QMessageBox.information(
            self, "提示",
            f"已重置 {file_path.name} 的「{step_type.display_name}」步骤。\n"
            f"请点击「全部开始」重新处理。"
        )

    # ==================== 工作流控制 ====================

    def _start_workflow(self, files: List[Path]):
        """启动工作流"""
        if not self.workflow_module:
            return

        if not files:
            QMessageBox.warning(self, "提示", "没有可处理的文件")
            return

        # ★ 检查是否有部分步骤已完成的文件
        has_partial = False
        partial_count = 0
        for f in files:
            unique_key = make_pipeline_key(f)
            state = self.pipeline_states.get(unique_key, {})
            steps_state = state.get('steps', {})
            # 检查是否至少有一个步骤已完成
            if any(s.get('status') == 'completed' for s in steps_state.values()):
                partial_count += 1
                has_partial = True

        if has_partial:
            reply = QMessageBox.warning(
                self, "部分文件已存在产物",
                f"本轮将处理 {len(files)} 个文件，其中 {partial_count} 个已有部分产物。\n\n"
                f"继续处理将覆盖已有产物，可能产生重复文件。\n"
                f"如不希望覆盖，请先通过「回滚」清除产物后再开始。\n\n"
                f"是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                self._is_running = False
                self.start_all_btn.setEnabled(True)
                self.start_all_btn.setText("▶ 全部开始")
                self.pause_all_btn.setEnabled(False)
                return

        # ★ 只重置本轮要处理的文件，保留已完成文件的状态
        for f in files:
            unique_key = make_pipeline_key(f)
            state = self.pipeline_states.get(unique_key)
            if state:
                state['steps'] = {}  # 清空该文件的所有步骤状态
            row = self.row_widgets.get(unique_key)
            if row:
                row.set_all_waiting()

        self._is_running = True
        self._start_time = time.time()
        self._completed_steps = 0
        self._completed_files = 0

        self.start_all_btn.setEnabled(False)
        self.start_all_btn.setText("🔄 处理中...")
        self.pause_all_btn.setEnabled(True)

        # 获取配置
        mode_key = self._get_mode_key()
        repair_config = self._get_global_repair_config()
        epub_css = self.workflow_module._get_epub_css()
        pdf_margins = self.workflow_module._get_pdf_margins()

        # ★ 使用常量构建 step_workers
        step_workers = {
            StepKey.REPAIR: self.workflow_module.step_spins[StepKey.REPAIR].value(),
            StepKey.MD2EPUB: self.workflow_module.step_spins[StepKey.MD2EPUB].value(),
            StepKey.EPUB2PDF: self.workflow_module.step_spins[StepKey.EPUB2PDF].value(),
            StepKey.EPUB2DOCX: self.workflow_module.step_spins[StepKey.EPUB2DOCX].value(),
        }

        # ★ 收集 Word 参数
        docx_page_size = "a4"
        if hasattr(self.workflow_module, 'docx_page_size_group'):
            docx_btn = self.workflow_module.docx_page_size_group.checkedButton()
            if docx_btn:
                docx_page_size = docx_btn.property("size_key")
        
        docx_fix_soft_breaks = self.workflow_module.docx_fix_soft_breaks_cb.isChecked()

        self.monitor_worker = MonitorWorkflowWorker(
            files=files,
            workflow_mode=mode_key,
            output_dir=self.workflow_module.output_dir,
            global_repair_config=repair_config,
            epub_css=epub_css,
            pdf_margins=pdf_margins,
            keep_intermediate=self.workflow_module.keep_intermediate_cb.isChecked(),
            auto_open=self.workflow_module.auto_open_cb.isChecked(),
            rename_by_title=self.workflow_module.rename_by_title_cb.isChecked(),
            use_yaml_title=self.workflow_module.use_yaml_title_cb.isChecked(),
            step_workers=step_workers,
            row_configs=self.workflow_module.panel_get_all_row_configs() if self.workflow_module else {},
            docx_page_size=docx_page_size,
            docx_fix_soft_breaks=docx_fix_soft_breaks,
        )

        # 连接信号
        self.monitor_worker.signals.step_state_changed.connect(self._on_step_state_changed)
        self.monitor_worker.signals.overall_progress.connect(self._on_overall_progress)
        self.monitor_worker.signals.log_message.connect(self._on_worker_log)
        self.monitor_worker.signals.all_done.connect(self._on_all_done)

        self.monitor_worker.start()

    def _stop_worker(self):
        """停止当前 Worker"""
        if self.monitor_worker and self.monitor_worker.isRunning():
            self.monitor_worker.stop()
            self.monitor_worker.wait(3000)
        self._is_running = False

    def _reset_all_states(self):
        """重置所有行的状态"""
        for key, row in self.row_widgets.items():
            row.set_all_waiting()
            # ★ 确保 file 字段是 Path 对象
            file_path = self.pipeline_states.get(key, {}).get('file', key)
            if isinstance(file_path, str):
                file_path = Path(file_path)
            self.pipeline_states[key] = {
                'file': file_path,
                'steps': {},
            }

        self._completed_steps = 0
        self._completed_files = 0
        self._update_overall_progress(0, self._total_steps, 0, 0)

    # ==================== Worker 信号回调 ====================

    def _on_step_state_changed(self, file_path: Path, step_name: str, state: dict):
        """步骤状态更新回调（标准化版本 + 调试日志）"""
        key = make_pipeline_key(file_path)
        row = self.row_widgets.get(key)

        if not row:
            return

        step_type = STEP_NAME_TO_TYPE.get(step_name)
        if not step_type:
            return

        status_str = state.get('status', '')
        status_map = {
            'processing': StepStatus.PROCESSING,
            'completed': StepStatus.COMPLETED,
            'completed_cleaned': StepStatus.COMPLETED_CLEANED,
            'failed': StepStatus.FAILED,
            'skipped': StepStatus.SKIPPED,
        }
        step_status = status_map.get(status_str, StepStatus.WAITING)

        progress = state.get('progress', 0)
        output_path = state.get('output_path', '')
        error = state.get('error_message', '')
        elapsed = state.get('elapsed', 0)

        row.update_step(step_type, step_status, progress, output_path, error, elapsed)

        if key not in self.pipeline_states:
            self.pipeline_states[key] = {'file': file_path, 'steps': {}}
        self.pipeline_states[key]['steps'][step_type] = state

        # ★ 每次步骤状态变化时刷新底部进度
        self._restore_ui_from_pipeline()

    def _on_overall_progress(self, completed_steps: int, total_steps: int,
                             completed_files: int, remaining_seconds: float):
        """总体进度更新回调"""
        self._completed_steps = completed_steps
        self._completed_files = completed_files
        self._update_overall_progress(completed_steps, total_steps,
                                        completed_files, remaining_seconds)

    def _on_worker_log(self, message: str, level: str):
        """Worker 日志回调"""
        self._append_log(f"[Worker] {message}", level)

    def _on_all_done(self, results: list):
        """工作流完成回调"""
        self._is_running = False

        self.start_all_btn.setEnabled(True)
        self.start_all_btn.setText("▶ 全部开始")
        self.pause_all_btn.setEnabled(False)

        success_count = sum(1 for r in results if r['status'] == 'success')
        failed_count = len(results) - success_count

        self._append_log("=" * 50)
        self._append_log(
            f"✅ 工作流完成！成功: {success_count}, 失败: {failed_count}",
            "SUCCESS" if failed_count == 0 else "WARNING")
        self._append_log("=" * 50)

        QMessageBox.information(
            self, "完成",
            f"工作流处理完成！\n\n✅ 成功: {success_count} 个\n❌ 失败: {failed_count} 个"
        )

        if self.workflow_module and hasattr(self.workflow_module, 'all_results'):
            for r in results:
                if r not in self.workflow_module.all_results:
                    self.workflow_module.all_results.append(r)

        # 同步结果到主模块
        if self.workflow_module:
            self.workflow_module.log(
                f"📊 监视面板工作流完成: 成功 {success_count}, 失败 {failed_count}",
                "SUCCESS")

    # ==================== 进度更新 ====================

    def _update_overall_progress(self, completed: int, total: int,
                                  files_done: int, remaining: float):
        """更新总体进度条显示"""
        if total > 0:
            percent = int(completed / total * 100)
            self.overall_bar.setValue(percent)
        else:
            percent = 0
            self.overall_bar.setValue(0)

        # 格式文本
        elapsed = time.time() - self._start_time if self._start_time > 0 else 0
        elapsed_str = f"{int(elapsed // 60)}分{int(elapsed % 60)}秒" if elapsed > 60 else f"{elapsed:.0f}秒"

        if remaining > 0:
            remain_str = f"{int(remaining // 60)}分{int(remaining % 60)}秒" if remaining > 60 else f"{remaining:.0f}秒"
            self.overall_bar.setFormat(f"{completed}/{total} 步骤完成 | 已耗时 {elapsed_str} | 预估剩余 {remain_str}")
        else:
            self.overall_bar.setFormat(f"{completed}/{total} 步骤完成 | 已耗时 {elapsed_str}")

        # 统计文本
        total_files = len(self.row_widgets)
        failed = total_files - files_done - (completed // max(1, len(MODE_STEPS.get(self._get_mode_key(), []))))
        self.stats_label.setText(
            f"✅ {files_done}/{total_files} 文件完成  |   "
            f"📊 {completed}/{total} 步骤完成  |   "
            f"⏱ 已耗时 {elapsed_str}"
        )

    # ==================== 日志 ====================

    def _append_log(self, message: str, level: str = "INFO"):
        if not message.startswith("[Worker]") and not message.startswith("[面板]"):
            message = f"[面板] {message}"
        if self.workflow_module:
            self.workflow_module.panel_append_log(message, level)

    def _flush_logs(self):
        """刷新日志到显示区域（从统一缓存读取）"""
        if not self.workflow_module:
            return
        
        log_cache = self.workflow_module.panel_log_cache
        if not log_cache:
            return

        total_count = len(log_cache)

        colors = {
            "INFO": "#d4d4d4",
            "SUCCESS": "#27ae60",
            "WARNING": "#f39c12",
            "ERROR": "#e74c3c",
        }

        html_parts = []
        for timestamp, msg, level in log_cache[-20:]:
            color = colors.get(level, "#d4d4d4")
            html_parts.append(
                f'<span style="color:#888;">[{timestamp}]</span> '
                f'<span style="color:{color};">{msg}</span>'
            )

        self.log_text.setHtml("<br>".join(html_parts))
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

        self.log_status_label.setText(f"共 {total_count} 条日志")

    # ==================== 预览方法 ====================

    def _preview_md(self, file_path: Path):
        """预览 MD 产物 — 用系统默认编辑器打开"""
        if not file_path.exists():
            QMessageBox.warning(self, "提示", "文件不存在")
            return
        if sys.platform == 'win32':
            os.startfile(str(file_path))
        elif sys.platform == 'darwin':
            import subprocess
            subprocess.run(['open', str(file_path)])
        else:
            import subprocess
            subprocess.run(['xdg-open', str(file_path)])

    def _preview_epub(self, file_path: Path):
        """预览 EPUB（用系统默认阅读器打开）"""
        if not file_path.exists():
            QMessageBox.warning(self, "提示", "EPUB 文件不存在")
            return

        if sys.platform == 'win32':
            os.startfile(str(file_path))
        elif sys.platform == 'darwin':
            import subprocess
            subprocess.run(['open', str(file_path)])
        else:
            import subprocess
            subprocess.run(['xdg-open', str(file_path)])

    def _preview_pdf(self, file_path: Path):
        """预览 PDF（用系统默认阅读器打开）"""
        if not file_path.exists():
            QMessageBox.warning(self, "提示", "PDF 文件不存在")
            return

        if sys.platform == 'win32':
            os.startfile(str(file_path))
        elif sys.platform == 'darwin':
            import subprocess
            subprocess.run(['open', str(file_path)])
        else:
            import subprocess
            subprocess.run(['xdg-open', str(file_path)])
    
    def _preview_docx(self, file_path: Path):
        """预览 Word（用系统默认编辑器打开）"""
        if not file_path.exists():
            QMessageBox.warning(self, "提示", "Word 文件不存在")
            return
        if sys.platform == 'win32':
            os.startfile(str(file_path))
        elif sys.platform == 'darwin':
            import subprocess
            subprocess.run(['open', str(file_path)])
        else:
            import subprocess
            subprocess.run(['xdg-open', str(file_path)])

    # ==================== 修复预览（独立配置调试） ====================

    def _on_preview_repair(self, file_path: Path):
        """监视面板行 → 修复预览（使用该行的独立配置 + 全局配置合并）
        
        使用 ApplicationModal 避免嵌套模态死锁，parent 设为 None 保持独立。
        """
        global_config = self._get_global_repair_config()
        row_config = self.workflow_module.panel_get_row_config(file_path) if self.workflow_module else {}
        effective_config = self._merge_repair_configs(global_config, row_config)
        
        try:
            text = file_path.read_text(encoding='utf-8')
        except Exception as e:
            QMessageBox.warning(self, "错误", f"无法读取文件:\n{e}")
            return
        
        from modules.md_repair.processor import FormulaPreviewer
        previewer = FormulaPreviewer(effective_config)
        try:
            changes = previewer.preview(text, file_path)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"预检失败:\n{e}")
            return
        
        from modules.md_repair.dialogs import SideBySidePreviewDialog
        
        # ★ 关键修复：parent=None + ApplicationModal，避免嵌套模态死锁
        dialog = SideBySidePreviewDialog(
            changes, None,
            file_name=str(file_path)
        )
        dialog.set_config(effective_config)
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.set_standalone_config_mode(True)  # ★ 设为独立配置模式

        if not changes:
            dialog.quick_group.setChecked(True)
        
        dialog.exec()

        # 配置回写（用户关闭修复预览时执行）
        if dialog._config_apply_pending and dialog._config_to_apply:
            sparse = self._diff_repair_config(global_config, dialog._config_to_apply)
            key = make_pipeline_key(file_path)  # ✅

            if self.workflow_module:                # ✅ 正确缩进
                self.workflow_module.panel_set_row_config(file_path, sparse)
                
                row = self.row_widgets.get(key)  # ✅
                if row:
                    row.set_config_indicator(
                        self.workflow_module.panel_has_row_config(file_path) if self.workflow_module else False
                    )
                
                self._append_log(f"⚙️ {file_path.name}: 已更新独立修复配置", "INFO")

    def _merge_repair_configs(self, global_config: Dict, row_config: Dict) -> Dict:
        """合并全局配置和行独立配置（行配置覆盖全局）
        
        Args:
            global_config: 全局修复配置（来自 QSettings）
            row_config: 行独立配置（稀疏存储，仅含覆盖项）
            
        Returns:
            Dict: 合并后的完整有效配置
        """
        import copy
        merged = copy.deepcopy(global_config)
        if not row_config:
            return merged
        
        # 顶层配置覆盖
        for key in MDRepairKey.TOP_LEVEL_KEYS:
            if key in row_config:
                merged[key] = row_config[key]
        
        # ★ formula_config 嵌套覆盖（使用常量）
        if MDRepairKey.FORMULA_CONFIG in row_config:
            if MDRepairKey.FORMULA_CONFIG not in merged:
                merged[MDRepairKey.FORMULA_CONFIG] = {}
            merged[MDRepairKey.FORMULA_CONFIG].update(row_config[MDRepairKey.FORMULA_CONFIG])
        
        return merged

    def _diff_repair_config(self, global_config: Dict, new_config: Dict) -> Dict:
        """对比新旧配置，只保留与全局不同的项（稀疏存储）
        
        Args:
            global_config: 全局配置
            new_config: 用户调整后的新配置
            
        Returns:
            Dict: 仅包含与全局不同项的稀疏字典
        """
        sparse = {}
        fc_global = global_config.get(MDRepairKey.FORMULA_CONFIG, {})
        fc_new = new_config.get(MDRepairKey.FORMULA_CONFIG, {})
        
        # 对比顶层配置
        for key in MDRepairKey.TOP_LEVEL_KEYS:
            if key in new_config and new_config[key] != global_config.get(key):
                sparse[key] = new_config[key]
        
        # 对比公式级配置
        sparse_fc = {}
        for key in MDRepairKey.FORMULA_CONFIG_KEYS:
            if key in fc_new and fc_new[key] != fc_global.get(key):
                sparse_fc[key] = fc_new[key]
        
        if sparse_fc:
            sparse[MDRepairKey.FORMULA_CONFIG] = sparse_fc
        
        return sparse

    # ==================== 辅助方法 ====================

    def _get_global_repair_config(self) -> Dict:
        """获取全局修复配置"""
        if self.workflow_module:
            return self.workflow_module._get_repair_config()
        from modules.md_repair.processor import DEFAULT_REPAIR_CONFIG
        import copy
        return copy.deepcopy(DEFAULT_REPAIR_CONFIG)

    def dragEnterEvent(self, event):
        """拖入时检查是否有 .md 文件"""
        if event.mimeData().hasUrls():
            # 检查是否至少有一个 .md 文件或文件夹
            from pathlib import Path
            for url in event.mimeData().urls():
                path = Path(url.toLocalFile())
                if path.suffix.lower() == '.md' or path.is_dir():
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):
        """拖放文件到监视面板 → 同步到主模块文件列表 → 刷新行"""
        if not self.workflow_module:
            return

        from pathlib import Path
        accepted = []
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if not path.exists():
                continue
            if path.is_file() and path.suffix.lower() == '.md':
                accepted.append(path)
            elif path.is_dir():
                for md_file in path.rglob("*.md"):
                    accepted.append(md_file)
                for md_file in path.rglob("*.MD"):
                    accepted.append(md_file)

        if not accepted:
            event.ignore()
            return

        # 去重
        seen = set()
        unique = []
        for f in accepted:
            fa = str(f.absolute())
            if fa not in seen:
                seen.add(fa)
                unique.append(f)

        # 同步到主模块
        added = self.workflow_module.file_list.add_files(unique)
        if added > 0:
            self._append_log(f"📁 拖入 {added} 个文件", "INFO")
            self._refresh_rows()
        event.acceptProposedAction()

    def _refresh_rows(self):
        """清空并重建所有行"""
        self._selected_rows.clear()  # ★ 清空选中状态，避免引用已删除的 widget
        if self._empty_label:
            self.pipeline_layout.removeWidget(self._empty_label)
            self._empty_label.deleteLater()
            self._empty_label = None

        # 移除所有行 widget（保留底部弹簧）
        while self.pipeline_layout.count() > 1:
            item = self.pipeline_layout.takeAt(0)
            if item.widget():
                widget = item.widget()
                # ★ 只对 FilePipelineRow 实例断开信号
                if isinstance(widget, FilePipelineRow):
                    try:
                        widget.config_requested.disconnect()
                        widget.preview_requested.disconnect()
                        widget.repair_preview_requested.disconnect()  # ★ 新增
                        widget.rollback_requested.disconnect()
                        widget.retry_requested.disconnect()
                        widget.remove_requested.disconnect()      # ★ 新增
                        widget.row_clicked.disconnect()            # ★ 新增

                    except TypeError:
                        pass  # 信号可能未连接
                widget.deleteLater()

        # 重新填充
        self._populate_rows()

    # ==================== 窗口事件 ====================

    def closeEvent(self, event):
        # ★ 只有面板自己启动了 Worker 时才需要确认
        if self.monitor_worker and self.monitor_worker.isRunning():
            reply = QMessageBox.question(
                self, "确认关闭",
                "监视面板有正在执行的任务，关闭将停止该任务。\n"
                "确定要关闭吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._stop_worker()
        # 主界面 Worker 正在运行 → 直接关闭，不弹窗
        self._synced_main_results = False
        self._log_timer.stop()
        self._bring_main_to_front()
        super().closeEvent(event)

    def reject(self):
        """Esc 关闭"""
        # ★ 只有面板自己启动了 Worker 时才需要确认
        if self.monitor_worker and self.monitor_worker.isRunning():
            reply = QMessageBox.question(
                self, "确认关闭",
                "监视面板有正在执行的任务，关闭将停止该任务。\n"
                "（主界面的任务不受影响）\n确定要关闭吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            self._stop_worker()
        # 主界面 Worker 正在运行 → 直接关闭，不弹窗
        self._synced_main_results = False
        self._log_timer.stop()
        self._bring_main_to_front()
        super().reject()

    def _on_log_pin_toggled(self, checked: bool):
        """日志固定按钮切换"""
        self.log_pin_btn.setText("📌" if checked else "📍")
        self.log_pin_btn.setToolTip("固定日志面板" if checked else "取消固定（可隐藏）")

    def _on_log_hide(self):
        if self.log_pin_btn.isChecked():
            return
        self.log_panel_container.setVisible(False)
        self.show_log_btn.setVisible(True)

    def _show_log_panel(self):
        """显示日志面板"""
        self.log_panel_container.setVisible(True)
        self.show_log_btn.setVisible(False)

    def _toggle_log_panel(self):
        if self.log_panel_container.isVisible():
            if self.log_pin_btn.isChecked():
                return
            self.log_panel_container.setVisible(False)
            self.show_log_btn.setVisible(True)
        else:
            self.log_panel_container.setVisible(True)
            self.show_log_btn.setVisible(False)

    def keyPressEvent(self, event):
        """捕获 Delete 键删除选中的行 / Ctrl+V 粘贴"""
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if self._selected_rows:
                self._delete_selected_rows()
                return
        elif event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_V:
            from PyQt6.QtWidgets import QApplication
            text = QApplication.clipboard().text()
            if text:
                accepted = self._parse_clipboard_files(text)
                if accepted:
                    self._add_files_to_pipeline(accepted)
                    return
            mime = QApplication.clipboard().mimeData()
            if mime.hasUrls():
                accepted = self._extract_files_from_urls(mime.urls())
                if accepted:
                    self._add_files_to_pipeline(accepted)
                    return
        super().keyPressEvent(event)

    def _delete_selected_rows(self):
        """删除所有选中的行"""
        if not self._selected_rows:
            return
        
        count = len(self._selected_rows)
        reply = QMessageBox.question(
            self, "确认批量移除",
            f"将移除 {count} 个文件。\n此操作不会删除磁盘上的文件。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        file_list = self.workflow_module.file_list
        for row in list(self._selected_rows):
            file_path = row.file_path
            unique_key = make_pipeline_key(file_path)
            for i in range(file_list.count()):
                item = file_list.item(i)
                if item and str(file_path) in item.toolTip():
                    file_list.setCurrentItem(item)
                    break
            file_list.remove_selected()

            if self.workflow_module:
                self.workflow_module.panel_set_row_config(file_path, None)  # 清空独立配置
            self.pipeline_states.pop(unique_key, None)  # property 会转发

            self.row_widgets.pop(unique_key, None)
        
        self._selected_rows.clear()
        self._append_log(f"🗑️ 已批量移除 {count} 个文件", "INFO")
        self._refresh_rows()

    def _parse_clipboard_files(self, text: str) -> list:
        """解析剪贴板文本，提取 .md 文件路径"""
        from pathlib import Path
        found = []
        for line in text.strip().splitlines():
            line = line.strip().strip('"').strip("'")
            if not line:
                continue
            try:
                path = Path(line)
                if path.is_file() and path.suffix.lower() == '.md' and path.exists():
                    found.append(path)
                elif path.is_dir() and path.exists():
                    for md_file in path.rglob("*.md"):
                        found.append(md_file)
            except Exception:
                continue
        return found

    def _extract_files_from_urls(self, urls: list) -> list:
        """从剪贴板 URL 列表提取 .md 文件"""
        from pathlib import Path
        found = []
        for url in urls:
            path = Path(url.toLocalFile())
            if not path.exists():
                continue
            if path.is_file() and path.suffix.lower() == '.md':
                found.append(path)
            elif path.is_dir():
                for md_file in path.rglob("*.md"):
                    found.append(md_file)
        return found

    def _add_files_to_pipeline(self, files: list):
        """去重后添加到主模块并刷新行"""
        if not self.workflow_module:
            return
        
        # 去重
        seen = set()
        unique = []
        for f in files:
            fa = str(f.absolute())
            if fa not in seen:
                seen.add(fa)
                unique.append(f)
        
        if not unique:
            return
        
        added = self.workflow_module.file_list.add_files(unique)
        if added > 0:
            self._append_log(f"📋 粘贴 {added} 个文件", "INFO")
            self._refresh_rows()

    def _on_remove_file(self, file_path: Path):
        """右键删除文件：同步主模块文件列表 + 刷新监视面板行"""
        if not self.workflow_module:
            return

        # 确认对话框
        reply = QMessageBox.question(
            self, "确认移除",
            f"将移除文件：{file_path.name}\n\n此操作不会删除磁盘上的文件。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        file_list = self.workflow_module.file_list
        
        # 在 file_list 中找到并选中该文件
        for i in range(file_list.count()):
            item = file_list.item(i)
            if item and str(file_path) in item.toolTip():
                file_list.setCurrentItem(item)
                break
        
        # 调用 remove_selected 删除
        removed = file_list.remove_selected()
        if removed:
            self._append_log(f"🗑️ 已移除: {file_path.name}", "INFO")
            # 清除该文件的独立配置

            if self.workflow_module:
                self.workflow_module.panel_set_row_config(file_path, None)

            key = make_pipeline_key(file_path)
            self.pipeline_states.pop(key, None)
            self.row_widgets.pop(key, None)
            self._refresh_rows()

    def _on_rollback_all(self):
        """全部回滚：清除所有产物并重置状态"""
        if self._is_running:
            QMessageBox.warning(self, "提示", "工作流正在运行中，请先暂停或等待完成")
            return

        # 统计产物数量
        total_files = 0
        for key, state in self.pipeline_states.items():
            for step_type, step_state in state.get('steps', {}).items():
                output_path = step_state.get('output_path', '')
                if output_path:
                    p = Path(output_path)
                    if p.exists():
                        total_files += 1

        if total_files == 0:
            QMessageBox.information(self, "提示", "没有可回滚的产物")
            return

        reply = QMessageBox.question(
            self, "确认全部回滚",
            f"将删除所有 {total_files} 个产物文件。\n\n"
            f"包括：中间产物（_fixed.md / .epub）和最终结果（.pdf）\n"
            f"原始输入文件不会被删除。\n\n"
            f"此操作不可撤销。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        deleted = 0
        for key, state in self.pipeline_states.items():
            for step_type, step_state in state.get('steps', {}).items():
                output_path = step_state.get('output_path', '')
                if output_path:
                    p = Path(output_path)
                    if p.exists():
                        try:
                            p.unlink()
                            deleted += 1
                        except Exception as e:
                            self._append_log(f"⚠️ 无法删除 {p.name}: {e}", "WARNING")
            state['steps'] = {}

        # 重置所有行的 UI
        for row in self.row_widgets.values():
            row.set_all_waiting()

        self._completed_steps = 0
        self._completed_files = 0
        self._update_overall_progress(0, self._total_steps, 0, 0)

        self._append_log(f"🗑 全部回滚完成，已删除 {deleted} 个文件", "INFO")
        QMessageBox.information(self, "完成", f"已删除 {deleted} 个产物文件，所有步骤已重置")

    def _on_clear_log(self):
        if self.workflow_module:
            self.workflow_module.panel_log_cache.clear()
        self.log_text.clear()
        self.log_status_label.setText("")
        self._append_log("🗑 日志已清空", "INFO")

    def _on_clean_intermediate(self):
        """清理中间产物：删除过程文件，只保留最终结果"""
        if self._is_running:
            QMessageBox.warning(self, "提示", "工作流正在运行中，请先暂停或等待完成")
            return

        mode_key = self._get_mode_key()
        steps = MODE_STEPS.get(mode_key, [])
        if len(steps) <= 1:
            QMessageBox.information(self, "提示", "当前工作流模式没有中间产物")
            return

        # 中间步骤 = 除最后一步外的所有步骤
        intermediate_steps = steps[:-1]
        final_step = steps[-1]

        # 统计
        to_delete = []
        for key, state in self.pipeline_states.items():
            for step_type in intermediate_steps:
                step_state = state.get('steps', {}).get(step_type, {})
                output_path = step_state.get('output_path', '')
                if output_path:
                    p = Path(output_path)
                    if p.exists():
                        to_delete.append(p)
            # 清除中间步骤的状态（保留最终步骤）
            for step_type in intermediate_steps:
                state['steps'].pop(step_type, None)

        if not to_delete:
            QMessageBox.information(self, "提示", "没有可清理的中间产物")
            return

        reply = QMessageBox.question(
            self, "确认清理",
            f"将删除 {len(to_delete)} 个中间产物文件：\n"
            f"• _fixed.md（MD修复产物）\n"
            f"• .epub（中间电子书）\n\n"
            f"最终结果（{final_step.display_name}产物）将被保留。\n"
            f"此操作不可撤销。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        deleted = 0
        for p in to_delete:
            try:
                p.unlink()
                deleted += 1
            except Exception as e:
                self._append_log(f"⚠️ 无法删除 {p.name}: {e}", "WARNING")

        # 重置中间步骤的 UI 状态
        for row in self.row_widgets.values():
            for step_type in intermediate_steps:
                row.update_step(step_type, StepStatus.WAITING)

        self._append_log(f"🧹 已清理 {deleted} 个中间产物，最终结果已保留", "INFO")
        QMessageBox.information(self, "完成", f"已删除 {deleted} 个中间产物")

    def _on_save_log(self):
        """保存日志到文件"""
        log_cache = self.workflow_module.panel_log_cache if self.workflow_module else []
        if not log_cache:
            QMessageBox.information(self, "提示", "没有日志内容可保存")
            return

        from PyQt6.QtWidgets import QFileDialog
        from datetime import datetime

        default_name = f"epub_monitor_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存日志", default_name, "文本文件 (*.txt);;所有文件 (*.*)")

        if not file_path:
            return

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                for timestamp, msg, level in log_cache:
                    f.write(f"[{timestamp}] [{level}] {msg}\n")

            self._append_log(f"💾 日志已保存到: {file_path}", "SUCCESS")
            QMessageBox.information(self, "成功", f"日志已保存到:\n{file_path}")
        except Exception as e:
            self._append_log(f"❌ 保存日志失败: {e}", "ERROR")
            QMessageBox.critical(self, "错误", f"保存失败: {e}")

    def _check_main_worker(self):
        if not self.workflow_module:
            return
        worker = getattr(self.workflow_module, 'worker', None)
        if not worker:
            return
        
        if worker.isRunning():
            if self._last_worker_id != id(worker):
                worker.step_state_changed.connect(self._on_step_state_changed)
                worker.finished_all.connect(self._on_main_worker_finished)
                self._last_worker_id = id(worker)
                self._is_running = True
                self.start_all_btn.setEnabled(False)
                self.start_all_btn.setText("🔄 监视中...")
                self._append_log("📡 已连接主界面工作流", "INFO")
                self._restore_ui_from_pipeline()
                running = getattr(worker, '_running_results', None)
                if running:
                    self._sync_running_results(running)
                if hasattr(worker, 'results') and worker.results:
                    self._sync_running_results(worker.results)
            return
        
        # ★ 以下是缺失的部分：Worker 已完成但有结果
        if hasattr(worker, 'results') and worker.results:
            if self._last_worker_id != id(worker):
                self._on_main_worker_finished(worker.results)
                self._last_worker_id = id(worker)
                self._append_log("📡 已同步主界面工作流结果", "INFO")

        # ★ 同时同步所有历史累积结果
        if hasattr(self.workflow_module, 'all_results') and self.workflow_module.all_results:
            if not self._synced_main_results:
                self._on_main_worker_finished(self.workflow_module.all_results)
                self._synced_main_results = True

    def _sync_running_results(self, running: list):
        """将 Worker 的中间结果同步到 pipeline_states 并刷新 UI"""
        self._on_main_worker_finished(running, is_final=False)

# ==================== 元信息 ====================
__author__ = "YQJ"
__version__ = "1.2.1"
__date__ = "2026.05.23"