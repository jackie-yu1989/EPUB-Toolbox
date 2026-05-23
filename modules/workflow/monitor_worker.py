#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
监视面板 - 支持实时状态上报的工作流 Worker
扩展现有 WorkflowWorker，在步骤处理过程中实时发射状态信号
"""

import os
import sys
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from threading import Event

from PyQt6.QtCore import QThread, pyqtSignal, QObject

from modules.workflow.processor import run_repair_step, run_md2epub_step, run_epub2pdf_step, run_epub2docx_step
from modules.workflow.module import WORKFLOW_MODES, _SKIP_SENTINEL, _STOP_SENTINEL

# ★ 导入常量化配置键及工作流专用常量
from core.config_keys import MDRepairKey
from .constants import StepKey, ModeKey
from .monitor_row import StepStatus, StepType


# ==================== 信号定义 ====================

class MonitorWorkerSignals(QObject):
    """监视面板 Worker 信号集合"""

    step_state_changed = pyqtSignal(Path, str, dict)
    overall_progress = pyqtSignal(int, int, int, float)
    log_message = pyqtSignal(str, str)
    all_done = pyqtSignal(list)


# ==================== Worker ====================

class MonitorWorkflowWorker(QThread):
    """支持实时状态上报的工作流 Worker"""

    def __init__(
        self,
        files: List[Path],
        workflow_mode: str,
        output_dir: Optional[Path] = None,
        global_repair_config: Optional[Dict[str, Any]] = None,
        epub_css: str = "",
        pdf_margins: Optional[Dict[str, int]] = None,
        keep_intermediate: bool = True,
        auto_open: bool = False,
        rename_by_title: bool = False,
        use_yaml_title: bool = True,
        step_workers: Optional[Dict[str, int]] = None,
        row_configs: Optional[Dict[Path, Dict[str, Any]]] = None,
        signals: Optional[MonitorWorkerSignals] = None,
        docx_page_size: str = "a4",
        docx_fix_soft_breaks: bool = True
    ):
        super().__init__()
        self.files = files
        self.workflow_mode = workflow_mode
        self.output_dir = output_dir
        self.global_repair_config = global_repair_config or {}
        self.epub_css = epub_css
        self.pdf_margins = pdf_margins or {}
        self.keep_intermediate = keep_intermediate
        self.auto_open = auto_open
        self.rename_by_title = rename_by_title
        self.use_yaml_title = use_yaml_title
        self._stop_event = Event()
        self.results: List[Dict] = []
        self.row_configs = row_configs or {}
        self.signals = signals or MonitorWorkerSignals()

        # ★ 动态接收 Word 转换参数
        self.docx_page_size = docx_page_size
        self.docx_fix_soft_breaks = docx_fix_soft_breaks

        if rename_by_title:
            from modules.md_repair.processor import MarkdownTitleExtractor
            self.title_extractor = MarkdownTitleExtractor()
        else:
            self.title_extractor = None

        cpu_count = os.cpu_count() or 4
        default_workers = min(4, cpu_count)

        # ★ 使用常量作为键名
        self.step_workers = step_workers or {
            StepKey.REPAIR: min(2, cpu_count),
            StepKey.MD2EPUB: default_workers,
            StepKey.EPUB2PDF: default_workers,
            StepKey.EPUB2DOCX: default_workers,
        }

        self._step_elapsed_times: Dict[str, List[float]] = {
            StepKey.REPAIR: [], 
            StepKey.MD2EPUB: [], 
            StepKey.EPUB2PDF: [],
            StepKey.EPUB2DOCX: []
        }

    def stop(self):
        self._stop_event.set()

    def _get_row_config(self, file_path: Path) -> Dict[str, Any]:
        import copy
        config = copy.deepcopy(self.global_repair_config)
        row_override = self.row_configs.get(file_path, {})
        if row_override:
            for key, value in row_override.items():
                # ★ 使用常量替代硬编码 "formula_config"
                if key == MDRepairKey.FORMULA_CONFIG:
                    continue
                config[key] = value
            # ★ 使用常量替代硬编码 "formula_config"
            if MDRepairKey.FORMULA_CONFIG in row_override and MDRepairKey.FORMULA_CONFIG in config:
                config[MDRepairKey.FORMULA_CONFIG].update(row_override[MDRepairKey.FORMULA_CONFIG])
            elif MDRepairKey.FORMULA_CONFIG in row_override:
                config[MDRepairKey.FORMULA_CONFIG] = row_override[MDRepairKey.FORMULA_CONFIG]
        return config

    def _estimate_remaining(self, steps_done: int, total_steps: int) -> float:
        remaining = total_steps - steps_done
        if remaining <= 0:
            return 0.0
        all_times = []
        for times in self._step_elapsed_times.values():
            all_times.extend(times)
        if not all_times:
            return remaining * 10.0
        return remaining * (sum(all_times) / len(all_times))

    def run(self):
        from concurrent.futures import ThreadPoolExecutor
        from queue import Queue, Empty
        from threading import Lock

        mode_info = WORKFLOW_MODES[self.workflow_mode]
        steps = mode_info['steps']
        total_files = len(self.files)

        # ★ 使用常量构建映射
        step_type_map = {
            StepKey.REPAIR: StepType.REPAIR,
            StepKey.MD2EPUB: StepType.MD2EPUB,
            StepKey.EPUB2PDF: StepType.EPUB2PDF,
            StepKey.EPUB2DOCX: StepType.EPUB2DOCX,
        }

        self.signals.log_message.emit(f"🚀 启动工作流: {mode_info['name']}", "INFO")
        self.signals.log_message.emit(f"📊 {total_files} 个文件，{len(steps)} 个步骤，流水线并行处理", "INFO")

        if self.row_configs:
            custom_files = [f.name for f in self.row_configs.keys()]
            self.signals.log_message.emit(
                f"⚙️ 独立配置: {len(custom_files)} 个文件 "
                f"({', '.join(custom_files[:5])}{'...' if len(custom_files) > 5 else ''})", "INFO")

        start_total = time.time()
        all_output_paths = self._preprocess_output_paths(steps, total_files)

        # ★ 使用常量作为键名
        step_funcs = {
            StepKey.REPAIR: run_repair_step,
            StepKey.MD2EPUB: run_md2epub_step,
            StepKey.EPUB2PDF: run_epub2pdf_step,
            StepKey.EPUB2DOCX: run_epub2docx_step,
        }

        total_steps_count = total_files * len(steps)
        steps_completed = 0
        files_completed = 0
        step_lock = Lock()

        # ====== 流水线工作函数 ======
        def step_worker(step_name, input_queue, output_queue, step_func):
            nonlocal steps_completed, files_completed

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

                # ★ 始终从 file_result 取原始文件路径用于信号发射
                original_file = Path(file_result['file']) if 'file' in file_result else current_file               

                if current_file is None:
                    output_queue.put(_SKIP_SENTINEL)
                    continue

                row_config = self._get_row_config(current_file)

                # 发射「处理中」
                step_type = step_type_map.get(step_name)
                if step_type:
                    self.signals.step_state_changed.emit(
                        original_file, step_name, {"status": "processing", "progress": 0})

                self.signals.log_message.emit(f"  [{step_name}] {Path(current_file).name}", "INFO")

                output_path = all_output_paths.get(file_idx, {}).get(step_name)
                log_cb = lambda m: self.signals.log_message.emit(f"     {m}", "INFO")

                if output_path:
                    output_path.parent.mkdir(parents=True, exist_ok=True)

                step_start = time.time()

                try:
                    # ★ 使用常量进行分支判断
                    if step_name == StepKey.REPAIR:
                        kwargs = {'config': row_config, 'log_callback': log_cb}
                        if output_path:
                            kwargs['output_filename'] = output_path.name
                        success, msg, output = step_func(current_file, out_dir, **kwargs)
                    elif step_name == StepKey.MD2EPUB:
                        kwargs = {'css': self.epub_css, 'log_callback': log_cb, 'use_yaml_title': self.use_yaml_title}
                        if output_path:
                            kwargs['output_epub'] = output_path
                        success, msg, output = step_func(current_file, out_dir, **kwargs)
                    elif step_name == StepKey.EPUB2PDF:
                        kwargs = {'margins': self.pdf_margins, 'log_callback': log_cb}
                        if output_path:
                            kwargs['output_pdf'] = output_path
                        success, msg, output = step_func(current_file, out_dir, **kwargs)
                    elif step_name == StepKey.EPUB2DOCX:
                        kwargs = {
                            'page_size': self.docx_page_size,
                            'fix_soft_breaks': self.docx_fix_soft_breaks,
                            'log_callback': log_cb
                        }
                        if output_path:
                            kwargs['output_docx'] = output_path
                        success, msg, output = step_func(current_file, out_dir, **kwargs)
                    else:
                        continue
                except Exception as e:
                    success, msg, output = False, str(e), None

                elapsed = time.time() - step_start

                with step_lock:
                    self._step_elapsed_times[step_name].append(elapsed)
                    steps_completed += 1
                    remaining = self._estimate_remaining(steps_completed, total_steps_count)

                # 发射结果状态
                if step_type:
                    if success and output:
                        self.signals.step_state_changed.emit(
                            original_file, step_name,
                            {"status": "completed", "output_path": str(output), "elapsed": elapsed})
                    else:
                        self.signals.step_state_changed.emit(
                            original_file, step_name,
                            {"status": "failed", "error_message": msg, "elapsed": elapsed})

                with step_lock:
                    self.signals.overall_progress.emit(steps_completed, total_steps_count, files_completed, remaining)

                if success and output:
                    file_result['outputs'][step_name] = str(output)
                    # ★ 传递给下游的是产物路径（output），让下游正确处理
                    output_queue.put((file_idx, file_result, output, out_dir))
                else:
                    file_result['status'] = 'failed'
                    file_result['error'] = msg
                    self.signals.log_message.emit(f"❌ {Path(original_file).name} 失败: {msg}", "ERROR")
                    output_queue.put(_SKIP_SENTINEL)

        # ====== 创建队列 ======
        queues = [Queue(maxsize=total_files + 1) for _ in range(len(steps) + 1)]
        all_futures = []

        with ThreadPoolExecutor(max_workers=max(self.step_workers.values())) as executor:
            for i, step_name in enumerate(steps):
                step_count = self.step_workers.get(step_name, min(total_files, 4))
                for _ in range(step_count):
                    future = executor.submit(step_worker, step_name, queues[i], queues[i + 1], step_funcs[step_name])
                    all_futures.append(future)

            # 推入所有文件
            for file_idx, md_file in enumerate(self.files):
                if self._stop_event.is_set():
                    break
                source_dir = md_file.parent
                source_dir.mkdir(parents=True, exist_ok=True)
                if self.output_dir:
                    self.output_dir.mkdir(parents=True, exist_ok=True)
                file_result = {'file': str(md_file), 'status': 'success', 'outputs': {}}
                queues[0].put((file_idx, file_result, md_file, source_dir))

            # 发送结束信号
            first_step = steps[0]
            first_step_workers = self.step_workers.get(first_step, min(total_files, 4))
            for _ in range(first_step_workers):
                queues[0].put(_STOP_SENTINEL)

            # ====== 收集最终结果（以文件数为准，与 module.py 同步） ======
            final_queue = queues[-1]
            total_to_collect = total_files

            while total_to_collect > 0 and not self._stop_event.is_set():
                try:
                    item = final_queue.get(timeout=1.0)
                except Empty:
                    self.signals.overall_progress.emit(
                        steps_completed, total_steps_count, files_completed, 0
                    )
                    continue

                if item is _STOP_SENTINEL:
                    continue

                # ★ _SKIP_SENTINEL：上游失败 → 该文件已终结
                if item is _SKIP_SENTINEL:
                    total_to_collect -= 1
                    continue

                file_idx, file_result, final_output, out_dir = item
                self.results.append(file_result)
                total_to_collect -= 1  # ★ 无论成功失败都减

                if file_result['status'] == 'success':
                    files_completed += 1
                    final_name = Path(final_output).name if final_output else "未知"
                    self.signals.log_message.emit(
                        f"✅ [{files_completed}/{total_files}] "
                        f"{Path(file_result['file']).name} → {final_name}",
                        "SUCCESS")
                else:
                    self.signals.log_message.emit(
                        f"❌ {Path(file_result['file']).name}: {file_result.get('error', '未知')}",
                        "ERROR")

                with step_lock:
                    self.signals.overall_progress.emit(
                        steps_completed, total_steps_count, files_completed, 0
                    )

            # ★ 通知所有 worker 退出
            self._stop_event.set()

            for future in all_futures:
                try:
                    future.result(timeout=3)
                except Exception:
                    pass

        # ====== 清理 ======
        self._clean_intermediates(steps, all_output_paths)

        total_time = time.time() - start_total
        success_count = sum(1 for r in self.results if r['status'] == 'success')
        self.signals.log_message.emit(
            f"\n{'='*50}\n⏱️ 流水线完成，耗时: {total_time:.1f}秒\n"
            f"   成功: {success_count}/{total_files}\n{'='*50}",
            "SUCCESS" if success_count == total_files else "WARNING")

        if self.auto_open:
            out_dir = self.output_dir or self.files[0].parent
            self._open_folder(out_dir)

        self.signals.overall_progress.emit(total_steps_count, total_steps_count, success_count, 0)
        self.signals.all_done.emit(self.results)

    def _preprocess_output_paths(self, steps: List[str], total_files: int) -> Dict[int, Dict[str, Path]]:
        all_output_paths = {}
        for file_idx, md_file in enumerate(self.files):
            source_dir = md_file.parent
            source_dir.mkdir(parents=True, exist_ok=True)
            final_dir = self.output_dir or source_dir
            if self.output_dir:
                final_dir.mkdir(parents=True, exist_ok=True)
            file_paths = {}
            if self.rename_by_title and self.title_extractor:
                base_name, title_used, extracted_title = self.title_extractor.generate_name(md_file, source_dir)
                clean_base = base_name.replace('.md', '').replace('_fixed', '') if title_used else md_file.stem
                if title_used:
                    self.signals.log_message.emit(f"📝 YAML标题: {extracted_title} → {clean_base}", "INFO")
            else:
                clean_base = md_file.stem
            for i, step_name in enumerate(steps):
                is_final = (i == len(steps) - 1)
                
                # ★ 使用常量进行步骤判断
                if step_name == StepKey.REPAIR:
                    file_paths[StepKey.REPAIR] = source_dir / f"{clean_base}_fixed.md"
                elif step_name == StepKey.MD2EPUB:
                    file_paths[StepKey.MD2EPUB] = (final_dir if is_final else source_dir) / f"{clean_base}.epub"
                elif step_name == StepKey.EPUB2PDF:
                    file_paths[StepKey.EPUB2PDF] = final_dir / f"{clean_base}.pdf"
                elif step_name == StepKey.EPUB2DOCX:
                    file_paths[StepKey.EPUB2DOCX] = final_dir / f"{clean_base}.docx"
            all_output_paths[file_idx] = file_paths
        return all_output_paths

    def _clean_intermediates(self, steps: List[str], all_output_paths: Dict[int, Dict[str, Path]]):
        if self.keep_intermediate or len(steps) <= 1:
            return
        intermediates = steps[:-1]
        for file_idx in all_output_paths:
            for step in intermediates:
                output_path = all_output_paths[file_idx].get(step)
                if output_path and output_path.exists():
                    try:
                        output_path.unlink()
                        self.signals.log_message.emit(
                            f"🗑️ 已清理中间文件: {output_path.name}", "INFO")
                        # ★ 发射状态更新：产物已清理
                        self.signals.step_state_changed.emit(
                            self.files[file_idx],  # 原始文件
                            step,
                            {"status": "completed_cleaned", "output_path": str(output_path)}
                        )
                    except Exception:
                        pass

    @staticmethod
    def _open_folder(folder: Path):
        folder_str = str(folder)
        if sys.platform == 'win32':
            os.startfile(folder_str)
        elif sys.platform == 'darwin':
            import subprocess
            subprocess.run(['open', folder_str])
        else:
            import subprocess
            subprocess.run(['xdg-open', folder_str])

# ==================== 元信息 ====================
__author__ = "YQJ"
__version__ = "1.0.1"
__date__ = "2026.05.23"