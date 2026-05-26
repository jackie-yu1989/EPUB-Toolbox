#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
EPUB工具箱 - 统一调度主程序
集成 MD公式修复、MD转EPUB、EPUB转Word、EPUB转PDF 和组合工作流自动编排五大功能
"""

# ===== 必须在所有 import 之前 =====
import sys
import os
import ctypes
import signal
import atexit
import logging
import shutil
import struct
from typing import List, Optional, Dict
from PyQt6.QtCore import QSharedMemory

try:
    import keyboard
    HAS_KEYBOARD = True
except Exception:
    HAS_KEYBOARD = False

MAX_INSTANCES = 1

# 检测是否在 pythonw 模式下运行
if sys.executable.lower().endswith('pythonw.exe') or 'pythonw' in sys.executable.lower():
    sys.stdout = open(os.devnull, 'w')
    sys.stderr = open(os.devnull, 'w')

logger = logging.getLogger(__name__)


def resource_path(relative_path):
    """获取资源文件的绝对路径 - 适用于PyInstaller打包后的exe"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


# ===== 正常导入 =====
import random
import time
from pathlib import Path
from threading import Thread

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QStackedWidget, QProgressBar, QStatusBar,
    QMessageBox, QFrame, QSplitter, QToolButton, QSystemTrayIcon, QMenu
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QSettings, QStandardPaths
from PyQt6.QtGui import (
    QFont, QAction, QKeySequence, QIcon
)

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

# ★ 必须在类定义之前导入
from core.base_module import BaseModule
from core.theme_manager import ThemeManager
from core.components import LogPanel, AboutDialog
from modules import MDRepairModule, MD2EPUBModule, EPUB2PDFModule, WorkflowModule, EPUB2DOCXModule
from core.splash_manager import SplashManager
from core.config_keys import SettingsDomain, SettingsKey

# ★ 统一版本信息（单一数据源）
from core.version import __app_name__, __version__, __date__, __author__, __description__


# ==================== 可折叠日志面板 ====================

class CollapsibleLogPanel(QWidget):
    """可折叠的日志面板容器"""
    
    visibility_changed = pyqtSignal(bool)
    pin_state_changed = pyqtSignal(bool)
    
    def __init__(self, log_panel, parent=None):
        super().__init__(parent)
        self.log_panel = log_panel
        self.is_pinned = True
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(0)
        
        log_header = QWidget()
        log_header.setFixedHeight(40)
        log_header.setStyleSheet("""
            background-color: #f8f9fa;
            border-bottom: 1px solid #dee2e6;
            border-radius: 4px 4px 0 0;
        """)
        log_header_layout = QHBoxLayout(log_header)
        log_header_layout.setContentsMargins(10, 0, 5, 0)
        
        log_title = QLabel("📋 转换日志")
        log_title.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        log_header_layout.addWidget(log_title)
        log_header_layout.addStretch()
        
        self.pin_btn = QToolButton()
        self.pin_btn.setText("📌")
        self.pin_btn.setToolTip("固定日志面板（始终显示）")
        self.pin_btn.setCheckable(True)
        self.pin_btn.setChecked(True)
        self.pin_btn.clicked.connect(self._on_pin_toggled)
        log_header_layout.addWidget(self.pin_btn)
        
        self.hide_btn = QToolButton()
        self.hide_btn.setText("✕")
        self.hide_btn.setToolTip("隐藏日志面板")
        self.hide_btn.clicked.connect(self.hide_panel)
        log_header_layout.addWidget(self.hide_btn)
        
        layout.addWidget(log_header)
        layout.addWidget(self.log_panel)
    
    def _on_pin_toggled(self, checked: bool):
        self.is_pinned = checked
        self.pin_btn.setText("📌" if checked else "📍")
        self.pin_btn.setToolTip(
            "固定日志面板（始终显示）" if checked 
            else "取消固定（日志面板可隐藏）"
        )
        self.pin_state_changed.emit(checked)
    
    def set_pin_state(self, pinned: bool):
        self.is_pinned = pinned
        self.pin_btn.setChecked(pinned)
        self.pin_btn.setText("📌" if pinned else "📍")
    
    def hide_panel(self):
        if self.is_pinned:
            return
        self.setVisible(False)
        self.visibility_changed.emit(False)
    
    def show_panel(self):
        self.setVisible(True)
        self.visibility_changed.emit(True)
    
    def toggle_panel(self):
        if self.isVisible():
            self.hide_panel()
        else:
            self.show_panel()


# ==================== 导航按钮 ====================

class NavButton(QPushButton):
    """导航按钮"""
    
    def __init__(self, module_id: str, icon: str, text: str, parent=None):
        super().__init__(f"{icon}  {text}", parent)
        self.module_id = module_id
        self.setProperty("class", "nav-button")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(45)
        font = QFont("Microsoft YaHei", 11)
        self.setFont(font)


# ==================== 主窗口 ====================

