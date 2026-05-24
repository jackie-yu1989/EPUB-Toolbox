#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工作流模块 - PyQt6 UI 封装
支持五种自动处理流程
★ 新增：Word 排版预设支持
"""

import os
import sys
import time
import logging
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any
from threading import Event

# ★ 导入常量化配置键及工作流专用常量
from core.config_keys import SettingsDomain, MDRepairKey, WorkflowKey
from .constants import StepKey, ModeKey

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QRadioButton, QSpinBox, QCheckBox, QLineEdit,
    QFileDialog, QGridLayout, QMessageBox, QFrame, QComboBox,
    QButtonGroup
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QSettings

from core.base_module import BaseModule
from core.components import UnifiedFileListWidget, FileStatus, LogPanel
from core.theme_manager import ThemeManager
from core.components.file_list import DropHotzoneMixin
from .processor import run_repair_step, run_md2epub_step, run_epub2pdf_step, run_epub2docx_step
from modules.workflow.pipeline_state import resolve_source_file, make_pipeline_key

logger = logging.getLogger(__name__)


# ==================== 哨兵对象 ====================

_SKIP_SENTINEL = object()   # ★ 跳过标记（上游步骤失败）
_STOP_SENTINEL = object()   # ★ 结束信号（所有文件处理完毕）


# ==================== 工作流模式 ====================

WORKFLOW_MODES = {

    ModeKey.MD_TO_PDF: {
        'name': '（产出PDF） MD直转EPUB → 导出PDF',
        'icon': '📖➡📕',
        'steps': [StepKey.MD2EPUB, StepKey.EPUB2PDF],
        'desc': '输入Markdown → 转换EPUB电子书 → 导出PDF文档'
    },
    ModeKey.FULL_TO_PDF: {
        'name': '（产出PDF） 修复MD → 间转EPUB → 导出PDF',
        'icon': '📝➡📖➡📕',
        'steps': [StepKey.REPAIR, StepKey.MD2EPUB, StepKey.EPUB2PDF],
        'desc': '输入Markdown → 修复Markdown → 转换EPUB电子书 → 导出PDF文档'
    },
    ModeKey.MD_TO_DOCX: {
        'name': '（产出Word） MD直转EPUB → 导出Word',
        'icon': '📖➡📄',
        'steps': [StepKey.MD2EPUB, StepKey.EPUB2DOCX],
        'desc': '输入Markdown → 转换EPUB电子书 → 导出Word文档'
    },
    ModeKey.FULL_TO_DOCX: {
        'name': '（产出Word） 修复MD → 间转EPUB → 导出Word',
        'icon': '📝➡📖➡📄',
        'steps': [StepKey.REPAIR, StepKey.MD2EPUB, StepKey.EPUB2DOCX],
        'desc': '输入Markdown → 修复Markdown → 转换EPUB电子书 → 导出Word文档'
    },
    ModeKey.REPAIR_TO_EPUB: {
        'name': '（产出EPUB） 修复Markdown → 导出EPUB',
        'icon': '📝➡📖',
        'steps': [StepKey.REPAIR, StepKey.MD2EPUB],
        'desc': '输入Markdown → 修复Markdown → 转换EPUB电子书'
    }
}


# ==================== 工作线程 ====================

class WorkflowWorker(QThread):
    """工作流执行线程 - 流水线并行架构"""
    
    progress_updated = pyqtSignal(int, str, int, int)
    file_status_signal = pyqtSignal(Path, str)
    log_message = pyqtSignal(str, str)
    finished_all = pyqtSignal(list)
    step_state_changed = pyqtSignal(Path, str, dict)
    
    def __init__(
        self,
        files: List[Path],
        workflow_mode: str,
        output_dir: Optional[Path] = None,
        repair_config: Dict[str, Any] = None,
        epub_css: str = "",
        pdf_margins: Dict[str, int] = None,
        keep_intermediate: bool = True,
        auto_open: bool = False,
        rename_by_title: bool = False,
        max_workers: int = 4,
        use_yaml_title: bool = True,
        step_workers: Dict[str, int] = None,
        show_page_numbers: bool = False,
        docx_page_size: str = "a4",
        docx_fix_soft_breaks: bool = True,
        docx_preset: str = "book"      # ★ 新增：Word排版预设
    ):
        super().__init__()
        self.files = files
        self.workflow_mode = workflow_mode
        self.output_dir = output_dir
        self.repair_config = repair_config or {}
        self.epub_css = epub_css
        self.pdf_margins = pdf_margins or {}
        self.keep_intermediate = keep_intermediate
        self.auto_open = auto_open
        self._stop_event = Event()
        self.results = []
        self.max_workers = max_workers
        self.rename_by_title = rename_by_title
        self.use_yaml_title = use_yaml_title
        self.show_page_numbers = show_page_numbers
        self.step_workers = step_workers or {}
        
        # Word 转换参数
        self.docx_page_size = docx_page_size
        self.docx_fix_soft_breaks = docx_fix_soft_breaks
        self.docx_preset = docx_preset  # ★ 新增

        if rename_by_title:
            from modules.md_repair.processor import MarkdownTitleExtractor
            self.title_extractor = MarkdownTitleExtractor()
        else:
            self.title_extractor = None
    
    def stop(self):
        """优雅停止工作流"""
        self._stop_event.set()
        logger.debug("工作流收到停止信号")
    
    def run(self):
        from concurrent.futures import ThreadPoolExecutor
        from queue import Queue, Empty

        mode_info = WORKFLOW_MODES[self.workflow_mode]
        steps = mode_info['steps']
        total_files = len(self.files)

        self.log_message.emit(
            f"🚀 启动工作流: {mode_info['name']}", "INFO")
        self.log_message.emit(
            f"📊 {total_files} 个文件，{len(steps)} 个步骤，流水线并行处理", "INFO")

        start_total = time.time()

        # ====== 预处理：为所有文件预生成输出路径 ======
        all_output_paths = self._preprocess_output_paths(steps, total_files)

        # ====== 步骤函数定义 ======
        step_funcs = {
            StepKey.REPAIR: run_repair_step,
            StepKey.MD2EPUB: run_md2epub_step,
            StepKey.EPUB2PDF: run_epub2pdf_step,
            StepKey.EPUB2DOCX: run_epub2docx_step,
        }

        # ====== 流水线工作函数 ======
        def step_worker(step_name, input_queue, output_queue, step_func):
            """单个步骤的工作线程"""
            while not self._stop_event.is_set():
                try:
                    item = input_queue.get(timeout=0.5)
                except Empty:
                    continue

                if item is _STOP_SENTINEL:
                    output_queue.put(_STOP_SENTINEL)
                    break

                if item is _SKIP_SENTINEL:
                    output_queue.put(_SKIP_SENTINEL)
                    continue

                file_idx, file_result, current_file, out_dir = item

                if current_file is None:
                    output_queue.put(_SKIP_SENTINEL)
                    continue

                original_file = Path(file_result['file'])

                self.step_state_changed.emit(original_file, step_name,
                    {"status": "processing", "progress": 0})

                self.log_message.emit(
                    f"  [{step_name}] {Path(current_file).name}", "INFO")

                output_path = all_output_paths.get(file_idx, {}).get(step_name)
                log_cb = lambda m: self.log_message.emit(f"     {m}", "INFO")

                if output_path:
                    output_path.parent.mkdir(parents=True, exist_ok=True)

                try:
                    if step_name == StepKey.REPAIR:
                        kwargs = {'config': self.repair_config, 'log_callback': log_cb}
                        if output_path:
                            kwargs['output_filename'] = output_path.name
                        success, msg, output = step_func(current_file, out_dir, **kwargs)

                    elif step_name == StepKey.MD2EPUB:
                        kwargs = {'css': self.epub_css, 'log_callback': log_cb}
                        if output_path:
                            kwargs['output_epub'] = output_path
                        kwargs['use_yaml_title'] = self.use_yaml_title
                        success, msg, output = step_func(current_file, out_dir, **kwargs)

                    elif step_name == StepKey.EPUB2PDF:
                        kwargs = {'margins': self.pdf_margins, 'log_callback': log_cb}
                        if output_path:
                            kwargs['output_pdf'] = output_path
                        if self.show_page_numbers:
                            kwargs['show_page_numbers'] = True
                        success, msg, output = step_func(current_file, out_dir, **kwargs)

                    elif step_name == StepKey.EPUB2DOCX:
                        kwargs = {
                            'page_size': self.docx_page_size,
                            'fix_soft_breaks': self.docx_fix_soft_breaks,
                            'font_preset': self.docx_preset,  # ★ 传递排版预设
                            'log_callback': log_cb
                        }
                        if output_path:
                            kwargs['output_docx'] = output_path
                        success, msg, output = step_func(current_file, out_dir, **kwargs)

                    else:
                        continue
                except Exception as e:
                    success, msg, output = False, str(e), None
                    logger.error(f"步骤 {step_name} 异常: {e}")

                if success and output:
                    file_result['outputs'][step_name] = str(output)
                    
                    self.step_state_changed.emit(original_file, step_name,
                        {"status": "completed", "output_path": str(output), "elapsed": 0})
                    
                    if not hasattr(self, '_running_results'):
                        self._running_results = []
                    existing = [r for r in self._running_results if r['file'] == file_result['file']]
                    if existing:
                        existing[0]['outputs'][step_name] = str(output)
                    else:
                        self._running_results.append({
                            'file': file_result['file'],
                            'status': 'success',
                            'outputs': {step_name: str(output)}
                        })
                     
                    output_queue.put((file_idx, file_result, output, out_dir))

                else:
                    file_result['status'] = 'failed'
                    file_result['error'] = msg
                    self.file_status_signal.emit(Path(file_result['file']), 'failed')
                    self.step_state_changed.emit(original_file, step_name,
                        {"status": "failed", "error_message": msg, "elapsed": 0})             
                              
                    output_queue.put(_SKIP_SENTINEL)

        # ====== 创建队列 ======
        queues = [Queue(maxsize=total_files + 1) for _ in range(len(steps) + 1)]

        # 启动每个步骤的工作线程池
        all_futures = []

        total_worker_count = sum(
            self.step_workers.get(step, min(total_files, self.max_workers))
            for step in steps
        )
        executor_max = max(total_worker_count, self.max_workers)
        with ThreadPoolExecutor(max_workers=executor_max) as executor:

            for i, step_name in enumerate(steps):
                step_count = self.step_workers.get(step_name, min(total_files, self.max_workers))
                for _ in range(step_count):
                    future = executor.submit(
                        step_worker, step_name, queues[i], queues[i + 1], step_funcs[step_name]
                    )
                    all_futures.append(future)

            # 将所有文件推入第一个队列
            for file_idx, md_file in enumerate(self.files):
                if self._stop_event.is_set():
                    break

                self.file_status_signal.emit(md_file, 'processing')
                source_dir = md_file.parent
                source_dir.mkdir(parents=True, exist_ok=True)

                if self.output_dir:
                    self.output_dir.mkdir(parents=True, exist_ok=True)

                file_result = {
                    'file': str(md_file),
                    'status': 'success',
                    'outputs': {}
                }

                queues[0].put((file_idx, file_result, md_file, source_dir))

                progress = int((file_idx / total_files) * 33)
                self.progress_updated.emit(
                    progress, f"准备中... {file_idx + 1}/{total_files}",
                    file_idx, total_files)

            # ====== 收集最终结果 ======
            completed = 0
            final_queue = queues[-1]
            total_to_collect = total_files

            while completed < total_to_collect and not self._stop_event.is_set():
                try:
                    item = final_queue.get(timeout=1.0)
                except Empty:
                    self.progress_updated.emit(
                        50 + int((completed / max(total_files, 1)) * 50),
                        f"处理中... {completed}/{total_files}",
                        completed, total_files)
                    continue

                if item is _SKIP_SENTINEL:
                    total_to_collect -= 1
                    continue

                if item is _STOP_SENTINEL:
                    continue

                file_idx, file_result, final_output, out_dir = item
                self.results.append(file_result)

                if file_result['status'] == 'success':
                    self.file_status_signal.emit(
                        Path(file_result['file']), 'success')
                    completed += 1
                    final_output_name = Path(final_output).name if final_output else "未知"
                    self.log_message.emit(
                        f"✅ [{completed}/{total_files}] "
                        f"{Path(file_result['file']).name} → {final_output_name}",
                        "SUCCESS")
                else:
                    completed += 1

                progress = 50 + int((completed / max(total_files, 1)) * 50)
                self.progress_updated.emit(
                    progress,
                    f"处理中... {completed}/{total_files}",
                    completed, total_files)

            self._stop_event.set()

            for future in all_futures:
                try:
                    future.result(timeout=5)
                except Exception:
                    pass

        # ====== 清理中间产物 ======
        self._clean_intermediates(steps, all_output_paths)

        total_time = time.time() - start_total

        success_count = sum(1 for r in self.results if r['status'] == 'success')
        self.log_message.emit(
            f"\n{'='*50}\n⏱️ 流水线完成，耗时: {total_time:.1f}秒\n"
            f"   成功: {success_count}/{total_files}\n{'='*50}",
            "SUCCESS" if success_count == total_files else "WARNING")

        if self.auto_open:
            if self.output_dir:
                self._open_folder(self.output_dir)
            else:
                opened = set()
                for r in self.results:
                    if r['status'] == 'success':
                        outputs = r.get('outputs', {})
                        if outputs:
                            last_output = list(outputs.values())[-1]
                            p = Path(last_output)
                            if p.exists() and p.parent not in opened:
                                self._open_folder(p.parent)
                                opened.add(p.parent)

        self.progress_updated.emit(100, "工作流完成", success_count, total_files)
        self.finished_all.emit(self.results)
    
    def _preprocess_output_paths(self, steps: List[str], total_files: int) -> Dict[int, Dict[str, Path]]:
        """预处理所有文件的输出路径"""
        all_output_paths = {}
        
        for file_idx, md_file in enumerate(self.files):
            source_dir = md_file.parent
            source_dir.mkdir(parents=True, exist_ok=True)
            
            final_dir = self.output_dir or source_dir
            if self.output_dir:
                final_dir.mkdir(parents=True, exist_ok=True)
            
            file_paths = {}
            
            if self.rename_by_title and self.title_extractor:
                base_name, title_used, extracted_title = self.title_extractor.generate_name(
                    md_file, source_dir
                )
                clean_base = (
                    base_name.replace('.md', '').replace('_fixed', '')
                    if title_used else md_file.stem
                )
                if title_used:
                    self.log_message.emit(
                        f"📝 YAML标题: {extracted_title} → {clean_base}", "INFO")
            else:
                clean_base = md_file.stem
            
            for i, step_name in enumerate(steps):
                is_final = (i == len(steps) - 1)
                
                if step_name == StepKey.REPAIR:
                    file_paths[StepKey.REPAIR] = source_dir / f"{clean_base}_fixed.md"
                elif step_name == StepKey.MD2EPUB:
                    file_paths[StepKey.MD2EPUB] = (
                        final_dir if is_final else source_dir
                    ) / f"{clean_base}.epub"
                elif step_name == StepKey.EPUB2PDF:
                    file_paths[StepKey.EPUB2PDF] = final_dir / f"{clean_base}.pdf"
                elif step_name == StepKey.EPUB2DOCX:
                    file_paths[StepKey.EPUB2DOCX] = final_dir / f"{clean_base}.docx"
            
            all_output_paths[file_idx] = file_paths
        
        return all_output_paths
    
    def _clean_intermediates(self, steps: List[str], all_output_paths: Dict[int, Dict[str, Path]]):
        """清理中间产物"""
        if self.keep_intermediate:
            return
        
        if len(steps) <= 1:
            return
        
        intermediates = steps[:-1]
        
        for file_idx in all_output_paths:
            for step in intermediates:
                output_path = all_output_paths[file_idx].get(step)
                if output_path and output_path.exists():
                    try:
                        output_path.unlink()
                        self.log_message.emit(
                            f"🗑️ 已清理中间文件: {output_path.name}", "INFO")
                    except Exception as e:
                        logger.debug(f"清理中间文件失败: {output_path} - {e}")
    
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

class WorkflowModule(BaseModule):
    """工作流模块 - 自动编排处理流程"""
    
    @property
    def module_id(self) -> str:
        return "workflow"
    
    @property
    def module_name(self) -> str:
        return "0-组合工作流"
    
    @property
    def module_icon(self) -> str:
        return "🔄"
    
    @property
    def module_description(self) -> str:
        return (
            "5种工作流模式，流水线并行。"
            "📊 监视面板：实时追踪、行独立配置、步骤回滚。"
        )
    
    @property
    def accepted_extensions(self) -> List[str]:
        return ['.md']
    
    def on_activate(self):
        """模块被激活时刷新 MD 修复设置按钮状态 + 加载配置"""
        self._load_config()
        self._update_repair_hint()
    
    def on_deactivate(self):
        """模块失去焦点时保存配置"""
        self._save_config()
        if getattr(self, 'is_processing', False):
            self.stop_processing()
    
    def check_dependencies(self) -> Tuple[bool, str]:
        """检查三个步骤的依赖"""
        from core.utils import check_pandoc, check_calibre
        
        messages = []
        all_ok = True
        
        messages.append("✅ MD公式修复: 就绪（纯Python）")
        
        pandoc_ok, pandoc_msg = check_pandoc()
        if pandoc_ok:
            messages.append(f"✅ MD转EPUB: {pandoc_msg}")
        else:
            messages.append(f"⚠️ MD转EPUB: {pandoc_msg}")
            all_ok = False
        
        calibre_ok, calibre_msg = check_calibre()
        if calibre_ok:
            messages.append(f"✅ EPUB转PDF: {calibre_msg}")
        else:
            messages.append(f"⚠️ EPUB转PDF: {calibre_msg}")
            all_ok = False
        
        return all_ok, "\n".join(messages)
    
    def create_ui(self, parent=None) -> QWidget:
        """创建模块 UI"""
        self.settings = QSettings(SettingsDomain.EPUB_TOOLBOX, SettingsDomain.WORKFLOW)
        
        widget = QWidget(parent)

        layout = QVBoxLayout(widget)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # ---- 文件列表 ----
        layout.addWidget(self._create_file_section())
        
        # ---- 输出设置 ----
        layout.addWidget(self._create_output_section())
        
        # ---- 田字形设置面板 ----
        layout.addWidget(self._create_grid_settings())
        
        layout.addStretch()
        
        # 状态变量
        self.output_dir: Optional[Path] = None
        self.worker: Optional[WorkflowWorker] = None
        self.all_results = []
        self.progress_bar = None
        self.log_panel = None

        # 统一流水线状态
        self.pipeline_states: Dict[str, dict] = {}
        self.panel_log_cache: List[tuple] = []
        self._pipeline_total_steps = 0
        self._pipeline_completed_steps = 0
        self._pipeline_completed_files = 0
        self._pipeline_start_time = 0.0
        
        self._update_repair_hint()

        return widget

    def _create_file_section(self) -> QGroupBox:
        """创建文件列表区域"""
        file_group = QGroupBox()
        file_layout = QVBoxLayout(file_group)

        # 自定义标题栏：标题 + 监视面板按钮
        title_widget = QWidget()
        title_layout = QHBoxLayout(title_widget)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(10)

        title_label = QLabel("📁 选择Markdown文件 (支持拖拽，Ctrl+V)")
        title_label.setStyleSheet("font-weight: bold;")
        title_layout.addWidget(title_label)
        title_layout.addStretch()

        # 监视面板按钮
        self.monitor_btn = QPushButton("📊 监视面板")
        self.monitor_btn.setToolTip(
            "打开可视化流水线监视面板\n\n"
            "功能：\n"
            "• 每个文件一行，显示各步骤状态条\n"
            "• 每行可独立设置修复配置\n"
            "• 预览中间产物、回滚步骤\n"
            "• 总体进度 + 预估剩余时间"
        )
        self.monitor_btn.setStyleSheet("""
            QPushButton {
                padding: 5px 12px;
                background-color: #2ecc71;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #27ae60;
            }
        """)
        self.monitor_btn.clicked.connect(self._open_monitor_panel)
        title_layout.addWidget(self.monitor_btn)

        file_layout.addWidget(title_widget)

        self.file_list = UnifiedFileListWidget(['.md'])
        self.file_list.files_added.connect(self._on_files_added)
        file_layout.addWidget(self.file_list)

        # 按钮行
        btn_layout = QHBoxLayout()
        add_file_btn = QPushButton("➕ 添加文件")
        add_file_btn.clicked.connect(self._add_files)
        add_folder_btn = QPushButton("📂 添加文件夹")
        add_folder_btn.clicked.connect(self._add_folder)
        remove_btn = QPushButton("❌ 移除选中")
        remove_btn.clicked.connect(self._remove_selected)
        clear_btn = QPushButton("🗑️ 清空全部")
        clear_btn.clicked.connect(self._clear_all)

        self.force_reprocess_cb = QCheckBox("忽略状态")
        self.force_reprocess_cb.setToolTip(
            "默认情况下，已经处理过的文件不会再次处理。\n"
            "勾选此项后，将重新处理列表中的所有文件。")

        btn_layout.addWidget(add_file_btn)
        btn_layout.addWidget(add_folder_btn)
        btn_layout.addWidget(remove_btn)
        btn_layout.addWidget(clear_btn)
        btn_layout.addWidget(self.force_reprocess_cb)
        btn_layout.addStretch()
        file_layout.addLayout(btn_layout)

        DropHotzoneMixin.install(file_group, self.file_list, self.accepted_extensions)

        return file_group
    
    def _create_output_section(self) -> QGroupBox:
        """创建输出设置区域"""
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
    
    def _create_grid_settings(self) -> QWidget:
        """创建设置面板 - 三列布局（工作流模式移至底部，与右侧列对齐）"""
        grid_widget = QWidget()
        grid_layout = QGridLayout(grid_widget)
        grid_layout.setSpacing(10)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        
        # ===== 顶部区域：设置组 =====
        
        # 左列：分步并行设置
        exec_section = self._create_execution_section()
        
        # ★ 中间列：MD修复设置（上） + 目标文件设置（下）
        middle_widget = QWidget()
        middle_layout = QVBoxLayout(middle_widget)
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.setSpacing(10)
        middle_layout.addWidget(self._create_repair_section())      # ★ 上：MD修复设置
        middle_layout.addWidget(self._create_target_file_section()) # ★ 下：目标文件设置
        middle_layout.addStretch()
        
        # 右列：EPUB设置 → Word设置 → PDF设置
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)
        right_layout.addWidget(self._create_epub_section())
        right_layout.addWidget(self._create_docx_section())
        right_layout.addWidget(self._create_pdf_section())
        right_layout.addStretch()
        
        # ===== 底部区域：工作流模式 =====
        mode_section = self._create_mode_section()
        
        # 布局
        grid_layout.addWidget(exec_section, 0, 0, 1, 1)
        grid_layout.addWidget(middle_widget, 0, 1, 1, 1)
        grid_layout.addWidget(right_widget, 0, 2, 2, 1)   # 右列横跨2行
        grid_layout.addWidget(mode_section, 1, 0, 1, 2)   # 工作流模式横跨左+中
        
        # 列拉伸比例
        grid_layout.setColumnStretch(0, 1)
        grid_layout.setColumnStretch(1, 1)
        grid_layout.setColumnStretch(2, 1)
        
        # 行拉伸比例
        grid_layout.setRowStretch(0, 1)  # 设置区域行（可拉伸）
        grid_layout.setRowStretch(1, 0)  # 工作流模式行（不拉伸）
        
        return grid_widget

    def _create_target_file_section(self) -> QGroupBox:
        """创建目标文件设置区域"""
        target_group = QGroupBox("🎯 目标文件设置")
        target_layout = QVBoxLayout(target_group)
        target_layout.setSpacing(6)
        
        self.rename_by_title_cb = QCheckBox("使用YAML标题重命名")
        self.rename_by_title_cb.setToolTip(
            "提取Markdown文件YAML头部的title字段作为输出文件名\n"
            "所有输出文件（_fixed.md / .epub / .pdf）都将使用提取的标题命名\n"
            "未找到标题时使用原文件名")
        target_layout.addWidget(self.rename_by_title_cb)
        
        self.keep_intermediate_cb = QCheckBox("保留中间文件")
        self.keep_intermediate_cb.setChecked(True)
        self.keep_intermediate_cb.setToolTip(
            "保留公式修复后的 _fixed.md 和 EPUB 文件\n"
            "取消勾选则工作流完成后自动清理")
        target_layout.addWidget(self.keep_intermediate_cb)
        
        self.auto_open_cb = QCheckBox("完成后打开目录")
        self.auto_open_cb.setToolTip("工作流完成后自动打开输出文件夹")
        target_layout.addWidget(self.auto_open_cb)
        
        return target_group

    def _create_mode_section(self) -> QGroupBox:
        """创建工作流模式选择区域"""
        mode_group = QGroupBox("📋 工作流模式")
        mode_layout = QVBoxLayout(mode_group)
        mode_layout.setSpacing(6)

        self.mode_group = QButtonGroup()
        self.mode_buttons = {}

        modes_data = [
            (ModeKey.MD_TO_PDF, '生成 PDF ：📕-📖-⭕ ||', '直转 EPUB 后，导出为 PDF'),
            (ModeKey.FULL_TO_PDF, '生成 PDF ：📕-📖-📝 ||', '修复 MD，间转 EPUB，导出 PDF'),
            (ModeKey.MD_TO_DOCX, '生成Word：📄-📖-⭕ ||', '直转 EPUB 后，导出为 Word'),
            (ModeKey.FULL_TO_DOCX, '生成Word：📄-📖-📝 ||', '修复 MD，间转 EPUB，导出 Word'),
            (ModeKey.REPAIR_TO_EPUB, '生成EPUB：📖-📝-⭕ ||', '修复 Markdown 后，导出为 EPUB'),
        ]

        for mode_key, label_text, help_text in modes_data:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 2, 0, 2)
            row_layout.setSpacing(6)

            rb = QRadioButton(label_text)
            rb.setToolTip(WORKFLOW_MODES[mode_key]['desc'])
            self.mode_group.addButton(rb)
            self.mode_buttons[mode_key] = rb
            row_layout.addWidget(rb)

            desc_label = QLabel(f"<span style='color:#888; font-size:10px;'>{help_text}</span>")
            row_layout.addWidget(desc_label, 1)

            mode_layout.addWidget(row)

        self.mode_buttons[ModeKey.REPAIR_TO_EPUB].setChecked(True)

        return mode_group
     
    def _create_epub_section(self) -> QGroupBox:
        """创建 EPUB 设置区域"""
        epub_group = QGroupBox("📖 EPUB 设置")
        epub_layout = QVBoxLayout(epub_group)
        epub_layout.setSpacing(6)
        
        css_row = QHBoxLayout()

        from core.css_manager import CssManager
        css_manager = CssManager()
        styles = css_manager.discover_styles()

        self.css_buttons = {}
        default_found = False
        for i, style_info in enumerate(styles):
            rb = QRadioButton(style_info.name)
            rb.setToolTip(style_info.description)
            if style_info.is_default and not default_found:
                rb.setChecked(True)
                default_found = True
            elif i == 0 and not default_found:
                rb.setChecked(True)
                default_found = True
            self.css_buttons[style_info.key] = rb
            css_row.addWidget(rb)

        css_row.addStretch()
        epub_layout.addLayout(css_row)
        
        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("主题:"))
        self.color_combo = QComboBox()
        self.color_combo.setFixedWidth(100)
        
        tm = ThemeManager()
        self.color_presets = tm.get_color_presets()
        for color_key, color_info in self.color_presets.items():
            self.color_combo.addItem(color_info['name'], color_key)
        self.color_combo.setCurrentIndex(0)
        color_row.addWidget(self.color_combo)
        color_row.addStretch()
        epub_layout.addLayout(color_row)

        self.use_yaml_title_cb = QCheckBox("YAML标题作为内部标题")
        self.use_yaml_title_cb.setChecked(True)
        self.use_yaml_title_cb.setToolTip(
            "勾选后，提取YAML的title字段作为EPUB内部标题（书籍元数据和正文开头）。\n"
            "取消勾选则使用文件名作为标题。"
        )
        epub_layout.addWidget(self.use_yaml_title_cb)        
        
        return epub_group
    
    def _create_pdf_section(self) -> QGroupBox:
        """创建 PDF 设置区域"""
        pdf_group = QGroupBox("📕 PDF 设置")
        pdf_layout = QVBoxLayout(pdf_group)
        pdf_layout.setSpacing(6)
        
        from modules.epub2pdf.processor import PRESETS
        self.pdf_preset_group = QButtonGroup()
        
        preset_row = QHBoxLayout()
        preset_row.setSpacing(10)
        
        preset_names = {"1": "极限紧凑", "2": "左右紧凑", "3": "上下紧凑", "4": "对称装订"}
        
        for key in ["1", "2", "3", "4"]:
            preset = PRESETS[key]
            name = preset_names.get(key, preset['name'])
            rb = QRadioButton(name)
            rb.setToolTip(
                f"上边距: {preset['top']}pt  下边距: {preset['bottom']}pt\n"
                f"左边距: {preset['left']}pt  右边距: {preset['right']}pt\n"
                f"字号: {preset.get('font_size', 12)}pt")
            rb.setProperty("preset_key", key)
            self.pdf_preset_group.addButton(rb)
            preset_row.addWidget(rb)
            if key == "1":
                rb.setChecked(True)
        
        preset_row.addStretch()
        pdf_layout.addLayout(preset_row)
        
        # 显示页码
        self.workflow_show_page_numbers_cb = QCheckBox("显示页码在PDF页面底部")
        self.workflow_show_page_numbers_cb.setToolTip(
            "在PDF页面底部显示页码\n"
            "勾选后，每个PDF文件将包含页码"
        )
        pdf_layout.addWidget(self.workflow_show_page_numbers_cb)
        
        return pdf_group

    def _create_docx_section(self) -> QGroupBox:
        """创建 Word 设置区域（含排版预设）"""
        docx_group = QGroupBox("📄 Word 设置")
        docx_layout = QVBoxLayout(docx_group)
        docx_layout.setSpacing(8)
        docx_layout.setContentsMargins(10, 12, 10, 12)
        
        # 1. 页面尺寸单选组
        page_size_layout = QHBoxLayout()
        page_size_layout.setContentsMargins(0, 0, 0, 0)
        page_size_layout.setSpacing(10)
        
        page_size_label = QLabel("页面尺寸:")
        page_size_label.setFixedWidth(65)
        page_size_layout.addWidget(page_size_label)
        
        self.docx_page_size_group = QButtonGroup()
        sizes = [("A4", "a4"), ("Letter", "letter"), ("B5", "b5"), ("A5", "a5")]
        for text, key in sizes:
            btn = QRadioButton(text)
            btn.setProperty("size_key", key)
            btn.setToolTip(f"输出 Word 页面尺寸：{text}")
            self.docx_page_size_group.addButton(btn)
            page_size_layout.addWidget(btn)
            if key == "a4":
                btn.setChecked(True)
        
        page_size_layout.addStretch()
        docx_layout.addLayout(page_size_layout)
        
        # 2. ★ 排版预设
        preset_layout = QHBoxLayout()
        preset_layout.setContentsMargins(0, 5, 0, 5)
        preset_layout.setSpacing(10)
        
        preset_label = QLabel("排版预设:")
        preset_label.setFixedWidth(65)
        preset_layout.addWidget(preset_label)
        
        self.docx_preset_combo = QComboBox()
        self.docx_preset_combo.setMinimumWidth(200)
        self.docx_preset_combo.setToolTip(
            "选择输出 Word 文档的排版样式\n\n"
            "📖 书籍排版\n"
            "  正文：宋体 12pt（小四），1.5倍行距\n"
            "  标题：楷体，一级标题：14pt（四号）\n"
            "  英文：Times New Roman\n\n"
            "📚 学术论文\n"
            "  正文：宋体 10.5pt（五号），1.5倍行距\n"
            "  标题：黑体，一级标题：14pt（四号）\n"
            "  英文：Times New Roman\n\n"
            "🔧 技术文档\n"
            "  正文：宋体 9.5pt（小五），1.25倍行距\n"
            "  标题：黑体，一级标题：12pt（小四）\n"
            "  代码/英文：Consolas\n\n"
            "💼 商务报告\n"
            "  正文：微软雅黑 10.5pt（五号），1.25倍行距\n"
            "  标题：微软雅黑，一级标题：14pt（四号）\n"
            "  英文：Arial\n\n"
            "⏸️ 保留原样\n"
            "  保留 Calibre 原始样式"
        )
        
        # 添加预设选项
        self.docx_preset_combo.addItem("📖 书籍排版 (楷体标题，正文宋体)", "book")
        self.docx_preset_combo.addItem("📚 学术论文 (黑体标题，正文宋体)", "academic")
        self.docx_preset_combo.addItem("🔧 技术文档 (等宽字体，适合代码)", "technical")
        self.docx_preset_combo.addItem("💼 商务报告 (微软雅黑 - Arial)", "business")
        self.docx_preset_combo.addItem("⏸️ 保留原样 (Calibre - Iowan Old Style)", "none")
        
        self.docx_preset_combo.setCurrentIndex(0)
        preset_layout.addWidget(self.docx_preset_combo)
        preset_layout.addStretch()
        docx_layout.addLayout(preset_layout)
        
        # 3. 软回车修复复选框
        self.docx_fix_soft_breaks_cb = QCheckBox("✨ 自动修复软回车 (↓ → ¶)")
        self.docx_fix_soft_breaks_cb.setChecked(True)
        self.docx_fix_soft_breaks_cb.setToolTip(
            "转换后自动将 Word 软回车(<w:br>)拆分为标准硬段落(<w:p>)，\n"
            "彻底解决段落破碎、无法统一调整格式的问题。"
        )
        docx_layout.addWidget(self.docx_fix_soft_breaks_cb)
        
        return docx_group
    
    def _create_repair_section(self) -> QGroupBox:
        """创建 MD 修复设置区域"""
        repair_group = QGroupBox("📝 MD 修复设置")
        repair_layout = QVBoxLayout(repair_group)
        
        self.repair_config_btn = QPushButton("🔧 公式修复")
        self.repair_config_btn.setFixedWidth(200)
        self.repair_config_btn.setToolTip(
            "打开MD公式修复的高级设置\n"
            "可选择预设方案或自定义每个修复功能的开关\n"
            "修改后自动保存，供工作流使用")
        self.repair_config_btn.clicked.connect(self._open_repair_settings)
        repair_layout.addWidget(self.repair_config_btn)
        repair_layout.addStretch()
        
        return repair_group
    
    def _create_execution_section(self) -> QGroupBox:
        """创建分步并行设置区域"""
        exec_group = QGroupBox("⚙️ 分步并行设置")
        exec_layout = QVBoxLayout(exec_group)
        exec_layout.setSpacing(6)
        
        cpu_count = os.cpu_count() or 4
        default_workers = min(4, cpu_count)
        
        # 每步骤并行数
        workers_layout = QGridLayout()
        workers_layout.setSpacing(4)
        
        step_defaults = {
            StepKey.REPAIR: min(2, cpu_count),
            StepKey.MD2EPUB: default_workers,
            StepKey.EPUB2PDF: default_workers,
            StepKey.EPUB2DOCX: default_workers,
        }
        
        step_labels = {
            StepKey.REPAIR: "📝 MD公式修复",
            StepKey.MD2EPUB: "📖 MD转EPUB",
            StepKey.EPUB2DOCX: "📄 EPUB转Word",
            StepKey.EPUB2PDF: "📕 EPUB转PDF",
        }
        
        self.step_spins = {}
        for i, (step_key, label) in enumerate(step_labels.items()):
            workers_layout.addWidget(QLabel(f"{label}:"), i, 0)
            
            spin = QSpinBox()
            spin.setMinimum(1)
            spin.setMaximum(10)
            spin.setValue(step_defaults[step_key])
            spin.setFixedWidth(60)
            spin.setToolTip(
                "CPU密集型，建议较少" if step_key == StepKey.REPAIR
                else "子进程等待，可适当多开"
            )
            self.step_spins[step_key] = spin
            workers_layout.addWidget(spin, i, 1)
        
        exec_layout.addLayout(workers_layout)
        
        return exec_group
    
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
            self.log(f"🗑️ 清空了 {count} 个文件")
    
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
    
    # ====== 配置获取 ======
    
    def _get_selected_mode(self) -> str:
        for mode_key, rb in self.mode_buttons.items():
            if rb.isChecked():
                return mode_key
        return ModeKey.FULL_TO_PDF
    
    def _get_epub_css(self) -> str:
        tm = ThemeManager()
        color_key = self.color_combo.currentData()
        color_info = self.color_presets.get(color_key, {})
        primary_color = color_info.get('color', None)
        
        style_key = self._get_selected_css_style()
        return tm.get_css_with_color(style_key, primary_color)
    
    def _get_pdf_margins(self) -> Dict[str, int]:
        from modules.epub2pdf.processor import PRESETS
        
        checked = self.pdf_preset_group.checkedButton()
        if checked:
            preset_key = checked.property("preset_key")
            if preset_key and preset_key in PRESETS:
                preset = PRESETS[preset_key]
                return {
                    'top': preset['top'],
                    'bottom': preset['bottom'],
                    'left': preset['left'],
                    'right': preset['right'],
                    'font_size': preset.get('font_size', 12)
                }
        
        return {'top': 0, 'bottom': 0, 'left': 0, 'right': 0, 'font_size': 12}
    
    def _get_docx_page_size(self) -> str:
        """获取 Word 页面尺寸"""
        btn = self.docx_page_size_group.checkedButton()
        if btn:
            return btn.property("size_key")
        return "a4"
    
    def _get_repair_config(self) -> Dict[str, Any]:
        """从 QSettings 读取 MD 修复配置"""
        settings = QSettings(SettingsDomain.EPUB_TOOLBOX, SettingsDomain.MD_REPAIR)
        saved = settings.value(MDRepairKey.CONFIG_V4)
        
        if saved and isinstance(saved, dict):
            if MDRepairKey.FORMULA_CONFIG not in saved:
                from modules.md_repair.processor import ConfigurableFormulaFixer
                saved[MDRepairKey.FORMULA_CONFIG] = ConfigurableFormulaFixer.get_default_config()
            return saved
        
        from modules.md_repair.processor import DEFAULT_REPAIR_CONFIG
        import copy
        return copy.deepcopy(DEFAULT_REPAIR_CONFIG)
    
    def _open_repair_settings(self):
        """打开 MD 修复高级设置弹窗"""
        try:
            from modules.md_repair.dialogs import AdvancedSettingsDialog
        except ImportError:
            QMessageBox.warning(None, "错误", "无法加载MD修复设置对话框")
            return
        
        current_config = self._get_repair_config()
        dialog = AdvancedSettingsDialog(current_config)
        
        if dialog.exec() == AdvancedSettingsDialog.DialogCode.Accepted:
            new_config = dialog.get_config()
            settings = QSettings(SettingsDomain.EPUB_TOOLBOX, SettingsDomain.MD_REPAIR)
            settings.setValue(MDRepairKey.CONFIG_V4, new_config)
            self._update_repair_hint()
            self.log("✅ 已更新MD修复配置", "INFO")
    
    def _update_repair_hint(self):
        """更新MD修复配置按钮文字（显示当前方案）"""
        try:
            from modules.md_repair.processor import RepairProfile
            
            config = self._get_repair_config()
            matched = RepairProfile.match_config(config)
            
            if matched:
                self.repair_config_btn.setText(f"🔧 公式修复 ({matched.name})")
            else:
                self.repair_config_btn.setText("🔧 公式修复 (自定义)")
        except Exception:
            self.repair_config_btn.setText("🔧 公式修复")
    
    # ==================== 配置持久化 ====================
    
    def get_config(self) -> dict:
        """收集 UI 上的所有设置"""
        return {
            WorkflowKey.MODE: self._get_selected_mode(),
            WorkflowKey.STEP_WORKERS: {
                StepKey.REPAIR: self.step_spins[StepKey.REPAIR].value(),
                StepKey.MD2EPUB: self.step_spins[StepKey.MD2EPUB].value(),
                StepKey.EPUB2PDF: self.step_spins[StepKey.EPUB2PDF].value(),
                StepKey.EPUB2DOCX: self.step_spins[StepKey.EPUB2DOCX].value(),
            },
            WorkflowKey.RENAME_BY_TITLE: self.rename_by_title_cb.isChecked(),
            WorkflowKey.USE_YAML_TITLE: self.use_yaml_title_cb.isChecked(),
            WorkflowKey.KEEP_INTERMEDIATE: self.keep_intermediate_cb.isChecked(),
            WorkflowKey.AUTO_OPEN: self.auto_open_cb.isChecked(),
            WorkflowKey.SHOW_PAGE_NUMBERS: self.workflow_show_page_numbers_cb.isChecked(),
            WorkflowKey.OUTPUT_DIR: str(self.output_dir) if self.output_dir else None,
            WorkflowKey.EPUB_CSS_STYLE: self._get_selected_css_style(),
            WorkflowKey.EPUB_COLOR_KEY: self.color_combo.currentData(),
            WorkflowKey.PDF_PRESET_KEY: (
                self.pdf_preset_group.checkedButton().property("preset_key")
                if self.pdf_preset_group.checkedButton() else "1"
            ),
            # ★ Word 设置
            WorkflowKey.DOCX_PAGE_SIZE: self._get_docx_page_size(),
            WorkflowKey.DOCX_FIX_SOFT_BREAKS: self.docx_fix_soft_breaks_cb.isChecked(),
            WorkflowKey.DOCX_PRESET: self.docx_preset_combo.currentData(),
        }

    def _load_config(self):
        """从 QSettings 读取并应用到 UI"""
        settings = QSettings(SettingsDomain.EPUB_TOOLBOX, SettingsDomain.SETTINGS)
        cfg = settings.value(WorkflowKey.CONFIG, {})
        if not cfg:
            return
        
        # 恢复工作流模式
        mode = cfg.get(WorkflowKey.MODE, ModeKey.REPAIR_TO_EPUB)
        if mode in self.mode_buttons:
            self.mode_buttons[mode].setChecked(True)
        
        # 恢复分步并行数
        step_workers = cfg.get(WorkflowKey.STEP_WORKERS, {})
        for step_key, spin in self.step_spins.items():
            if step_key in step_workers:
                spin.setValue(step_workers[step_key])
        
        # 恢复复选框
        if hasattr(self, 'rename_by_title_cb'):
            self.rename_by_title_cb.setChecked(cfg.get(WorkflowKey.RENAME_BY_TITLE, False))
        if hasattr(self, 'use_yaml_title_cb'):
            self.use_yaml_title_cb.setChecked(cfg.get(WorkflowKey.USE_YAML_TITLE, True))
        if hasattr(self, 'keep_intermediate_cb'):
            self.keep_intermediate_cb.setChecked(cfg.get(WorkflowKey.KEEP_INTERMEDIATE, True))
        if hasattr(self, 'auto_open_cb'):
            self.auto_open_cb.setChecked(cfg.get(WorkflowKey.AUTO_OPEN, False))
        if hasattr(self, 'workflow_show_page_numbers_cb'):
            self.workflow_show_page_numbers_cb.setChecked(cfg.get(WorkflowKey.SHOW_PAGE_NUMBERS, False))
        
        # 恢复输出目录
        output_dir_str = cfg.get(WorkflowKey.OUTPUT_DIR)
        if output_dir_str:
            self.output_dir = Path(output_dir_str)
            if hasattr(self, 'output_dir_edit'):
                self.output_dir_edit.setText(output_dir_str)
        
        # 恢复 EPUB CSS 风格
        css_style = cfg.get(WorkflowKey.EPUB_CSS_STYLE, "clean")
        if hasattr(self, 'css_buttons') and css_style in self.css_buttons:
            self.css_buttons[css_style].setChecked(True)
        
        # 恢复 EPUB 颜色
        color_key = cfg.get(WorkflowKey.EPUB_COLOR_KEY, "blue")
        if hasattr(self, 'color_combo'):
            idx = self.color_combo.findData(color_key)
            if idx >= 0:
                self.color_combo.setCurrentIndex(idx)
        
        # 恢复 PDF 预设
        pdf_preset = cfg.get(WorkflowKey.PDF_PRESET_KEY, "1")
        if hasattr(self, 'pdf_preset_group'):
            for btn in self.pdf_preset_group.buttons():
                if btn.property("preset_key") == pdf_preset:
                    btn.setChecked(True)
                    break
        
        # ★ 恢复 Word 设置
        if hasattr(self, 'docx_page_size_group'):
            docx_page_size = cfg.get(WorkflowKey.DOCX_PAGE_SIZE, "a4")
            for btn in self.docx_page_size_group.buttons():
                if btn.property("size_key") == docx_page_size:
                    btn.setChecked(True)
                    break
        
        if hasattr(self, 'docx_fix_soft_breaks_cb'):
            self.docx_fix_soft_breaks_cb.setChecked(
                cfg.get(WorkflowKey.DOCX_FIX_SOFT_BREAKS, True)
            )
        
        if hasattr(self, 'docx_preset_combo'):
            docx_preset = cfg.get(WorkflowKey.DOCX_PRESET, "book")
            idx = self.docx_preset_combo.findData(docx_preset)
            if idx >= 0:
                self.docx_preset_combo.setCurrentIndex(idx)

    def _save_config(self):
        """保存设置到 QSettings"""
        settings = QSettings(SettingsDomain.EPUB_TOOLBOX, SettingsDomain.SETTINGS)
        settings.setValue(WorkflowKey.CONFIG, self.get_config())
    
    # ====== 处理流程 ======
    
    def start_processing(self, files: List[Path] = None, **kwargs) -> bool:
        """开始工作流"""
        if self.force_reprocess_cb.isChecked():
            all_files = self.file_list.get_all_files()
            if not all_files:
                QMessageBox.warning(None, "警告", "请先添加文件")
                return False
            self.file_list.reset_all_status()
            files = self.file_list.get_all_files()
            self.log(f"🔄 忽略状态模式：将重新处理全部 {len(files)} 个文件", "INFO")
        else:
            files = self.file_list.get_pending_files()
            if not files:
                all_files = self.file_list.get_all_files()
                if all_files:
                    failed = self.file_list.get_files_by_status(FileStatus.FAILED)
                    if failed:
                        reply = QMessageBox.question(
                            None, "提示",
                            f"有 {len(failed)} 个文件处理失败，是否重试？",
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                        if reply == QMessageBox.StandardButton.Yes:
                            for f in failed:
                                self.file_list.update_status(f, FileStatus.PENDING)
                            files = failed
                        else:
                            return False
                    else:
                        QMessageBox.information(
                            None, "提示",
                            "所有文件都已处理完成！\n\n"
                            "如需重新处理，请勾选「忽略状态」选项。")
                        return False
                else:
                    QMessageBox.warning(None, "警告", "请先添加文件")
                    return False
        
        # 输出路径校验
        if self.output_dir_edit.text().strip() and not self.output_dir:
            QMessageBox.warning(None, "警告",
                "输出路径无效，请检查路径是否正确，或清空使用默认目录")
            return False
        
        mode_key = self._get_selected_mode()
        mode_info = WORKFLOW_MODES[mode_key]
        
        # 确认对话框
        confirm_msg = (
            f"即将使用「{mode_info['name']}」模式\n"
            f"处理 {len(files)} 个文件。\n\n"
            f"步骤：{' → '.join(mode_info['steps'])}\n"
            f"输出模式：{'统一目录' if self.output_dir else '跟随源文件'}\n"
            f"保留中间文件：{'是' if self.keep_intermediate_cb.isChecked() else '否'}"
        )
        if self.rename_by_title_cb.isChecked():
            confirm_msg += "\nYAML标题重命名：已启用"
        if self.workflow_show_page_numbers_cb.isChecked():
            confirm_msg += "\n显示页码：已启用"
        confirm_msg += "\n\n是否继续？"

        reply = QMessageBox.question(
            None, "确认", confirm_msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return False
        
        self.is_processing = True
        
        if self.progress_bar:
            self.progress_bar.setValue(0)
        
        self.log("=" * 60)
        self.log(f"🚀 启动工作流: {mode_info['name']}")
        self.log(f"   文件数: {len(files)}")
        self.log(f"   保留中间文件: {'是' if self.keep_intermediate_cb.isChecked() else '否'}")
        self.log("=" * 60)
        
        # 构建步骤 worker 配置
        step_workers = {
            StepKey.REPAIR: self.step_spins[StepKey.REPAIR].value(),
            StepKey.MD2EPUB: self.step_spins[StepKey.MD2EPUB].value(),
            StepKey.EPUB2PDF: self.step_spins[StepKey.EPUB2PDF].value(),
            StepKey.EPUB2DOCX: self.step_spins[StepKey.EPUB2DOCX].value(),
        }

        # 收集 Word 转换参数
        docx_page_size = self._get_docx_page_size()
        docx_fix_soft_breaks = self.docx_fix_soft_breaks_cb.isChecked()
        docx_preset = self.docx_preset_combo.currentData()

        self.worker = WorkflowWorker(
            files=files,
            workflow_mode=mode_key,
            output_dir=self.output_dir,
            repair_config=self._get_repair_config(),
            epub_css=self._get_epub_css(),
            pdf_margins=self._get_pdf_margins(),
            keep_intermediate=self.keep_intermediate_cb.isChecked(),
            auto_open=self.auto_open_cb.isChecked(),
            rename_by_title=self.rename_by_title_cb.isChecked(),
            use_yaml_title=self.use_yaml_title_cb.isChecked(),
            step_workers=step_workers,
            show_page_numbers=self.workflow_show_page_numbers_cb.isChecked(),
            docx_page_size=docx_page_size,
            docx_fix_soft_breaks=docx_fix_soft_breaks,
            docx_preset=docx_preset,
        )

        self.worker.progress_updated.connect(self._on_progress_updated)
        self.worker.file_status_signal.connect(self._on_file_status_changed)
        self.worker.log_message.connect(self.log)
        self.worker.step_state_changed.connect(self._on_pipeline_step_changed)
        self.worker.finished_all.connect(self._on_finished)
        
        self.worker.start()
        return True
    
    def stop_processing(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.log("⏹️ 正在停止工作流...", "WARNING")
    
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
        self.all_results.extend(results)
        if self.progress_bar:
            self.progress_bar.setValue(100)
        
        success = sum(1 for r in results if r['status'] == 'success')
        failed = len(results) - success
        
        self.log("")
        self.log("=" * 60)
        self.log(f"✅ 工作流完成！成功: {success}, 失败: {failed}",
                 "SUCCESS" if failed == 0 else "WARNING")
        
        if failed > 0:
            self.log("失败列表:", "WARNING")
            for r in results:
                if r['status'] == 'failed':
                    self.log(f"  - {Path(r['file']).name}: {r.get('error', '未知')}",
                             "ERROR")
        self.log("=" * 60)
        
        self.update_progress(100, f"完成 - 成功: {success}, 失败: {failed}")
        
        self._save_config()
        
        if self.force_reprocess_cb.isChecked():
            self.force_reprocess_cb.setChecked(False)
        
        QMessageBox.information(
            None, "完成",
            f"工作流处理完成！\n\n✅ 成功: {success} 个\n❌ 失败: {failed} 个")

    def _on_pipeline_step_changed(self, file_path: Path, step_name: str, state: dict):
        """主界面 Worker 的步骤状态同步到统一流水线"""
        key = make_pipeline_key(file_path)
        
        if key not in self.pipeline_states:
            self.pipeline_states[key] = {
                'file': resolve_source_file(file_path),
                'steps': {}
            }
        
        self.pipeline_states[key]['steps'][step_name] = state

    def _get_selected_css_style(self) -> str:
        """获取当前选中的 CSS 风格 key"""
        for key, rb in self.css_buttons.items():
            if rb.isChecked():
                return key
        return "clean"

    # ====== 统一流水线状态管理 ======

    def panel_update_step_state(self, file_path: Path, step_name: str, state: dict):
        key = make_pipeline_key(file_path)
        if key not in self.pipeline_states:
            self.pipeline_states[key] = {
                'file': resolve_source_file(file_path),
                'steps': {}
            }
        self.pipeline_states[key]['steps'][step_name] = state

    def panel_append_log(self, message: str, level: str = "INFO"):
        timestamp = time.strftime("%H:%M:%S")
        self.panel_log_cache.append((timestamp, message, level))
        if len(self.panel_log_cache) > 500:
            self.panel_log_cache = self.panel_log_cache[-500:]

    def panel_get_logs(self) -> List[tuple]:
        return self.panel_log_cache

    def panel_reset_file_states(self, file_paths: List[Path]):
        for fp in file_paths:
            key = make_pipeline_key(fp)
            if key in self.pipeline_states:
                self.pipeline_states[key]['steps'] = {}

    def panel_get_all_states(self) -> Dict:
        return self.pipeline_states

    def panel_clear_all_states(self):
        self.pipeline_states.clear()
        self.panel_log_cache.clear()
        self._pipeline_total_steps = 0
        self._pipeline_completed_steps = 0
        self._pipeline_completed_files = 0
        self._pipeline_start_time = 0.0

    def panel_get_row_config(self, file_path: Path) -> Dict:
        return getattr(self, '_panel_row_configs', {}).get(file_path, {})

    def panel_set_row_config(self, file_path: Path, config: Dict):
        if not hasattr(self, '_panel_row_configs'):
            self._panel_row_configs = {}
        if config:
            self._panel_row_configs[file_path] = config
        else:
            self._panel_row_configs.pop(file_path, None)

    def panel_has_row_config(self, file_path: Path) -> bool:
        return file_path in getattr(self, '_panel_row_configs', {})

    def panel_get_all_row_configs(self) -> Dict:
        return getattr(self, '_panel_row_configs', {})

    def _open_monitor_panel(self):
        from modules.workflow.monitor_panel import MonitorPanelDialog
        dialog = MonitorPanelDialog(parent=None, workflow_module=self)
        dialog.exec()
        self.log("📊 监视面板已关闭", "INFO")


# ==================== 元信息 ====================
__author__ = "YQJ"
__version__ = "1.6.0"
__date__ = "2026.05.24"