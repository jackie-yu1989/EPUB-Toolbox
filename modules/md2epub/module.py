#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MD转EPUB模块 - PyQt6界面封装
提供 Markdown 到 EPUB 的批量转换功能，支持多种排版风格和主题颜色
"""

import os
import sys
import time
import shutil
import logging
import subprocess
from pathlib import Path
from typing import List, Tuple, Optional, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from threading import Event

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QRadioButton, QSpinBox, QCheckBox, QLineEdit,
    QFileDialog, QGridLayout, QMessageBox, QComboBox, QFrame
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QSettings

from core.base_module import BaseModule
from core.components import UnifiedFileListWidget, FileStatus, LogPanel
from core.utils import check_pandoc, check_mermaid
from core.theme_manager import ThemeManager
# ★ 导入常量化配置键
from core.config_keys import SettingsDomain, MD2EpubKey
from .processor import convert_markdown_to_epub
from modules.md_repair.processor import MarkdownTitleExtractor
from core.components.file_list import DropHotzoneMixin

# 模块级日志记录器
logger = logging.getLogger(__name__)


class ConversionWorker(QThread):
    """MD 转 EPUB 工作线程
    
    使用 ThreadPoolExecutor 实现多文件并行转换。
    支持 YAML 标题重命名、临时文件分散管理、智能打开输出目录。
    """
    
    # 信号定义
    progress_updated = pyqtSignal(int, str, int, int)
    file_status_signal = pyqtSignal(Path, str)
    file_completed = pyqtSignal(dict)
    log_message = pyqtSignal(str, str)
    finished_all = pyqtSignal(list)
    temp_roots_created = pyqtSignal(list)
    
    def __init__(self, input_files: List[Path], output_mode: str, 
                 output_dir: Optional[Path] = None,
                 css: str = "", max_workers: int = 4, keep_temp: bool = False,
                 auto_open: bool = False, rename_with_title: bool = False,
                 title_fields: Optional[List[str]] = None,
                 use_yaml_title: bool = True):
        """初始化工作线程
        
        Args:
            input_files: 待转换的 Markdown 文件列表
            output_mode: 输出模式 "custom" | "source"
            output_dir: 自定义输出目录
            css: EPUB CSS 样式
            max_workers: 最大并行线程数
            keep_temp: 是否保留临时文件
            auto_open: 完成后是否自动打开输出目录
            rename_with_title: 是否使用 YAML 标题重命名
            title_fields: YAML 标题字段优先级列表
        """
        super().__init__()
        self.input_files = input_files
        self.output_mode = output_mode
        self.output_dir = output_dir
        self.css = css
        self.max_workers = max_workers
        self.keep_temp = keep_temp
        self.auto_open = auto_open
        self.rename_with_title = rename_with_title
        self.title_fields = title_fields
        self._stop_event = Event()  # ★ 使用 Event 替代布尔标志
        self.results = []
        self.temp_roots = set()
        self.use_yaml_title = use_yaml_title
        # 初始化标题提取器
        if rename_with_title:
            self.title_extractor = MarkdownTitleExtractor()
        else:
            self.title_extractor = None
    
    def stop(self):
        """优雅停止转换"""
        self._stop_event.set()
        logger.debug("转换工作线程收到停止信号")
    
    def _get_temp_root_for_file(self, md_file: Path) -> Path:
        """获取指定文件的临时根目录"""
        if self.output_mode == "custom" and self.output_dir:
            return self.output_dir / ".epub_temp"
        else:
            return md_file.parent / ".epub_temp"
    
    def _get_unique_output_path(self, output_path: Path) -> Path:
        """获取唯一的输出路径（避免覆盖已有文件）
        
        策略：
            1. 路径不存在 → 直接返回
            2. 存在 → 依次尝试 _1, _2, ... _999 后缀
            3. 全部冲突 → 使用时间戳后缀
        """
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
        
        # 收集并创建所有临时根目录
        for md_file in self.input_files:
            temp_root = self._get_temp_root_for_file(md_file)
            self.temp_roots.add(temp_root)
            temp_root.mkdir(parents=True, exist_ok=True)
        
        self.temp_roots_created.emit(list(self.temp_roots))
        
        self.log_message.emit(
            f"开始转换 {total} 个文件，并行数: {self.max_workers}", "INFO"
        )
        if len(self.temp_roots) == 1:
            self.log_message.emit(
                f"📁 临时文件目录: {list(self.temp_roots)[0]}", "INFO"
            )
        else:
            self.log_message.emit(
                f"📁 临时文件分布在 {len(self.temp_roots)} 个目录", "INFO"
            )
        
        if self.rename_with_title:
            self.log_message.emit("🔍 YAML标题重命名已启用", "INFO")
        
        start_total = time.time()
        completed = 0
        rename_count = 0
        
        # 预处理：为每个文件生成最终输出路径
        file_output_map = {}
        
        for md_file in self.input_files:
            if self.output_mode == "custom" and self.output_dir:
                output_dir_path = Path(self.output_dir).resolve()
            else:
                output_dir_path = md_file.resolve().parent
            
            output_dir_path.mkdir(parents=True, exist_ok=True)
            
            if self.rename_with_title and self.title_extractor:
                new_name, title_used, extracted_title = \
                    self.title_extractor.generate_name(md_file, output_dir_path)
                if title_used:
                    new_name = new_name.replace('.md', '.epub')
                    if not new_name.endswith('.epub'):
                        base = new_name.rsplit('.', 1)[0] if '.' in new_name else new_name
                        new_name = base + '.epub'
                    output_epub = output_dir_path / new_name
                    rename_count += 1
                    self.log_message.emit(
                        f"📝 将重命名: {md_file.name} → {new_name}（标题: {extracted_title}）",
                        "INFO"
                    )
                else:
                    output_epub = output_dir_path / md_file.with_suffix('.epub').name
                    title_used = False
                    extracted_title = None
            else:
                output_epub = output_dir_path / md_file.with_suffix('.epub').name
                title_used = False
                extracted_title = None
            
            output_epub = self._get_unique_output_path(output_epub)
            file_output_map[md_file] = (output_epub, title_used, extracted_title)
        
        if self.rename_with_title and rename_count > 0:
            self.log_message.emit(
                f"📊 共 {rename_count}/{total} 个文件将使用YAML标题命名", "INFO"
            )
        elif self.rename_with_title:
            self.log_message.emit("ℹ️ 未找到有效的YAML标题，将使用原文件名", "INFO")
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures: Dict[Future, Tuple[Path, Path, Path, Path, bool, Optional[str]]] = {}
            
            for md_file in self.input_files:
                if self._stop_event.is_set():
                    self.log_message.emit("转换已被用户停止", "WARNING")
                    break
                
                self.file_status_signal.emit(md_file, 'processing')
                
                output_epub, title_used, extracted_title = file_output_map[md_file]
                
                temp_root = self._get_temp_root_for_file(md_file)
                work_dir = temp_root / f"{md_file.stem}_{int(time.time()*1000)}"
                
                def log_callback(msg):
                    self.log_message.emit(f"   {msg}", "INFO")
                
                future = executor.submit(
                    self._convert_single_file,
                    md_file, output_epub, work_dir, log_callback
                )
                futures[future] = (
                    md_file, output_epub, work_dir, temp_root, 
                    title_used, extracted_title
                )
            
            for future in as_completed(futures):
                if self._stop_event.is_set():
                    break
                
                (md_file, output_epub, work_dir, temp_root, 
                 title_used, extracted_title) = futures[future]
                completed += 1
                
                try:
                    success, msg, elapsed = future.result(timeout=300)
                    
                    if success:
                        self.file_status_signal.emit(md_file, 'success')
                        
                        result_entry = {
                            'file': str(md_file),
                            'output': str(output_epub),
                            'status': 'success',
                            'message': msg,
                            'temp_root': str(temp_root),
                            'title_used': title_used
                        }
                        
                        if title_used:
                            result_entry['extracted_title'] = extracted_title
                            result_entry['original_name'] = md_file.name
                            result_entry['new_name'] = output_epub.name
                            self.log_message.emit(
                                f"✅ [{completed}/{total}] {md_file.name} → "
                                f"{output_epub.name} ({elapsed:.1f}秒)\n"
                                f"   📝 已重命名（标题: {extracted_title}）",
                                "SUCCESS"
                            )
                        else:
                            self.log_message.emit(
                                f"✅ [{completed}/{total}] {md_file.name} → "
                                f"{output_epub.name} ({elapsed:.1f}秒)",
                                "SUCCESS"
                            )
                        
                        self.results.append(result_entry)
                    else:
                        self.file_status_signal.emit(md_file, 'failed')
                        self.log_message.emit(
                            f"❌ [{completed}/{total}] {md_file.name} - "
                            f"失败: {msg}",
                            "ERROR"
                        )
                        self.results.append({
                            'file': str(md_file),
                            'status': 'failed',
                            'message': msg
                        })
                    
                    # 清理单个文件的临时目录
                    if not self.keep_temp and work_dir.exists():
                        shutil.rmtree(work_dir, ignore_errors=True)
                    
                except Exception as e:
                    self.file_status_signal.emit(md_file, 'failed')
                    self.log_message.emit(
                        f"❌ {md_file.name} - 异常: {str(e)}", "ERROR"
                    )
                    self.results.append({
                        'file': str(md_file),
                        'status': 'failed',
                        'message': str(e)
                    })
                    
                    if not self.keep_temp and work_dir.exists():
                        shutil.rmtree(work_dir, ignore_errors=True)
                
                progress = int(completed / total * 100) if total > 0 else 0
                self.progress_updated.emit(
                    progress, f"转换中... {completed}/{total}", completed, total
                )
        
        total_time = time.time() - start_total
        
        # 清理空的临时根目录
        if not self.keep_temp:
            for temp_root in self.temp_roots:
                self._clean_empty_temp_root(temp_root)
        
        if self.rename_with_title and rename_count > 0:
            self.log_message.emit(f"📊 本次共重命名 {rename_count} 个文件", "INFO")
        
        self.log_message.emit(f"总耗时: {total_time:.1f}秒", "INFO")
        
        # 智能打开输出目录
        if not self._stop_event.is_set() and self.auto_open:
            if self.output_mode == "custom" and self.output_dir:
                self._open_folder(self.output_dir)
                self.log_message.emit(
                    f"📂 已打开输出目录: {self.output_dir}", "INFO"
                )
            elif self.input_files:
                self._smart_open_output_folders()
        
        self.finished_all.emit(self.results)
    
    def _convert_single_file(self, md_file: Path, output_epub: Path, 
                             work_dir: Path, log_callback) -> Tuple[bool, str, float]:
        """转换单个文件"""
        start_time = time.time()
        
        work_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            success, msg = convert_markdown_to_epub(
                md_file, output_epub, work_dir, self.css, log_callback,
                use_yaml_title=self.use_yaml_title
            )
            elapsed = time.time() - start_time
            return success, msg, elapsed
            
        except Exception as e:
            return False, str(e), time.time() - start_time
    
    def _clean_empty_temp_root(self, temp_root: Path):
        """清理空的临时根目录"""
        if temp_root.exists():
            try:
                if not any(temp_root.iterdir()):
                    temp_root.rmdir()
            except Exception:
                pass
    
    def _smart_open_output_folders(self):
        """智能打开输出文件夹"""
        output_folders = set()
        for res in self.results:
            if res.get('status') == 'success' and res.get('output'):
                # ✅ 强制 resolve，杜绝相对路径
                output_folders.add(Path(res['output']).resolve().parent)

        # ✅ 兜底：如果 results 为空（例如全部失败），使用输入文件的绝对父目录
        if not output_folders:
            output_folders = set(f.resolve().parent for f in self.input_files)
            
        if not output_folders:
            return

        folder_list = list(output_folders)
        if len(folder_list) == 1:
            self._open_folder(folder_list[0])
            self.log_message.emit(f"📂 已打开输出目录: {folder_list[0]}", "INFO")
        elif len(folder_list) <= 3:
            for folder in folder_list:
                self._open_folder(folder)
            self.log_message.emit(f"📂 已打开 {len(folder_list)} 个输出目录", "INFO")
        else:
            self._open_folder(folder_list[0])
            self.log_message.emit(f"📂 输出文件分布在 {len(folder_list)} 个不同目录，已打开第一个目录: {folder_list[0]}", "INFO")
    
    @staticmethod
    def _open_folder(folder: Path):
        """跨平台打开文件夹"""
        try:
            # ✅ 终极保险：强制转换为绝对路径，防止 Windows explorer 打开"文档"
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


class MD2EPUBModule(BaseModule):
    """MD 转 EPUB 模块
    
    将 Markdown 文件批量转换为精美排版的 EPUB 电子书。
    支持两种排版风格、10种主题颜色、YAML标题重命名、批量并行处理。
    """
    
    # ==================== 模块元信息 ====================
    
    @property
    def module_id(self) -> str:
        return "md2epub"
    
    @property
    def module_name(self) -> str:
        return "2-MD转EPUB"
    
    @property
    def module_icon(self) -> str:
        return "📖"
    
    @property
    def module_description(self) -> str:
        return (
            "Markdown → EPUB 精美排版电子书。"
            "外部CSS自动发现、10色主题、YAML标题、Mermaid图表。"
        )
    
    @property
    def accepted_extensions(self) -> List[str]:
        return ['.md']
    
    # ==================== 依赖检查 ====================
    
    def check_dependencies(self) -> Tuple[bool, str]:
        """检查 Pandoc 和 Mermaid 依赖"""
        pandoc_ok, pandoc_msg = check_pandoc()
        if not pandoc_ok:
            return False, "未找到 Pandoc，请先安装 Pandoc"
        
        mermaid_ok, mermaid_msg = check_mermaid()
        if mermaid_ok:
            return True, "Pandoc 已就绪，Mermaid 可用"
        else:
            return True, "Pandoc 已就绪（Mermaid 不可用，图表将被跳过）"
    
    # ==================== UI 构建 ====================
    
    def create_ui(self, parent=None) -> QWidget:
        """创建模块 UI 界面"""
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
        self.last_temp_roots: List[Path] = []
        
        return widget
    
    def _create_file_section(self) -> QGroupBox:
        """创建文件列表区域"""
        file_group = QGroupBox("📁 选择 Markdown 文件（支持拖拽，Ctrl+V）")
        file_layout = QVBoxLayout(file_group)
        
        self.file_list = UnifiedFileListWidget(['.md'])
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
        
        # 忽略状态复选框
        self.force_reprocess_cb = QCheckBox("忽略状态")
        self.force_reprocess_cb.setToolTip(
            "默认情况下，已经转换过的文件不会再次转换。\n"
            "勾选此项后，将重新转换列表中的所有文件。\n\n"
            "适用场景：\n"
            "• 修改了CSS样式或主题颜色后想重新转换\n"
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
        options_layout = QGridLayout()
        
        # CSS 样式选择（动态发现）
        options_layout.addWidget(QLabel("CSS样式:"), 0, 0)
        css_layout = QHBoxLayout()

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
                # 没有任何 CSS 声明 @default: true 时的回退
                rb.setChecked(True)
                default_found = True
            self.css_buttons[style_info.key] = rb
            css_layout.addWidget(rb)

        css_layout.addStretch()
        options_layout.addLayout(css_layout, 0, 1, 1, 2)
        
        # 主题颜色选择
        options_layout.addWidget(QLabel("主题颜色:"), 1, 0)
        color_layout = QHBoxLayout()
        self.color_combo = QComboBox()
        self.color_combo.setFixedWidth(100)
        
        tm = ThemeManager()
        self.color_presets = tm.get_color_presets()
        for color_key, color_info in self.color_presets.items():
            self.color_combo.addItem(f"{color_info['name']}", color_key)
        self.color_combo.setCurrentIndex(0)
        color_layout.addWidget(self.color_combo)
        
        self.color_preview = QLabel("预览")
        self.color_preview.setFixedSize(50, 25)
        self.color_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        color_layout.addWidget(self.color_preview)
        color_layout.addStretch()
        options_layout.addLayout(color_layout, 1, 1, 1, 2)
        
        self.color_combo.currentIndexChanged.connect(self._on_color_changed)
        self._on_color_changed(0)
        
        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #dee2e6; margin: 5px 0;")
        options_layout.addWidget(sep, 2, 0, 1, 4)
        
        # 并行线程数
        options_layout.addWidget(QLabel("并行线程数:"), 3, 0)
        
        cpu_count = os.cpu_count() or 4
        default_workers = min(4, cpu_count)  # ★ 自适应默认值
        
        self.worker_spin = QSpinBox()
        self.worker_spin.setMinimum(1)
        self.worker_spin.setMaximum(16)
        self.worker_spin.setValue(default_workers)
        self.worker_spin.setFixedWidth(80)
        options_layout.addWidget(self.worker_spin, 3, 1)
        
        cpu_label = QLabel(f"(CPU: {cpu_count}核)")
        cpu_label.setObjectName("infoLabel")
        options_layout.addWidget(cpu_label, 3, 2)
        
        # 保留临时文件
        self.keep_temp_cb = QCheckBox("保留临时文件（用于调试）")
        options_layout.addWidget(self.keep_temp_cb, 4, 0, 1, 3)
        
        # 自动打开
        self.auto_open_cb = QCheckBox("转换完成后打开输出目录")
        options_layout.addWidget(self.auto_open_cb, 5, 0, 1, 3)

        # ★ 新增：YAML标题作为EPUB内部标题
        self.use_yaml_title_cb = QCheckBox("使用YAML标题作为EPUB内部标题")
        self.use_yaml_title_cb.setChecked(True)  # 默认勾选
        self.use_yaml_title_cb.setToolTip(
            "勾选后，程序将读取Markdown文件的YAML头部信息，\n"
            "提取title字段作为EPUB电子书的内部标题（显示在书籍元数据和正文开头）。\n"
            "取消勾选则使用文件名作为标题。"
        )
        options_layout.addWidget(self.use_yaml_title_cb, 6, 0, 1, 3)
        
        # YAML 标题重命名
        self.rename_with_title_cb = QCheckBox("使用YAML标题重命名输出文件")
        self.rename_with_title_cb.setToolTip(
            "勾选后，程序将读取Markdown文件的YAML头部信息，\n"
            "提取title字段作为输出EPUB文件名。\n"
            "支持的字段：title、标题、name、slug、文件名\n"
            "未找到标题时使用原文件名（向后兼容）。"
        )
        options_layout.addWidget(self.rename_with_title_cb, 7, 0, 1, 3)
        
        options_layout.setColumnStretch(3, 1)
        options_group.setLayout(options_layout)
        
        return options_group
    
    # ==================== 外部注入 ====================
    
    def set_progress_bar(self, progress_bar):
        """注入进度条组件"""
        self.progress_bar = progress_bar
    
    def set_log_panel(self, log_panel: LogPanel):
        """注入日志面板组件"""
        self.log_panel = log_panel
    
    # ==================== UI 事件处理 ====================
    
    def _on_color_changed(self, index: int):
        """颜色选择变化时更新预览色块"""
        color_key = self.color_combo.currentData()
        color_info = self.color_presets.get(color_key, {})
        color_code = color_info.get('color', '#3498db')
        color_name = color_info.get('name', '预览')
        
        # 根据亮度自动选择文字颜色
        r, g, b = int(color_code[1:3], 16), int(color_code[3:5], 16), int(color_code[5:7], 16)
        brightness = (r * 299 + g * 587 + b * 114) / 1000
        text_color = "white" if brightness < 128 else "#333333"
        
        self.color_preview.setStyleSheet(f"""
            background-color: {color_code};
            border-radius: 4px;
            color: {text_color};
            font-weight: bold;
            font-size: 9pt;
        """)
        self.color_preview.setText(color_name[:4])
    
    def _on_output_dir_text_changed(self, text: str):
        """输出目录编辑框文本变化时同步更新（支持粘贴路径）"""
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
    
    def _on_files_added(self, files: List[Path]):
        added = self.file_list.add_files(files)
        if added > 0:
            self.log(f"添加了 {added} 个文件")
    
    def _add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            None, "选择Markdown文件", "",
            "Markdown文件 (*.md);;所有文件 (*.*)"
        )
        if files:
            added = self.file_list.add_files([Path(f) for f in files])
            self.log(f"添加了 {added} 个文件")
    
    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(
            None, "选择包含Markdown文件的文件夹"
        )
        if folder:
            folder_path = Path(folder)
            md_files = list(folder_path.rglob("*.md")) + list(folder_path.rglob("*.MD"))
            added = self.file_list.add_files(md_files)
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
    
    # ==================== 临时文件管理 ====================
    
    def _get_temp_roots_info(self) -> List[Tuple[Path, int, int]]:
        """获取临时文件目录信息"""
        info_list = []
        for temp_root in self.last_temp_roots:
            if temp_root.exists():
                file_count = 0
                total_size = 0
                for root, _, files in os.walk(temp_root):
                    for f in files:
                        fp = Path(root) / f
                        if fp.exists():
                            total_size += fp.stat().st_size
                            file_count += 1
                if file_count > 0:
                    info_list.append((temp_root, file_count, total_size))
        return info_list
    
    def _clean_all_temp_files(self) -> bool:
        """清理所有临时文件"""
        success = True
        for temp_root in self.last_temp_roots:
            if temp_root.exists():
                try:
                    shutil.rmtree(temp_root, ignore_errors=True)
                except Exception:
                    success = False
        self.last_temp_roots = []
        return success
    
    def _show_temp_files_cleanup_dialog(self, success_count: int):
        """显示临时文件清理对话框
        
        Args:
            success_count: 成功转换的文件数
        """
        temp_info = self._get_temp_roots_info()
        if not temp_info:
            return
        
        # 构建详细信息
        details = []
        total_size = 0
        total_files = 0
        for path, count, size in temp_info:
            size_mb = size / (1024 * 1024)
            details.append(f"• {path}\n  ({count} 个文件, {size_mb:.2f} MB)")
            total_files += count
            total_size += size
        
        total_mb = total_size / (1024 * 1024)
        details_text = "\n\n".join(details)
        
        msg_box = QMessageBox()
        msg_box.setWindowTitle("清理临时文件")
        msg_box.setIcon(QMessageBox.Icon.Question)
        
        if len(temp_info) == 1:
            msg_box.setText(
                f"已保留 {success_count} 个文件的临时文件。\n\n"
                f"临时文件位置:\n{details_text}\n\n"
                f"是否清理临时文件？"
            )
            open_text = "打开临时文件夹"
        else:
            msg_box.setText(
                f"已保留 {success_count} 个文件的临时文件。\n\n"
                f"临时文件分布:\n{details_text}\n\n"
                f"总计: {len(temp_info)} 个位置, {total_mb:.2f} MB\n\n"
                f"是否清理所有临时文件？"
            )
            open_text = f"打开所有临时文件夹 ({len(temp_info)}个)"
        
        yes_btn = msg_box.addButton("是", QMessageBox.ButtonRole.YesRole)
        no_btn = msg_box.addButton("否", QMessageBox.ButtonRole.NoRole)
        open_btn = msg_box.addButton(open_text, QMessageBox.ButtonRole.ActionRole)
        
        msg_box.exec()
        clicked_btn = msg_box.clickedButton()
        
        if clicked_btn == yes_btn:
            if self._clean_all_temp_files():
                self.log("✅ 已清理所有临时文件", "SUCCESS")
        elif clicked_btn == open_btn:
            opened_count = 0
            for temp_root in self.last_temp_roots:
                if temp_root.exists():
                    folder = str(temp_root)
                    if sys.platform == 'win32':
                        subprocess.run(['explorer', folder], shell=True)
                    elif sys.platform == 'darwin':
                        subprocess.run(['open', folder])
                    else:
                        subprocess.run(['xdg-open', folder])
                    opened_count += 1
            
            if opened_count == 1:
                self.log("📂 已打开临时文件夹", "INFO")
            else:
                self.log(f"📂 已打开 {opened_count} 个临时文件夹", "INFO")
    
    # ★ ==================== 配置持久化（新增） ====================
    
    def get_config(self) -> dict:
        """收集 UI 上的所有设置"""
        return {
            MD2EpubKey.CSS_STYLE: self._get_selected_css_style(),
            MD2EpubKey.COLOR_KEY: self.color_combo.currentData(),
            MD2EpubKey.MAX_THREADS: self.worker_spin.value(),
            MD2EpubKey.KEEP_TEMP: self.keep_temp_cb.isChecked(),
            MD2EpubKey.AUTO_OPEN: self.auto_open_cb.isChecked(),
            MD2EpubKey.RENAME_WITH_TITLE: self.rename_with_title_cb.isChecked(),
            MD2EpubKey.USE_YAML_TITLE: self.use_yaml_title_cb.isChecked(),
            MD2EpubKey.OUTPUT_DIR: str(self.output_dir) if self.output_dir else None,
        }

    def _load_config(self):
        """从 QSettings 读取并应用到 UI"""
        settings = QSettings(SettingsDomain.EPUB_TOOLBOX, SettingsDomain.SETTINGS)
        cfg = settings.value(MD2EpubKey.CONFIG, {})
        if not cfg:
            return
        
        css_style = cfg.get(MD2EpubKey.CSS_STYLE, "clean")
        if hasattr(self, 'css_buttons') and css_style in self.css_buttons:
            self.css_buttons[css_style].setChecked(True)
        
        color_key = cfg.get(MD2EpubKey.COLOR_KEY, "blue")
        if hasattr(self, 'color_combo'):
            idx = self.color_combo.findData(color_key)
            if idx >= 0:
                self.color_combo.setCurrentIndex(idx)
        
        if hasattr(self, 'worker_spin'):
            self.worker_spin.setValue(cfg.get(MD2EpubKey.MAX_THREADS, 4))
        if hasattr(self, 'keep_temp_cb'):
            self.keep_temp_cb.setChecked(cfg.get(MD2EpubKey.KEEP_TEMP, False))
        if hasattr(self, 'auto_open_cb'):
            self.auto_open_cb.setChecked(cfg.get(MD2EpubKey.AUTO_OPEN, False))
        if hasattr(self, 'rename_with_title_cb'):
            self.rename_with_title_cb.setChecked(cfg.get(MD2EpubKey.RENAME_WITH_TITLE, False))
        if hasattr(self, 'use_yaml_title_cb'):
            self.use_yaml_title_cb.setChecked(cfg.get(MD2EpubKey.USE_YAML_TITLE, True))
        
        output_dir_str = cfg.get(MD2EpubKey.OUTPUT_DIR)
        if output_dir_str:
            self.output_dir = Path(output_dir_str)
            if hasattr(self, 'output_dir_edit'):
                self.output_dir_edit.setText(output_dir_str)

    def _save_config(self):
        """保存设置到 QSettings"""
        settings = QSettings(SettingsDomain.EPUB_TOOLBOX, SettingsDomain.SETTINGS)
        settings.setValue(MD2EpubKey.CONFIG, self.get_config())

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
    
    # ==================== 核心处理逻辑 ====================
    
    def start_processing(self, files: List[Path] = None, **kwargs) -> bool:
        """开始批量转换"""
        # 确定文件列表
        if self.force_reprocess_cb.isChecked():
            all_files = self.file_list.get_all_files()
            if not all_files:
                QMessageBox.warning(None, "警告", "请先添加要转换的Markdown文件")
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
                        f"有 {len(failed_files)} 个文件转换失败，是否重试？",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    )
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
                QMessageBox.warning(None, "警告", "请先添加要转换的Markdown文件")
                return False
        
        # 依赖检查
        pandoc_ok, _ = check_pandoc()
        if not pandoc_ok:
            QMessageBox.critical(None, "错误", "未检测到 Pandoc，无法进行转换")
            return False
        
        # 输出路径校验
        if self.output_dir_edit.text().strip() and not self.output_dir:
            QMessageBox.warning(
                None, "警告",
                "输出路径无效，请检查路径是否正确，或清空使用默认目录"
            )
            return False
        
        # 确认对话框
        if self.rename_with_title_cb.isChecked():
            confirm_msg = (
                f"即将转换 {len(files)} 个文件。\n\n"
                "已启用「YAML标题重命名」功能：\n"
                "• 程序将读取每个文件的YAML头部\n"
                "• 提取title字段作为输出EPUB文件名\n"
                "• 未找到标题的文件将使用原文件名\n\n"
                "是否继续？"
            )
        else:
            confirm_msg = (
                f"即将转换 {len(files)} 个文件。\n\n"
                f"输出模式：{'统一目录' if self.output_dir else '跟随源文件'}\n"
                f"是否继续？"
            )

        reply = QMessageBox.question(
            None, "确认", confirm_msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return False
        
        # 启动处理
        self.is_processing = True
        
        if self.progress_bar:
            self.progress_bar.setValue(0)
        
        output_mode = "custom" if self.output_dir else "source"
        
        # 生成 CSS
        tm = ThemeManager()
        color_key = self.color_combo.currentData()
        color_info = self.color_presets.get(color_key, {})
        primary_color = color_info.get('color', None)
        
        style_key = self._get_selected_css_style()
        css = tm.get_css_with_color(style_key, primary_color)

        # 获取风格名称用于日志
        from core.css_manager import CssManager
        for s in CssManager().discover_styles():
            if s.key == style_key:
                style_name = s.name
                break
        else:
            style_name = style_key
        
        self.log("=" * 60)
        self.log(f"开始批量转换 {len(files)} 个文件...")
        self.log(f"输出模式: {'统一目录' if output_mode == 'custom' else '跟随源文件'}")
        self.log(f"CSS样式: {style_name}")
        self.log(f"主题颜色: {color_info.get('name', '默认')}")
        self.log(f"并行线程数: {self.worker_spin.value()}")
        self.log(f"YAML标题重命名: {'启用' if self.rename_with_title_cb.isChecked() else '禁用'}")
        self.log("=" * 60)
        
        # 创建并启动工作线程
        self.worker = ConversionWorker(
            input_files=files,
            output_mode=output_mode,
            output_dir=self.output_dir,
            css=css,
            max_workers=self.worker_spin.value(),
            keep_temp=self.keep_temp_cb.isChecked(),
            auto_open=self.auto_open_cb.isChecked(),
            rename_with_title=self.rename_with_title_cb.isChecked(),
            use_yaml_title=self.use_yaml_title_cb.isChecked(), 
        )
        
        self.worker.temp_roots_created.connect(self._on_temp_roots_created)
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
    
    # ==================== Worker 回调 ====================
    
    def _on_temp_roots_created(self, temp_roots: List[Path]):
        self.last_temp_roots = temp_roots
    
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
            file_path, status_map.get(status, FileStatus.PENDING)
        )
    
    def _on_finished(self, results: list):
        """转换完成回调"""
        self.is_processing = False
        
        if self.progress_bar:
            self.progress_bar.setValue(100)
        
        success_count = sum(1 for r in results if r['status'] == 'success')
        failed_count = len(results) - success_count
        
        # ★ 保存用户设置
        self._save_config()
        
        self.log("")
        self.log("=" * 60)
        self.log(f"转换完成！成功: {success_count}, 失败: {failed_count}", "SUCCESS")
        
        # YAML 重命名统计
        if self.rename_with_title_cb.isChecked() and success_count > 0:
            renamed_count = sum(1 for r in results if r.get('title_used'))
            if renamed_count > 0:
                self.log(f"📝 YAML标题重命名: {renamed_count} 个文件", "INFO")
                for r in results:
                    if r.get('title_used') and r['status'] == 'success':
                        self.log(
                            f"   {r.get('original_name', '')} → "
                            f"{r.get('new_name', '')}", 
                            "INFO"
                        )
            if success_count - renamed_count > 0:
                self.log(
                    f"ℹ️ {success_count - renamed_count} 个文件未找到YAML标题，"
                    f"使用原文件名", 
                    "INFO"
                )
        
        # 失败列表
        if failed_count > 0:
            self.log("失败列表:", "WARNING")
            for r in results:
                if r['status'] == 'failed':
                    self.log(
                        f"  - {Path(r['file']).name}: {r['message']}", 
                        "ERROR"
                    )
        self.log("=" * 60)
        
        self.update_progress(100, f"完成 - 成功: {success_count}, 失败: {failed_count}")
        
        # 重置强制重处理
        if self.force_reprocess_cb.isChecked():
            self.force_reprocess_cb.setChecked(False)
        
        # 临时文件清理弹窗
        if self.keep_temp_cb.isChecked() and success_count > 0 and self.last_temp_roots:
            self._show_temp_files_cleanup_dialog(success_count)
        
        QMessageBox.information(
            None, "完成",
            f"转换任务已完成！\n\n成功: {success_count} 个\n失败: {failed_count} 个"
        )

    def _get_selected_css_style(self) -> str:
        """获取当前选中的 CSS 风格 key"""
        for key, rb in self.css_buttons.items():
            if rb.isChecked():
                return key
        return "clean"

# ==================== 元信息 ====================
__author__ = "YQJ"
__version__ = "1.4.0"
__date__ = "2026.05.23"