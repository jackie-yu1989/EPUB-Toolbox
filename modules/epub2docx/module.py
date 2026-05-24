#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
EPUB转DOCX模块 - PyQt6界面封装
提供 EPUB 到 DOCX 的批量转换功能
"""

import os
import sys
import time
import logging
from pathlib import Path
from typing import List, Tuple, Optional, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from threading import Event

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QRadioButton, QSpinBox, QCheckBox, QLineEdit,
    QFileDialog, QFrame, QButtonGroup, QMessageBox,QComboBox
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QSettings

from core.base_module import BaseModule
from core.components import UnifiedFileListWidget, FileStatus, LogPanel
from core.utils import check_calibre
# ★ 导入常量化配置键
from core.config_keys import SettingsDomain, EPUB2DocxKey
from .processor import convert_epub_to_docx
from core.components.file_list import DropHotzoneMixin

# 模块级日志记录器
logger = logging.getLogger(__name__)


class ConversionWorker(QThread):
    """EPUB 转 DOCX 工作线程"""
    progress_updated = pyqtSignal(int, str, int, int)
    file_status_signal = pyqtSignal(Path, str)
    log_message = pyqtSignal(str, str)
    finished_all = pyqtSignal(list)

    def __init__(self, input_files: List[Path], output_mode: str,
                 output_dir: Optional[Path] = None,
                 page_size: str = "a4",
                 fix_soft_breaks: bool = True,
                 font_preset: str = "academic",      # ★ 新增
                 max_workers: int = 4, auto_open: bool = False):
        super().__init__()
        self.input_files = input_files
        self.output_mode = output_mode
        self.output_dir = output_dir
        self.page_size = page_size
        self.fix_soft_breaks = fix_soft_breaks
        self.font_preset = font_preset                # ★ 新增
        self.max_workers = max_workers
        self.auto_open = auto_open
        self._stop_event = Event()
        self.results = []

    def stop(self):
        """优雅停止转换"""
        self._stop_event.set()
        logger.debug("转换工作线程收到停止信号")

    def _get_unique_output_path(self, output_path: Path) -> Path:
        """获取唯一的输出路径"""
        if not output_path.exists():
            return output_path

        parent = output_path.parent
        stem = output_path.stem
        suffix = output_path.suffix

        for counter in range(1, 1000):
            new_path = parent / f"{stem}_{counter}{suffix}"
            if not new_path.exists():
                return new_path

        timestamp = int(time.time() * 1000)
        return parent / f"{stem}_{timestamp}{suffix}"

    def run(self):
        """执行批量转换"""
        total = len(self.input_files)
        self.results = []

        self.log_message.emit(
            f"开始转换 {total} 个文件，并行数: {self.max_workers}", "INFO"
        )

        start_total = time.time()
        completed = 0

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures: Dict[Future, Tuple[Path, Path]] = {}

            for epub_file in self.input_files:
                if self._stop_event.is_set():
                    self.log_message.emit("转换已被用户停止", "WARNING")
                    break

                if self.output_mode == "custom" and self.output_dir:
                    output_dir_path = self.output_dir
                else:
                    output_dir_path = epub_file.parent

                output_dir_path.mkdir(parents=True, exist_ok=True)

                output_docx = output_dir_path / epub_file.with_suffix('.docx').name
                output_docx = self._get_unique_output_path(output_docx)

                self.file_status_signal.emit(epub_file, 'processing')

                # 创建日志回调
                def log_cb(msg):
                    self.log_message.emit(msg, "INFO")

                future = executor.submit(
                    convert_epub_to_docx,
                    epub_file,           # 参数1: epub_file
                    output_docx,         # 参数2: output_docx
                    self.page_size,      # 参数3: page_size
                    self.fix_soft_breaks,# 参数4: fix_soft_breaks
                    True,                # 参数5: auto_typography (★ 新增，设为 True)
                    self.font_preset,    # 参数6: font_preset
                    log_cb               # 参数7: log_callback
                )
                futures[future] = (epub_file, output_docx)

            for future in as_completed(futures):
                if self._stop_event.is_set():
                    break

                epub_file, output_docx = futures[future]
                completed += 1

                try:
                    success, msg, elapsed = future.result(timeout=300)

                    if success:
                        self.file_status_signal.emit(epub_file, 'success')
                        self.log_message.emit(
                            f"✅ [{completed}/{total}] {epub_file.name} → "
                            f"{output_docx.name} ({elapsed:.1f}秒)",
                            "SUCCESS"
                        )
                        self.results.append({
                            'file': str(epub_file),
                            'output': str(output_docx),
                            'status': 'success',
                            'message': msg
                        })
                    else:
                        self.file_status_signal.emit(epub_file, 'failed')
                        self.log_message.emit(
                            f"❌ [{completed}/{total}] {epub_file.name} - "
                            f"失败: {msg}",
                            "ERROR"
                        )
                        self.results.append({
                            'file': str(epub_file),
                            'status': 'failed',
                            'message': msg
                        })

                except Exception as e:
                    self.file_status_signal.emit(epub_file, 'failed')
                    self.log_message.emit(
                        f"❌ {epub_file.name} - 异常: {str(e)}",
                        "ERROR"
                    )
                    self.results.append({
                        'file': str(epub_file),
                        'status': 'failed',
                        'message': str(e)
                    })

                progress = int(completed / total * 100) if total > 0 else 0
                self.progress_updated.emit(
                    progress, f"转换中... {completed}/{total}", completed, total
                )

        total_time = time.time() - start_total
        self.log_message.emit(f"总耗时: {total_time:.1f}秒", "INFO")

        if not self._stop_event.is_set() and self.auto_open:
            if self.output_mode == "custom" and self.output_dir:
                self._open_folder(self.output_dir)
                self.log_message.emit(
                    f"📂 已打开输出目录: {self.output_dir}", "INFO"
                )
            elif self.input_files:
                self._smart_open_output_folders()

        self.finished_all.emit(self.results)

    def _smart_open_output_folders(self):
        """智能打开输出文件夹"""
        # ✅ 修复：基于实际生成的输出文件提取目录，并强制 resolve 为绝对路径
        output_folders = set()
        for res in self.results:
            if res.get('status') == 'success' and res.get('output'):
                output_folders.add(Path(res['output']).resolve().parent)
        
        # 兜底：如果 results 为空（例如全部失败），使用输入文件的绝对父目录
        if not output_folders:
            output_folders = set(f.resolve().parent for f in self.input_files)
            
        if not output_folders:
            return

        folder_list = list(output_folders)
        if len(folder_list) == 1:
            self._open_folder(folder_list[0])
            self.log_message.emit(
                f"📂 已打开输出目录: {folder_list[0]}", "INFO"
            )
        elif len(folder_list) <= 3:
            for folder in folder_list:
                self._open_folder(folder)
            self.log_message.emit(
                f"📂 已打开 {len(folder_list)} 个输出目录", "INFO"
            )
        else:
            self._open_folder(folder_list[0])
            self.log_message.emit(
                f"📂 输出文件分布在 {len(folder_list)} 个不同目录",
                "INFO"
            )

    @staticmethod
    def _open_folder(folder: Path):
        """跨平台打开文件夹"""
        try:
            # ✅ 终极保险：强制转换为绝对路径，彻底杜绝 Windows explorer 打开"文档"
            folder = folder.resolve()
        except Exception:
            pass
            
        folder_str = str(folder)
        if sys.platform == 'win32':
            import subprocess
            subprocess.run(['explorer', folder_str], shell=True)
        elif sys.platform == 'darwin':
            import subprocess
            subprocess.run(['open', folder_str])
        else:
            import subprocess
            subprocess.run(['xdg-open', folder_str])


class EPUB2DOCXModule(BaseModule):
    """EPUB 转 DOCX 模块"""

    @property
    def module_id(self) -> str:
        return "epub2docx"

    @property
    def module_name(self) -> str:
        return "3-EPUB转Word"

    @property
    def module_icon(self) -> str:
        return "📄"

    @property
    def module_description(self) -> str:
        return (
            "EPUB → Word 批量转换。"
            "软回车自动转硬段落、5种排版预设、页面尺寸可选。"
        )

    @property
    def accepted_extensions(self) -> List[str]:
        return ['.epub']

    def check_dependencies(self) -> Tuple[bool, str]:
        """检查 Calibre 依赖"""
        calibre_ok, _ = check_calibre()
        if not calibre_ok:
            return False, "未找到 Calibre，请先安装 Calibre"
        return True, "Calibre 已就绪"

    def create_ui(self, parent=None) -> QWidget:
        """创建模块 UI"""
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
        self.worker: Optional[ConversionWorker] = None
        self.progress_bar = None
        self.log_panel = None

        return widget

    def _create_file_section(self) -> QGroupBox:
        """创建文件列表区域"""
        file_group = QGroupBox("📁 选择 EPUB 文件（支持拖拽，Ctrl+V）")
        file_layout = QVBoxLayout(file_group)

        self.file_list = UnifiedFileListWidget(['.epub'])
        self.file_list.files_added.connect(self._on_files_added)
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

        self.force_reprocess_cb = QCheckBox("忽略状态")
        self.force_reprocess_cb.setToolTip(
            "勾选后将重新转换列表中的所有文件"
        )

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

    def _create_options_section(self) -> QGroupBox:
        """创建转换选项区域"""
        options_group = QGroupBox("⚙️ 转换选项")
        options_layout = QVBoxLayout(options_group)
        options_layout.setSpacing(10)
        options_layout.setContentsMargins(15, 15, 15, 15)

        # ✅ 1. 页面尺寸 (扁平化布局)
        page_size_layout = QHBoxLayout()
        page_size_layout.setContentsMargins(0, 0, 0, 0)
        page_size_layout.setSpacing(15)
        
        page_size_label = QLabel("页面尺寸：")
        page_size_layout.addWidget(page_size_label)
        
        self.page_size_btn_group = QButtonGroup()
        sizes = [("A4", "a4"), ("Letter", "letter"), ("B5", "b5"), ("A5", "a5")]
        for text, key in sizes:
            btn = QRadioButton(text)
            btn.setProperty("size_key", key)
            self.page_size_btn_group.addButton(btn)
            page_size_layout.addWidget(btn)
            
        self.page_size_btn_group.buttons()[0].setChecked(True)
        page_size_layout.addStretch()
        options_layout.addLayout(page_size_layout)

        # 分隔线
        sep0 = QFrame()
        sep0.setFrameShape(QFrame.Shape.HLine)
        sep0.setStyleSheet("background-color: #dee2e6; margin: 5px 0;")
        options_layout.addWidget(sep0)

        # ★ 2. 排版预设（5个精选预设）
        preset_layout = QHBoxLayout()
        preset_layout.setSpacing(10)
        preset_layout.setContentsMargins(0, 5, 0, 5)
        
        preset_label = QLabel("排版预设：")
        preset_layout.addWidget(preset_label)
        
        self.style_preset_combo = QComboBox()
        self.style_preset_combo.setMinimumWidth(230)
        
        # 5个精选预设
        self.style_preset_combo.addItem("📖 书籍排版  (标题楷体，正文宋体)", "book")
        self.style_preset_combo.addItem("📚 学术论文  (标题黑体，正文宋体)", "academic")
        self.style_preset_combo.addItem("🔧 技术文档  (标题黑体，正文宋体)", "technical")
        self.style_preset_combo.addItem("💼 商务报告  (微软雅黑 - Arial)", "business")
        self.style_preset_combo.addItem("⏸️ 保留原样  (Calibre - Iowan Old Style)", "none")
        
        # 详细 tooltip
        self.style_preset_combo.setToolTip(
            "选择输出 Word 文档的排版样式\n\n"
            
            "📖 书籍排版\n"
            "  正文：宋体 12pt（小四），1.5倍行距\n"
            "  标题：楷体，一级标题：14pt（四号），缩进0字符\n"
            "  英文：Times New Roman（学术英文标准）\n\n"

            "📚 学术论文\n"
            "  正文：宋体 10.5pt（五号），1.5倍行距\n"
            "  标题：黑体，一级标题：14pt（四号），缩进1字符\n"
            "  英文：Times New Roman（学术英文标准）\n\n"

            "🔧 技术文档\n"
            "  正文：宋体 9.5pt（小五），1.25倍行距\n"
            "  标题：黑体，一级标题：12pt（小四），缩进0字符\n"
            "  代码/英文：Consolas（等宽字体）\n\n"
            
            "💼 商务报告\n"
            "  正文：微软雅黑 10.5pt（五号），1.25倍行距\n"
            "  标题：微软雅黑，一级标题：14pt（四号），缩进0字符\n"
            "  英文：Arial（无衬线）\n\n"
           
            "⏸️ 保留原样\n"
            "  保留 Calibre 原始样式（中英文 - Iowan Old Style）"
        )
        
        self.style_preset_combo.setCurrentIndex(0)  # 默认选中学术
        preset_layout.addWidget(self.style_preset_combo)
        preset_layout.addStretch()
        options_layout.addLayout(preset_layout)

        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #dee2e6; margin: 5px 0;")
        options_layout.addWidget(sep)

        # 3. 软回车修复
        self.fix_soft_breaks_cb = QCheckBox("✨ 自动修复软回车 (↓ → ¶)")
        self.fix_soft_breaks_cb.setChecked(True)
        self.fix_soft_breaks_cb.setToolTip(
            "转换后自动将 Word 软回车合并为标准段落"
        )
        options_layout.addWidget(self.fix_soft_breaks_cb)

        # 4. 分隔线
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("background-color: #dee2e6; margin: 5px 0;")
        options_layout.addWidget(sep2)

        # 5. 并行线程数
        workers_layout = QHBoxLayout()
        workers_layout.addWidget(QLabel("并行线程数: "))
        
        cpu_count = os.cpu_count() or 4
        self.worker_spin = QSpinBox()
        self.worker_spin.setRange(1, 16)
        self.worker_spin.setValue(min(4, cpu_count))
        self.worker_spin.setFixedWidth(60)
        workers_layout.addWidget(self.worker_spin)
        workers_layout.addWidget(QLabel(f"(CPU: {cpu_count}核)"))
        workers_layout.addStretch()
        options_layout.addLayout(workers_layout)

        # 6. 自动打开
        self.auto_open_cb = QCheckBox("转换完成后自动打开输出目录")
        options_layout.addWidget(self.auto_open_cb)

        return options_group

    def set_progress_bar(self, progress_bar):
        """注入进度条"""
        self.progress_bar = progress_bar

    def set_log_panel(self, log_panel: LogPanel):
        """注入日志面板"""
        self.log_panel = log_panel

    def _on_files_added(self, files: List[Path]):
        added = self.file_list.add_files(files)
        if added > 0:
            self.log(f"添加了 {added} 个文件")

    def _add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            None, "选择 EPUB 文件", "", "EPUB 文件 (*.epub);;所有文件 (*.*)"
        )
        if files:
            added = self.file_list.add_files([Path(f) for f in files])
            self.log(f"添加了 {added} 个文件")

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(
            None, "选择包含 EPUB 文件的文件夹"
        )
        if folder:
            folder_path = Path(folder)
            epub_files = list(folder_path.rglob("*.epub"))
            added = self.file_list.add_files(epub_files)
            self.log(f"从文件夹添加了 {added} 个文件")

    def _remove_selected(self):
        removed = self.file_list.remove_selected()
        if removed:
            self.log(f"移除了 {len(removed)} 个文件")

    def _clear_all(self):
        count = self.file_list.count()
        self.file_list.clear_all()
        if count > 0:
            self.log(f"清空了 {count} 个文件")

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

    def get_config(self) -> dict:
        """收集 UI 上的所有设置"""
        page_size = "a4"
        if hasattr(self, 'page_size_btn_group'):
            btn = self.page_size_btn_group.checkedButton()
            if btn:
                page_size = btn.property("size_key")
        
        fix_soft_breaks = self.fix_soft_breaks_cb.isChecked()
        max_threads = self.worker_spin.value()
        auto_open = self.auto_open_cb.isChecked()
        output_dir = getattr(self, 'output_dir', None)

        preset_value = "book"
        if hasattr(self, 'style_preset_combo'):
            preset_value = self.style_preset_combo.currentData()

        return {
            EPUB2DocxKey.PAGE_SIZE: page_size,
            EPUB2DocxKey.FIX_SOFT_BREAKS: fix_soft_breaks,
            EPUB2DocxKey.TYPOGRAPHY_PRESET: preset_value,
            EPUB2DocxKey.MAX_THREADS: max_threads,
            EPUB2DocxKey.AUTO_OPEN: auto_open,
            EPUB2DocxKey.OUTPUT_DIR: str(output_dir) if output_dir else None
        }

    def _load_config(self):
        """从 QSettings 读取并应用到 UI"""
        settings = QSettings(SettingsDomain.EPUB_TOOLBOX, SettingsDomain.SETTINGS)
        cfg = settings.value(EPUB2DocxKey.CONFIG, {})
        if not cfg:
            return

        # 恢复页面尺寸
        page_size = cfg.get(EPUB2DocxKey.PAGE_SIZE, "a4")
        if hasattr(self, 'page_size_btn_group'):
            for btn in self.page_size_btn_group.buttons():
                if btn.property("size_key") == page_size:
                    btn.setChecked(True)
                    break

        # 恢复复选框和数值
        if hasattr(self, 'fix_soft_breaks_cb'):
            self.fix_soft_breaks_cb.setChecked(cfg.get(EPUB2DocxKey.FIX_SOFT_BREAKS, True))
        
        # 恢复排版预设
        if hasattr(self, 'style_preset_combo'):
            preset = cfg.get(EPUB2DocxKey.TYPOGRAPHY_PRESET, "book")
            idx = self.style_preset_combo.findData(preset)
            if idx >= 0:
                self.style_preset_combo.setCurrentIndex(idx)
        
        if hasattr(self, 'worker_spin'):
            self.worker_spin.setValue(cfg.get(EPUB2DocxKey.MAX_THREADS, 4))
        if hasattr(self, 'auto_open_cb'):
            self.auto_open_cb.setChecked(cfg.get(EPUB2DocxKey.AUTO_OPEN, False))
        
        # 恢复输出目录
        output_dir_str = cfg.get(EPUB2DocxKey.OUTPUT_DIR)
        if output_dir_str:
            self.output_dir = Path(output_dir_str)
            if hasattr(self, 'output_dir_edit'):
                self.output_dir_edit.setText(output_dir_str)

    def _save_config(self):
        """保存设置到 QSettings"""
        # ★ 使用统一的 SettingsDomain + 常量键名
        settings = QSettings(SettingsDomain.EPUB_TOOLBOX, SettingsDomain.SETTINGS)
        settings.setValue(EPUB2DocxKey.CONFIG, self.get_config())

    def start_processing(self, files: List[Path] = None, **kwargs) -> bool:
        """开始批量转换"""
        if self.force_reprocess_cb.isChecked():
            all_files = self.file_list.get_all_files()
            if not all_files:
                QMessageBox.warning(None, "警告", "请先添加要转换的 EPUB 文件")
                return False
            self.file_list.reset_all_status()
            files = self.file_list.get_all_files()
            self.log(f"🔄 强制重新处理模式：将重新转换全部 {len(files)} 个文件", "INFO")
        else:
            files = self.file_list.get_pending_files()
            if not files:
                all_files = self.file_list.get_all_files()
                if all_files:
                    QMessageBox.information(
                        None, "提示",
                        "所有文件都已转换完成！\n"
                        "如需重新处理，请勾选「忽略状态」选项。"
                    )
                    return False
                else:
                    QMessageBox.warning(None, "警告", "请先添加要转换的 EPUB 文件")
                    return False

        calibre_ok, _ = check_calibre()
        if not calibre_ok:
            QMessageBox.critical(
                None, "错误",
                "未找到 Calibre 转换工具！\n"
                "请安装 Calibre 电子书管理软件\n"
                "下载地址：https://calibre-ebook.com/"
            )
            return False

        if self.output_dir_edit.text().strip() and not self.output_dir:
            QMessageBox.warning(
                None, "警告",
                "输出路径无效，请检查路径是否正确，或清空使用默认目录"
            )
            return False

        self.is_processing = True

        if self.progress_bar:
            self.progress_bar.setValue(0)

        config = self.get_config()

        self.log("=" * 60)
        self.log(f"开始批量转换 {len(files)} 个文件...")
        self.log(f"输出模式: {'统一目录' if self.output_dir else '跟随源文件'}")
        selected_btn = self.page_size_btn_group.checkedButton()
        self.log(f"页面尺寸: {selected_btn.text() if selected_btn else 'A4'}")
        self.log(f"修复软回车: {'是' if config[EPUB2DocxKey.FIX_SOFT_BREAKS] else '否'}")
        # ★ 显示排版预设
        preset_text = self.style_preset_combo.currentText()
        self.log(f"排版预设: {preset_text}")
        self.log(f"并行线程数: {config[EPUB2DocxKey.MAX_THREADS]}")
        self.log("=" * 60)

        self.worker = ConversionWorker(
            input_files=files,
            output_mode="custom" if self.output_dir else "source",
            output_dir=self.output_dir,
            page_size=config[EPUB2DocxKey.PAGE_SIZE],
            fix_soft_breaks=config[EPUB2DocxKey.FIX_SOFT_BREAKS],
            font_preset=config.get(EPUB2DocxKey.TYPOGRAPHY_PRESET, "book"),  # ★ 关键：使用 TYPOGRAPHY_PRESET
            max_workers=config[EPUB2DocxKey.MAX_THREADS],
            auto_open=config[EPUB2DocxKey.AUTO_OPEN]
        )

        self.worker.progress_updated.connect(self._on_progress_updated)
        self.worker.file_status_signal.connect(self._on_file_status_changed)
        self.worker.log_message.connect(self.log)
        self.worker.finished_all.connect(self._on_finished)

        self.worker.start()
        return True

    def stop_processing(self):
        """停止当前转换"""
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.log("正在停止转换...", "WARNING")

    def _on_progress_updated(self, value: int, message: str, completed: int, total: int):
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
            file_path, status_map.get(status, FileStatus.PENDING)
        )

    def _on_finished(self, results: list):
        self.is_processing = False
        if self.progress_bar:
            self.progress_bar.setValue(100)

        success_count = sum(1 for r in results if r['status'] == 'success')
        failed_count = len(results) - success_count

        # ✅ 保存用户设置
        self._save_config()

        self.log("")
        self.log("=" * 60)
        self.log(f"转换完成！成功: {success_count}, 失败: {failed_count}", "SUCCESS")
        self.log("=" * 60)

        self.update_progress(
            100, f"完成 - 成功: {success_count}, 失败: {failed_count}"
        )

        if self.force_reprocess_cb.isChecked():
            self.force_reprocess_cb.setChecked(False)

        QMessageBox.information(
            None, "完成",
            f"转换任务已完成！\n成功: {success_count} 个\n失败: {failed_count} 个"
        )

    def on_activate(self):
        """模块被激活（切换到此标签页）时调用"""
        self._load_config()
        self.log(f"已切换到 {self.module_name}", "INFO")

    def on_deactivate(self):
        """模块失去焦点（切换到其他模块或关闭窗口）时调用"""
        # ✅ 核心修复：离开模块时，立即保存当前最新的 UI 状态
        self._save_config()
        
        # 如果切走时还在处理，则停止处理（保持与其他模块一致的规范）
        if getattr(self, 'is_processing', False):
            self.stop_processing()


# ==================== 元信息 ====================
__author__ = "YQJ"
__version__ = "1.1.1"
__date__ = "2026.05.23"