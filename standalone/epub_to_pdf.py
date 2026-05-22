#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
EPUB转PDF工具 - 独立版本
将 EPUB 电子书转换为 PDF 文档
"""

import sys
import os
import time
import subprocess
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from enum import Enum

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QListWidget, QListWidgetItem, QTextEdit,
    QProgressBar, QFileDialog, QGroupBox, QRadioButton, QCheckBox,
    QSpinBox, QComboBox, QLineEdit, QGridLayout, QMessageBox,
    QStatusBar, QFrame, QSplitter, QScrollArea, QButtonGroup
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings
from PyQt6.QtGui import (
    QFont, QColor, QTextCursor, QDragEnterEvent, QDropEvent, QIntValidator
)


# ==================== 元信息 ====================
__author__ = "YQJ"
__version__ = "2.1.0"
__date__ = "2026.04.28"
__app_name__ = "EPUB转PDF工具"


# ==================== 文件状态枚举 ====================
class FileStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    
    @property
    def icon(self) -> str:
        icons = {
            FileStatus.PENDING: "⏳",
            FileStatus.PROCESSING: "🔄",
            FileStatus.SUCCESS: "✅",
            FileStatus.FAILED: "❌"
        }
        return icons.get(self, "📄")


# ==================== 可拖拽文件列表 ====================
class DropFileListWidget(QListWidget):
    files_added = pyqtSignal(list)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.file_paths: Dict[int, Path] = {}
        self.file_status: Dict[int, FileStatus] = {}
        self.completed_files: set = set()
    
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()
    
    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()
    
    def dropEvent(self, event: QDropEvent):
        epub_files = []
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if not path.exists():
                continue
            if path.is_file() and path.suffix.lower() == '.epub':
                epub_files.append(path)
            elif path.is_dir():
                for fp in path.rglob("*.epub"):
                    epub_files.append(fp)
                for fp in path.rglob("*.EPUB"):
                    epub_files.append(fp)
        if epub_files:
            epub_files = list(dict.fromkeys(epub_files))
            self.files_added.emit(epub_files)
            event.acceptProposedAction()
        else:
            event.ignore()
    
    def reset_all_status(self):
        for path in self.file_paths.values():
            self.update_status(path, FileStatus.PENDING)

    def add_file(self, file_path: Path) -> bool:
        if file_path in self.file_paths.values():
            return False
        index = self.count()
        self.file_paths[index] = file_path
        self.file_status[index] = FileStatus.PENDING
        item = QListWidgetItem(f"{FileStatus.PENDING.icon} {file_path.name}")
        item.setToolTip(str(file_path))
        self.addItem(item)
        return True
    
    def add_files(self, files: List[Path]) -> int:
        added = 0
        for f in files:
            if str(f.absolute()) in self.completed_files:
                continue
            if self.add_file(f):
                added += 1
        return added
    
    def remove_selected(self) -> List[Path]:
        removed = []
        for item in sorted(self.selectedItems(), key=lambda x: self.row(x), reverse=True):
            row = self.row(item)
            if row in self.file_paths:
                removed.append(self.file_paths[row])
                self.completed_files.discard(str(self.file_paths[row].absolute()))
                del self.file_paths[row]
                del self.file_status[row]
            self.takeItem(row)
        self._reindex()
        return removed
    
    def clear_all(self):
        self.clear()
        self.file_paths.clear()
        self.file_status.clear()
        self.completed_files.clear()
    
    def update_status(self, file_path: Path, status: FileStatus):
        colors = {
            FileStatus.SUCCESS: QColor(39, 174, 96),
            FileStatus.FAILED: QColor(231, 76, 60),
            FileStatus.PROCESSING: QColor(52, 152, 219),
            FileStatus.PENDING: QColor(128, 128, 128)
        }
        for index, path in self.file_paths.items():
            if path == file_path:
                self.file_status[index] = status
                if status == FileStatus.SUCCESS:
                    self.completed_files.add(str(file_path.absolute()))
                item = self.item(index)
                if item:
                    base_name = file_path.name
                    for old_icon in ["⏳", "🔄", "✅", "❌"]:
                        base_name = base_name.replace(f"{old_icon} ", "")
                    item.setText(f"{status.icon} {base_name}")
                    item.setForeground(colors.get(status, QColor(0, 0, 0)))
                break
    
    def get_all_files(self) -> List[Path]:
        return list(self.file_paths.values())
    
    def get_pending_files(self) -> List[Path]:
        return [path for idx, path in self.file_paths.items() 
                if self.file_status[idx] == FileStatus.PENDING]
    
    def get_files_by_status(self, status: FileStatus) -> List[Path]:
        return [path for idx, path in self.file_paths.items() 
                if self.file_status.get(idx) == status]
    
    def _reindex(self):
        new_paths = {}
        new_status = {}
        for i in range(self.count()):
            item = self.item(i)
            item_text = item.text()
            for idx, path in self.file_paths.items():
                if path.name in item_text:
                    new_paths[i] = path
                    new_status[i] = self.file_status[idx]
                    break
        self.file_paths = new_paths
        self.file_status = new_status


# ==================== 工具函数 ====================
def find_executable(name: str) -> Optional[str]:
    import shutil
    exe_path = shutil.which(name)
    if exe_path:
        return exe_path
    if sys.platform == 'win32':
        if name == 'ebook-convert':
            common_paths = [
                r'C:\Program Files\Calibre2\ebook-convert.exe',
                r'C:\Program Files (x86)\Calibre2\ebook-convert.exe',
                os.path.expanduser(r'~\AppData\Local\Programs\Calibre\ebook-convert.exe'),
            ]
            for path in common_paths:
                if Path(path).exists():
                    return path
    return None


_STARTUP_INFO = None
if sys.platform == 'win32':
    _STARTUP_INFO = subprocess.STARTUPINFO()
    _STARTUP_INFO.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    _STARTUP_INFO.wShowWindow = subprocess.SW_HIDE


# ==================== 预设配置 ====================
PRESETS = {
    "1": {"name": "极限紧凑版", "top": 0, "bottom": 0, "left": 0, "right": 0, "font_size": 12},
    "2": {"name": "左右紧凑版", "top": 10, "bottom": 10, "left": 0, "right": 0, "font_size": 12},
    "3": {"name": "上下紧凑版", "top": 0, "bottom": 0, "left": 10, "right": 10, "font_size": 12},
    "4": {"name": "对称装订版", "top": 10, "bottom": 10, "left": 10, "right": 10, "font_size": 12}
}

PRESET_NAMES = {
    "1": "极限紧凑", "2": "左右紧凑", "3": "上下紧凑", "4": "对称装订"
}


# ==================== 转换核心 ====================
def check_calibre() -> Tuple[bool, str]:
    ebook_convert = find_executable('ebook-convert')
    if not ebook_convert:
        return False, "未找到 Calibre (ebook-convert)"
    try:
        result = subprocess.run(
            [ebook_convert, '--version'], capture_output=True, text=True, timeout=10,
            startupinfo=_STARTUP_INFO
        )
        if result.returncode == 0:
            return True, result.stdout.strip().split('\n')[0] if result.stdout else "Calibre 已安装"
        return False, "ebook-convert 无法正常运行"
    except Exception as e:
        return False, str(e)


def convert_epub_to_pdf(epub_file: Path, output_pdf: Path, margins: Dict[str, int]) -> Tuple[bool, str, float]:
    start_time = time.time()
    ebook_convert = find_executable('ebook-convert')
    if not ebook_convert:
        return False, "未找到 ebook-convert", 0
    
    cmd = [
        ebook_convert, str(epub_file), str(output_pdf),
        f"--margin-top={margins['top']}", f"--margin-bottom={margins['bottom']}",
        f"--margin-left={margins['left']}", f"--margin-right={margins['right']}",
        f"--pdf-default-font-size={margins.get('font_size', 12)}",
        "--pdf-mono-font-size=10", 
        # "--pdf-page-numbers" # 注释掉后，EPUB转PDF时，页脚没有页码。
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, startupinfo=_STARTUP_INFO)
        elapsed = time.time() - start_time
        if result.returncode == 0:
            return True, "转换成功", elapsed
        else:
            return False, result.stderr[:200] if result.stderr else "未知错误", elapsed
    except subprocess.TimeoutExpired:
        return False, "转换超时（超过300秒）", time.time() - start_time
    except Exception as e:
        return False, str(e), time.time() - start_time


# ==================== 工作线程 ====================
class ConversionWorker(QThread):
    progress_updated = pyqtSignal(int, str, int, int)
    file_status_signal = pyqtSignal(Path, str)
    log_message = pyqtSignal(str, str)
    finished_all = pyqtSignal(list)
    
    def __init__(self, files: List[Path], output_mode: str, output_dir: Path = None,
                 margins: Dict[str, int] = None, max_workers: int = 4, auto_open: bool = False):
        super().__init__()
        self.files = files
        self.output_mode = output_mode
        self.output_dir = output_dir
        self.margins = margins or {}
        self.max_workers = max_workers
        self.auto_open = auto_open
        self._is_running = True
        self.results = []
    
    def stop(self):
        self._is_running = False
    
    def _get_unique_path(self, path: Path) -> Path:
        if not path.exists():
            try:
                path.touch(exist_ok=False)
                return path
            except FileExistsError:
                pass
        parent, stem, suffix = path.parent, path.stem, path.suffix
        counter = 1
        while counter <= 100:
            new = parent / f"{stem}_{counter}{suffix}"
            if not new.exists():
                try:
                    new.touch(exist_ok=False)
                    return new
                except FileExistsError:
                    pass
            counter += 1
        import uuid
        return parent / f"{stem}_{uuid.uuid4().hex[:8]}{suffix}"
    
    def run(self):
        total = len(self.files)
        self.results = []
        self.log_message.emit(f"开始转换 {total} 个文件，并行数: {self.max_workers}", "INFO")
        
        start = time.time()
        completed = 0
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {}
            for epub_file in self.files:
                if not self._is_running:
                    break
                self.file_status_signal.emit(epub_file, 'processing')
                out_dir = self.output_dir if self.output_mode == "custom" else epub_file.parent
                out_dir.mkdir(parents=True, exist_ok=True)
                output_pdf = out_dir / epub_file.with_suffix('.pdf').name
                output_pdf = self._get_unique_path(output_pdf)
                future = executor.submit(convert_epub_to_pdf, epub_file, output_pdf, self.margins)
                futures[future] = (epub_file, output_pdf)
            
            for future in as_completed(futures):
                if not self._is_running:
                    break
                epub_file, output_pdf = futures[future]
                completed += 1
                try:
                    success, msg, elapsed = future.result(timeout=300)
                    if success:
                        self.file_status_signal.emit(epub_file, 'success')
                        self.log_message.emit(f"✅ [{completed}/{total}] {epub_file.name} → {output_pdf.name} ({elapsed:.1f}秒)", "SUCCESS")
                        self.results.append({'file': str(epub_file), 'output': str(output_pdf), 'status': 'success'})
                    else:
                        self.file_status_signal.emit(epub_file, 'failed')
                        self.log_message.emit(f"❌ [{completed}/{total}] {epub_file.name}: {msg}", "ERROR")
                        self.results.append({'file': str(epub_file), 'status': 'failed', 'message': msg})
                except Exception as e:
                    self.file_status_signal.emit(epub_file, 'failed')
                    self.log_message.emit(f"❌ {epub_file.name}: {e}", "ERROR")
                    self.results.append({'file': str(epub_file), 'status': 'failed', 'message': str(e)})
                self.progress_updated.emit(int(completed/total*100), f"转换中... {completed}/{total}", completed, total)
        
        elapsed = time.time() - start
        self.log_message.emit(f"总耗时: {elapsed:.1f}秒", "INFO")
        if self._is_running and self.auto_open:
            self._smart_open()
        self.finished_all.emit(self.results)
    
    def _smart_open(self):
        dirs = set()
        for f in self.files:
            if self.output_mode == "custom" and self.output_dir:
                dirs.add(self.output_dir)
            else:
                dirs.add(f.parent)
        lst = list(dirs)
        if len(lst) == 1:
            self._open_folder(lst[0])
        elif len(lst) <= 3:
            for d in lst:
                self._open_folder(d)
    
    def _open_folder(self, folder: Path):
        if sys.platform == 'win32':
            os.startfile(str(folder))
        elif sys.platform == 'darwin':
            subprocess.run(['open', str(folder)])
        else:
            subprocess.run(['xdg-open', str(folder)])


# ==================== 主窗口 ====================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{__app_name__} v{__version__}")
        self.setMinimumSize(900, 620)
        self.resize(1000, 680)
        
        self.output_dir: Optional[Path] = None
        self.worker: Optional[ConversionWorker] = None
        self.presets = PRESETS
        
        self._setup_ui()
    
    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # ====== 左侧：设置面板（整体滚动） ======
        left_panel = QWidget()
        left_outer = QVBoxLayout(left_panel)
        left_outer.setSpacing(0)
        left_outer.setContentsMargins(0, 0, 0, 0)
        
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        left_content = QWidget()
        left_layout = QVBoxLayout(left_content)
        left_layout.setSpacing(10)
        left_layout.setContentsMargins(10, 10, 10, 10)
        
        # ====== 文件列表 ======
        file_group = QGroupBox("📁 选择EPUB文件 (支持拖拽)")
        file_layout = QVBoxLayout(file_group)
        self.file_list = DropFileListWidget()
        self.file_list.setMinimumHeight(80)
        self.file_list.setMaximumHeight(120)
        self.file_list.files_added.connect(self._on_files_added)
        file_layout.addWidget(self.file_list)

        btn_layout = QHBoxLayout()
        for text, slot in [("➕ 添加文件", self._add_files), ("📂 添加文件夹", self._add_folder),
                           ("❌ 移除选中", self._remove_selected), ("🗑️ 清空全部", self._clear_all)]:
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            btn_layout.addWidget(btn)
        
        self.cb_force_reprocess = QCheckBox("忽略状态")
        self.cb_force_reprocess.setToolTip(
            "默认情况下，已经处理过的文件不会再次处理。\n"
            "勾选此项后，将重新处理列表中的所有文件。")
        btn_layout.addWidget(self.cb_force_reprocess)
        btn_layout.addStretch()

        file_layout.addLayout(btn_layout)
        left_layout.addWidget(file_group)
        
        # ====== 输出设置 ======
        out_group = QGroupBox("📂 输出设置")
        out_layout = QVBoxLayout(out_group)
        mode_layout = QHBoxLayout()
        self.out_source = QRadioButton("与源文件同目录")
        self.out_custom = QRadioButton("统一输出到:")
        self.out_source.setChecked(True)
        mode_layout.addWidget(self.out_source)
        mode_layout.addWidget(self.out_custom)
        mode_layout.addStretch()
        out_layout.addLayout(mode_layout)
        dir_layout = QHBoxLayout()
        self.out_dir_edit = QLineEdit()
        self.out_dir_edit.setEnabled(False)
        self.out_dir_edit.setPlaceholderText("请选择输出目录")
        dir_layout.addWidget(self.out_dir_edit)
        browse_btn = QPushButton("浏览...")
        browse_btn.setEnabled(False)
        browse_btn.clicked.connect(self._select_output_dir)
        dir_layout.addWidget(browse_btn)
        out_layout.addLayout(dir_layout)
        self.out_custom.toggled.connect(lambda c: (self.out_dir_edit.setEnabled(c), browse_btn.setEnabled(c)))
        left_layout.addWidget(out_group)
        
        # ====== 转换选项（整合页边距设置，参考原项目布局） ======
        options_group = QGroupBox("⚙️ 转换选项")
        options_layout = QVBoxLayout(options_group)
        options_layout.setSpacing(10)
        
        # --- 页边距预设 ---
        preset_label = QLabel("📐 页边距预设:")
        preset_label.setStyleSheet("font-weight: bold;")
        options_layout.addWidget(preset_label)
        
        self.preset_group = QButtonGroup()
        preset_layout = QHBoxLayout()
        preset_layout.setSpacing(10)
        for key in ["1", "2", "3", "4"]:
            preset = self.presets[key]
            display_name = PRESET_NAMES.get(key, preset['name'])
            rb = QRadioButton(display_name)
            rb.setToolTip(f"上{preset['top']} 下{preset['bottom']} 左{preset['left']} 右{preset['right']}")
            rb.setProperty("preset_key", key)
            self.preset_group.addButton(rb)
            preset_layout.addWidget(rb)
            if key == "1":
                rb.setChecked(True)
        preset_layout.addStretch()
        options_layout.addLayout(preset_layout)
        self.preset_group.buttonClicked.connect(self._on_preset_change)
        
        # --- 自定义边距（单行紧凑布局） ---
        custom_label = QLabel("⚙️ 自定义边距:")
        custom_label.setStyleSheet("font-weight: bold; margin-top: 5px;")
        options_layout.addWidget(custom_label)
        
        custom_widget = QWidget()
        custom_layout = QHBoxLayout(custom_widget)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        custom_layout.setSpacing(5)
        
        def create_margin_edit(value=0, max_val=100):
            edit = QLineEdit(str(value))
            edit.setValidator(QIntValidator(0, max_val))
            edit.setFixedWidth(38)
            edit.setAlignment(Qt.AlignmentFlag.AlignRight)
            edit.setStyleSheet("padding: 2px 4px; border: 1px solid #dcdcdc; border-radius: 3px; background: white;")
            return edit
        
        custom_layout.addWidget(QLabel("上"))
        self.top_margin = create_margin_edit(0)
        custom_layout.addWidget(self.top_margin)
        custom_layout.addWidget(QLabel("pt"))
        custom_layout.addSpacing(8)
        
        custom_layout.addWidget(QLabel("下"))
        self.bottom_margin = create_margin_edit(0)
        custom_layout.addWidget(self.bottom_margin)
        custom_layout.addWidget(QLabel("pt"))
        custom_layout.addSpacing(8)
        
        custom_layout.addWidget(QLabel("左"))
        self.left_margin = create_margin_edit(0)
        custom_layout.addWidget(self.left_margin)
        custom_layout.addWidget(QLabel("pt"))
        custom_layout.addSpacing(8)
        
        custom_layout.addWidget(QLabel("右"))
        self.right_margin = create_margin_edit(0)
        custom_layout.addWidget(self.right_margin)
        custom_layout.addWidget(QLabel("pt"))
        custom_layout.addSpacing(8)
        
        custom_layout.addWidget(QLabel("字号"))
        self.font_size = QLineEdit("12")
        self.font_size.setValidator(QIntValidator(8, 72))
        self.font_size.setFixedWidth(38)
        self.font_size.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.font_size.setStyleSheet("padding: 2px 4px; border: 1px solid #dcdcdc; border-radius: 3px; background: white;")
        custom_layout.addWidget(self.font_size)
        custom_layout.addWidget(QLabel("pt"))
        custom_layout.addStretch()
        
        options_layout.addWidget(custom_widget)
        
        # --- 分隔线 ---
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #dcdcdc; margin: 5px 0;")
        options_layout.addWidget(sep)
        
        # --- 并行线程数 ---
        worker_widget = QWidget()
        worker_layout = QHBoxLayout(worker_widget)
        worker_layout.setContentsMargins(0, 0, 0, 0)
        worker_layout.addWidget(QLabel("并行线程数:"))
        self.worker_spin = QSpinBox()
        self.worker_spin.setRange(1, 16)
        self.worker_spin.setValue(min(os.cpu_count() or 4, 6))
        self.worker_spin.setFixedWidth(80)
        worker_layout.addWidget(self.worker_spin)
        worker_layout.addWidget(QLabel(f"(CPU: {os.cpu_count() or 6}核)"))
        worker_layout.addStretch()
        options_layout.addWidget(worker_widget)
        
        # --- 自动打开 ---
        self.cb_auto_open = QCheckBox("转换完成后打开输出目录")
        self.cb_auto_open.setChecked(False)
        options_layout.addWidget(self.cb_auto_open)
        
        left_layout.addWidget(options_group)
        
        # ====== 控制按钮 ======
        ctrl_layout = QHBoxLayout()
        self.process_btn = QPushButton("🚀 开始转换")
        self.process_btn.setStyleSheet(
            "background-color: #27ae60; color: white; font-weight: bold; "
            "padding: 10px 25px; border-radius: 6px; font-size: 12pt;"
        )
        self.process_btn.clicked.connect(self._start_processing)
        ctrl_layout.addStretch()
        ctrl_layout.addWidget(self.process_btn)
        self.stop_btn = QPushButton("⏹️ 停止转换")
        self.stop_btn.setStyleSheet(
            "background-color: #e74c3c; color: white; font-weight: bold; "
            "padding: 10px 25px; border-radius: 6px; font-size: 12pt;"
        )
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_processing)
        ctrl_layout.addWidget(self.stop_btn)
        ctrl_layout.addStretch()
        left_layout.addLayout(ctrl_layout)
        
        # ====== 进度条 ======
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumHeight(22)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet("""
            QProgressBar { border: 1px solid #dcdcdc; border-radius: 4px; text-align: center; }
            QProgressBar::chunk { background-color: #27ae60; border-radius: 3px; }
        """)
        left_layout.addWidget(self.progress_bar)
        
        left_layout.addStretch()
        left_scroll.setWidget(left_content)
        left_outer.addWidget(left_scroll)
        
        # ====== 右侧：日志面板 ======
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(5, 5, 5, 5)
        log_header = QLabel("📋 转换日志")
        log_header.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        right_layout.addWidget(log_header)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 10))
        right_layout.addWidget(self.log_text)
        log_toolbar = QHBoxLayout()
        clear_btn = QPushButton("🗑️ 清空")
        clear_btn.clicked.connect(lambda: self.log_text.clear())
        log_toolbar.addWidget(clear_btn)
        save_btn = QPushButton("💾 保存")
        save_btn.clicked.connect(self._save_log)
        log_toolbar.addWidget(save_btn)
        log_toolbar.addStretch()
        right_layout.addLayout(log_toolbar)
        
        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(right_panel)
        main_splitter.setSizes([550, 500])
        
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(main_splitter)
        
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_label = QLabel("就绪")
        self.status_bar.addWidget(self.status_label)
        self.file_count_label = QLabel("已选择 0 个文件")
        self.status_bar.addPermanentWidget(self.file_count_label)
    
    def _on_preset_change(self):
        checked = self.preset_group.checkedButton()
        if checked:
            preset_key = checked.property("preset_key")
            if preset_key and preset_key in self.presets:
                preset = self.presets[preset_key]
                self.top_margin.setText(str(preset["top"]))
                self.bottom_margin.setText(str(preset["bottom"]))
                self.left_margin.setText(str(preset["left"]))
                self.right_margin.setText(str(preset["right"]))
                self.font_size.setText(str(preset.get("font_size", 12)))
                self._log(f"切换到预设：{preset['name']}")
    
    def _get_current_margins(self) -> Dict[str, int]:
        try:
            return {
                "top": int(self.top_margin.text()),
                "bottom": int(self.bottom_margin.text()),
                "left": int(self.left_margin.text()),
                "right": int(self.right_margin.text()),
                "font_size": int(self.font_size.text())
            }
        except ValueError:
            return {"top": 0, "bottom": 0, "left": 0, "right": 0, "font_size": 12}
    
    # ====== 文件操作 ======
    def _on_files_added(self, files: List[Path]):
        added = self.file_list.add_files(files)
        if added > 0:
            self._log(f"添加了 {added} 个文件")
        self._update_file_count()
    
    def _add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "选择EPUB文件", "", "EPUB文件 (*.epub);;所有文件 (*.*)")
        if files:
            added = self.file_list.add_files([Path(f) for f in files])
            self._log(f"添加了 {added} 个文件")
            self._update_file_count()
    
    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择包含EPUB文件的文件夹")
        if folder:
            path = Path(folder)
            epub_files = list(path.rglob("*.epub")) + list(path.rglob("*.EPUB"))
            added = self.file_list.add_files(epub_files)
            self._log(f"从文件夹添加了 {added} 个文件")
            self._update_file_count()
    
    def _remove_selected(self):
        removed = self.file_list.remove_selected()
        if removed:
            self._log(f"移除了 {len(removed)} 个文件")
        self._update_file_count()
    
    def _clear_all(self):
        self.file_list.clear_all()
        self._log("已清空文件列表")
        self._update_file_count()
    
    def _update_file_count(self):
        self.file_count_label.setText(f"已选择 {self.file_list.count()} 个文件")
    
    def _select_output_dir(self):
        directory = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if directory:
            self.output_dir = Path(directory)
            self.out_dir_edit.setText(str(self.output_dir))
    
    # ====== 处理逻辑 ======

    def _start_processing(self):
        if self.cb_force_reprocess.isChecked():
            all_files = self.file_list.get_all_files()
            if not all_files:
                QMessageBox.warning(self, "警告", "请先添加文件")
                return
            self.file_list.reset_all_status()
            files = self.file_list.get_all_files()
            self._log(f"🔄 忽略状态模式：将重新处理全部 {len(files)} 个文件", "INFO")
        else:
            files = self.file_list.get_pending_files()
            if not files:
                all_files = self.file_list.get_all_files()
                if all_files:
                    failed = self.file_list.get_files_by_status(FileStatus.FAILED)
                    if failed:
                        reply = QMessageBox.question(self, "提示", 
                            f"有 {len(failed)} 个文件失败，是否重试？",
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                        if reply == QMessageBox.StandardButton.Yes:
                            for f in failed:
                                self.file_list.update_status(f, FileStatus.PENDING)
                            files = failed
                        else:
                            return
                    else:
                        QMessageBox.information(self, "提示", "所有文件都已转换完成！")
                        return
                else:
                    QMessageBox.warning(self, "警告", "请先添加文件")
                    return
        
        calibre_ok, calibre_msg = check_calibre()
        if not calibre_ok:
            QMessageBox.critical(self, "错误",
                "未找到 Calibre 转换工具！\n\n请安装 Calibre 电子书管理软件\n下载地址：https://calibre-ebook.com/")
            return
        
        if self.out_custom.isChecked() and not self.output_dir:
            QMessageBox.warning(self, "警告", "请选择输出目录")
            return
        
        reply = QMessageBox.question(self, "确认", f"即将转换 {len(files)} 个文件，是否继续？",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        self.process_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        
        margins = self._get_current_margins()
        output_mode = "custom" if self.out_custom.isChecked() else "source"
        output_dir = self.output_dir if output_mode == "custom" else None
        
        self.worker = ConversionWorker(
            files=files, output_mode=output_mode, output_dir=output_dir,
            margins=margins, max_workers=self.worker_spin.value(),
            auto_open=self.cb_auto_open.isChecked()
        )
        self.worker.progress_updated.connect(self._on_progress)
        self.worker.file_status_signal.connect(self._on_file_status)
        self.worker.log_message.connect(self._log)
        self.worker.finished_all.connect(self._on_finished)
        self.worker.start()

    def _stop_processing(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self._log("正在停止转换...", "WARNING")
            self.stop_btn.setEnabled(False)

    
    def _on_progress(self, value: int, msg: str, completed: int, total: int):
        self.progress_bar.setValue(value)
        self.status_label.setText(f"{msg} - {completed}/{total}")
    
    def _on_file_status(self, file_path: Path, status: str):
        status_map = {'processing': FileStatus.PROCESSING, 'success': FileStatus.SUCCESS,
                      'failed': FileStatus.FAILED, 'pending': FileStatus.PENDING}
        self.file_list.update_status(file_path, status_map.get(status, FileStatus.PENDING))
    
    def _on_finished(self, results: list):
        self.process_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

        if self.cb_force_reprocess.isChecked():
            self.cb_force_reprocess.setChecked(False)        

        self.progress_bar.setValue(100)
        success = sum(1 for r in results if r['status'] == 'success')
        failed = len(results) - success
        self._log("")
        self._log(f"转换完成！成功: {success}, 失败: {failed}", "SUCCESS" if failed == 0 else "WARNING")
        self.status_label.setText(f"完成 - 成功: {success}, 失败: {failed}")
        QMessageBox.information(self, "完成", f"转换任务已完成！\n\n成功: {success} 个\n失败: {failed} 个")
    
    def _log(self, msg: str, level: str = "INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        icons = {"INFO": "ℹ️", "SUCCESS": "✅", "WARNING": "⚠️", "ERROR": "❌"}
        colors = {"INFO": "#2c3e50", "SUCCESS": "#27ae60", "WARNING": "#e67e22", "ERROR": "#e74c3c"}
        self.log_text.setTextColor(QColor(colors.get(level, "#2c3e50")))
        self.log_text.append(f"[{timestamp}] {icons.get(level, '📝')} {msg}")
        self.log_text.moveCursor(QTextCursor.MoveOperation.End)
    
    def _save_log(self):
        text = self.log_text.toPlainText()
        if not text:
            QMessageBox.information(self, "提示", "没有日志内容")
            return
        name = f"epub2pdf_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        path, _ = QFileDialog.getSaveFileName(self, "保存日志", name, "文本文件 (*.txt)")
        if path:
            Path(path).write_text(text, encoding='utf-8')
            self._log(f"日志已保存: {path}", "SUCCESS")


# ==================== 主入口 ====================
def main():
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setApplicationVersion(__version__)
    app.setStyle('Fusion')
    
    calibre_ok, calibre_msg = check_calibre()
    if not calibre_ok:
        QMessageBox.warning(None, "依赖缺失",
            f"未检测到 Calibre！\n\nEPUB转PDF功能需要 Calibre 支持。\n请访问 https://calibre-ebook.com/ 下载安装。\n\n{calibre_msg}")
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()