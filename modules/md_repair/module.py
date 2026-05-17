#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MD公式修复模块 - PyQt6界面封装（增强版 v4.3.6）
"""

import os
import sys
import time
import logging
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from threading import Event
from core.config_keys import SettingsDomain, MDRepairKey

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QRadioButton, QSpinBox, QCheckBox, QLineEdit,
    QFileDialog, QGridLayout, QMessageBox, QFrame, QMenu
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QSettings

from core.base_module import BaseModule
from core.components import UnifiedFileListWidget, FileStatus, LogPanel
from core.components.file_list import DropHotzoneMixin
from .processor import (
    MarkdownFormulaProcessor, MarkdownTitleExtractor,
    ConfigurableFormulaFixer, FormulaPreviewer, RepairProfile
)
from .dialogs import AdvancedSettingsDialog, SideBySidePreviewDialog


logger = logging.getLogger(__name__)


# ==================== 工作线程 ====================

class RepairWorker(QThread):
    """公式修复工作线程"""

    progress_updated = pyqtSignal(int, str, int, int)
    file_status_signal = pyqtSignal(Path, str)
    log_message = pyqtSignal(str, str)
    finished_all = pyqtSignal(list)

    def __init__(self, files: List[Path], output_mode: str,
                 output_dir: Path = None, max_workers: int = 4,
                 config: Dict[str, Any] = None,
                 rename_by_title: bool = False, auto_open: bool = False):
        super().__init__()
        self.files = files
        self.output_mode = output_mode
        self.output_dir = output_dir
        self.max_workers = max_workers
        self.config = config or {}
        self.rename_by_title = rename_by_title
        self.auto_open = auto_open
        self._stop_event = Event()  # ★ 使用 Event 替代布尔标志
        self.results = []
        self.title_extractor = MarkdownTitleExtractor() if rename_by_title else None

    def stop(self):
        self._stop_event.set()

    def run(self):
        total = len(self.files)
        self.results = []

        self.log_message.emit(
            f"开始处理 {total} 个文件，并行数: {self.max_workers}", "INFO")
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
                    self.log_message.emit(
                        f"📝 将重命名: {f.name} → {name}（标题: {extracted}）", "INFO")
            else:
                name = f"{f.stem}_fixed.md"
                title_used, extracted = False, None

            output_path = out_dir / name
            output_path = self._get_unique_path(output_path)
            file_output_map[f] = (output_path, title_used, extracted)

        if self.rename_by_title:
            self.log_message.emit(
                f"📊 共 {rename_count}/{total} 个文件将使用YAML标题", "INFO")

        start = time.time()
        completed = 0

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {}
            for f in self.files:
                if self._stop_event.is_set():
                    break
                self.file_status_signal.emit(f, 'processing')
                output_path, _, _ = file_output_map[f]
                future = executor.submit(self._process_file, f, output_path)
                futures[future] = f

            for future in as_completed(futures):
                if self._stop_event.is_set():
                    break
                f = futures[future]
                completed += 1

                try:
                    result = future.result(timeout=300)
                    output_path, title_used, extracted = file_output_map[f]
                    result.update({
                        'title_used': title_used,
                        'extracted_title': extracted,
                        'original_name': f.name,
                        'new_name': output_path.name
                    })
                    self.results.append(result)

                    progress = int(completed / total * 100)

                    if result['status'] == 'success':
                        self.file_status_signal.emit(f, 'success')
                        stats = result.get('stats', {})
                        msg = f"✅ [{completed}/{total}] {f.name} → {output_path.name}"
                        if stats.get('total_formulas', 0) > 0:
                            msg += f": 公式{stats['total_formulas']}个，修复{stats['fixed_formulas']}个"
                        for key, label in [
                            ('func_normalized', '函数名'),
                            ('subsup_fixed', '上下标'),
                            ('bracket_fixed', '括号'),
                            ('markdown_escaped', '转义'),
                            ('image_captions_fixed', '图片标题'),
                            ('encoding_fixed', '编码修复'),
                            ('dollar_escaped', '美元转义')
                        ]:
                            if stats.get(key, 0) > 0:
                                msg += f"，{label}{stats[key]}个"
                        if title_used:
                            msg += f"\n   📝 已重命名（标题: {extracted}）"
                        self.log_message.emit(msg, "SUCCESS")
                    else:
                        self.file_status_signal.emit(f, 'failed')
                        self.log_message.emit(
                            f"❌ [{completed}/{total}] {f.name}: {result.get('error')}", "ERROR")

                except Exception as e:
                    self.file_status_signal.emit(f, 'failed')
                    self.log_message.emit(f"❌ {f.name}: {e}", "ERROR")
                    self.results.append({
                        'file': str(f), 'status': 'failed', 'error': str(e)
                    })

                self.progress_updated.emit(
                    progress, f"处理中... {completed}/{total}", completed, total)

        elapsed = time.time() - start
        self.log_message.emit(f"总耗时: {elapsed:.1f}秒", "INFO")

        if not self._stop_event.is_set() and self.auto_open:
            self._smart_open()

        self.finished_all.emit(self.results)

    def _process_file(self, input_file: Path, output_file: Path) -> dict:
        """处理单个文件"""
        try:
            processor = MarkdownFormulaProcessor(
                input_file, output_file.parent, self.config)
            text, actual = processor.process(output_filename=output_file.name)
            if text is None:
                return {
                    'file': str(input_file), 'output': '',
                    'status': 'failed',
                    'error': '处理后的文本为空',
                    'stats': processor.stats
                }
            return {
                'file': str(input_file),
                'output': str(actual),
                'status': 'success',
                'stats': processor.stats,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {
                'file': str(input_file),
                'status': 'failed',
                'error': f'{type(e).__name__}: {str(e)}'
            }

    def _get_unique_path(self, path: Path) -> Path:
        """获取唯一输出路径"""
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
        """智能打开输出目录"""
        dirs = set(Path(r['output']).parent for r in self.results if r.get('output'))
        lst = list(dirs)
        if len(lst) == 1:
            self._open_folder(lst[0])
        elif len(lst) <= 3:
            for d in lst:
                self._open_folder(d)

    @staticmethod
    def _open_folder(folder: Path):
        """跨平台打开文件夹"""
        folder_str = str(folder)
        if sys.platform == 'win32':
            os.startfile(folder_str)
        elif sys.platform == 'darwin':
            import subprocess
            subprocess.run(['open', folder_str])
        else:
            import subprocess
            subprocess.run(['xdg-open', folder_str])


# ==================== 模块类 ====================

class MDRepairModule(BaseModule):
    """MD公式修复模块"""

    @property
    def module_id(self) -> str:
        return "md_repair"

    @property
    def module_name(self) -> str:
        return "3-MD公式修复"

    @property
    def module_icon(self) -> str:
        return "📝"

    @property
    def module_description(self) -> str:
        return (
            "修复 Markdown 文件中 LaTeX 公式格式错误。"
            "16项可配置修复（不勾选=不修复），4套预设方案。"
            "批量预检摘要与并排对比预览（Ctrl+Shift+L），"
            "MathJax v3 离线实时渲染（缩放+换行）。"
            "快速调整面板累积式调试（勾选自动生效），配置更新一键同步。"
        )
    
    @property
    def accepted_extensions(self) -> List[str]:
        return ['.md']

    def on_activate(self):
        self.last_config = self._load_config()
        self._update_profile_hint()

    def check_dependencies(self) -> Tuple[bool, str]:
        return True, "就绪（纯Python实现）"

    # ====== 配置管理 ======

    def _get_default_config(self) -> Dict[str, Any]:
        from .processor import DEFAULT_REPAIR_CONFIG
        import copy
        return copy.deepcopy(DEFAULT_REPAIR_CONFIG)

    def _load_config(self) -> Dict[str, Any]:
        defaults = self._get_default_config()
        saved = self.settings.value(MDRepairKey.CONFIG_V4)
        if saved and isinstance(saved, dict):
            for key, value in saved.items():
                if key == 'formula_config' and isinstance(value, dict):
                    defaults['formula_config'].update(value)
                else:
                    defaults[key] = value
        return defaults

    def _save_config(self):
        self.settings.setValue(MDRepairKey.CONFIG_V4, self.last_config)

    # ====== UI 创建 ======

    def create_ui(self, parent=None) -> QWidget:
        self.settings = QSettings(SettingsDomain.EPUB_TOOLBOX, SettingsDomain.MD_REPAIR)
        self.last_config = self._load_config()

        widget = QWidget(parent)

        layout = QVBoxLayout(widget)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)

        # 文件列表
        layout.addWidget(self._create_file_section())

        # 输出设置
        layout.addWidget(self._create_output_section())

        # 转换选项
        layout.addWidget(self._create_options_section())

        layout.addStretch()

        self.output_dir: Optional[Path] = None
        self.worker: Optional[RepairWorker] = None
        self.progress_bar = None
        self.log_panel = None

        self._update_profile_hint()

        return widget

    def _create_file_section(self) -> QGroupBox:
        file_group = QGroupBox("📁 选择Markdown文件 (支持拖拽，Ctrl+V，右键预览)")
        file_layout = QVBoxLayout(file_group)

        self.file_list = UnifiedFileListWidget(['.md'])
        self.file_list.files_added.connect(self._on_files_added)
        self.file_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_list.customContextMenuRequested.connect(self._on_context_menu)
        file_layout.addWidget(self.file_list)

        btn_layout = QHBoxLayout()
        add_file_btn = QPushButton("➕ 添加文件")
        add_file_btn.clicked.connect(self._add_files)
        add_folder_btn = QPushButton("📂 添加文件夹")
        add_folder_btn.clicked.connect(self._add_folder)
        remove_btn = QPushButton("❌ 移除选中")
        remove_btn.clicked.connect(self._remove_selected)
        clear_btn = QPushButton("🗑️ 清空全部")
        clear_btn.clicked.connect(self._clear_all)

        btn_layout.addWidget(add_file_btn)
        btn_layout.addWidget(add_folder_btn)
        btn_layout.addWidget(remove_btn)
        btn_layout.addWidget(clear_btn)

        self.force_reprocess_cb = QCheckBox("忽略状态")
        self.force_reprocess_cb.setToolTip(
            "默认情况下，已经处理过的文件不会再次处理。\n"
            "勾选此项后，将重新处理列表中的所有文件。\n\n"
            "适用场景：\n• 修改了修复配置后想重新处理\n"
            "• 之前处理失败的文件想再次尝试\n• 需要覆盖之前的输出文件")
        btn_layout.addWidget(self.force_reprocess_cb)

        btn_layout.addStretch()
        file_layout.addLayout(btn_layout)

        # ★ 扩大拖放热区
        DropHotzoneMixin.install(file_group, self.file_list, self.accepted_extensions)

        return file_group

    def _create_output_section(self) -> QGroupBox:
        output_group = QGroupBox("📂 输出设置")
        output_layout = QHBoxLayout(output_group)

        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setPlaceholderText("默认与源文件同目录")
        self.output_dir_edit.textChanged.connect(self._on_output_dir_text_changed)
        output_layout.addWidget(self.output_dir_edit)

        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self._select_output_dir)
        output_layout.addWidget(browse_btn)

        return output_group

    def _create_options_section(self) -> QGroupBox:
        options_group = QGroupBox("⚙️ 转换选项")
        options_layout = QGridLayout()
        options_layout.setVerticalSpacing(8)
        options_layout.setHorizontalSpacing(10)

        self.advanced_btn = QPushButton("🔧 高级设置")
        self.advanced_btn.clicked.connect(self._open_advanced_settings)
        self.advanced_btn.setToolTip(
            "打开高级修复选项\n"
            "可选择预设方案或自定义每个修复功能的开关\n"
            "每个选项旁有 ⓘ 可查看详细说明")
        self.advanced_btn.setStyleSheet(
            "QPushButton { padding: 8px 16px; font-size: 13px; font-weight: bold; "
            "color: #ffffff; background-color: #3498db; "
            "border: 1px solid #2980b9; border-radius: 4px; }"
            "QPushButton:hover { background-color: #2980b9; border-color: #1c6ea4; }"
            "QPushButton:pressed { background-color: #2471a3; }")
        options_layout.addWidget(self.advanced_btn, 0, 0, 1, 3)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #dee2e6; margin: 5px 0;")
        options_layout.addWidget(sep, 1, 0, 1, 3)

        options_layout.addWidget(QLabel("并行线程数:"), 2, 0)

        cpu_count = os.cpu_count() or 4
        default_workers = min(4, cpu_count)

        workers_layout = QHBoxLayout()
        self.worker_spin = QSpinBox()
        self.worker_spin.setMinimum(1)
        self.worker_spin.setMaximum(16)
        self.worker_spin.setValue(default_workers)
        self.worker_spin.setFixedWidth(80)
        workers_layout.addWidget(self.worker_spin)
        options_layout.addLayout(workers_layout, 2, 1)

        cpu_label = QLabel(f"(CPU: {cpu_count}核)")
        cpu_label.setObjectName("infoLabel")
        options_layout.addWidget(cpu_label, 3, 2)

        self.auto_open_cb = QCheckBox("处理完成后打开输出目录")
        options_layout.addWidget(self.auto_open_cb, 3, 0, 1, 3)

        self.rename_by_title_cb = QCheckBox("使用YAML标题重命名输出文件")
        self.rename_by_title_cb.setToolTip(
            "勾选后，程序将读取Markdown文件的YAML头部信息，\n"
            "提取title字段作为输出文件名。\n"
            "支持的字段：title、标题、name、slug、文件名\n"
            "未找到标题时使用原文件名（向后兼容）。")
        options_layout.addWidget(self.rename_by_title_cb, 4, 0, 1, 3)

        options_layout.setColumnStretch(3, 1)
        options_group.setLayout(options_layout)

        return options_group

    # ====== 右键菜单 ======

    def _on_context_menu(self, position):
        menu = QMenu(self.file_list)

        open_folder_action = menu.addAction("📂 打开所在文件夹")
        menu.addSeparator()
        preview_action = menu.addAction("🔍 预览此文件")
        menu.addSeparator()
        remove_action = menu.addAction("❌ 移除选中")
        clear_action = menu.addAction("🗑️ 清空列表")

        selected_files = self._get_selected_files()

        if not selected_files:
            open_folder_action.setEnabled(False)
            preview_action.setEnabled(False)
            remove_action.setEnabled(False)

        if self.file_list.count() == 0:
            clear_action.setEnabled(False)

        action = menu.exec(self.file_list.mapToGlobal(position))

        if action == open_folder_action and selected_files:
            self._open_folder_for_selected(selected_files[0])
        elif action == preview_action and selected_files:
            self._preview_files(selected_files)
        elif action == remove_action:
            self._remove_selected()
        elif action == clear_action:
            self._clear_all()

    def _get_selected_files(self) -> List[Path]:
        selected = []
        for item in self.file_list.selectedItems():
            row = self.file_list.row(item)
            if row in self.file_list.file_paths:
                selected.append(self.file_list.file_paths[row])
        return selected

    def _open_folder_for_selected(self, file_path: Path):
        import subprocess
        folder = str(file_path.parent)
        if sys.platform == 'win32':
            subprocess.run(['explorer', folder], shell=True)
        elif sys.platform == 'darwin':
            subprocess.run(['open', folder])
        else:
            subprocess.run(['xdg-open', folder])

    # ====== 预检预览 ======

    def _preview_files(self, files: List[Path] = None, entry_point: str = "context_menu"):
        """执行预检预览
        
        Args:
            files: 要预览的文件列表
            entry_point: 
                "context_menu" — 右键菜单，严格校验，就地解决
                "shortcut"     — Ctrl+Shift+L / 菜单栏，零阻断，展示功能
        """
        if files is None:
            all_files = self.file_list.get_all_files()
            if entry_point == "context_menu":
                selected = self._get_selected_files()
                files = selected if selected else []
            else:
                selected = self._get_selected_files()
                files = selected if selected else all_files
        
        config = self._get_current_config()
        has_features = self._has_any_feature_enabled(config)
        has_files = bool(files)
        
        # ============================================================
        # 入口2：Ctrl+Shift+L / 菜单 — 零阻断，探索式进入
        # ============================================================
        if entry_point == "shortcut":
            # 无文件 → 直接打开高级设置展示功能（不弹提示阻断）
            if not has_files:
                self._open_advanced_settings()
                return
            
            # 有文件 + 无配置 → 打开预览窗口，快速调整面板高亮
            if not has_features:
                test_file = files[0]
                try:
                    text = test_file.read_text(encoding='utf-8')
                except Exception as e:
                    QMessageBox.warning(None, "错误", f"无法读取文件: {e}")
                    return
                previewer = FormulaPreviewer(config)
                try:
                    changes = previewer.preview(text, test_file)
                except Exception as e:
                    QMessageBox.warning(None, "错误", f"预检处理失败: {e}")
                    return
                dialog = SideBySidePreviewDialog(changes, None, file_name=str(test_file))
                dialog.set_config(config)
                dialog.quick_group.setChecked(True)  # 面板高亮展开
                dialog.exec()
                if dialog._config_apply_pending and dialog._config_to_apply:
                    self._on_preview_config_apply(dialog._config_to_apply)
                return
            
            # 有文件 + 有配置 → 正常流程
            if len(files) == 1:
                test_file = files[0]
                try:
                    text = test_file.read_text(encoding='utf-8')
                except Exception as e:
                    QMessageBox.warning(None, "错误", f"无法读取文件: {e}")
                    return
                previewer = FormulaPreviewer(config)
                try:
                    changes = previewer.preview(text, test_file)
                except Exception as e:
                    QMessageBox.warning(None, "错误", f"预检处理失败: {e}")
                    return
                if not changes:
                    QMessageBox.information(None, "预检结果", f"✅ 未检测到需要修改的内容。")
                    return
                dialog = SideBySidePreviewDialog(changes, None, file_name=str(test_file))
                dialog.set_config(config)
                dialog.exec()
                if dialog._config_apply_pending and dialog._config_to_apply:
                    self._on_preview_config_apply(dialog._config_to_apply)
                return
            
            # 多文件 → 批量摘要
            from .batch_preview import BatchPreviewDialog
            dialog = BatchPreviewDialog(files, config, None)
            dialog.exec()
            return
        
        # ============================================================
        # 入口1：右键菜单 — 严格校验，就地解决
        # ============================================================
        if not files:
            return  # 理论上不会走到这里
        
        test_file = files[0]
        try:
            text = test_file.read_text(encoding='utf-8')
        except Exception as e:
            QMessageBox.warning(None, "错误", f"无法读取文件: {e}")
            return
        
        previewer = FormulaPreviewer(config)
        try:
            changes = previewer.preview(text, test_file)
        except Exception as e:
            QMessageBox.warning(None, "错误", f"预检处理失败: {e}")
            return
        
        # 无配置 → 仍打开预览，面板高亮
        if not has_features:
            dialog = SideBySidePreviewDialog(changes, None, file_name=str(test_file))
            dialog.set_config(config)
            dialog.quick_group.setChecked(True)
            dialog.exec()
            if dialog._config_apply_pending and dialog._config_to_apply:
                self._on_preview_config_apply(dialog._config_to_apply)
            return
        
        # 无变更
        if not changes:
            QMessageBox.information(None, "预检结果", f"✅ 未检测到需要修改的内容。")
            return
        
        # 正常预览
        dialog = SideBySidePreviewDialog(changes, None, file_name=str(test_file))
        dialog.set_config(config)
        dialog.exec()
        if dialog._config_apply_pending and dialog._config_to_apply:
            self._on_preview_config_apply(dialog._config_to_apply)

    # ====== 高级设置 ======

    def _open_advanced_settings(self):
        dialog = AdvancedSettingsDialog(self.last_config.copy())
        if dialog.exec() == AdvancedSettingsDialog.DialogCode.Accepted:
            self.last_config = dialog.get_config()
            self._save_config()
            self._update_profile_hint()
            self.log("✅ 已更新修复配置", "INFO")

    def _update_profile_hint(self):
        """更新高级设置按钮文字（显示当前方案）"""
        matched = RepairProfile.match_config(self.last_config)
        
        if matched:
            self.advanced_btn.setText(f"🔧 高级设置 ({matched.name})")
        else:
            self.advanced_btn.setText("🔧 高级设置 (自定义)")

    def _has_any_feature_enabled(self, config: Dict[str, Any]) -> bool:
        """检查是否至少启用了一项修复功能"""
        fc = config.get('formula_config', {})
        return (
            config.get('clean_extra_newlines', False) or
            config.get('add_space_after_inline', False) or
            config.get('inline_to_display', False) or
            config.get('image_caption_enabled', False) or
            config.get('escape_isolated_dollars', False) or
            config.get('fix_encoding', False) or
            fc.get('subsup_fix', False) or
            fc.get('func_normalize', False) or
            fc.get('matrix_newline_remove', False) or
            fc.get('bracket_check', False) or
            fc.get('bm_to_vec', False) or
            fc.get('remove_size_commands', False) or
            fc.get('matrix_add_multiplication', False) or
            fc.get('dl_commands_to_text', False) or
            fc.get('markdown_escape_inline', False)
        )


    def _get_current_config(self) -> Dict[str, Any]:
        return self.last_config

    # ====== 公共接口 ======

    def set_progress_bar(self, progress_bar):
        self.progress_bar = progress_bar

    def set_log_panel(self, log_panel: LogPanel):
        self.log_panel = log_panel

    # ====== 文件操作 ======

    def _on_files_added(self, files: List[Path]):
        added = self.file_list.add_files(files)
        if added > 0:
            self.log(f"📁 添加了 {added} 个文件")

    def _add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            None, "选择Markdown文件", "",
            "Markdown文件 (*.md);;所有文件 (*.*)")
        if files:
            added = self.file_list.add_files([Path(f) for f in files])
            self.log(f"📁 添加了 {added} 个文件")

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(
            None, "选择包含Markdown文件的文件夹")
        if folder:
            folder_path = Path(folder)
            md_files = list(folder_path.rglob("*.md")) + list(folder_path.rglob("*.MD"))
            added = self.file_list.add_files(md_files)
            self.log(f"📁 从文件夹添加了 {added} 个文件")

    def _remove_selected(self):
        removed = self.file_list.remove_selected()
        if removed:
            self.log(f"🗑️ 移除了 {len(removed)} 个文件")

    def _clear_all(self):
        count = self.file_list.count()
        self.file_list.clear_all()
        if count > 0:
            self.log(f"🗑️ 已清空文件列表（共 {count} 个）")

    def _select_output_dir(self):
        directory = QFileDialog.getExistingDirectory(None, "选择输出目录")
        if directory:
            self.output_dir = Path(directory)
            self.output_dir_edit.setText(str(self.output_dir))

    def _on_output_dir_text_changed(self, text: str):
        text = text.strip()
        if text:
            path = Path(text)
            if path.exists() and path.is_dir():
                self.output_dir = path
                self.output_dir_edit.setStyleSheet("")
            else:
                self.output_dir_edit.setStyleSheet("border: 1px solid #e74c3c;")
        else:
            self.output_dir = None
            self.output_dir_edit.setStyleSheet("")

    # ====== 处理流程 ======

    def start_processing(self, files: List[Path] = None, **kwargs) -> bool:
        if self.force_reprocess_cb.isChecked():
            all_files = self.file_list.get_all_files()
            if not all_files:
                QMessageBox.warning(None, "警告", "请先添加文件")
                return False
            self.file_list.reset_all_status()
            files = self.file_list.get_all_files()
            self.log(f"🔄 强制重新处理模式：将重新处理全部 {len(files)} 个文件", "INFO")
        else:
            files = self.file_list.get_pending_files()
            if not files:
                all_files = self.file_list.get_all_files()
                if all_files:
                    failed_files = self.file_list.get_files_by_status(FileStatus.FAILED)
                    if failed_files:
                        reply = QMessageBox.question(
                            None, "提示",
                            f"有 {len(failed_files)} 个文件处理失败，是否重试？\n\n"
                            "提示：也可以勾选「忽略状态」来处理所有文件。",
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                        if reply == QMessageBox.StandardButton.Yes:
                            for f in failed_files:
                                self.file_list.update_status(f, FileStatus.PENDING)
                            files = failed_files
                        else:
                            return False
                    else:
                        QMessageBox.information(
                            None, "提示",
                            "所有文件都已处理完成！\n\n"
                            "如需重新处理，请勾选「忽略状态」选项。")
                        return False
                else:
                    QMessageBox.warning(None, "警告", "请先添加要处理的Markdown文件")
                    return False

        if self.output_dir_edit.text().strip() and not self.output_dir:
            QMessageBox.warning(None, "警告",
                "输出路径无效，请检查路径是否正确，或清空使用默认目录")
            return False

        # 高风险功能提醒
        fc = self.last_config.get('formula_config', {})
        high_risk = []
        if fc.get('bm_to_vec'):
            high_risk.append("\\bm→\\vec 转换")
        if self.last_config.get('inline_to_display'):
            high_risk.append("独立行内转块级")
        if self.last_config.get('image_caption_enabled'):
            high_risk.append("图片标题样式化")

        if high_risk:
            reply = QMessageBox.question(
                None, "⚠️ 高风险功能提醒",
                "以下高风险功能已启用：\n\n" +
                "\n".join(f"  • {f}" for f in high_risk) +
                "\n\n建议先用「右键 → 预检预览」查看变更。\n是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return False

        # 确认弹窗（少量文件时跳过）
        if len(files) >= 5:
            if self.rename_by_title_cb.isChecked():
                confirm_msg = (
                    f"即将处理 {len(files)} 个文件。\n\n"
                    "已启用「YAML标题重命名」功能：\n"
                    "• 程序将读取每个文件的YAML头部\n"
                    "• 提取title字段作为输出文件名\n"
                    "• 未找到标题的文件将使用原文件名\n\n"
                    "是否继续？"
                )
            else:
                confirm_msg = f"即将处理 {len(files)} 个文件，是否继续？"

            reply = QMessageBox.question(
                None, "确认", confirm_msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return False

        # 检查是否有功能启用
        if not self._has_any_feature_enabled(self.last_config):
            QMessageBox.information(
                None, "提示",
                "当前未启用任何修复功能，处理不会产生变更。\n\n"
                "请打开「高级设置」选择预设方案或勾选需要的功能。\n"
                "推荐选择「🟢 安全模式」预设方案一键启用常用功能。"
            )
            return False


        self._save_config()

        self.is_processing = True

        if self.progress_bar:
            self.progress_bar.setValue(0)

        output_mode = "custom" if self.output_dir else "source"
        config = self._get_current_config()

        self.log("=" * 60)
        self.log(f"开始批量处理 {len(files)} 个文件...")
        self.log(f"输出模式: {'统一目录' if output_mode == 'custom' else '跟随源文件'}")
        self.log(f"并行线程数: {self.worker_spin.value()}")
        self.log(f"YAML标题重命名: {'启用' if self.rename_by_title_cb.isChecked() else '禁用'}")
        self.log(f"高级设置: {self.advanced_btn.text()}")
        self.log("=" * 60)

        self.worker = RepairWorker(
            files=files,
            output_mode=output_mode,
            output_dir=self.output_dir,
            max_workers=self.worker_spin.value(),
            config=config,
            rename_by_title=self.rename_by_title_cb.isChecked(),
            auto_open=self.auto_open_cb.isChecked(),
        )

        self.worker.progress_updated.connect(self._on_progress_updated)
        self.worker.file_status_signal.connect(self._on_file_status_changed)
        self.worker.log_message.connect(self.log)
        self.worker.finished_all.connect(self._on_finished)

        self.worker.start()
        return True

    def stop_processing(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.log("正在停止处理...", "WARNING")

    def _on_progress_updated(self, value: int, message: str,
                             completed: int, total: int):
        if self.progress_bar:
            self.progress_bar.setValue(value)
        self.update_progress(value, message)

    def _on_file_status_changed(self, file_path: Path, status: str):
        status_map = {
            'pending': FileStatus.PENDING,
            'processing': FileStatus.PROCESSING,
            'success': FileStatus.SUCCESS,
            'failed': FileStatus.FAILED
        }
        self.file_list.update_status(
            file_path, status_map.get(status, FileStatus.PENDING))

    def _on_finished(self, results: list):
        self.is_processing = False

        if self.progress_bar:
            self.progress_bar.setValue(100)

        success_count = sum(1 for r in results if r['status'] == 'success')
        failed_count = len(results) - success_count

        self.log("")
        self.log("=" * 60)
        self.log(f"📊 处理完成！成功: {success_count}, 失败: {failed_count}",
                "SUCCESS" if failed_count == 0 else "WARNING")

        if self.rename_by_title_cb.isChecked() and success_count > 0:
            renamed_count = sum(1 for r in results if r.get('title_used'))
            if renamed_count > 0:
                self.log(f"📝 YAML标题重命名: {renamed_count} 个文件", "INFO")
                for r in results:
                    if r.get('title_used') and r['status'] == 'success':
                        self.log(
                            f"   {r.get('original_name', '')} → "
                            f"{r.get('new_name', '')}", "INFO")
            if success_count - renamed_count > 0:
                self.log(
                    f"ℹ️ {success_count - renamed_count} 个文件未找到YAML标题，使用原文件名",
                    "INFO")

        if failed_count > 0:
            self.log("失败列表:", "WARNING")
            for r in results:
                if r['status'] == 'failed':
                    self.log(f"  - {Path(r['file']).name}: {r.get('error', '未知错误')}",
                            "ERROR")
        self.log("=" * 60)

        self.update_progress(100, f"完成 - 成功: {success_count}, 失败: {failed_count}")

        if self.force_reprocess_cb.isChecked():
            self.force_reprocess_cb.setChecked(False)

        QMessageBox.information(
            None, "完成",
            f"处理任务已完成！\n\n✅ 成功: {success_count} 个\n❌ 失败: {failed_count} 个")


    def _on_preview_config_apply(self, config: Dict[str, Any]):
        """预览对话框请求更新配置
        
        将快速调整面板中的勾选状态写回 QSettings，
        并刷新主界面按钮状态。
        """
        self.last_config = config
        self._save_config()
        self._update_profile_hint()
        self.log("✅ 已从预览面板更新修复配置", "INFO")

# ==================== 元信息 ====================
__author__ = "YQJ"
__version__ = "4.6.0"
__date__ = "2026.05.09"