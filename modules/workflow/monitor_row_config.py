#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
监视面板 - 行独立修复配置对话框
为单个文件提供独立的 MD 修复设置，覆盖全局配置
"""

import copy
from pathlib import Path
from typing import Dict, Any, Optional, List

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QCheckBox, QScrollArea, QFrame, QWidget, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from modules.md_repair.processor import FeatureHelpDatabase
from core.config_keys import MDRepairKey


# ==================== 功能说明数据库缓存 ====================

_help_db: Optional[Dict[str, Dict[str, Any]]] = None

def _get_help_db() -> Dict[str, Dict[str, Any]]:
    global _help_db
    if _help_db is None:
        _help_db = FeatureHelpDatabase.get_all_features()
    return _help_db


# ==================== 功能分组定义 ====================

FEATURE_SECTIONS = [
    ("🟢 格式与语法修复", [
        'clean_newlines', 'add_space_after_inline', 'subsup_fix',
        'func_normalize', 'matrix_newline_remove', 'bracket_check',
        'fix_encoding', 'escape_isolated_dollars'
    ]),
    ("🟡 语义增强", [
        'markdown_escape_inline', 'matrix_add_multiplication', 'remove_size_commands'
    ]),
    ("🛡️ 安全保护", [
        'respect_macros', 'dl_commands_to_text'
    ]),
    ("🔴 高级转换", [
        'bm_to_vec', 'inline_to_display'
    ]),
    ("🖼️ 用户定制", [
        'image_caption'
    ]),
]


# ==================== 对话框 ====================

class RowRepairConfigDialog(QDialog):
    """单文件修复配置对话框（简化版）

    仅显示功能复选框，无预设方案按钮。
    初始值从全局配置继承，用户可覆盖。

    特性：
        - 复选框三态：已勾选 / 未勾选 / 使用全局（斜体灰色）
        - 「重置为全局」按钮一键恢复
        - 仅保存与全局不同的配置项（稀疏存储）
    """

    def __init__(self, file_path: Path, global_config: Dict[str, Any],
                parent=None, existing_row_config: Dict = None):
        """初始化行配置对话框
        Args:
            file_path: 目标文件路径
            global_config: 全局修复配置（作为默认值）
            parent: 父级窗口
            existing_row_config: ★ 已有的行独立配置（用于回显）
        """
        super().__init__(parent)
        self.file_path = file_path
        self.global_config = copy.deepcopy(global_config)
        self.result_config: Optional[Dict[str, Any]] = None
        self._existing_row_config = existing_row_config or {}  # ★ 新增

        self.checkboxes: Dict[str, QCheckBox] = {}
        self._global_values: Dict[str, bool] = {}

        self.setWindowTitle(f"⚙️ {file_path.name} — 独立修复设置")
        self.setMinimumWidth(520)
        self.setMaximumWidth(560)
        self.resize(500, 600)

        self._setup_ui()
        self._load_global_defaults()

    def _setup_ui(self):
        """构建 UI 布局"""
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        # 标题
        title = QLabel(f"📝 独立修复设置")
        title.setFont(QFont("Microsoft YaHei", 13, QFont.Weight.Bold))
        layout.addWidget(title)

        # 文件名提示
        file_hint = QLabel(f"文件: <b>{self.file_path.name}</b>")
        file_hint.setWordWrap(True)
        file_hint.setStyleSheet("color: #555;")
        layout.addWidget(file_hint)

        # 说明文字
        hint = QLabel(
            "此设置仅对该文件生效，覆盖全局修复配置。<br>"
            "未修改的项将使用全局设置。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; font-size: 11px; padding: 4px; background: #fef9e7; border-radius: 4px;")
        layout.addWidget(hint)

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

        # 滚动区域 — 功能复选框
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(8)
        scroll_layout.setContentsMargins(0, 0, 0, 0)

        help_db = _get_help_db()

        for section_title, feature_keys in FEATURE_SECTIONS:
            section_group = QGroupBox(section_title)
            section_group_layout = QVBoxLayout(section_group)
            section_group_layout.setSpacing(4)

            for key in feature_keys:
                info = help_db.get(key, {})
                if not info:
                    continue

                cb = QCheckBox(f"{info.get('icon', '')} {info.get('name', key)}")
                cb.setToolTip(info.get('trigger', ''))
                cb.toggled.connect(self._on_checkbox_changed)
                self.checkboxes[key] = cb
                section_group_layout.addWidget(cb)

            scroll_layout.addWidget(section_group)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll, 1)  # stretch=1

        # 底部按钮行
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        # 重置按钮
        reset_btn = QPushButton("🔄 重置为全局设置")
        reset_btn.setAutoDefault(False)
        reset_btn.setToolTip("将所有选项恢复为全局配置的默认值")
        reset_btn.setStyleSheet("""
            QPushButton {
                padding: 6px 14px;
                border: 1px solid #ddd;
                border-radius: 4px;
                background: #fafafa;
            }
            QPushButton:hover {
                background: #e8e8e8;
            }
        """)
        reset_btn.clicked.connect(self._load_global_defaults)
        btn_layout.addWidget(reset_btn)

        # ★ 全部选择
        select_all_btn = QPushButton("☑️ 全部选择")
        reset_btn.setAutoDefault(False)
        select_all_btn.setToolTip("自动勾选列表中的所有功能选项")
        select_all_btn.setStyleSheet("""
            QPushButton {
                padding: 6px 12px;
                border: 1px solid #27ae60;
                border-radius: 4px;
                background: #eafaf1;
                color: #27ae60;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #d5f5e3;
            }
        """)
        select_all_btn.clicked.connect(self._select_all)
        btn_layout.addWidget(select_all_btn)

        # ★ 全部取消
        deselect_all_btn = QPushButton("☐ 全部取消")
        reset_btn.setAutoDefault(False)
        deselect_all_btn.setToolTip("自动取消勾选列表中的所有功能选项")
        deselect_all_btn.setStyleSheet("""
            QPushButton {
                padding: 6px 12px;
                border: 1px solid #e74c3c;
                border-radius: 4px;
                background: #fdedec;
                color: #e74c3c;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #fadbd8;
            }
        """)
        deselect_all_btn.clicked.connect(self._deselect_all)
        btn_layout.addWidget(deselect_all_btn)

        btn_layout.addStretch()

        # 确定按钮
        ok_btn = QPushButton("✅ 确定")
        ok_btn.setStyleSheet("""
            QPushButton {
                padding: 6px 20px;
                background-color: #27ae60;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #219a52; }
        """)
        ok_btn.clicked.connect(self._on_ok)
        ok_btn.setDefault(True)
        btn_layout.addWidget(ok_btn)

        # 取消按钮
        cancel_btn = QPushButton("取消")
        reset_btn.setAutoDefault(False)
        cancel_btn.setStyleSheet("""
            QPushButton {
                padding: 6px 14px;
                border: 1px solid #ddd;
                border-radius: 4px;
                background: #fafafa;
            }
            QPushButton:hover { background: #e8e8e8; }
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

    def _load_global_defaults(self):
        """从全局配置载入默认值"""
        fc = self.global_config.get('formula_config', {})

        # 顶层配置项
        self._global_values['clean_newlines'] = self.global_config.get('clean_extra_newlines', False)
        self._global_values['add_space_after_inline'] = self.global_config.get('add_space_after_inline', False)
        self._global_values['inline_to_display'] = self.global_config.get('inline_to_display', False)
        self._global_values['image_caption'] = self.global_config.get('image_caption_enabled', False)
        self._global_values['fix_encoding'] = self.global_config.get('fix_encoding', False)
        self._global_values['escape_isolated_dollars'] = self.global_config.get('escape_isolated_dollars', False)

        # 公式级配置项
        self._global_values['subsup_fix'] = fc.get('subsup_fix', False)
        self._global_values['func_normalize'] = fc.get('func_normalize', False)
        self._global_values['matrix_newline_remove'] = fc.get('matrix_newline_remove', False)
        self._global_values['bracket_check'] = fc.get('bracket_check', False)
        self._global_values['markdown_escape_inline'] = fc.get('markdown_escape_inline', False)
        self._global_values['matrix_add_multiplication'] = fc.get('matrix_add_multiplication', False)
        self._global_values['dl_commands_to_text'] = fc.get('dl_commands_to_text', False)
        self._global_values['remove_size_commands'] = fc.get('remove_size_commands', False)
        self._global_values['bm_to_vec'] = fc.get('bm_to_vec', False)
        self._global_values['respect_macros'] = fc.get('respect_macros', False)

        # ★ 设置所有复选框，优先使用已有独立配置的值
        for key, cb in self.checkboxes.items():
            cb.blockSignals(True)
            if key in self._global_values:
                value = self._get_row_config_value(key, self._global_values[key])
                cb.setChecked(value)
                cb.setStyleSheet("")
                cb.setToolTip(_get_help_db().get(key, {}).get('trigger', ''))
                # 标记与全局的差异
                if value != self._global_values[key]:
                    cb.setStyleSheet("""
                        QCheckBox {
                            color: #e67e22;
                            font-weight: bold;
                        }
                    """)
            cb.blockSignals(False)

    def _get_row_config_value(self, key: str, global_value: bool) -> bool:
        """获取某项在已有独立配置中的值，没有则返回全局值"""
        top_mapping = {
            'clean_newlines': MDRepairKey.CLEAN_EXTRA_NEWLINES,
            'add_space_after_inline': MDRepairKey.ADD_SPACE_AFTER_INLINE,
            'inline_to_display': MDRepairKey.INLINE_TO_DISPLAY,
            'image_caption': MDRepairKey.IMAGE_CAPTION_ENABLED,
            'fix_encoding': MDRepairKey.FIX_ENCODING,
            'escape_isolated_dollars': MDRepairKey.ESCAPE_ISOLATED_DOLLARS,
        }
        
        if key in top_mapping:
            field = top_mapping[key]
            if field in self._existing_row_config:
                return self._existing_row_config[field]
        else:
            fc = self._existing_row_config.get(MDRepairKey.FORMULA_CONFIG, {})
            if key in fc:
                return fc[key]
        
        return global_value

    def _on_checkbox_changed(self):
        """复选框变化时更新样式（标记为已覆盖）"""
        for key, cb in self.checkboxes.items():
            if key not in self._global_values:
                continue
            global_val = self._global_values[key]
            if cb.isChecked() != global_val:
                # 与全局不同 → 高亮标记
                cb.setStyleSheet("""
                    QCheckBox {
                        color: #e67e22;
                        font-weight: bold;
                    }
                """)
                cb.setToolTip(
                    f"{_get_help_db().get(key, {}).get('trigger', '')}\n\n"
                    f"⚠️ 已覆盖全局设置（全局: {'✅' if global_val else '❌'}）"
                )
            else:
                # 与全局相同 → 正常样式
                cb.setStyleSheet("")
                cb.setToolTip(_get_help_db().get(key, {}).get('trigger', ''))

    def _select_all(self):
        """勾选所有修复功能"""
        for cb in self.checkboxes.values():
            cb.setChecked(True)

    def _deselect_all(self):
        """取消所有修复功能"""
        for cb in self.checkboxes.values():
            cb.setChecked(False)

    def _on_ok(self):
        """收集配置并关闭

        仅保存与全局不同的配置项（稀疏存储），
        以减少内存占用并明确标记覆盖范围。
        """
        # 顶层配置映射
        top_mapping = {
            'clean_newlines': MDRepairKey.CLEAN_EXTRA_NEWLINES,
            'add_space_after_inline': MDRepairKey.ADD_SPACE_AFTER_INLINE,
            'inline_to_display': MDRepairKey.INLINE_TO_DISPLAY,
            'image_caption': MDRepairKey.IMAGE_CAPTION_ENABLED,
            'fix_encoding': MDRepairKey.FIX_ENCODING,
            'escape_isolated_dollars': MDRepairKey.ESCAPE_ISOLATED_DOLLARS,
        }

        self.result_config = {}

        for key, cb in self.checkboxes.items():
            if key not in self._global_values:
                continue

            current_val = cb.isChecked()
            global_val = self._global_values[key]

            # 只保存与全局不同的项
            if current_val != global_val:
                if key in top_mapping:
                    self.result_config[top_mapping[key]] = current_val
                else:
                    if 'formula_config' not in self.result_config:
                        self.result_config['formula_config'] = {}
                    self.result_config['formula_config'][key] = current_val

        self.accept()

    def get_config(self) -> Optional[Dict[str, Any]]:
        """获取最终的配置字典（稀疏，仅含覆盖项）

        Returns:
            Dict 或 None: 配置字典，无修改时返回空 dict
        """
        return self.result_config


# ==================== 元信息 ====================
__author__ = "YQJ"
__version__ = "1.1.0"
__date__ = "2026.05.09"