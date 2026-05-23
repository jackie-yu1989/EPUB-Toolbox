#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
EPUB转PDF模块 - PyQt6界面封装
提供 EPUB 到 PDF 的批量转换功能，支持多种页边距预设和自定义设置
"""

import os
import sys
import time
import logging
import subprocess
from pathlib import Path
from typing import List, Tuple, Optional, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from threading import Event

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QRadioButton, QSpinBox, QCheckBox, QLineEdit,
    QFileDialog, QGridLayout, QMessageBox, QButtonGroup, QFrame
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QSettings
from PyQt6.QtGui import QIntValidator

from core.base_module import BaseModule
from core.components import UnifiedFileListWidget, FileStatus, LogPanel
from core.utils import check_calibre, find_executable
# ★ 导入常量化配置键
from core.config_keys import SettingsDomain, EPUB2PdfKey
from .processor import convert_epub_to_pdf, PRESETS
from core.components.file_list import DropHotzoneMixin


# 模块级日志记录器
logger = logging.getLogger(__name__)


class ConversionWorker(QThread):
    """EPUB 转 PDF 工作线程
    
    使用 ThreadPoolExecutor 实现多文件并行转换。
    通过 Event 实现优雅停止，避免强制终止导致的文件损坏。
    """
    
    # 信号定义
    progress_updated = pyqtSignal(int, str, int, int)   # 进度百分比, 描述, 已完成数, 总数
    file_status_signal = pyqtSignal(Path, str)          # 文件路径, 状态
    log_message = pyqtSignal(str, str)                  # 消息, 级别
    finished_all = pyqtSignal(list)                     # 结果列表
    
    def __init__(self, input_files: List[Path], output_mode: str, 
                 output_dir: Optional[Path] = None,
                 margins: Optional[Dict[str, int]] = None, 
                 max_workers: int = 4, auto_open: bool = False,
                 show_page_numbers: bool = False):
        """初始化工作线程
        
        Args:
            input_files: 待转换的 EPUB 文件列表
            output_mode: 输出模式，"custom"=统一目录，"source"=跟随源文件
            output_dir: 自定义输出目录（output_mode="custom" 时使用）
            margins: 页边距设置字典
            max_workers: 最大并行线程数
            auto_open: 完成后是否自动打开输出目录
        """
        super().__init__()
        self.input_files = input_files
        self.output_mode = output_mode
        self.output_dir = output_dir
        self.margins = margins or {}
        self.max_workers = max_workers
        self.auto_open = auto_open
        self.show_page_numbers = show_page_numbers
        self._stop_event = Event()
        self.results = []
    
    def stop(self):
        """优雅停止转换（不强制终止正在进行的转换）"""
        self._stop_event.set()
        logger.debug("转换工作线程收到停止信号")
    
    def _get_unique_output_path(self, output_path: Path) -> Path:
        """获取唯一的输出路径（避免覆盖已有文件）
        
        策略：
            1. 路径不存在 → 直接返回
            2. 存在 → 依次尝试 _1, _2, ... _999 后缀
            3. 全部冲突 → 使用时间戳后缀（极端回退）
        
        Args:
            output_path: 期望的输出路径
            
        Returns:
            Path: 可用的唯一输出路径
        """
        # 路径可用，直接返回
        if not output_path.exists():
            return output_path
        
        parent = output_path.parent
        stem = output_path.stem
        suffix = output_path.suffix
        
        # 尝试数字后缀（1-999）
        for counter in range(1, 1000):
            new_path = parent / f"{stem}_{counter}{suffix}"
            if not new_path.exists():
                return new_path
        
        # 极端回退：时间戳
        timestamp = int(time.time() * 1000)
        return parent / f"{stem}_{timestamp}{suffix}"
    
    def run(self):
        """执行批量转换（在线程池中并行处理）"""
        total = len(self.input_files)
        self.results = []
        
        self.log_message.emit(
            f"开始转换 {total} 个文件，并行数: {self.max_workers}", 
            "INFO"
        )
        
        start_total = time.time()
        completed = 0
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures: Dict[Future, Tuple[Path, Path]] = {}
            
            # 提交所有转换任务
            for epub_file in self.input_files:
                if self._stop_event.is_set():
                    self.log_message.emit("转换已被用户停止", "WARNING")
                    break
                
                # 确定输出目录
                if self.output_mode == "custom" and self.output_dir:
                    output_dir_path = self.output_dir
                else:
                    output_dir_path = epub_file.parent
                
                output_dir_path.mkdir(parents=True, exist_ok=True)
                
                # 生成唯一输出路径
                output_pdf = output_dir_path / epub_file.with_suffix('.pdf').name
                output_pdf = self._get_unique_output_path(output_pdf)
                
                # 更新文件状态
                self.file_status_signal.emit(epub_file, 'processing')
                
                # 提交到线程池
                future = executor.submit(
                    convert_epub_to_pdf,
                    epub_file, output_pdf, self.margins,
                    self.show_page_numbers
                )
                futures[future] = (epub_file, output_pdf)
            
            # 收集任务结果
            for future in as_completed(futures):
                if self._stop_event.is_set():
                    # 收到停止信号后不再处理新结果
                    break
                
                epub_file, output_pdf = futures[future]
                completed += 1
                
                try:
                    success, msg, elapsed = future.result(timeout=300)
                    
                    if success:
                        self.file_status_signal.emit(epub_file, 'success')
                        self.log_message.emit(
                            f"✅ [{completed}/{total}] {epub_file.name} → "
                            f"{output_pdf.name} ({elapsed:.1f}秒)", 
                            "SUCCESS"
                        )
                        self.results.append({
                            'file': str(epub_file), 
                            'output': str(output_pdf),
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
                
                # 更新进度
                progress = int(completed / total * 100) if total > 0 else 0
                self.progress_updated.emit(
                    progress, f"转换中... {completed}/{total}", completed, total
                )
        
        total_time = time.time() - start_total
        self.log_message.emit(f"总耗时: {total_time:.1f}秒", "INFO")
        
        # ★ 智能打开输出目录
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
        # ✅ 修复：基于 self.results 中实际生成的输出文件路径提取目录，并强制 resolve 为绝对路径
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
                f"📂 输出文件分布在 {len(folder_list)} 个不同目录，"
                f"已打开第一个目录: {folder_list[0]}",
                "INFO"
            )
            # 列出前 3 个其他目录
            other_folders = [str(f) for f in folder_list[1:4]]
            if len(folder_list) > 4:
                self.log_message.emit(
                    f"   其他目录: {', '.join(other_folders)}...", "INFO"
                )
            else:
                self.log_message.emit(
                    f"   其他目录: {', '.join(str(f) for f in folder_list[1:])}",
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
            subprocess.run(['explorer', folder_str], shell=True)
        elif sys.platform == 'darwin':
            subprocess.run(['open', folder_str])
        else:
            subprocess.run(['xdg-open', folder_str])


class EPUB2PDFModule(BaseModule):
    """EPUB 转 PDF 模块
    
    将 EPUB 电子书批量转换为 PDF 文档。
    支持 4 种页边距预设、自定义边距/字号、拖拽/粘贴导入、多线程并行处理。
    """
    
    # ==================== 模块元信息 ====================
    
    @property
    def module_id(self) -> str:
        return "epub2pdf"
    
    @property
    def module_name(self) -> str:
        return "4-EPUB转PDF"
    
    @property
    def module_icon(self) -> str:
        return "📕"
    
    @property
    def module_description(self) -> str:
        return (
            "EPUB → PDF 批量转换。"
            "4种页边距预设、自定义字号、可选页码、多线程并行。"
        )

    
    @property
    def accepted_extensions(self) -> List[str]:
        return ['.epub']
    
    # ==================== 依赖检查 ====================
    
    def check_dependencies(self) -> Tuple[bool, str]:
        """检查 Calibre 依赖是否满足"""
        calibre_ok, calibre_msg = check_calibre()
        if not calibre_ok:
            return False, "未找到 Calibre，请先安装 Calibre"
        return True, calibre_msg
    
    # ==================== UI 构建 ====================
    
    def create_ui(self, parent=None) -> QWidget:
        """创建模块 UI 界面
        
        布局结构：
            1. 文件列表区（拖拽/粘贴/按钮添加，支持忽略状态）
            2. 输出设置区（自定义目录或跟随源文件）
            3. 转换选项区（预设页边距、自定义边距/字号、并行设置）
        """
        widget = QWidget(parent)

        layout = QVBoxLayout(widget)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # ---- 文件列表 ----
        layout.addWidget(self._create_file_section())
        
        # ---- 输出设置 ----
        layout.addWidget(self._create_output_section())
        
        # ---- 转换选项 ----
        layout.addWidget(self._create_options_section())
        
        layout.addStretch()
        
        # 初始化状态
        self.output_dir: Optional[Path] = None
        self.worker: Optional[ConversionWorker] = None
        self.progress_bar = None
        self.log_panel = None
        
        return widget
    
    def _create_file_section(self) -> QGroupBox:
        """创建文件列表区域"""
        file_group = QGroupBox("📁 选择 EPUB 文件（支持拖拽，Ctrl+V）")
        file_layout = QVBoxLayout(file_group)
        
        # 文件列表组件
        self.file_list = UnifiedFileListWidget(['.epub'])
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
        
        # 忽略状态复选框
        self.force_reprocess_cb = QCheckBox("忽略状态")
        self.force_reprocess_cb.setToolTip(
            "默认情况下，已经转换过的文件不会再次转换。\n"
            "勾选此项后，将重新转换列表中的所有文件。\n\n"
            "适用场景：\n"
            "• 修改了页边距设置后想重新转换\n"
            "• 之前转换失败的文件想再次尝试\n"
            "• 需要覆盖之前的输出文件"
        )
        
        btn_layout.addWidget(add_file_btn)
        btn_layout.addWidget(add_folder_btn)
        btn_layout.addWidget(remove_btn)
        btn_layout.addWidget(clear_btn)
        btn_layout.addWidget(self.force_reprocess_cb)
        btn_layout.addStretch()
        
        file_layout.addLayout(btn_layout)
        
        # ★ 扩大拖放热区
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
        
        # -- 页边距预设 --
        options_layout.addWidget(self._create_preset_widget())
        
        # -- 自定义边距 --
        options_layout.addWidget(self._create_custom_margin_widget())
        
        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #dee2e6; margin: 5px 0;")
        options_layout.addWidget(sep)
        
        # -- 并行线程数 --
        options_layout.addWidget(self._create_workers_widget())
        
        # -- 自动打开复选框 --
        self.auto_open_cb = QCheckBox("转换完成后打开输出目录")
        options_layout.addWidget(self.auto_open_cb)
        
        # 显示页码
        self.show_page_numbers_cb = QCheckBox("显示页码在PDF页面底部")
        self.show_page_numbers_cb.setToolTip(
            "在PDF页面底部居中显示页码（当前页）"
        )
        options_layout.addWidget(self.show_page_numbers_cb)

        return options_group
    
    def _create_preset_widget(self) -> QWidget:
        """创建页边距预设选择区域"""
        self.preset_group = QButtonGroup()
        
        preset_widget = QWidget()
        preset_layout = QHBoxLayout(preset_widget)
        preset_layout.setContentsMargins(0, 0, 0, 0)
        preset_layout.setSpacing(10)
        
        preset_label = QLabel("页边距预设:")
        preset_label.setFixedWidth(75)
        preset_layout.addWidget(preset_label)
        
        # 预设显示名称映射（简化 UI 显示）
        preset_names = {
            "1": "极限紧凑",
            "2": "左右紧凑",
            "3": "上下紧凑",
            "4": "对称装订"
        }
        
        for key, preset in PRESETS.items():
            display_name = preset_names.get(key, preset['name'])
            rb = QRadioButton(display_name)
            rb.setToolTip(
                f"上{preset['top']} 下{preset['bottom']} "
                f"左{preset['left']} 右{preset['right']}"
            )
            rb.setProperty("preset_key", key)
            self.preset_group.addButton(rb)
            preset_layout.addWidget(rb)
            
            if key == "1":
                rb.setChecked(True)
        
        preset_layout.addStretch()
        
        # 连接切换信号
        self.preset_group.buttonClicked.connect(self._on_preset_change) 
        
        return preset_widget
    
    def _create_custom_margin_widget(self) -> QWidget:
        """创建自定义边距输入区域"""
        custom_widget = QWidget()
        custom_layout = QHBoxLayout(custom_widget)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        custom_layout.setSpacing(5)
        
        custom_label = QLabel("自定义边距:")
        custom_label.setFixedWidth(75)
        custom_layout.addWidget(custom_label)
        
        # QLineEdit 工厂函数
        def create_margin_edit(value: int = 0, max_val: int = 100) -> QLineEdit:
            edit = QLineEdit()
            edit.setText(str(value))
            edit.setValidator(QIntValidator(0, max_val))
            edit.setFixedWidth(28)
            edit.setAlignment(Qt.AlignmentFlag.AlignRight)
            edit.setStyleSheet("""
                QLineEdit {
                    padding: 2px 4px;
                    border: 1px solid #dcdcdc;
                    border-radius: 3px;
                    background: white;
                }
                QLineEdit:focus {
                    border-color: #3498db;
                }
            """)
            return edit
        
        # 上边距
        custom_layout.addWidget(QLabel("上"))
        self.top_margin = create_margin_edit(0)
        custom_layout.addWidget(self.top_margin)
        custom_layout.addWidget(QLabel("pt"))
        custom_layout.addSpacing(8)
        
        # 下边距
        custom_layout.addWidget(QLabel("下"))
        self.bottom_margin = create_margin_edit(0)
        custom_layout.addWidget(self.bottom_margin)
        custom_layout.addWidget(QLabel("pt"))
        custom_layout.addSpacing(8)
        
        # 左边距
        custom_layout.addWidget(QLabel("左"))
        self.left_margin = create_margin_edit(0)
        custom_layout.addWidget(self.left_margin)
        custom_layout.addWidget(QLabel("pt"))
        custom_layout.addSpacing(8)
        
        # 右边距
        custom_layout.addWidget(QLabel("右"))
        self.right_margin = create_margin_edit(0)
        custom_layout.addWidget(self.right_margin)
        custom_layout.addWidget(QLabel("pt"))
        custom_layout.addSpacing(8)
        
        # 正文字号
        custom_layout.addWidget(QLabel("字号"))
        self.font_size = QLineEdit()
        self.font_size.setText("12")
        self.font_size.setValidator(QIntValidator(8, 72))
        self.font_size.setFixedWidth(28)
        self.font_size.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.font_size.setStyleSheet("""
            QLineEdit {
                padding: 2px 4px;
                border: 1px solid #dcdcdc;
                border-radius: 3px;
                background: white;
            }
            QLineEdit:focus {
                border-color: #3498db;
            }
        """)
        custom_layout.addWidget(self.font_size)
        custom_layout.addWidget(QLabel("pt"))
        
        custom_layout.addStretch()
        
        return custom_widget
    
    def _create_workers_widget(self) -> QWidget:
        """创建并行线程数设置区域"""
        workers_widget = QWidget()
        workers_layout = QHBoxLayout(workers_widget)
        workers_layout.setContentsMargins(0, 0, 0, 0)
        workers_layout.setSpacing(5)
        
        workers_label = QLabel("并行线程数:")
        workers_label.setFixedWidth(75)
        workers_layout.addWidget(workers_label)
        
        cpu_count = os.cpu_count() or 4
        default_workers = min(4, cpu_count)  # ★ 自适应默认值
        
        self.worker_spin = QSpinBox()
        self.worker_spin.setMinimum(1)
        self.worker_spin.setMaximum(16)
        self.worker_spin.setValue(default_workers)
        self.worker_spin.setFixedWidth(60)
        self.worker_spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        workers_layout.addWidget(self.worker_spin)
        
        cpu_label = QLabel(f"(CPU: {cpu_count}核)")
        cpu_label.setObjectName("infoLabel")
        workers_layout.addWidget(cpu_label)
        workers_layout.addStretch()
        
        return workers_widget
    
    # ==================== 外部注入 ====================
    
    def set_progress_bar(self, progress_bar):
        """注入进度条组件"""
        self.progress_bar = progress_bar
    
    def set_log_panel(self, log_panel: LogPanel):
        """注入日志面板组件"""
        self.log_panel = log_panel
    
    # ==================== UI 事件处理 ====================
    
    def _on_preset_change(self):
        """预设切换时同步更新自定义边距输入框"""
        checked = self.preset_group.checkedButton()
        if checked:
            preset_key = checked.property("preset_key")
            if preset_key and preset_key in PRESETS:
                preset = PRESETS[preset_key]
                self.top_margin.setText(str(preset["top"]))
                self.bottom_margin.setText(str(preset["bottom"]))
                self.left_margin.setText(str(preset["left"]))
                self.right_margin.setText(str(preset["right"]))
                self.font_size.setText(str(preset.get("font_size", 12)))
                self.log(f"切换到预设：{preset['name']}")
    
    def _on_files_added(self, files: List[Path]):
        """文件列表添加文件回调"""
        added = self.file_list.add_files(files)
        if added > 0:
            self.log(f"添加了 {added} 个文件")
    
    def _add_files(self):
        """添加文件按钮"""
        files, _ = QFileDialog.getOpenFileNames(
            None, "选择 EPUB 文件", "", "EPUB 文件 (*.epub);;所有文件 (*.*)"
        )
        if files:
            added = self.file_list.add_files([Path(f) for f in files])
            self.log(f"添加了 {added} 个文件")
    
    def _add_folder(self):
        """添加文件夹按钮"""
        folder = QFileDialog.getExistingDirectory(
            None, "选择包含 EPUB 文件的文件夹"
        )
        if folder:
            folder_path = Path(folder)
            epub_files = list(folder_path.rglob("*.epub"))
            added = self.file_list.add_files(epub_files)
            self.log(f"从文件夹添加了 {added} 个文件")
    
    def _remove_selected(self):
        """移除选中按钮"""
        removed = self.file_list.remove_selected()
        if removed:
            self.log(f"移除了 {len(removed)} 个文件")
    
    def _clear_all(self):
        """清空全部按钮"""
        count = self.file_list.count()
        self.file_list.clear_all()
        if count > 0:
            self.log(f"清空了 {count} 个文件")
    
    def _select_output_dir(self):
        """选择输出目录"""
        directory = QFileDialog.getExistingDirectory(None, "选择输出目录")
        if directory:
            self.output_dir = Path(directory)
            self.output_dir_edit.setText(str(self.output_dir))
    
    def _on_output_dir_text_changed(self, text: str):
        """输出目录编辑框文本变化时同步更新（支持粘贴路径）
        
        仅当路径有效时才更新 self.output_dir，
        无效路径保留旧值，避免 UI 显示与内部状态不一致。
        """
        text = text.strip()
        if text:
            path = Path(text)
            if path.exists() and path.is_dir():
                self.output_dir = path
                self.output_dir_edit.setStyleSheet("")  # 恢复正常样式
            else:
                # 路径无效，设置警告样式
                self.output_dir_edit.setStyleSheet(
                    "border: 1px solid #e74c3c;"
                )
        else:
            self.output_dir = None
            self.output_dir_edit.setStyleSheet("")  # 恢复正常样式
    
    # ==================== 核心处理逻辑 ====================
    
    def _get_current_margins(self) -> Dict[str, int]:
        """获取当前页边距设置
        
        Returns:
            Dict[str, int]: 包含 top/bottom/left/right/font_size 的字典
        """
        try:
            return {
                "top": int(self.top_margin.text()),
                "bottom": int(self.bottom_margin.text()),
                "left": int(self.left_margin.text()),
                "right": int(self.right_margin.text()),
                "font_size": int(self.font_size.text())
            }
        except ValueError:
            # 输入非数字时回退到默认值
            return {
                "top": 0, "bottom": 0, "left": 0, "right": 0, "font_size": 12
            }
    
    # ★ ==================== 配置持久化（新增） ====================
    
    def get_config(self) -> dict:
        """收集 UI 上的所有设置"""
        return {
            EPUB2PdfKey.MARGINS: self._get_current_margins(),
            EPUB2PdfKey.SHOW_PAGE_NUMBERS: self.show_page_numbers_cb.isChecked(),
            EPUB2PdfKey.MAX_THREADS: self.worker_spin.value(),
            EPUB2PdfKey.AUTO_OPEN: self.auto_open_cb.isChecked(),
            EPUB2PdfKey.OUTPUT_DIR: str(self.output_dir) if self.output_dir else None,
        }

    def _load_config(self):
        """从 QSettings 读取并应用到 UI"""
        settings = QSettings(SettingsDomain.EPUB_TOOLBOX, SettingsDomain.SETTINGS)
        cfg = settings.value(EPUB2PdfKey.CONFIG, {})
        if not cfg:
            return

        # 恢复页边距
        margins = cfg.get(EPUB2PdfKey.MARGINS, {})
        if margins and hasattr(self, 'top_margin'):
            self.top_margin.setText(str(margins.get('top', 0)))
            self.bottom_margin.setText(str(margins.get('bottom', 0)))
            self.left_margin.setText(str(margins.get('left', 0)))
            self.right_margin.setText(str(margins.get('right', 0)))
            self.font_size.setText(str(margins.get('font_size', 12)))

        if hasattr(self, 'show_page_numbers_cb'):
            self.show_page_numbers_cb.setChecked(cfg.get(EPUB2PdfKey.SHOW_PAGE_NUMBERS, False))
        if hasattr(self, 'worker_spin'):
            self.worker_spin.setValue(cfg.get(EPUB2PdfKey.MAX_THREADS, 4))
        if hasattr(self, 'auto_open_cb'):
            self.auto_open_cb.setChecked(cfg.get(EPUB2PdfKey.AUTO_OPEN, False))

        output_dir_str = cfg.get(EPUB2PdfKey.OUTPUT_DIR)
        if output_dir_str:
            self.output_dir = Path(output_dir_str)
            if hasattr(self, 'output_dir_edit'):
                self.output_dir_edit.setText(output_dir_str)

    def _save_config(self):
        """保存设置到 QSettings"""
        settings = QSettings(SettingsDomain.EPUB_TOOLBOX, SettingsDomain.SETTINGS)
        settings.setValue(EPUB2PdfKey.CONFIG, self.get_config())

    def on_activate(self):
        """模块被激活（切换到此标签页）时调用"""
        self._load_config()
        self.log(f"已切换到 {self.module_name}", "INFO")

    def on_deactivate(self):
        """模块失去焦点（切换到其他模块或关闭窗口）时调用"""
        self._save_config()
        if getattr(self, 'is_processing', False):
            self.stop_processing()
    
    # ★ ==================== 配置持久化结束 ====================
    
    def start_processing(self, files: List[Path] = None, **kwargs) -> bool:
        """开始批量转换
        
        Args:
            files: 可选的文件列表，为 None 时从文件列表组件获取
            **kwargs: 额外参数（预留扩展）
            
        Returns:
            bool: 是否成功启动处理
        """
        # -- 确定要处理的文件列表 --
        if self.force_reprocess_cb.isChecked():
            all_files = self.file_list.get_all_files()
            if not all_files:
                QMessageBox.warning(None, "警告", "请先添加要转换的 EPUB 文件")
                return False
            self.file_list.reset_all_status()
            files = self.file_list.get_all_files()
            self.log(
                f"🔄 强制重新处理模式：将重新转换全部 {len(files)} 个文件", 
                "INFO"
            )
        else:
            files = self.file_list.get_pending_files()
            if not files:
                all_files = self.file_list.get_all_files()
                if all_files:
                    failed_files = self.file_list.get_files_by_status(FileStatus.FAILED)
                    if failed_files:
                        reply = QMessageBox.question(
                            None, "提示",
                            f"有 {len(failed_files)} 个文件转换失败，是否重试？\n\n"
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
                            "所有文件都已转换完成！\n\n"
                            "如需重新处理，请勾选「忽略状态」选项。"
                        )
                        return False
                else:
                    QMessageBox.warning(None, "警告", "请先添加要转换的 EPUB 文件")
                    return False
        
        # -- 依赖检查 --
        calibre_ok, _ = check_calibre()
        if not calibre_ok:
            QMessageBox.critical(
                None, "错误", 
                "未找到 Calibre 转换工具！\n\n"
                "请安装 Calibre 电子书管理软件\n"
                "下载地址：https://calibre-ebook.com/"
            )
            return False
        
        # -- 输出路径校验 --
        if self.output_dir_edit.text().strip() and not self.output_dir:
            QMessageBox.warning(
                None, "警告", 
                "输出路径无效，请检查路径是否正确，或清空使用默认目录"
            )
            return False
        
        # -- 确认对话框 --
        margins = self._get_current_margins()
        
        page_num_text = "显示页码：是\n" if self.show_page_numbers_cb.isChecked() else ""
        
        reply = QMessageBox.question(
            None, "确认",
            f"即将转换 {len(files)} 个文件。\n\n"
            f"页边距：上{margins['top']} 下{margins['bottom']} "
            f"左{margins['left']} 右{margins['right']} "
            f"字号{margins['font_size']}\n"
            f"{page_num_text}"
            f"输出模式：{'统一目录' if self.output_dir else '跟随源文件'}\n\n"
            f"是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return False
        
        # -- 启动处理 --
        self.is_processing = True
        
        if self.progress_bar:
            self.progress_bar.setValue(0)
        
        output_mode = "custom" if self.output_dir else "source"
        margins = self._get_current_margins()
        
        # 记录转换参数
        self.log("=" * 60)
        self.log(f"开始批量转换 {len(files)} 个文件...")
        self.log(
            f"输出模式: {'统一目录' if output_mode == 'custom' else '跟随源文件'}"
        )
        self.log(
            f"页边距: 上{margins['top']} 下{margins['bottom']} "
            f"左{margins['left']} 右{margins['right']} 字号{margins['font_size']}"
        )
        self.log(f"并行线程数: {self.worker_spin.value()}")
        self.log("=" * 60)
        
        # 创建并启动工作线程
        self.worker = ConversionWorker(
            input_files=files,
            output_mode=output_mode,
            output_dir=self.output_dir,
            margins=margins,
            max_workers=self.worker_spin.value(),
            auto_open=self.auto_open_cb.isChecked(),
            show_page_numbers=self.show_page_numbers_cb.isChecked()
        )
        
        # 连接信号
        self.worker.progress_updated.connect(self._on_progress_updated)
        self.worker.file_status_signal.connect(self._on_file_status_changed)
        self.worker.log_message.connect(self.log)
        self.worker.finished_all.connect(self._on_finished)
        
        self.worker.start()
        return True
    
    def stop_processing(self):
        """停止当前转换（优雅停止，不强制终止正在转换的任务）"""
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.log("正在停止转换...", "WARNING")
    
    # ==================== Worker 回调 ====================
    
    def _on_progress_updated(self, value: int, message: str, 
                             completed: int, total: int):
        """进度更新回调"""
        if self.progress_bar:
            self.progress_bar.setValue(value)
        self.update_progress(value, message)
    
    def _on_file_status_changed(self, file_path: Path, status: str):
        """文件状态变更回调"""
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
        """转换完成回调"""
        self.is_processing = False
        
        if self.progress_bar:
            self.progress_bar.setValue(100)
        
        # 统计结果
        success_count = sum(1 for r in results if r['status'] == 'success')
        failed_count = len(results) - success_count
        
        # ★ 保存用户设置
        self._save_config()
        
        self.log("")
        self.log("=" * 60)
        self.log(f"转换完成！成功: {success_count}, 失败: {failed_count}", "SUCCESS")
        
        if failed_count > 0:
            self.log("失败列表:", "WARNING")
            for r in results:
                if r['status'] == 'failed':
                    self.log(
                        f"  - {Path(r['file']).name}: {r['message']}", 
                        "ERROR"
                    )
        self.log("=" * 60)
        
        self.update_progress(
            100, f"完成 - 成功: {success_count}, 失败: {failed_count}"
        )
        
        # 重置强制重处理复选框
        if self.force_reprocess_cb.isChecked():
            self.force_reprocess_cb.setChecked(False)
        
        # 显示完成提示
        QMessageBox.information(
            None, "完成",
            f"转换任务已完成！\n\n成功: {success_count} 个\n失败: {failed_count} 个"
        )


# ==================== 元信息 ====================
__author__ = "YQJ"
__version__ = "1.2.0"
__date__ = "2026.05.23"