class EPUBToolboxHub(QMainWindow):
    """EPUB工具箱主窗口 - 完整优化版本"""

    _wake_signal = pyqtSignal()
    
    DEFAULT_CLOSE_TO_TRAY = True
    
    def __init__(self):
        super().__init__()

        atexit.register(self._atexit_cleanup)
        signal.signal(signal.SIGINT, self._signal_handler)
        self._wake_signal.connect(self._show_from_tray)

        icon_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "resources", "icon.ico"
        )
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        self.settings = QSettings(SettingsDomain.EPUB_TOOLBOX, SettingsDomain.SETTINGS)
        self.theme_manager = ThemeManager("light")
        self._cached_stylesheets = {}
        
        self.modules: Dict[str, BaseModule] = {}
        self.current_module: Optional[BaseModule] = None
        self.nav_buttons: Dict[str, NavButton] = {}
        
        self.close_to_tray = self.settings.value(
            SettingsKey.CLOSE_TO_TRAY, self.DEFAULT_CLOSE_TO_TRAY, type=bool
        )
        self._is_force_quit = False
        
        self._register_modules()
        self._setup_tray()
        self._register_hotkey()
        self._setup_shortcuts()

        self.log_panel = LogPanel(show_toolbar=True)
        self.log_panel.setMinimumWidth(300)
        
        self.collapsible_log = CollapsibleLogPanel(self.log_panel)
        self.collapsible_log.visibility_changed.connect(self._on_log_visibility_changed)
        self.collapsible_log.pin_state_changed.connect(self._on_pin_state_changed)
        
        for module in self.modules.values():
            module.set_log_panel(self.log_panel)
        
        self._setup_ui()
        self._apply_theme()
        self._log_hotkey_status()
        self._check_all_dependencies()
        
        QTimer.singleShot(50, self._restore_settings)
        
        if self.modules:
            startup_module = self._get_startup_module()
            first_module_id = startup_module if startup_module else list(self.modules.keys())[0]
            self._switch_module(first_module_id)

    # ==================== 系统托盘 ====================

    def _setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        tray_icon_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "resources", "icon.ico"
        )
        if os.path.exists(tray_icon_path):
            self.tray_icon.setIcon(QIcon(tray_icon_path))
        else:
            self.tray_icon.setIcon(QIcon(resource_path("resources/icon.ico")))
        self.tray_icon.setToolTip(f"{__app_name__} v{__version__}")

        tray_menu = QMenu()
        show_action = QAction("显示窗口", self)
        show_action.triggered.connect(self._show_from_tray)
        tray_menu.addAction(show_action)
        tray_menu.addSeparator()
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self._quit_app)
        tray_menu.addAction(quit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.DoubleClick,
                       QSystemTrayIcon.ActivationReason.Trigger):
            self._show_from_tray()
    
    def _show_from_tray(self):
        if self.isMinimized():
            self.showNormal()
        self.setWindowState(
            self.windowState() & ~Qt.WindowState.WindowMinimized
        )
        self.show()
        
        # ★ Windows API：强制将窗口置于最前
        if sys.platform == 'win32':
            hwnd = int(self.winId())
            # 模拟 Alt 键释放前台锁定
            ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)  # Alt down
            ctypes.windll.user32.keybd_event(0x12, 0, 2, 0)  # Alt up
            # 强制置顶并激活
            SW_SHOW = 5
            ctypes.windll.user32.ShowWindow(hwnd, SW_SHOW)
            ctypes.windll.user32.SetForegroundWindow(hwnd)
        else:
            self.activateWindow()
            self.raise_()

    def _quit_app(self):
        self._is_force_quit = True
        self.close_to_tray = False
        self.close()

    # ==================== 全局热键 ====================

    def _register_hotkey(self):
        self._hotkey_registered = False
        self._hotkey_error = None
        
        if HAS_KEYBOARD:
            try:
                keyboard.add_hotkey('ctrl+shift+k', self._on_hotkey_activated)
                self._hotkey_registered = True
            except Exception as e:
                self._hotkey_error = str(e)
    
    def _on_hotkey_activated(self):
        self._wake_signal.emit()
    
    def _log_hotkey_status(self):
        if HAS_KEYBOARD:
            if self._hotkey_registered:
                self.log_panel.log(
                    "⌨️ 全局热键 Ctrl+Shift+K 已就绪（支持后台唤醒）", 
                    "SUCCESS"
                )
            else:
                self.log_panel.log(
                    "ℹ️ 全局热键注册失败（需管理员权限）。"
                    "Ctrl+Shift+K 仅在前台可用，后台唤醒请双击托盘图标。",
                    "INFO"
                )
        else:
            self.log_panel.log(
                "ℹ️ keyboard 库未安装。"
                "Ctrl+Shift+K 仅在前台可用，后台唤醒请双击托盘图标。\n"
                "   安装 keyboard 并授予管理员权限可启用后台全局热键唤醒。",
                "INFO"
            )

    # ==================== 设置恢复 ====================

    def _restore_settings(self):
        try:
            is_pinned = self.settings.value(SettingsKey.LOG_PANEL_PINNED, True, type=bool)
            self.collapsible_log.set_pin_state(is_pinned)
            
            log_visible = self.settings.value(SettingsKey.LOG_PANEL_VISIBLE, True, type=bool)
            
            if not log_visible and not is_pinned:
                self.collapsible_log.hide_panel()
                self.toggle_log_action.setChecked(False)
            else:
                self.collapsible_log.show_panel()
                self.toggle_log_action.setChecked(True)
            
            QTimer.singleShot(50, self._safe_restore_splitter_sizes)
            
        except Exception as e:
            logger.warning(f"恢复用户设置失败: {e}")
            self.main_splitter.setSizes([220, 660, 440])
    
    def _safe_restore_splitter_sizes(self):
        try:
            sizes = self.settings.value(SettingsKey.SPLITTER_SIZES)
            
            if not sizes or len(sizes) != 3:
                self.main_splitter.setSizes([220, 660, 440])
                return
            
            valid_sizes = all(isinstance(s, int) and s >= 50 for s in sizes)
            if not valid_sizes:
                self.main_splitter.setSizes([220, 660, 440])
                return
            
            for i in range(self.main_splitter.count()):
                widget = self.main_splitter.widget(i)
                if widget and not widget.isVisible():
                    widget.setVisible(True)
            
            self.main_splitter.setSizes(sizes)
            
        except Exception:
            self.main_splitter.setSizes([220, 660, 440])

    # ==================== 模块注册 ====================

    def _register_modules(self):
        module_classes = [
            WorkflowModule,
            MDRepairModule,
            MD2EPUBModule,
            EPUB2DOCXModule,
            EPUB2PDFModule,
        ]
        for module_class in module_classes:
            module = module_class()
            self.modules[module.module_id] = module
            module.signals.status_changed.connect(self._on_module_status_changed)
            module.signals.progress_updated.connect(self._on_module_progress_updated)
            module.signals.log_message.connect(self._on_module_log)

    # ==================== 快捷键 ====================

    def _setup_shortcuts(self):
        pass  # 所有快捷键通过菜单 QAction 绑定
    
    def _show_shortcuts(self):
        from core.components import ShortcutDialog
        dialog = ShortcutDialog(self)
        dialog.exec()    

    # ==================== UI 构建 ====================

    def _setup_ui(self):
        # self.setWindowTitle(f"{__app_name__} v{__version__}")
        self.setWindowTitle(f"{__app_name__}（公测版）")
        self.setMinimumSize(1020, 680)
        self.resize(1120, 780) # 默认高度设置
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        
        nav_panel = self._create_navigation_panel()
        nav_panel.setMinimumWidth(200)
        nav_panel.setMaximumWidth(220)
        self.main_splitter.addWidget(nav_panel)
        
        work_panel = self._create_work_panel()
        work_panel.setMinimumWidth(480)
        self.main_splitter.addWidget(work_panel)
        
        self.main_splitter.addWidget(self.collapsible_log)
        
        self.main_splitter.setSizes([210, 550, 440])
        
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self.main_splitter)
        
        self._setup_status_bar()
        self._setup_menu()
    
    def _create_navigation_panel(self) -> QFrame:
        nav_panel = QFrame()
        nav_panel.setObjectName("navPanel")
        nav_panel.setStyleSheet("""
            #navPanel {
                background-color: #f8f9fa;
                border-right: 1px solid #dee2e6;
            }
        """)
        
        nav_layout = QVBoxLayout(nav_panel)
        nav_layout.setContentsMargins(10, 15, 10, 15)
        nav_layout.setSpacing(8)
        
        title_label = QLabel(f"📚 {__app_name__}")
        title_font = QFont("Microsoft YaHei", 14, QFont.Weight.Bold)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setWordWrap(True)
        nav_layout.addWidget(title_label)
        
        version_label = QLabel(f"v{__version__}")
        version_label.setObjectName("infoLabel")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav_layout.addWidget(version_label)
        
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setFixedHeight(1)
        sep1.setStyleSheet("background-color: #dee2e6; margin: 10px 0;")
        nav_layout.addWidget(sep1)
        
        modules_label = QLabel("📦 功能模块")
        modules_label.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        modules_label.setStyleSheet("color: #6c757d; padding: 5px 0;")
        nav_layout.addWidget(modules_label)
        
        for module_id, module in self.modules.items():
            btn = NavButton(module_id, module.module_icon, module.module_name)
            btn.clicked.connect(
                lambda checked, mid=module_id: self._switch_module(mid)
            )
            self.nav_buttons[module_id] = btn
            nav_layout.addWidget(btn)
        
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setFixedHeight(1)
        sep2.setStyleSheet("background-color: #dee2e6; margin: 15px 0 10px 0;")
        nav_layout.addWidget(sep2)
        
        self.global_process_btn = QPushButton("🚀 开始处理")
        self.global_process_btn.setObjectName("navProcessBtn")
        self.global_process_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.global_process_btn.setMinimumHeight(45)
        self.global_process_btn.clicked.connect(self._on_global_process_clicked)
        nav_layout.addWidget(self.global_process_btn)
        
        self.global_stop_btn = QPushButton("⏹️ 停止处理")
        self.global_stop_btn.setObjectName("navStopBtn")
        self.global_stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.global_stop_btn.setMinimumHeight(45)
        self.global_stop_btn.setEnabled(False)
        self.global_stop_btn.clicked.connect(self._on_global_stop_clicked)
        nav_layout.addWidget(self.global_stop_btn)
        
        nav_layout.addSpacing(15)
        
        nav_layout.addWidget(self._create_description_box())
        nav_layout.addStretch()
        
        author_label = QLabel(f"© {__author__}")
        author_label.setObjectName("infoLabel")
        author_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav_layout.addWidget(author_label)
        
        return nav_panel
    
    def _create_description_box(self) -> QWidget:
        desc_container = QWidget()
        desc_container.setObjectName("descContainer")
        desc_container.setStyleSheet("""
            #descContainer {
                background-color: #f0f4f8;
                border: 1px solid #dce4ec;
                border-radius: 10px;
            }
        """)
        desc_layout = QVBoxLayout(desc_container)
        desc_layout.setContentsMargins(12, 15, 12, 15)
        
        desc_title = QLabel("📌 当前功能")
        desc_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc_title.setStyleSheet("""
            font-size: 8pt;
            color: #7f8c8d;
            letter-spacing: 1px;
            margin-bottom: 5px;
        """)
        desc_layout.addWidget(desc_title)
        
        self.module_desc_hint = QLabel("")
        self.module_desc_hint.setObjectName("moduleDescHint")
        self.module_desc_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.module_desc_hint.setWordWrap(True)
        self.module_desc_hint.setStyleSheet("""
            #moduleDescHint {
                font-size: 10.5pt;
                color: #2c3e50;
                line-height: 1.6;
            }
        """)
        desc_layout.addWidget(self.module_desc_hint)
        
        return desc_container
    
    def _create_work_panel(self) -> QWidget:
        work_panel = QWidget()
        work_layout = QVBoxLayout(work_panel)
        work_layout.setContentsMargins(0, 0, 0, 0)
        work_layout.setSpacing(0)
        
        self.module_header = QWidget()
        self.module_header.setFixedHeight(50)
        self.module_header.setStyleSheet("""
            background-color: #ffffff;
            border-bottom: 1px solid #dee2e6;
        """)
        header_layout = QHBoxLayout(self.module_header)
        header_layout.setContentsMargins(20, 0, 20, 0)
        header_layout.setSpacing(10)
        
        self.module_title_label = QLabel()
        self.module_title_label.setFont(QFont("Microsoft YaHei", 13, QFont.Weight.Bold))
        header_layout.addWidget(self.module_title_label)
        header_layout.addStretch()
        
        self.dep_status_label = QLabel()
        self.dep_status_label.setObjectName("infoLabel")
        header_layout.addWidget(self.dep_status_label)
        
        self.show_log_btn = QToolButton()
        self.show_log_btn.setText("📋")
        self.show_log_btn.setToolTip("显示日志面板 (Ctrl+L)")
        self.show_log_btn.clicked.connect(self._show_log_panel)
        self.show_log_btn.setVisible(False)
        header_layout.addWidget(self.show_log_btn)
        
        work_layout.addWidget(self.module_header)
        
        self.work_area = QStackedWidget()
        for module_id, module in self.modules.items():
            widget = module.ui_widget
            self.work_area.addWidget(widget)
            module.set_progress_bar(self._get_module_progress_bar(widget))
        work_layout.addWidget(self.work_area)
        
        self.global_progress_bar = QProgressBar()
        self.global_progress_bar.setMaximumHeight(18)
        self.global_progress_bar.setTextVisible(True)
        self.global_progress_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                background-color: #e9ecef;
            }
            QProgressBar::chunk {
                background-color: #27ae60;
            }
        """)
        work_layout.addWidget(self.global_progress_bar)
        
        return work_panel
    
    def _setup_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_label = QLabel("就绪")
        self.status_bar.addWidget(self.status_label)
        self.file_count_label = QLabel("")
        self.status_bar.addPermanentWidget(self.file_count_label)
    
    def _setup_menu(self):
        menubar = self.menuBar()
        
        file_menu = menubar.addMenu("文件(&F)")

        self.process_action = QAction("开始处理", self)  #🚀 开始处理
        self.process_action.setShortcut(QKeySequence("Ctrl+Shift+D"))
        self.process_action.triggered.connect(self._on_global_process_clicked)
        file_menu.addAction(self.process_action)

        file_menu.addSeparator()

        # ★ 预检预览
        self.preview_action = QAction("📋 批量预检摘要", self)
        self.preview_action.setShortcut(QKeySequence("Ctrl+Shift+L"))
        self.preview_action.setToolTip("批量扫描所有文件的公式变更摘要")
        self.preview_action.triggered.connect(self._on_preview_triggered)
        file_menu.addAction(self.preview_action)

        file_menu.addSeparator()
        
        # ★ 监视面板
        monitor_action = QAction("📊 监视面板(&M)", self)
        monitor_action.setShortcut(QKeySequence("Ctrl+Shift+M"))
        monitor_action.setToolTip("打开工作流可视化监视面板")
        monitor_action.triggered.connect(self._open_monitor_panel)
        file_menu.addAction(monitor_action)

        file_menu.addSeparator()   

        exit_action = QAction("退出(&X)", self)
        exit_action.setShortcut(QKeySequence("Ctrl+W"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        view_menu = menubar.addMenu("视图(&V)")
        
        theme_menu = view_menu.addMenu("切换主题")
        for theme_key, theme_name in self.theme_manager.get_available_themes().items():
            action = QAction(theme_name, self)
            action.triggered.connect(
                lambda checked, k=theme_key: self._change_theme(k)
            )
            theme_menu.addAction(action)
        
        module_menu = view_menu.addMenu("切换模块")
        self._module_menu_actions: Dict[str, QAction] = {}
        
        module_ids = list(self.modules.keys())
        keys = ["Ctrl+0", "Ctrl+1", "Ctrl+2", "Ctrl+3", "Ctrl+4"]
        
        for i, module_id in enumerate(module_ids):
            module = self.modules[module_id]
            shortcut = keys[i] if i < len(keys) else None
            
            action = QAction(f"{module.module_icon} {module.module_name}", self)
            action.setCheckable(True)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(
                lambda checked, mid=module_id: self._switch_module(mid)
            )
            
            self._module_menu_actions[module_id] = action
            module_menu.addAction(action)
        
        if module_ids:
            self._module_menu_actions[module_ids[0]].setChecked(True)
        
        # ★ 启动默认模块设置
        view_menu.addSeparator() #分隔线

        # ★ 启动默认模块设置
        startup_label = QAction("启动时默认切换到：", self)
        startup_label.setEnabled(False)
        view_menu.addAction(startup_label)

        self._startup_module_actions = {}
        for module_id, module in self.modules.items():
            action = QAction(f"  {module.module_icon} {module.module_name}", self)
            action.setCheckable(True)
            action.triggered.connect(
                lambda checked, mid=module_id: self._set_startup_module(mid)
            )
            self._startup_module_actions[module_id] = action
            view_menu.addAction(action)

        # 恢复勾选状态
        saved = self._get_startup_module()
        if saved and saved in self._startup_module_actions:
            self._startup_module_actions[saved].setChecked(True)

        view_menu.addSeparator() #分隔线
        
        self.toggle_log_action = QAction("显示日志面板", self)
        self.toggle_log_action.setCheckable(True)
        self.toggle_log_action.setChecked(True)
        self.toggle_log_action.setShortcut(QKeySequence("Ctrl+L"))
        self.toggle_log_action.triggered.connect(self._toggle_log_panel)
        view_menu.addAction(self.toggle_log_action)
        
        clear_log_action = QAction("清空日志", self)
        clear_log_action.setShortcut(QKeySequence("Ctrl+Q"))
        clear_log_action.triggered.connect(self.log_panel.clear)
        view_menu.addAction(clear_log_action)
        
        self.clear_files_action = QAction("清空文件列表", self)
        self.clear_files_action.setShortcut(QKeySequence("Ctrl+Shift+Q"))
        self.clear_files_action.setToolTip("清空当前功能模块的所有已添加文件")
        self.clear_files_action.triggered.connect(self._on_clear_files_triggered)
        view_menu.addAction(self.clear_files_action)
        
        # ★ 新增：唤醒主窗口提示
        self.wake_action = QAction("唤醒主窗口", self)
        self.wake_action.setShortcut(QKeySequence("Ctrl+Shift+K"))
        self.wake_action.setToolTip("从系统托盘或后台唤醒主窗口并置于最前")
        self.wake_action.triggered.connect(self._show_from_tray)
        view_menu.addAction(self.wake_action)

        view_menu.addSeparator()


        tray_text = "关闭时隐藏到托盘" if self.close_to_tray else "关闭时直接退出"
        self.tray_action = QAction(tray_text, self)
        self.tray_action.setCheckable(True)
        self.tray_action.setChecked(self.close_to_tray)
        self.tray_action.setShortcut(QKeySequence("Ctrl+K"))
        self.tray_action.triggered.connect(self._toggle_tray_mode)
        view_menu.addAction(self.tray_action)
        
        help_menu = menubar.addMenu("帮助(&H)")
        
        dep_install_action = QAction("安装依赖工具(&D)", self)
        dep_install_action.setToolTip("一键安装 Pandoc、Calibre、Node.js + Mermaid CLI")
        dep_install_action.triggered.connect(self._show_dependency_installer)
        help_menu.addAction(dep_install_action)

        help_menu.addSeparator()

        shortcut_action = QAction("快捷键一览(&K)", self)
        shortcut_action.triggered.connect(self._show_shortcuts)
        help_menu.addAction(shortcut_action)

        help_menu.addSeparator()

        readme_action = QAction("用户手册(&U)", self)
        readme_action.setToolTip("打开项目完整使用文档（README.html）")
        readme_action.triggered.connect(self._open_readme)
        help_menu.addAction(readme_action)

        help_menu.addSeparator()

        about_action = QAction("关于(&A)", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

        help_menu.addSeparator()

        clear_data_action = QAction("清除用户数据(&C)", self)
        clear_data_action.setToolTip(
            "清除所有保存的设置（窗口布局、修复配置等），下次启动恢复默认"
        )
        clear_data_action.triggered.connect(self._clear_all_settings)
        help_menu.addAction(clear_data_action)

    def _show_dependency_installer(self):
        from core.components.dependency_installer import DependencyInstallerDialog
        dialog = DependencyInstallerDialog(self)
        dialog.exec()

    # ==================== 托盘模式切换 ====================

    def _toggle_tray_mode(self, checked: bool):
        self.close_to_tray = checked
        self.settings.setValue(SettingsKey.CLOSE_TO_TRAY, checked)
        self.tray_action.setText("关闭时隐藏到托盘" if checked else "关闭时直接退出")
        
        if checked:
            self.status_bar.showMessage(
                "✅ 已启用托盘模式：关闭窗口时将隐藏到系统托盘", 3500
            )
        else:
            self.status_bar.showMessage(
                "ℹ️ 已关闭托盘模式：关闭窗口时将直接退出程序", 3500
            )

    # ==================== 主题管理 ====================

    def _apply_theme(self):
        theme_name = self.theme_manager.current_theme
        if theme_name not in self._cached_stylesheets:
            self._cached_stylesheets[theme_name] = self.theme_manager.get_stylesheet()
        self.setStyleSheet(self._cached_stylesheets[theme_name])
        self.log_panel.set_dark_theme(theme_name == "dark")
    
    def _change_theme(self, theme_name: str):
        self.theme_manager.set_theme(theme_name)
        self._apply_theme()
        self.log_panel.log(
            f"已切换到{self.theme_manager.colors['name']}", "INFO"
        )

    # ==================== 依赖检查 ====================

    def _check_all_dependencies(self):
        self.log_panel.log("=" * 60)
        self.log_panel.log(f"📚 {__app_name__} v{__version__} 启动")
        self.log_panel.log("=" * 60)
        for module_id, module in self.modules.items():
            ok, msg = module.check_dependencies()
            if ok:
                self.log_panel.log(f"✅ {module.module_name}: {msg}", "SUCCESS")
            else:
                self.log_panel.log(f"⚠️ {module.module_name}: {msg}", "WARNING")
        self.log_panel.log("=" * 60)

    # ==================== 模块切换 ====================

    def _switch_module(self, module_id: str):
        if module_id not in self.modules:
            return
        
        for bid, btn in self.nav_buttons.items():
            if bid == module_id:
                btn.setProperty("class", "nav-button active")
            else:
                btn.setProperty("class", "nav-button")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        
        if hasattr(self, '_module_menu_actions'):
            for mid, action in self._module_menu_actions.items():
                action.setChecked(mid == module_id)
        
        if self.current_module:
            self.current_module.on_deactivate()
        
        self.current_module = self.modules[module_id]
        self.current_module.on_activate()
        
        for i in range(self.work_area.count()):
            widget = self.work_area.widget(i)
            if widget == self.current_module.ui_widget:
                self.work_area.setCurrentIndex(i)
                break
        
        self.module_title_label.setText(
            f"{self.current_module.module_icon} {self.current_module.module_name}"
        )
        
        ok, msg = self.current_module.check_dependencies()
        if ok:
            self.dep_status_label.setText("✅ 依赖就绪")
            self.dep_status_label.setStyleSheet("color: #27ae60;")
        else:
            self.dep_status_label.setText("⚠️ 依赖缺失")
            self.dep_status_label.setStyleSheet("color: #e67e22;")
        
        self.module_desc_hint.setText(self.current_module.module_description)
        self._update_global_buttons_state()
        self._update_file_count()
        self.log_panel.log(f"切换到模块: {self.current_module.module_name}")
        
        if hasattr(self.current_module, 'file_list'):
            self.current_module.file_list.setFocus()

    # ==================== 辅助方法 ====================

    def _get_module_progress_bar(self, widget: QWidget) -> Optional[QProgressBar]:
        """从模块 UI 中查找进度条"""
        for child in widget.findChildren(QProgressBar):
            return child
        return None
    
    def _update_file_count(self):
        if self.current_module and hasattr(self.current_module, 'file_list'):
            count = self.current_module.file_list.count()
            self.file_count_label.setText(f"已选择 {count} 个文件")
        else:
            self.file_count_label.setText("")
    
    def _update_global_buttons_state(self):
        if self.current_module:
            is_processing = self.current_module.is_processing
            self.global_process_btn.setEnabled(not is_processing)
            self.global_stop_btn.setEnabled(is_processing)
            if is_processing:
                self.global_process_btn.setText("🔄 处理中...")
            else:
                self.global_process_btn.setText("🚀 开始处理")
        else:
            self.global_process_btn.setEnabled(False)
            self.global_stop_btn.setEnabled(False)
            self.global_process_btn.setText("🚀 开始处理")

    # ==================== 处理控制 ====================

    def _on_global_process_clicked(self):
        if self.current_module:
            self.current_module.start_processing()
            self._update_global_buttons_state()
    
    def _on_global_stop_clicked(self):
        if self.current_module:
            self.current_module.stop_processing()
            self._update_global_buttons_state()

    def _on_clear_files_triggered(self):
        if self.current_module:
            self.current_module.clear_all_files()

    # ==================== 模块信号回调 ====================

    def _on_module_status_changed(self, status: str):
        if status == "processing":
            self.status_label.setText("处理中...")
        else:
            self.status_label.setText("就绪")
        self._update_global_buttons_state()
    
    def _on_module_progress_updated(self, percent: int, message: str):
        self.global_progress_bar.setValue(percent)
        if message:
            self.status_label.setText(message)
        self._update_file_count()
    
    def _on_module_log(self, message: str, level: str):
        self.log_panel.log(message, level)

    def _on_preview_triggered(self):
        """Ctrl+Shift+L 快捷键：预检预览"""
        if self.current_module and hasattr(self.current_module, '_preview_files'):
            self.current_module._preview_files(entry_point="shortcut") 

    def _open_monitor_panel(self):
        """菜单栏打开监视面板"""
        if hasattr(self, 'current_module') and self.current_module:
            if hasattr(self.current_module, '_open_monitor_panel'):
                self.current_module._open_monitor_panel()

    # ==================== 日志面板控制 ====================

    def _show_log_panel(self):
        self.collapsible_log.show_panel()
    
    def _toggle_log_panel(self, checked: bool):
        if checked:
            self.collapsible_log.show_panel()
        else:
            self.collapsible_log.hide_panel()
    
    def _on_log_visibility_changed(self, visible: bool):
        self.toggle_log_action.setChecked(visible)
        self.show_log_btn.setVisible(not visible)
        self.settings.setValue(SettingsKey.LOG_PANEL_VISIBLE, visible)
    
    def _on_pin_state_changed(self, pinned: bool):
        self.settings.setValue(SettingsKey.LOG_PANEL_PINNED, pinned)
        if pinned and not self.collapsible_log.isVisible():
            self.collapsible_log.show_panel()

    # ==================== 关于与设置 ====================

    def _show_about(self):
        dialog = AboutDialog(self)
        dialog.exec()

    def _open_readme(self):
        """用系统默认应用打开 README.html"""
        import os
        readme_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            "resources", "README.html"
        )
        if os.path.exists(readme_path):
            if sys.platform == 'win32':
                os.startfile(readme_path)
            elif sys.platform == 'darwin':
                import subprocess
                subprocess.run(['open', readme_path])
            else:
                import subprocess
                subprocess.run(['xdg-open', readme_path])
        else:
            QMessageBox.warning(self, "提示", "README.html 文件未找到")

    def _set_startup_module(self, module_id: str):
        """设置启动默认模块"""
        self.settings.setValue(SettingsKey.STARTUP_MODULE, module_id)
        for mid, action in self._startup_module_actions.items():
            action.setChecked(mid == module_id)

    def _get_startup_module(self) -> Optional[str]:
        """获取启动默认模块"""
        module_id = self.settings.value(SettingsKey.STARTUP_MODULE, None)
        if module_id and module_id in self.modules:
            return module_id
        return None

    def _clear_all_settings(self):
        """清除所有用户数据并支持一键重启应用默认设置"""
        reply = QMessageBox.question(
            self, "清除用户数据",
            "将清除所有保存的设置，包括：\n"
            "• 窗口布局和日志面板状态\n"
            "• MD公式修复的高级设置方案\n"
            "• 工作流模块的配置\n"
            "• EPUB转Word/PDF 等模块的转换选项与记忆状态\n"
            "下次启动将恢复默认设置。\n是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # 重置托盘模式为默认值
        self.close_to_tray = self.DEFAULT_CLOSE_TO_TRAY
        self.tray_action.setChecked(self.DEFAULT_CLOSE_TO_TRAY)

        # 1. 清除主窗口设置（含所有模块配置键）
        main_settings = QSettings(SettingsDomain.EPUB_TOOLBOX, SettingsDomain.SETTINGS)
        main_settings.clear()
        
        # 2. 清除 MD 修复配置
        repair_settings = QSettings(SettingsDomain.EPUB_TOOLBOX, SettingsDomain.MD_REPAIR)
        repair_settings.clear()
        
        # 3. 清除工作流独立域名（兼容旧版）
        workflow_settings = QSettings(SettingsDomain.EPUB_TOOLBOX, SettingsDomain.WORKFLOW)
        workflow_settings.clear()
        
        # 4. 清除独立版残留（兼容旧版）
        standalone_settings = QSettings("MDFormulaFixer", "SettingsV8")
        standalone_settings.clear()
        
        # ★ 强制同步到磁盘，确保内存缓存被刷新
        main_settings.sync()
        repair_settings.sync()
        workflow_settings.sync()
        standalone_settings.sync()
        
        # 5. 清理缓存目录（MathJax 缓存等）
        cache_dir = Path(QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.CacheLocation
        ))
        if cache_dir.exists():
            shutil.rmtree(cache_dir, ignore_errors=True)
        
        self.log_panel.log("🗑️ 已清除所有用户数据", "SUCCESS")
        
        # ★ 提供一键重启选项，确保默认设置立即生效
        restart_reply = QMessageBox.question(
            self, "重启程序",
            "用户数据已清除。\n\n"
            "由于 QSettings 存在内存缓存，建议立即重启程序\n"
            "以确保所有模块恢复到默认设置。\n\n"
            "是否立即重启？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        
        if restart_reply == QMessageBox.StandardButton.Yes:
            self._is_force_quit = True
            self.close()
            # 使用 os.execv 原地替换当前进程，实现干净重启
            os.execv(sys.executable, [sys.executable] + sys.argv)
        else:
            QMessageBox.information(
                self, "提示",
                "用户数据已清除。\n请手动重启程序以应用默认设置。"
            )

    # ==================== 关闭与清理 ====================

    def closeEvent(self, event):
        if self.close_to_tray and not self._is_force_quit:
            event.ignore()
            self.hide()
            self.tray_icon.showMessage(
                f"{__app_name__}",
                "程序已最小化到系统托盘，双击托盘图标恢复窗口。\n右键托盘图标可退出。",
                QSystemTrayIcon.MessageIcon.Information,
                2000
            )
            return
        
        processing_modules = [
            module.module_name
            for module in self.modules.values()
            if module.is_processing
        ]
        
        if processing_modules:
            reply = QMessageBox.question(
                self, "确认退出",
                f"以下模块正在处理中：\n\n• " + "\n• ".join(processing_modules) +
                "\n\n强制退出可能导致数据丢失。\n确定要退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
            
            self._graceful_shutdown(timeout=2000)
        else:
            self._save_all_settings()
            self._cleanup_temp_files()
        
        if hasattr(self, 'collapsible_log') and self.collapsible_log.isVisible():
            sizes = self.main_splitter.sizes()
            if len(sizes) == 3 and all(s >= 50 for s in sizes):
                self.settings.setValue(SettingsKey.SPLITTER_SIZES, sizes)
        
        if hasattr(self, 'tray_icon'):
            self.tray_icon.hide()
        
        if HAS_KEYBOARD:
            try:
                keyboard.unhook_all_hotkeys()
            except Exception as e:
                logger.warning(f"解绑热键失败: {e}")
        
        event.accept()
        QApplication.quit()

    def _graceful_shutdown(self, timeout: int = 3000):
        log_func = self.log_panel.log if hasattr(self, 'log_panel') and self.log_panel else print
        
        log_func("🛑 正在优雅关闭程序...", "INFO")
        
        for module_id, module in self.modules.items():
            if module.is_processing:
                log_func(f"  停止模块: {module.module_name}", "INFO")
                module.stop_processing()
        
        workers = []
        for module in self.modules.values():
            if hasattr(module, 'worker') and module.worker:
                if module.worker.isRunning():
                    workers.append(module.worker)
        
        if workers:
            log_func(
                f"⏳ 等待 {len(workers)} 个工作线程结束（最多 {timeout}ms）...",
                "INFO"
            )
            for worker in workers:
                if not worker.wait(timeout):
                    log_func(
                        f"  ⚠️ 线程 {worker.__class__.__name__} 未能在 {timeout}ms 内结束，强制终止",
                        "WARNING"
                    )
                    worker.terminate()
                    worker.wait(500)
        
        self._save_all_settings()
        self._cleanup_temp_files()
        QApplication.processEvents()
        log_func("✅ 程序已安全退出", "SUCCESS")

    def _save_all_settings(self):
        try:
            if hasattr(self, 'collapsible_log') and self.collapsible_log.isVisible():
                sizes = self.main_splitter.sizes()
                if len(sizes) == 3 and all(s >= 50 for s in sizes):
                    self.settings.setValue(SettingsKey.SPLITTER_SIZES, sizes)
            
            if hasattr(self, 'collapsible_log'):
                self.settings.setValue(SettingsKey.LOG_PANEL_PINNED, self.collapsible_log.is_pinned)
                self.settings.setValue(SettingsKey.LOG_PANEL_VISIBLE, self.collapsible_log.isVisible())

            self.settings.setValue(SettingsKey.CLOSE_TO_TRAY, self.close_to_tray)
            self.settings.sync()
            
            for module in self.modules.values():
                if hasattr(module, '_save_config'):
                    try:
                        module._save_config()
                    except Exception as e:
                        logger.warning(f"保存 {module.module_name} 配置失败: {e}")
        except Exception as e:
            logger.warning(f"保存设置失败: {e}")

    def _cleanup_temp_files(self):
        import shutil
        
        if 'workflow' in self.modules:
            module = self.modules['workflow']
            if hasattr(module, 'worker') and module.worker:
                if hasattr(module.worker, 'temp_roots'):
                    for temp_root in module.worker.temp_roots:
                        if temp_root and temp_root.exists():
                            try:
                                shutil.rmtree(temp_root, ignore_errors=True)
                                logger.debug(f"清理临时目录: {temp_root}")
                            except Exception:
                                pass
        
        if 'md2epub' in self.modules:
            module = self.modules['md2epub']
            if hasattr(module, 'last_temp_roots'):
                for temp_root in module.last_temp_roots:
                    if temp_root and temp_root.exists():
                        try:
                            shutil.rmtree(temp_root, ignore_errors=True)
                        except Exception:
                            pass

    # ==================== 信号处理 ====================

    def _signal_handler(self, signum, frame):
        if hasattr(self, 'log_panel') and self.log_panel:
            self.log_panel.log("⚠️ 收到中断信号，正在优雅退出...", "WARNING")
        self._graceful_shutdown()
        QApplication.quit()
    
    def _atexit_cleanup(self):
        pass
# ==================== 主入口 ====================

def main():
    """主函数 - 带启动画面版本"""

    # ★ 抑制 QThreadStorage 在非优雅退出后的调试警告
    os.environ.setdefault('QT_LOGGING_RULES', 'qt.thread.storage=false')

    app = QApplication(sys.argv)

    # ★ 清理 PyInstaller 单文件模式残留的临时目录
    import tempfile
    import time
    _temp_dir = Path(tempfile.gettempdir())
    _cleaned_count = 0
    for _old_dir in _temp_dir.glob("_MEI*"):
        try:
            if time.time() - _old_dir.stat().st_mtime > 86400:
                shutil.rmtree(_old_dir, ignore_errors=True)
                _cleaned_count += 1
        except Exception:
            pass
    if _cleaned_count > 0:
        print(f"[启动清理] 已清理 {_cleaned_count} 个残留临时目录")


    # ★ 多实例计数检测
    import struct
    import ctypes
    
    shared_memory = QSharedMemory("EPUBToolbox_InstanceCounter")

    if shared_memory.attach():
        shared_memory.lock()
        raw = bytes(shared_memory.data()) if shared_memory.size() >= 4 else b'\x00\x00\x00\x00'
        counter = struct.unpack('i', raw[:4])[0]
        shared_memory.unlock()

        if counter >= MAX_INSTANCES:
            QMessageBox.warning(
                None, "提示",
                f"EPUB 工具箱最多允许 {MAX_INSTANCES} 个窗口同时运行。\n"
                f"当前已有 {MAX_INSTANCES} 个窗口，请关闭一个后再试。"
            )
            return 0
        else:
            counter += 1
            shared_memory.lock()
            ctypes.memmove(int(shared_memory.data()), struct.pack('i', counter), 4)
            shared_memory.unlock()
    else:
        if not shared_memory.create(4):
            QMessageBox.warning(None, "错误", "无法启动程序")
            return 1
        shared_memory.lock()
        ctypes.memmove(int(shared_memory.data()), struct.pack('i', 1), 4)
        shared_memory.unlock()

    # ★ 关闭时减少计数
    def on_about_to_quit():
        if shared_memory.attach():
            shared_memory.lock()
            raw = bytes(shared_memory.data()) if shared_memory.size() >= 4 else b'\x00\x00\x00\x00'
            counter = struct.unpack('i', raw[:4])[0]
            if counter > 0:
                counter -= 1
                ctypes.memmove(int(shared_memory.data()), struct.pack('i', counter), 4)
            shared_memory.unlock()
            shared_memory.detach()

    app.aboutToQuit.connect(on_about_to_quit)


    def sigint_handler(signum, frame):
        QApplication.quit()
    
    signal.signal(signal.SIGINT, sigint_handler)
    app.setApplicationName(__app_name__)
    app.setApplicationVersion(__version__)
    app.setStyle('Fusion')
    
    # ★ 创建启动动画管理器
    splash = SplashManager(
        icon_path=resource_path("resources/icon.png"),
        title=__app_name__,
        version=__version__
    )
    
    splash.show_message("正在初始化...")
    app.processEvents()
    
    app.setWindowIcon(QIcon(resource_path("resources/icon.ico")))

    window = EPUBToolboxHub()
    
    # ★ 预热所有模块 UI
    splash.show_message("正在加载模块...")
    for module_id, module in window.modules.items():
        _ = module.ui_widget
    
    splash.finish(window)
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()