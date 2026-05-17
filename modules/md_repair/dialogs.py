#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MD公式修复模块 - 对话框组件
包含：AdvancedSettingsDialog / FeatureHelpDialog / SideBySidePreviewDialog
"""


import urllib.request
import difflib
import tempfile
import webbrowser
import logging
import copy
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
from threading import Thread
from core.config_keys import MDRepairKey

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QCheckBox, QComboBox, QScrollArea, QFrame,
    QDialogButtonBox, QTextEdit, QTextBrowser, QTabWidget,
    QSplitter, QWidget, QButtonGroup, QSlider, QSpinBox, QLineEdit,
    QGridLayout, QListWidget, QListWidgetItem, QMessageBox
)
from PyQt6.QtCore import Qt, QSettings, pyqtSignal, QEvent, QStandardPaths, QUrl
from PyQt6.QtGui import QFont, QColor, QIntValidator, QShortcut, QKeySequence

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    HAS_WEBENGINE = True
except ImportError:
    HAS_WEBENGINE = False

from .processor import (
    RiskLevel, FormulaChange, RepairProfile,
    FeatureHelpDatabase, ImageCaptionOptimizer,
    ConfigurableFormulaFixer, FormulaPreviewer
)


# 模块级日志记录器
logger = logging.getLogger(__name__)


# ==================== 模块级常量 ====================

# MathJax CDN URLs
MATHJAX_V2_CDN = "https://cdnjs.cloudflare.com/ajax/libs/mathjax/2.7.7/MathJax.js?config=TeX-MML-AM_CHTML"
MATHJAX_V3_CDN = "https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-svg.js"

# ==================== MathJax 本地缓存支持 ====================

# ★ 项目内置 MathJax 目录（resources/mathjax/）
import sys
_MATHJAX_BUNDLED_DIR = None

def _get_mathjax_bundled_dir() -> Optional[Path]:
    """获取项目内置的 MathJax 目录（resources/mathjax/）
    
    支持开发模式和 PyInstaller 打包模式。
    """
    global _MATHJAX_BUNDLED_DIR
    if _MATHJAX_BUNDLED_DIR is not None:
        return _MATHJAX_BUNDLED_DIR if _MATHJAX_BUNDLED_DIR != Path() else None
    
    candidates = [
        Path(__file__).parent.parent.parent / "resources" / "mathjax",
    ]
    
    if hasattr(sys, '_MEIPASS'):
        candidates.append(Path(sys._MEIPASS) / "resources" / "mathjax")
    
    for candidate in candidates:
        if candidate and candidate.exists():
            _MATHJAX_BUNDLED_DIR = candidate
            logger.debug(f"MathJax 内置目录: {candidate}")
            return candidate
    
    _MATHJAX_BUNDLED_DIR = Path()
    return None

def _get_mathjax_cache_dir() -> Path:
    """获取 MathJax 缓存目录"""
    cache_base = Path(QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.CacheLocation
    ))
    cache_dir = cache_base / "epub_toolbox" / "mathjax"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _get_mathjax_url() -> str:
    """获取 MathJax URL，优先级：项目内置 > 用户缓存 > CDN
    
    Returns:
        str: MathJax 的 URL（file:// 或 https://）
    """
    # 1. 优先使用项目内置（resources/mathjax/）
    bundled_dir = _get_mathjax_bundled_dir()
    if bundled_dir:
        main_file = bundled_dir / "tex-svg.js"
        extensions_dir = bundled_dir / "input" / "tex" / "extensions"
        if (main_file.exists() and main_file.stat().st_size > 10000 
                and extensions_dir.exists()):
            return QUrl.fromLocalFile(str(main_file)).toString()
    
    # 2. 其次使用用户缓存（AppData）
    cache_dir = _get_mathjax_cache_dir()
    main_file = cache_dir / "tex-svg.js"
    if main_file.exists() and main_file.stat().st_size > 10000:
        return QUrl.fromLocalFile(str(main_file)).toString()
    
    # 3. 最后使用 CDN
    return MATHJAX_V3_CDN


def _download_mathjax_async(parent=None):
    """异步下载 MathJax 到本地缓存（后台线程，不阻塞 UI）"""
    
    def _download():
        try:
            cache_dir = _get_mathjax_cache_dir()
            main_file = cache_dir / "tex-svg.js"
            
            if main_file.exists() and main_file.stat().st_size > 10000:
                return
            
            urllib.request.urlretrieve(MATHJAX_V3_CDN, main_file)
            logger.info(f"MathJax 已缓存到本地: {main_file}")
        except Exception as e:
            logger.debug(f"MathJax 缓存下载失败（将在下次使用时重试）: {e}")
    
    thread = Thread(target=_download, daemon=True)
    thread.start()

# HTML 模板（预定义，避免每次渲染时重建）
_MATHJAX_V3_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<script>
window.MathJax = {{
    tex: {{ inlineMath: [['$', '$'], ['\\\\(', '\\\\)']] }},
    svg: {{ fontCache: 'global' }}
}};
</script>
<script src="{mathjax_url}"></script>
<style>
    body {{
        font-family: 'Microsoft YaHei', serif;
        font-size: 16px; line-height: 1.8;
        padding: 12px 16px; color: #2c3e50;
        background: #fafafa; margin: 0;
    }}
    .formula {{
        background: #fff; border-left: 3px solid #3498db;
        padding: 14px 18px; margin: 8px 0;
        border-radius: 0 6px 6px 0; font-size: 17px;
    }}
</style>
</head>
<body>

<div class="formula">$${formula}$$</div>
</body>
</html>"""

_TEXT_PREVIEW_HTML_TEMPLATE = """
<style>
    body {{ font-family: 'Consolas', monospace; font-size: 14px; }}
    .formula {{ white-space: pre-wrap; padding: 10px; }}
</style>
<p style="color:#888;">📐 公式预览（文本模式）</p>
<div class="formula">{formula}</div>"""

_BROWSER_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<script type="text/javascript" async
    src="{mathjax_url}">
</script>
<style>
    body {{
        font-family: 'Microsoft YaHei', 'Times New Roman', serif;
        font-size: 18px;
        line-height: 1.8;
        padding: 40px;
        max-width: 900px;
        margin: 0 auto;
        color: #2c3e50;
        background: #fff;
    }}
    h1, h2, h3 {{
        color: #1a1a1a;
        margin-top: 1.5em;
    }}
    code {{
        background: #f4f4f4;
        padding: 2px 6px;
        border-radius: 3px;
        font-family: Consolas, monospace;
        font-size: 0.9em;
    }}
    pre {{
        background: #2d2d2d;
        color: #f8f8f2;
        padding: 16px;
        border-radius: 6px;
        overflow-x: auto;
    }}
    pre code {{
        background: none;
        padding: 0;
    }}
</style>
</head>
<body>
{content}
</body>
</html>"""

# 日志文本到功能键名的映射（预编译为模块级常量）
_LOG_TO_FEATURE_MAP = {
    '编码修复': 'fix_encoding',
    '括号': 'bracket_check',
    '上下标修正': 'subsup_fix',
    '函数名正体化': 'func_normalize',
    'Markdown转义': 'markdown_escape_inline',
    '移除矩阵末尾换行': 'matrix_newline_remove',
    '添加矩阵乘号': 'matrix_add_multiplication',
    '\\bm→\\vec': 'bm_to_vec',
    '移除:': 'remove_size_commands',
    '→\\text': 'dl_commands_to_text',
    '美元符号转义': 'escape_isolated_dollars',
    '多余换行': 'clean_newlines',
    '行内公式后添加空格': 'add_space_after_inline',
    '独立行内转块级': 'inline_to_display',
    '图片标题': 'image_caption',
}

# 功能键名到配置字段的映射（用于快速调整面板）
_FEATURE_TO_CONFIG_MAP = {
    'clean_newlines': ('top', MDRepairKey.CLEAN_EXTRA_NEWLINES),
    'add_space_after_inline': ('top', MDRepairKey.ADD_SPACE_AFTER_INLINE),
    'subsup_fix': ('formula', MDRepairKey.SUBSUP_FIX),
    'func_normalize': ('formula', MDRepairKey.FUNC_NORMALIZE),
    'matrix_newline_remove': ('formula', MDRepairKey.MATRIX_NEWLINE_REMOVE),
    'bracket_check': ('formula', MDRepairKey.BRACKET_CHECK),
    'markdown_escape_inline': ('formula', MDRepairKey.MARKDOWN_ESCAPE_INLINE),
    'matrix_add_multiplication': ('formula', MDRepairKey.MATRIX_ADD_MULTIPLICATION),
    'dl_commands_to_text': ('formula', MDRepairKey.DL_COMMANDS_TO_TEXT),
    'remove_size_commands': ('formula', MDRepairKey.REMOVE_SIZE_COMMANDS),
    'bm_to_vec': ('formula', MDRepairKey.BM_TO_VEC),
    'inline_to_display': ('top', MDRepairKey.INLINE_TO_DISPLAY),
    'image_caption': ('top', MDRepairKey.IMAGE_CAPTION_ENABLED),
    'respect_macros': ('formula', MDRepairKey.RESPECT_MACROS),
    'fix_encoding': ('top', MDRepairKey.FIX_ENCODING),
    'escape_isolated_dollars': ('top', MDRepairKey.ESCAPE_ISOLATED_DOLLARS),
}

# 功能说明 HTML 模板（用于展开详情）
_LOG_DETAIL_HTML_TEMPLATE = """
<style>
    body {{ font-family: 'Microsoft YaHei', sans-serif; font-size: 11px; line-height: 1.5; margin: 0; }}
    .label {{ color: #6c757d; font-weight: bold; }}
    .highlight {{ background: #fff3cd; padding: 4px 8px; border-radius: 3px; border-left: 3px solid #ffc107; margin: 4px 0; }}
    .example {{ background: #d4edda; padding: 4px 8px; border-radius: 3px; margin: 4px 0; }}
</style>
<p><span class="label">🎯 触发条件：</span>{trigger}</p>
<p><span class="label">⚡ 执行操作：</span>{action}</p>
<div class="highlight">📄 修改前：<code>{example_before}</code></div>
<div class="example">✅ 修改后：<code>{example_after}</code></div>
<p><span class="label">📋 建议：</span>{recommendation}</p>"""


# ==================== 并排对比预览对话框 ====================

class SideBySidePreviewDialog(QDialog):
    """并排对比预览对话框 - 显示公式修复前后的差异
    
    功能：
        - 左右并排对比原始/修复后公式
        - 逐处导航查看变更
        - 内嵌 MathJax 渲染预览（需联网）
        - 快速调整面板：边预览边开关功能
        - 修改详情可点击展开功能说明
        - 在系统浏览器中查看完整渲染效果
    """

    # ★ 新增信号：快速调整配置写回请求
    config_apply_requested = pyqtSignal(dict)    

    # 最大变更数提示阈值
    MAX_CHANGES_HINT_THRESHOLD = 20

    def __init__(self, changes: List[FormulaChange], parent=None, file_name: str = ""):
        """初始化预览对话框
        
        Args:
            changes: 公式变更列表
            parent: 父级窗口
            file_name: 文件名（用于标题显示）
        """
        super().__init__(parent)
        self.changes = changes
        self.file_name = file_name
        self.current_index = -1
        self._expanded_row = -1
        self._original_config = None
        self._temp_config = None
        self._checkboxes: Dict[str, QCheckBox] = {}
        self._current_formula = ""
        self._all_time_features: set = set()  # ★ 累积所有触发过的功能
        self._is_standalone_config = False  # ★ 独立配置模式标志
        self._request_open_row_config = False  # ★ 是否请求打开独立修复设置

        self._setup_ui()
        self._config_apply_pending = False
        self._config_to_apply = None

    def _setup_ui(self):
        """构建 UI 布局"""
        title = "🔍 修复预览"
        if self.file_name:
            title += f" - {Path(self.file_name).name}"
        title += f" ({len(self.changes)}处变更)"
        self.setWindowTitle(title)
        self.setMinimumSize(1000, 700)
        self.resize(1100, 800)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # 统计栏
        layout.addLayout(self._create_stats_bar())

        # 变更较多提示
        if len(self.changes) > self.MAX_CHANGES_HINT_THRESHOLD:
            hint = QLabel(
                f"💡 变更较多（{len(self.changes)}处），建议逐处检查后再决定是否应用"
            )
            hint.setStyleSheet("color: #e67e22; font-size: 12px; padding: 2px 0;")
            layout.addWidget(hint)

        # 左右对比视图
        layout.addWidget(self._create_diff_view(), 1)

        # 渲染预览面板
        layout.addWidget(self._create_render_panel())


        bottom_widget = QWidget()
        bottom_layout = QHBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(8)

        log_panel = self._create_log_panel()
        log_panel.setMinimumWidth(250)

        bottom_layout.addWidget(log_panel, 1)

        quick_panel = self._create_quick_panel()
        quick_panel.setMinimumWidth(350)

        bottom_layout.addWidget(quick_panel, 1)



        layout.addWidget(bottom_widget)

        # 关闭按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.reject)  # 改为 reject 而不是 accept
        close_btn.setStyleSheet("padding: 6px 20px;")
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        # 显示第一个变更
        if self.changes:
            self._show_change(0)

        # ★ 新增：Ctrl+W 关闭预览
        # from PyQt6.QtGui import QShortcut, QKeySequence, Qt

        close_shortcut = QShortcut(QKeySequence("Ctrl+W"), self)
        close_shortcut.activated.connect(self.reject)       

        # prev_shortcut = QShortcut(QKeySequence("Ctrl+Left"), self)
        # prev_shortcut.activated.connect(lambda: self._navigate(-1))

        # next_shortcut = QShortcut(QKeySequence("Ctrl+Right"), self)
        # next_shortcut.activated.connect(lambda: self._navigate(1))     

    def _create_stats_bar(self) -> QHBoxLayout:
        """创建统计栏"""
        stats_layout = QHBoxLayout()

        risk_counts = {'low': 0, 'medium': 0, 'high': 0}
        type_counts = {'inline': 0, 'display': 0}
        for c in self.changes:
            risk_counts[c.risk_level] = risk_counts.get(c.risk_level, 0) + 1
            type_counts[c.formula_type] = type_counts.get(c.formula_type, 0) + 1

        summary_parts = [f"共 {len(self.changes)} 处变更"]
        for level in ['high', 'medium', 'low']:
            if risk_counts[level] > 0:
                rl = RiskLevel(level)
                summary_parts.append(f"{rl.icon}{risk_counts[level]}")
        summary_parts.append(f"| 行内:{type_counts['inline']} 块级:{type_counts['display']}")

        # stats_label = QLabel("  ".join(summary_parts))
        # stats_label.setStyleSheet("font-size: 13px;")
        # stats_layout.addWidget(stats_label)

        self.stats_label = QLabel("  ".join(summary_parts))
        self.stats_label.setStyleSheet("font-size: 13px;")
        stats_layout.addWidget(self.stats_label)


        stats_layout.addStretch()

        # 上一处按钮
        self.prev_btn = QPushButton("⬆ 上一处")
        self.prev_btn.clicked.connect(lambda: self._navigate(-1))
        self.prev_btn.setFixedWidth(90)
        stats_layout.addWidget(self.prev_btn)

        # ★ 可编辑的当前编号输入框
        class JumpLineEdit(QLineEdit):
            def keyPressEvent(self, event):
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self.returnPressed.emit()
                    return
                super().keyPressEvent(event)

        self.page_input = JumpLineEdit()

        # ★ 安装事件过滤器，拦截 Ctrl+Left/Right
        self.page_input.installEventFilter(self)

        self.page_input.setFixedWidth(45)
        self.page_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_input.setValidator(QIntValidator(1, max(len(self.changes), 1)))

        self.page_input.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.page_input.setStyleSheet("""
            QLineEdit {
                padding: 3px 4px;
                border: 1px solid #bbb;
                border-radius: 3px;
                font-size: 13px;
                font-weight: bold;
                background: #fff;
            }
            QLineEdit:focus {
                border-color: #3498db;
            }
        """)
        self.page_input.setToolTip(
            "输入数字后按 Enter 跳转到指定变更\n"
            "范围：1 ~ {}".format(len(self.changes))
        )
        self.page_input.returnPressed.connect(self._on_jump_to_page)
        stats_layout.addWidget(self.page_input)

        # ★ 总数标签
        self.total_label = QLabel(f"/ {len(self.changes)}")
        self.total_label.setStyleSheet("font-size: 13px; color: #555; font-weight: bold;")
        stats_layout.addWidget(self.total_label)

        # 下一处按钮
        self.next_btn = QPushButton("⬇ 下一处")
        self.next_btn.clicked.connect(lambda: self._navigate(1))
        self.next_btn.setFixedWidth(90)
        stats_layout.addWidget(self.next_btn)

        return stats_layout

    def eventFilter(self, obj, event):
        """事件过滤器：处理 JumpLineEdit 中的 Ctrl+Left/Right"""

        if obj is self.page_input and event.type() == QEvent.Type.KeyPress:
            if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
                if event.key() == Qt.Key.Key_Left:
                    self._navigate(-1)
                    return True  # 事件已处理
                elif event.key() == Qt.Key.Key_Right:
                    self._navigate(1)
                    return True
        return super().eventFilter(obj, event)

    def _create_diff_view(self) -> QSplitter:
        """创建左右对比视图"""
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setMinimumHeight(120)
        splitter.setMaximumHeight(300)

        # 左侧：原始公式
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_header = QLabel("📄 原始公式")
        left_header.setStyleSheet(
            "background: #f8d7da; padding: 6px; font-weight: bold; border-radius: 4px;")
        left_layout.addWidget(left_header)

        self.original_view = QTextEdit()
        self.original_view.setReadOnly(True)
        self.original_view.setFont(QFont("Consolas", 11))
        left_layout.addWidget(self.original_view)
        splitter.addWidget(left_widget)

        # 右侧：修复后
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_header = QLabel("✅ 修复后")
        right_header.setStyleSheet(
            "background: #d4edda; padding: 6px; font-weight: bold; border-radius: 4px;")
        right_layout.addWidget(right_header)

        self.fixed_view = QTextEdit()
        self.fixed_view.setReadOnly(True)
        self.fixed_view.setFont(QFont("Consolas", 11))
        right_layout.addWidget(self.fixed_view)
        splitter.addWidget(right_widget)

        splitter.setSizes([500, 500])

        # 滚动同步
        self.original_view.verticalScrollBar().valueChanged.connect(
            self.fixed_view.verticalScrollBar().setValue)
        self.fixed_view.verticalScrollBar().valueChanged.connect(
            self.original_view.verticalScrollBar().setValue)

        return splitter

    def _create_render_panel(self) -> QGroupBox:
        """创建渲染预览面板"""
        render_group = QGroupBox("👁️ 渲染预览（公式效果）")
        render_layout = QVBoxLayout(render_group)

        # 标题行：按钮 + 缩放控件
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        
        # 缩放标签
        title_row.addWidget(QLabel("缩放:"))
        
        # 缩放滑块
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(50, 200)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setFixedWidth(120)
        self.zoom_slider.setToolTip("调整公式显示大小（50%-200%）")
        self.zoom_slider.valueChanged.connect(self._on_zoom_changed)
        title_row.addWidget(self.zoom_slider)
        
        # 缩放百分比标签
        self.zoom_label = QLabel("100%")
        self.zoom_label.setFixedWidth(40)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_row.addWidget(self.zoom_label)
        
        # 自动换行
        self.wrap_cb = QCheckBox("自动换行")
        self.wrap_cb.setChecked(False)
        self.wrap_cb.setToolTip("长公式自动换行显示")
        self.wrap_cb.toggled.connect(self._on_zoom_changed)
        title_row.addWidget(self.wrap_cb)
        
        # 重置按钮
        reset_btn = QPushButton("重置")
        reset_btn.setFixedWidth(50)
        reset_btn.clicked.connect(self._reset_zoom)
        title_row.addWidget(reset_btn)
        
        title_row.addStretch()
        
        # 浏览器按钮
        self.render_btn = QPushButton("🌐 在浏览器中查看")
        self.render_btn.setStyleSheet("""
            QPushButton {
                padding: 2px 8px;
                background-color: #3498db;
                color: white;
                border: none;
                border-radius: 3px;
                font-weight: bold;
                font-size: 9pt;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
        """)
        self.render_btn.clicked.connect(self._open_in_browser)
        title_row.addWidget(self.render_btn)
        
        render_layout.addLayout(title_row)

        # 内嵌预览
        if HAS_WEBENGINE:
            self.render_view = QWebEngineView()
            self.render_view.setMinimumHeight(80)
            self.render_view.setMaximumHeight(180)
        else:
            self.render_view = QTextBrowser()
            self.render_view.setFont(QFont("Microsoft YaHei", 11))
            self.render_view.setMinimumHeight(50)
            self.render_view.setMaximumHeight(80)
            self.render_view.setOpenExternalLinks(True)
        render_layout.addWidget(self.render_view)

        return render_group

    def _on_zoom_changed(self):
        """缩放或换行设置变化时刷新渲染"""
        if hasattr(self, '_current_formula') and self._current_formula:
            self._render_markdown(self._current_formula)

    def _reset_zoom(self):
        """重置缩放为默认值"""
        self.zoom_slider.setValue(100)
        self.wrap_cb.setChecked(False)

    def _create_quick_panel(self) -> QGroupBox:
        """创建快速调整面板"""
        self.quick_group = QGroupBox('⚙️ 快速调整（勾选后自动生效）')
        self.quick_group.setCheckable(True)
        self.quick_group.setChecked(True)   # ★ 默认展开
        quick_layout = QVBoxLayout(self.quick_group)

        # ★ 用 QScrollArea 包裹复选框容器，限制最大高度
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(350)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.quick_check_widget = QWidget()
        self.quick_check_layout = QVBoxLayout(self.quick_check_widget)
        self.quick_check_layout.setSpacing(2)
        self.quick_check_layout.addStretch()  # 底部弹簧，项少时不拉伸
        
        scroll.setWidget(self.quick_check_widget)
        quick_layout.addWidget(scroll)

        # 按钮行
        quick_btn_layout = QHBoxLayout()
        
        # 配置更新按钮
        self.apply_config_btn = QPushButton("📋 配置更新")
        self.apply_config_btn.setToolTip(
            "将快速调整面板中功能的勾选状态\n"
            "更新到高级修复选项中。\n"
            "面板中所有功能都会被同步。"
        )
        self.apply_config_btn.setStyleSheet("""
            QPushButton {
                padding: 5px 14px;
                background-color: #27ae60;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #219a52; }
        """)
        self.apply_config_btn.clicked.connect(self._on_apply_config)
        quick_btn_layout.addWidget(self.apply_config_btn)
        
        # ★ 新增：清除未勾选项按钮
        self.clear_unchecked_btn = QPushButton("🧹 清除未勾选项")
        self.clear_unchecked_btn.setToolTip(
            "从面板中移除所有当前未勾选的功能项\n"
            "不影响配置，仅清理面板显示\n\n"
            "被清除的项如果再次触发会自动重新出现"
        )
        self.clear_unchecked_btn.setStyleSheet("""
            QPushButton {
                padding: 5px 10px;
                background-color: #95a5a6;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #7f8c8d; }
            QPushButton:disabled { background-color: #ccc; color: #eee; }
        """)
        self.clear_unchecked_btn.clicked.connect(self._on_clear_unchecked)
        self.clear_unchecked_btn.setEnabled(False)  # 初始禁用
        quick_btn_layout.addWidget(self.clear_unchecked_btn)
        
        quick_btn_layout.addStretch()
        quick_layout.addLayout(quick_btn_layout)

        return self.quick_group


    def _create_log_panel(self) -> QGroupBox:
        """创建修改详情面板"""
        log_group = QGroupBox("📝 修改详情（点击查看功能说明）")
        log_layout = QVBoxLayout(log_group)

        # 日志列表
        self.log_list = QListWidget()
        self.log_list.setFont(QFont("Microsoft YaHei", 10))
        self.log_list.setMaximumHeight(150)
        self.log_list.itemClicked.connect(self._on_log_item_clicked)
        log_layout.addWidget(self.log_list)

        # 功能说明展开区域
        self.log_detail = QTextBrowser()
        self.log_detail.setFont(QFont("Microsoft YaHei", 10))
        self.log_detail.setMaximumHeight(200)
        self.log_detail.setVisible(False)
        self.log_detail.setStyleSheet("""
            QTextBrowser {
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 4px;
                padding: 8px;
            }
        """)
        log_layout.addWidget(self.log_detail)

        return log_group
    
    def _bring_to_front(self):
        """强制将主窗口置于最前"""
        from PyQt6.QtWidgets import QApplication, QMainWindow
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, QMainWindow):
                if widget.isMinimized():
                    widget.showNormal()
                widget.setWindowState(
                    widget.windowState() & ~Qt.WindowState.WindowMinimized
                )
                widget.show()
                widget.activateWindow()
                widget.raise_()
                break

    def closeEvent(self, event):
        self._all_time_features.clear()  # ★ 重置历史累积
        self._bring_to_front()
        super().closeEvent(event)

    def reject(self):
        self._all_time_features.clear()  # ★ 重置历史累积
        self._bring_to_front()
        super().reject()

    # ==================== 导航与显示 ====================

    def _show_change(self, index: int):
        """显示第 index 个变更"""
        if index < 0 or index >= len(self.changes):
            return

        self._refresh_stats_bar()

        self.current_index = index
        self._expanded_row = -1
        change = self.changes[index]
        rl = RiskLevel(change.risk_level)

        self.setWindowTitle(
            f"🔍 修复预览 [{index + 1}/{len(self.changes)}] - "
            f"{rl.icon} {rl.description}"
            + (f" - {Path(self.file_name).name}" if self.file_name else ""))

        original_html, fixed_html = self._compute_diff(change.original, change.fixed)
        self.original_view.setHtml(original_html)
        self.fixed_view.setHtml(fixed_html)

        self.log_list.clear()
        self.log_detail.setVisible(False)
        for log in change.changes:
            self.log_list.addItem(QListWidgetItem(log))

        self.prev_btn.setEnabled(index > 0)
        self.next_btn.setEnabled(index < len(self.changes) - 1)

        # ★ 同步输入框
        self.page_input.blockSignals(True)
        self.page_input.setText(str(index + 1))
        self.page_input.blockSignals(False)

        self._render_markdown(change.fixed)

    def _navigate(self, direction: int):
        """导航到上一处/下一处"""
        new_index = self.current_index + direction
        if 0 <= new_index < len(self.changes):
            self._show_change(new_index)
            self.page_input.setText(str(new_index + 1))  # ★ 在这里同步

    def _on_jump_to_page(self):
        """跳转到用户输入的变更编号"""
        try:
            target = int(self.page_input.text())
            if 1 <= target <= len(self.changes):
                self.page_input.setText(str(target))       # ★ 先设为用户期望值
                self._show_change(target - 1)              # ★ 再跳转
            else:
                self.page_input.setText(str(self.current_index + 1))
        except ValueError:
            self.page_input.setText(str(self.current_index + 1))
        
        # ★ 清除焦点，阻止 Enter 继续传递给其他按钮
        self.page_input.clearFocus()

    def _refresh_stats_bar(self):
        """刷新统计栏的按钮状态"""
        self.prev_btn.setEnabled(self.current_index > 0)
        self.next_btn.setEnabled(self.current_index < len(self.changes) - 1)

    # ==================== 差异计算 ====================

    @staticmethod
    def _compute_diff(original: str, fixed: str) -> Tuple[str, str]:
        """使用 difflib 计算差异并生成 HTML 高亮"""
        matcher = difflib.SequenceMatcher(None, original, fixed)
        original_parts, fixed_parts = [], []

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            orig_segment = SideBySidePreviewDialog._escape_html(original[i1:i2])
            fixed_segment = SideBySidePreviewDialog._escape_html(fixed[j1:j2])

            if tag == 'equal':
                original_parts.append(orig_segment)
                fixed_parts.append(fixed_segment)
            elif tag == 'replace':
                original_parts.append(
                    f'<span style="background-color:#ffcccc;text-decoration:line-through;'
                    f'border-radius:2px;padding:0 1px;">{orig_segment}</span>')
                fixed_parts.append(
                    f'<span style="background-color:#ccffcc;border-radius:2px;padding:0 1px;">'
                    f'{fixed_segment}</span>')
            elif tag == 'delete':
                original_parts.append(
                    f'<span style="background-color:#ffcccc;text-decoration:line-through;'
                    f'border-radius:2px;padding:0 1px;">{orig_segment}</span>')
            elif tag == 'insert':
                fixed_parts.append(
                    f'<span style="background-color:#ccffcc;border-radius:2px;padding:0 1px;">'
                    f'{fixed_segment}</span>')

        pre_style = (
            'white-space:pre-wrap;font-family:Consolas,monospace;'
            'font-size:12px;line-height:1.6;margin:4px;'
        )
        return (
            f'<pre style="{pre_style}">{"".join(original_parts)}</pre>',
            f'<pre style="{pre_style}">{"".join(fixed_parts)}</pre>'
        )

    @staticmethod
    def _escape_html(text: str) -> str:
        """转义 HTML 特殊字符"""
        return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    # ==================== 渲染预览 ====================

    def _render_markdown(self, formula: str):
        """内嵌预览：优先本地 MathJax（内置/缓存），其次 CDN"""
        self._current_formula = formula

        if HAS_WEBENGINE:
            escaped = self._escape_html(formula)
            
            # 获取缩放和换行设置
            zoom = self.zoom_slider.value() / 100.0
            wrap_css = "overflow-x: auto; white-space: nowrap;" if not self.wrap_cb.isChecked() else "overflow-x: visible; white-space: normal; word-break: break-all;"
            
            # 更新缩放标签
            self.zoom_label.setText(f"{int(zoom * 100)}%")
            
            # 构建带缩放的 HTML
            html = f"""<!DOCTYPE html>
    <html>
    <head>
    <meta charset="UTF-8">
    <script>
    window.MathJax = {{
        tex: {{ inlineMath: [['$', '$'], ['\\\\\\\\(', '\\\\\\\\)']] }},
        svg: {{ fontCache: 'global', scale: {zoom} }}
    }};
    </script>
    <script src="{{mathjax_url}}"></script>
    <style>
        body {{
            font-family: 'Microsoft YaHei', serif;
            font-size: {int(16 * zoom)}px;
            line-height: 1.8;
            padding: 12px 16px;
            color: #2c3e50;
            background: #fafafa;
            margin: 0;
        }}
        .formula {{
            background: #fff;
            border-left: 3px solid #3498db;
            padding: 14px 18px;
            margin: 8px 0;
            border-radius: 0 6px 6px 0;
            {wrap_css}
        }}
    </style>
    </head>
    <body>
    <div class="formula">$${escaped}$$</div>
    </body>
    </html>"""
            
            mathjax_url = _get_mathjax_url()
            html = html.replace("{mathjax_url}", mathjax_url)
            
            # baseUrl 设为 None，mathjax_url 直接指向 file:// 路径
            bundled_file = None
            bundled_dir = _get_mathjax_bundled_dir()
            if bundled_dir:
                main_file = bundled_dir / "tex-svg.js"
                extensions_dir = bundled_dir / "input" / "tex" / "extensions"
                if main_file.exists() and extensions_dir.exists():
                    bundled_file = main_file

            if bundled_file:
                # 直接用 file:// 加载 tex-svg.js 的绝对路径
                self.render_view.setHtml(html, QUrl.fromLocalFile(str(bundled_file)))
            elif mathjax_url.startswith("file://"):
                cache_dir = _get_mathjax_cache_dir()
                main_file = cache_dir / "tex-svg.js"
                self.render_view.setHtml(html, QUrl.fromLocalFile(str(main_file)))
            else:
                self.render_view.setHtml(html)
            
            _download_mathjax_async()
        else:
            escaped = self._escape_html(formula)
            html = _TEXT_PREVIEW_HTML_TEMPLATE.format(formula=escaped)
            self.render_view.setHtml(html)

        self.render_btn.setEnabled(True)

    def _open_in_browser(self):
        """在系统浏览器中打开修复后公式的渲染效果"""
        formula = getattr(self, '_current_formula', '')
        if not formula:
            return

        # 构建完整 Markdown 文本
        md_text = formula if formula.startswith('$$') else f"$$\n{formula}\n$$"

        mathjax_url = _get_mathjax_url()
        html_content = _BROWSER_HTML_TEMPLATE.format(
            mathjax_url=mathjax_url,
            content=md_text
        )

        try:
            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.html', delete=False, encoding='utf-8'
            ) as tmp:
                tmp.write(html_content)
                tmp_path = tmp.name
            webbrowser.open(f'file://{tmp_path}')
        except Exception as e:
            logger.warning(f"打开浏览器失败: {e}")

    # ==================== 日志详情展开 ====================

    def _on_log_item_clicked(self, item: QListWidgetItem):
        """点击日志项：切换展开/收起功能说明"""
        row = self.log_list.row(item)

        # 如果点击的是已展开的行 → 收起
        if row == self._expanded_row:
            self.log_detail.setVisible(False)
            self._expanded_row = -1
            return

        # 展开新行
        self._expanded_row = row
        log_text = item.text()

        help_db = FeatureHelpDatabase.get_all_features()
        feature_key = self._match_log_to_feature(log_text)

        if feature_key and feature_key in help_db:
            info = help_db[feature_key]
            html = _LOG_DETAIL_HTML_TEMPLATE.format(
                trigger=self._escape_html(info.get('trigger', '')),
                action=self._escape_html(info.get('action', '')),
                example_before=self._escape_html(info.get('example_before', '')),
                example_after=self._escape_html(info.get('example_after', '')),
                recommendation=info.get('recommendation', ''),
            )
            self.log_detail.setHtml(html)
            self.log_detail.setVisible(True)
        else:
            self.log_detail.setVisible(False)
            self._expanded_row = -1

    @staticmethod
    def _match_log_to_feature(log_text: str) -> Optional[str]:
        """根据日志文本匹配功能键名（使用预编译映射）"""
        for keyword, feature_key in _LOG_TO_FEATURE_MAP.items():
            if keyword in log_text:
                return feature_key
        return None

    def set_standalone_config_mode(self, enabled: bool = True):
        self._is_standalone_config = enabled
        if enabled:
            self.apply_config_btn.setText("📋 配置到独立设置")
            self.apply_config_btn.setToolTip(
                "将当前调整的勾选状态保存为该文件的独立修复配置。\n"
                "仅对该文件生效，不会影响其他文件的全局配置。\n\n"
                "点击后将弹出确认对话框，确定后打开独立修复设置进行二次确认。"
            )
            self.quick_group.setTitle('⚙️ 独立配置（勾选后自动生效，仅对该文件）')

    # ==================== 快速调整 ====================

    def set_config(self, config: Dict[str, Any]):
        """设置可调整的配置（由调用方在显示预览前调用）"""
        import copy
        self._original_config = config
        self._temp_config = copy.deepcopy(config)
        self._build_quick_settings()

    def _build_quick_settings(self):
        """累积式重建快速调整面板
        
        行为：
        - 保留所有历史触发过的功能（_all_time_features），不会因当前未触发而消失
        - 当前触发的功能使用其实际勾选状态，正常颜色显示
        - 历史但当前未触发的功能显示为灰色，提示用户可勾选尝试
        - 关闭窗口时 _all_time_features 会被清空，下次打开重新累积
        """
        if not self._temp_config:
            return

        # ★ 1. 收集当前触发功能
        current_features = self._get_current_features()

        # ★ 2. 更新历史累积
        self._all_time_features |= current_features

        # ★ 3. 合并需要显示的功能
        display_features = self._all_time_features.copy()

        # ★ 4. 清空并重建（保留弹簧）
        for cb in self._checkboxes.values():
            self.quick_check_layout.removeWidget(cb)
            cb.deleteLater()
        self._checkboxes.clear()

        # ★ 5. 如果没有需要显示的功能
        if not display_features:
            if self._is_standalone_config:
                self.quick_group.setTitle('⚙️ 独立配置（勾选后自动生效，当前无触发功能）')
            else:
                self.quick_group.setTitle('⚙️ 快速调整（勾选后自动生效，当前无触发功能）')
            self.clear_unchecked_btn.setEnabled(False)
            return

        # ★ 6. 创建复选框
        help_db = FeatureHelpDatabase.get_all_features()
        for key in sorted(display_features):
            info = help_db.get(key, {})
            if not info:
                continue

            is_checked = self._get_feature_value(key)
            is_current = key in current_features  # 当前是否触发

            cb = QCheckBox(f"{info.get('icon', '')} {info.get('name', key)}")
            cb.setChecked(is_checked)
            
            # ★ 当前未触发的功能给予视觉提示
            if not is_current:
                cb.setToolTip(
                    f"{info.get('trigger', '')}\n\n"
                    f"⚠️ 当前配置下未触发新的变更\n"
                    f"勾选后点击「重新预检」可能重新触发"
                )
                cb.setStyleSheet("color: #999;")
            else:
                cb.setToolTip(info.get('trigger', ''))
                cb.setStyleSheet("")
            
            cb.toggled.connect(self._on_quick_check_changed)
            self._checkboxes[key] = cb
            
            insert_pos = self.quick_check_layout.count() - 1
            self.quick_check_layout.insertWidget(insert_pos, cb)

        # ★ 7. 更新标题
        total = len(self._checkboxes)
        enabled = sum(1 for cb in self._checkboxes.values() if cb.isChecked())
        current_count = len(current_features)

        if self._is_standalone_config:
            self.quick_group.setTitle(
                f'⚙️ 独立配置（{enabled}/{total}项已勾选，{current_count}项触发，仅对该文件）'
            )
        else:
            self.quick_group.setTitle(
                f'⚙️ 快速调整（{enabled}/{total}项已勾选，{current_count}项触发，自动生效）'
            )

        # ★ 8. 更新"清除未勾选项"按钮状态
        unchecked_count = total - enabled
        self.clear_unchecked_btn.setEnabled(unchecked_count > 0)

    def _get_current_features(self) -> set:
        """获取当前变更涉及的功能集合"""
        features = set()
        for change in self.changes:
            for log in change.changes:
                key = self._match_log_to_feature(log)
                if key:
                    features.add(key)
        return features
    
    def _on_clear_unchecked(self):
        """清除所有未勾选的功能项（从面板和历史记录中移除）
        
        只移除未勾选的项，已勾选的项保留。
        被清除的项如果再次触发变更，会自动重新出现在面板中。
        """
        to_remove = [
            key for key, cb in self._checkboxes.items()
            if not cb.isChecked()
        ]
        
        if not to_remove:
            return
        
        for key in to_remove:
            cb = self._checkboxes.pop(key)
            self.quick_check_layout.removeWidget(cb)
            cb.deleteLater()
            self._all_time_features.discard(key)
        
        # 更新标题和按钮状态
        total = len(self._checkboxes)
        enabled = sum(1 for cb in self._checkboxes.values() if cb.isChecked())
        current_features = self._get_current_features()
        current_count = sum(1 for key in self._checkboxes if key in current_features)
        
        # 更新标题部分
        if self._is_standalone_config:
            self.quick_group.setTitle(
                f'⚙️ 独立配置（{enabled}/{total}项已勾选，{current_count}项触发，仅对该文件）'
            )
        else:
            self.quick_group.setTitle(
                f'⚙️ 快速调整（{enabled}/{total}项已勾选，{current_count}项触发，自动生效）'
            )
        self.clear_unchecked_btn.setEnabled(total - enabled > 0)

    def _get_feature_value(self, key: str) -> bool:
        """获取某项功能当前的值（使用预编译映射）"""
        if key not in _FEATURE_TO_CONFIG_MAP:
            return False

        level, field = _FEATURE_TO_CONFIG_MAP[key]
        if level == 'top':
            return self._temp_config.get(field, False)
        else:
            fc = self._temp_config.get('formula_config', {})
            return fc.get(field, False)

    def _on_quick_check_changed(self):
        """快速调整复选框变化时更新临时配置并自动重新预检"""
        fc = self._temp_config.get('formula_config', {})

        for key, cb in self._checkboxes.items():
            if key not in _FEATURE_TO_CONFIG_MAP:
                continue

            level, field = _FEATURE_TO_CONFIG_MAP[key]
            if level == 'top':
                self._temp_config[field] = cb.isChecked()
            else:
                fc[field] = cb.isChecked()
        
        # ★ 自动重新预检，立即刷新显示
        self._on_repreview()

    def _on_repreview(self):
        """重新预检当前文件"""
        if not self._temp_config or not self.file_name:
            return

        file_path = Path(self.file_name)
        if not file_path.exists():
            return

        # 读取文件内容
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                text = f.read()
        except Exception as e:
            logger.warning(f"读取文件失败: {e}")
            return

        # 重新预检
        previewer = FormulaPreviewer(self._temp_config)
        try:
            new_changes = previewer.preview(text, file_path)
        except Exception as e:
            logger.warning(f"预检失败: {e}")
            return

        # 刷新数据
        self.changes = new_changes
        self.current_index = -1

        # 更新标题
        title = "🔍 修复预览"
        if self.file_name:
            title += f" - {Path(self.file_name).name}"
        title += f" ({len(self.changes)}处变更)"
        self.setWindowTitle(title)

        # 更新统计栏
        self._refresh_stats_bar()
        
        # 更新跳转输入框的验证范围
        max_val = max(len(self.changes), 1)
        self.page_input.setValidator(QIntValidator(1, max_val))
        self.total_label.setText(f"/ {len(self.changes)}")

        # 刷新统计栏文字
        risk_counts = {'low': 0, 'medium': 0, 'high': 0}
        type_counts = {'inline': 0, 'display': 0}
        for c in self.changes:
            risk_counts[c.risk_level] = risk_counts.get(c.risk_level, 0) + 1
            type_counts[c.formula_type] = type_counts.get(c.formula_type, 0) + 1
        
        summary_parts = [f"共 {len(self.changes)} 处变更"]
        for level in ['high', 'medium', 'low']:
            if risk_counts[level] > 0:
                rl = RiskLevel(level)
                summary_parts.append(f"{rl.icon}{risk_counts[level]}")
        summary_parts.append(f"| 行内:{type_counts['inline']} 块级:{type_counts['display']}")
        
        self.stats_label.setText("  ".join(summary_parts))

        # ★ 累积式重建快速调整面板
        self._build_quick_settings()

        # 显示第一个变更（或清空视图）
        if self.changes:
            self._show_change(0)
        else:
            self.original_view.clear()
            self.fixed_view.clear()
            self.log_list.clear()
            self.log_detail.setVisible(False)
            self.render_view.setHtml(
                '<p style="color:#27ae60;">✅ 当前配置下未检测到需要修改的内容</p>'
            )
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
            self.page_input.setText("1")

    def _on_apply_config(self):
        """配置更新按钮回调"""
        if not self._temp_config or not self._original_config:
            return
    
        # ★ 独立配置模式：弹窗确认后打开独立修复设置，不关闭预览
        if self._is_standalone_config:
            # 同步面板勾选状态到 _temp_config
            fc = self._temp_config.get('formula_config', {})
            for key, cb in self._checkboxes.items():
                if key not in _FEATURE_TO_CONFIG_MAP:
                    continue
                level, field = _FEATURE_TO_CONFIG_MAP[key]
                if level == 'top':
                    self._temp_config[field] = cb.isChecked()
                else:
                    fc[field] = cb.isChecked()
            
            # ★ 弹窗确认
            reply = QMessageBox.question(
                self, "配置到独立设置",
                "将当前快速调整面板中的勾选状态\n"
                "保存为该文件的独立修复配置。\n\n"
                "点击「确定」将打开该文件的独立修复设置，\n"
                "您可以在其中进一步调整配置。\n"
                "关闭对话框后将自动重新预检。\n\n"
                "是否继续？",
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Ok
            )
            
            if reply != QMessageBox.StandardButton.Ok:
                return  # 用户取消，留在修复预览
            
            # ★ 打开独立修复设置对话框（模态，阻塞修复预览）
            from modules.workflow.monitor_row_config import RowRepairConfigDialog
            
            # 需要获取全局配置和文件路径
            file_path = Path(self.file_name) if self.file_name else None
            if file_path is None:
                return
            
            # 从 _original_config 中提取全局配置（首次打开时保存的原始配置）
            global_config = copy.deepcopy(self._original_config)
            
            # 打开独立修复设置
            dialog = RowRepairConfigDialog(
                file_path, global_config, self,
                existing_row_config=self._temp_config  # 传入当前调整的配置
            )
            if dialog.exec() == QDialog.DialogCode.Accepted:
                # 获取用户确认的稀疏配置
                sparse_config = dialog.get_config()
                if sparse_config:
                    # 合并到完整配置
                    merged = copy.deepcopy(global_config)
                    for key, value in sparse_config.items():
                        if key == 'formula_config':
                            merged.setdefault('formula_config', {}).update(value)
                        else:
                            merged[key] = value
                    self._temp_config = merged
                else:
                    # 用户重置为全局配置
                    self._temp_config = copy.deepcopy(global_config)
                
                self._original_config = copy.deepcopy(self._temp_config)
                self._config_to_apply = copy.deepcopy(self._temp_config)
                self._config_apply_pending = True
                
                # ★ 自动重新预检
                self._on_repreview()
            # 用户取消独立修复设置 → 留在修复预览，什么都不改
            
            return  # 不关闭修复预览

        # ★ 收集当前面板中存在的所有功能（可能为空）
        current_panel_keys = set(self._checkboxes.keys())
        
        # ★ 如果面板中有功能，同步它们的勾选状态到 _temp_config
        if current_panel_keys:
            fc = self._temp_config.get('formula_config', {})
            
            for key in current_panel_keys:
                if key not in _FEATURE_TO_CONFIG_MAP:
                    continue
                
                level, field = _FEATURE_TO_CONFIG_MAP[key]
                cb = self._checkboxes[key]
                
                if level == 'top':
                    self._temp_config[field] = cb.isChecked()
                else:
                    fc[field] = cb.isChecked()
        
        # ★ 构建更新说明
        help_db = FeatureHelpDatabase.get_all_features()
        
        if current_panel_keys:
            display_keys = current_panel_keys
        else:
            display_keys = [
                key for key in _FEATURE_TO_CONFIG_MAP
                if self._get_feature_value(key)
            ]
        
        if display_keys:
            def _display_width(text: str) -> int:
                width = 0
                for ch in text:
                    if '\u4e00' <= ch <= '\u9fff' or '\u3000' <= ch <= '\u303f' or '\uff00' <= ch <= '\uffef':
                        width += 2
                    else:
                        width += 1
                return width

            items_data = []
            for key in sorted(display_keys):
                info = help_db.get(key, {})
                name = info.get('name', key)
                is_checked = self._get_feature_value(key)
                status = "✅ 开启" if is_checked else "❌ 关闭"
                items_data.append((name, status))
            
            max_width = max(_display_width(name) for name, _ in items_data)
            
            updated_items = []
            for name, status in items_data:
                padding = (max_width - _display_width(name)) // 2
                updated_items.append(f"  {name}{'　' * padding}  {status}")
            
            detail_text = "\n".join(updated_items)
            
            msg = QMessageBox(self)
            msg.setWindowTitle("配置更新")
            msg.setIcon(QMessageBox.Icon.Question)
            msg.setMinimumWidth(600)
            msg.setText(
                f"以下 {len(display_keys)} 项功能的勾选状态将同步到高级修复选项：\n\n"
                f"{detail_text}\n\n"
                f"将打开高级修复选项进行确认。\n是否继续？"
            )
            msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            msg.setDefaultButton(QMessageBox.StandardButton.Yes)
            reply = msg.exec()

            if reply != QMessageBox.StandardButton.Yes:
                return
        
        # ★ 打开高级修复选项弹窗
        dialog = AdvancedSettingsDialog(copy.deepcopy(self._temp_config))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._temp_config = dialog.get_config()
            self._config_to_apply = copy.deepcopy(self._temp_config)
            self._config_apply_pending = True
        
        # ★ 自动重新预检
        self._on_repreview()

# ==================== 功能说明弹窗 ====================

class FeatureHelpDialog(QDialog):
    """功能说明弹窗 - 显示单个功能的详细说明"""
    
    _RISK_LABELS = {'low': '🟢 低风险', 'medium': '🟡 中风险', 'high': '🔴 高风险'}
    
    _OVERVIEW_HTML_TEMPLATE = """
<style>
    body {{ font-family: 'Microsoft YaHei', sans-serif; font-size: 13px; line-height: 1.6; }}
    h3 {{ color: #2c3e50; margin-top: 12px; margin-bottom: 6px; }}
    .highlight {{ background: #fff3cd; padding: 8px; border-radius: 4px; border-left: 3px solid #ffc107; }}
</style>
<h3>🎯 触发条件</h3><div class="highlight">{trigger}</div>
<h3>⚡ 执行操作</h3><p>{action}</p>
<h3>💡 为什么要修改</h3><p>{why}</p>
<h3>⚠️ 潜在问题</h3><p>{problem}</p>
<h3>📋 使用建议</h3><p><b>{recommendation}</b></p>"""
    
    _EXAMPLE_HTML_TEMPLATE = """
<style>
    body {{ font-family: 'Consolas', 'Microsoft YaHei', monospace; font-size: 13px; }}
    .before {{ background: #fff3cd; padding: 10px; border-radius: 4px; margin: 8px 0; }}
    .after {{ background: #d4edda; padding: 10px; border-radius: 4px; margin: 8px 0; }}
    .label {{ font-weight: bold; margin-top: 10px; }}
</style>
<p class="label">📄 修改前:</p>
<div class="before"><code>{example_before}</code></div>
<p class="label">✅ 修改后:</p>
<div class="after"><code>{example_after}</code></div>"""

    def __init__(self, feature_key: str, parent=None):
        """初始化功能说明弹窗
        
        Args:
            feature_key: 功能键名
            parent: 父级窗口
        """
        super().__init__(parent)
        self.feature_key = feature_key
        self.info = FeatureHelpDatabase.get_all_features().get(feature_key, {})
        self._setup_ui()

    def _setup_ui(self):
        """构建 UI 布局"""
        self.setWindowTitle(f"📖 功能说明 - {self.info.get('name', '未知功能')}")
        self.setMinimumWidth(520)
        self.setMaximumWidth(600)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        if not self.info:
            layout.addWidget(QLabel("⚠️ 该功能的详细说明暂未收录"))
            close_btn = QPushButton("关闭")
            close_btn.clicked.connect(self.accept)
            layout.addWidget(close_btn)
            return

        # 标题行
        layout.addLayout(self._create_title_row())

        # 分类
        category_label = QLabel(f"📂 分类: {self.info.get('category', '')}")
        category_label.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(category_label)

        # 详细标签页
        detail_tabs = QTabWidget()

        # 标签页1：概述
        overview_tab = QWidget()
        overview_layout = QVBoxLayout(overview_tab)
        overview_text = QTextBrowser()
        overview_text.setHtml(self._OVERVIEW_HTML_TEMPLATE.format(
            trigger=self._escape_html(self.info.get('trigger', '')),
            action=self._escape_html(self.info.get('action', '')),
            why=self._escape_html(self.info.get('why', '')),
            problem=self._escape_html(self.info.get('problem', '')),
            recommendation=self.info.get('recommendation', ''),
        ))
        overview_layout.addWidget(overview_text)
        detail_tabs.addTab(overview_tab, "📋 概述")

        # 标签页2：示例
        example_tab = QWidget()
        example_layout = QVBoxLayout(example_tab)
        example_text = QTextBrowser()
        example_text.setHtml(self._EXAMPLE_HTML_TEMPLATE.format(
            example_before=self._escape_html(self.info.get('example_before', '')),
            example_after=self._escape_html(self.info.get('example_after', '')),
        ))
        example_layout.addWidget(example_text)
        detail_tabs.addTab(example_tab, "💻 示例")

        layout.addWidget(detail_tabs)

        # 关闭按钮
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        close_btn.setStyleSheet("padding: 6px 20px;")
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)

    def _create_title_row(self) -> QHBoxLayout:
        """创建标题行"""
        title_row = QHBoxLayout()
        
        icon_label = QLabel(self.info.get('icon', '📌'))
        icon_label.setFont(QFont("Segoe UI Emoji", 20))
        title_row.addWidget(icon_label)

        name_label = QLabel(self.info.get('name', ''))
        name_label.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        title_row.addWidget(name_label)
        title_row.addStretch()

        risk = self.info.get('risk', 'low')
        risk_label = QLabel(self._RISK_LABELS.get(risk, ''))
        risk_label.setStyleSheet(
            f"color: {RiskLevel(risk).color}; font-weight: bold; font-size: 12px;")
        title_row.addWidget(risk_label)
        
        return title_row

    @staticmethod
    def _escape_html(text: str) -> str:
        """转义 HTML 特殊字符"""
        return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


# ==================== 高级设置对话框 ====================

class AdvancedSettingsDialog(QDialog):
    """高级修复选项弹窗 - 预设方案 + 独立功能开关"""

    def __init__(self, config: Dict[str, Any], parent=None):
        """初始化高级设置对话框
        
        Args:
            config: 当前配置字典
            parent: 父级窗口
        """
        super().__init__(parent)
        self.setWindowTitle("🔧 高级修复选项")
        self.setMinimumWidth(580)
        self.config = config.copy()
        self.checkboxes: Dict[str, QCheckBox] = {}
        self.selected_profile_name: str = ""
        self._setup_ui()
        self._load_config()

    def _setup_ui(self):
        """构建 UI 布局"""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # 预设方案按钮组
        layout.addLayout(self._create_profile_buttons())

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

        # 提示
        hint = QLabel(
            "💡 修改复选框将自动取消方案选择，切换为「自定义」。"
            "点击每个选项旁的 ⓘ 查看详细说明"
        )
        hint.setStyleSheet(
            "color: #666; padding: 4px; background: #f0f0f0; border-radius: 4px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(10)

        # 分类功能组
        sections = [
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
        for title, keys in sections:
            scroll_layout.addWidget(self._create_section(title, keys))

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll, 1)

        # 图片标题颜色
        layout.addLayout(self._create_color_selector())

        # 按钮行
        layout.addLayout(self._create_button_row())

    def _create_profile_buttons(self) -> QHBoxLayout:
        """创建预设方案按钮组"""
        profile_layout = QHBoxLayout()
        profile_layout.addWidget(QLabel("📋 预设方案:"))

        self.profile_group = QButtonGroup(self)
        self.profile_group.setExclusive(True)

        self.profile_buttons = []
        profiles = RepairProfile.get_builtin_profiles()
        for i, p in enumerate(profiles):
            btn = QPushButton(p.name)
            btn.setCheckable(True)
            btn.setToolTip(p.description)
            btn.setAutoDefault(False)     # ★ 新增：不让 Enter 触发此按钮            
            btn.setStyleSheet("""
                QPushButton {
                    padding: 6px 12px;
                    border: 2px solid #ddd;
                    border-radius: 4px;
                    background: #fafafa;
                    font-size: 12px;
                }
                QPushButton:hover {
                    border-color: #3498db;
                    background: #e8f4fd;
                }
                QPushButton:checked {
                    border-color: #3498db;
                    background: #d4e9fc;
                    font-weight: bold;
                }
            """)
            btn.clicked.connect(
                lambda checked, idx=i: self._on_profile_button_clicked(idx)
            )
            self.profile_group.addButton(btn, i)
            self.profile_buttons.append(btn)
            profile_layout.addWidget(btn)

        profile_layout.addStretch()
        return profile_layout

    def _create_color_selector(self) -> QHBoxLayout:
        """创建图片标题颜色选择器"""
        color_layout = QHBoxLayout()
        color_layout.addWidget(QLabel("🖼️ 图片标题颜色:"))
        self.color_combo = QComboBox()
        self.color_combo.addItems(list(ImageCaptionOptimizer.COLOR_SCHEMES.keys()))
        self.color_combo.setCurrentText('purple')
        color_layout.addWidget(self.color_combo)
        color_layout.addStretch()
        return color_layout

    def _create_button_row(self) -> QHBoxLayout:
        """创建按钮行"""
        btn_layout = QHBoxLayout()
        
        reset_btn = QPushButton("🔄 恢复默认")
        reset_btn.clicked.connect(self._reset_default)
        btn_layout.addWidget(reset_btn)

        select_all_btn = QPushButton("☑️ 全部选择")
        select_all_btn.setToolTip("勾选所有修复功能")
        select_all_btn.clicked.connect(self._select_all)
        btn_layout.addWidget(select_all_btn)

        deselect_all_btn = QPushButton("☐ 全部取消")
        deselect_all_btn.setToolTip("取消所有修复功能")
        deselect_all_btn.clicked.connect(self._deselect_all)
        btn_layout.addWidget(deselect_all_btn)

        btn_layout.addStretch()

        ok_btn = QPushButton("✅ 确定")
        ok_btn.clicked.connect(self._on_ok)
        ok_btn.setStyleSheet(
            "background-color: #27ae60; color: white; font-weight: bold; "
            "padding: 8px 20px; border-radius: 4px;")
        
        ok_btn.setDefault(True)          # ★ 新增：设为默认按钮
        ok_btn.setAutoDefault(True)      # ★ 新增：自动获取回车焦点

        btn_layout.addWidget(ok_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        return btn_layout

    def _create_section(self, title: str, feature_keys: List[str]) -> QGroupBox:
        """创建功能分组"""
        group = QGroupBox(title)
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(6)

        help_db = FeatureHelpDatabase.get_all_features()
        risk_icons = {'low': '🟢', 'medium': '🟡', 'high': '🔴'}
        risk_tooltips = {'low': '低风险', 'medium': '中风险', 'high': '高风险'}

        for key in feature_keys:
            info = help_db.get(key, {})
            if not info:
                continue

            row = QHBoxLayout()
            row.setSpacing(4)

            cb = QCheckBox(f"{info.get('icon', '')} {info.get('name', key)}")
            cb.setToolTip(info.get('trigger', ''))
            cb.toggled.connect(self._on_checkbox_changed)
            row.addWidget(cb, 1)
            self.checkboxes[key] = cb

            # 风险等级图标
            risk = info.get('risk', 'low')
            risk_label = QLabel(risk_icons.get(risk, ''))
            risk_label.setToolTip(risk_tooltips.get(risk, ''))
            risk_label.setFixedWidth(24)
            row.addWidget(risk_label)

            # 帮助按钮
            help_btn = QPushButton("ⓘ")
            help_btn.setFixedSize(20, 20)
            help_btn.setToolTip(f"查看「{info.get('name', '')}」的详细说明")
            help_btn.setStyleSheet(
                "QPushButton { border: none; background: transparent; color: #888; "
                "font-size: 14px; padding: 0px; } "
                "QPushButton:hover { color: #3498db; }")
            help_btn.clicked.connect(
                lambda checked, k=key: self._show_feature_help(k)
            )
            row.addWidget(help_btn)

            group_layout.addLayout(row)

        return group

    # ==================== 预设方案 ====================

    def _on_profile_button_clicked(self, index: int):
        """预设方案按钮点击"""
        profiles = RepairProfile.get_builtin_profiles()
        profile = profiles[index]
        self.selected_profile_name = profile.name
        self._apply_profile(profile)

    def _apply_profile(self, profile: RepairProfile):
        """应用预设方案到复选框"""
        config = profile.config

        # ★ 复用复选框设置
        self._apply_checkboxes_from_config(config)

        # 同步非复选框配置字段（_apply_checkboxes_from_config 不处理这些）
        if 'formula_config' not in self.config:
            self.config['formula_config'] = {}
        fc = self.config['formula_config']
        fc['escape_mode'] = config.get('escape_mode', 'standard')
        fc['bm_strict_mode'] = config.get('bm_strict_mode', True)
        self.config['image_caption_color'] = config.get('image_caption_color', 'purple')

    def _apply_checkboxes_from_config(self, config: Dict[str, Any]):
        """从配置字典设置复选框状态（纯 UI 操作，不修改 formula_config）
        
        与 _apply_profile 的区别：
            _apply_profile:     预设方案 → 复选框 + formula_config 同步
            _apply_checkboxes:  任意配置 → 仅复选框（用于 else 分支的回显）
        
        Args:
            config: 配置字典（通常是 self.config 或 profile.config）
        """
        fc = config.get('formula_config', {})

        for cb in self.checkboxes.values():
            cb.blockSignals(True)

        checkbox_map = {
            'clean_newlines': config.get('clean_extra_newlines', True),
            'add_space_after_inline': config.get('add_space_after_inline', True),
            'subsup_fix': fc.get('subsup_fix', config.get('subsup_fix', True)),
            'func_normalize': fc.get('func_normalize', config.get('func_normalize', True)),
            'matrix_newline_remove': fc.get('matrix_newline_remove', config.get('matrix_newline_remove', True)),
            'bracket_check': fc.get('bracket_check', config.get('bracket_check', True)),
            'markdown_escape_inline': config.get('markdown_escape_inline', fc.get('markdown_escape_inline', True)),
            'matrix_add_multiplication': config.get('matrix_add_multiplication', fc.get('matrix_add_multiplication', True)),
            'dl_commands_to_text': config.get('dl_commands_to_text', fc.get('dl_commands_to_text', True)),
            'remove_size_commands': config.get('remove_size_commands', fc.get('remove_size_commands', True)),
            'bm_to_vec': fc.get('bm_to_vec', config.get('bm_to_vec', False)),
            'inline_to_display': config.get('inline_to_display', False),
            'image_caption': config.get('image_caption_enabled', True),
            'respect_macros': fc.get('respect_macros', config.get('respect_macros', True)),
            'fix_encoding': config.get('fix_encoding', True),
            'escape_isolated_dollars': config.get('escape_isolated_dollars', True),
        }

        for var_name, cb in self.checkboxes.items():
            if cb:
                cb.setChecked(checkbox_map.get(var_name, False))

        self.color_combo.setCurrentText(config.get('image_caption_color', 'purple'))

        for cb in self.checkboxes.values():
            cb.blockSignals(False)

    def _on_checkbox_changed(self):
        """复选框变化时取消方案选择"""
        self.profile_group.setExclusive(False)
        for btn in self.profile_buttons:
            btn.setChecked(False)
        self.profile_group.setExclusive(True)
        self.selected_profile_name = ""

    def _select_all(self):
        """勾选所有修复功能"""
        self._clear_profile_selection()
        for cb in self.checkboxes.values():
            cb.setChecked(True)

    def _deselect_all(self):
        """取消所有修复功能"""
        self._clear_profile_selection()
        for cb in self.checkboxes.values():
            cb.setChecked(False)

    def _clear_profile_selection(self):
        """清除预设方案选择状态"""
        self.profile_group.setExclusive(False)
        for btn in self.profile_buttons:
            btn.setChecked(False)
        self.profile_group.setExclusive(True)
        self.selected_profile_name = ""

    # ==================== 功能帮助 ====================

    def _show_feature_help(self, feature_key: str):
        """显示功能帮助弹窗"""
        dialog = FeatureHelpDialog(feature_key, self)
        dialog.exec()

    # ==================== 配置加载与保存 ====================

    def _load_config(self):
        """从配置加载到 UI"""
        fc = self.config.get('formula_config', {})

        for cb in self.checkboxes.values():
            cb.blockSignals(True)

        # 尝试匹配预设方案
        matched = self._match_profile()
        if matched:
            btn_index = matched - 1
            if btn_index < len(self.profile_buttons):
                profiles = RepairProfile.get_builtin_profiles()
                self.profile_buttons[btn_index].setChecked(True)
                self.selected_profile_name = self.profile_buttons[btn_index].text()
                self._apply_profile(profiles[btn_index])
        else:
            self._clear_profile_selection()
            self._apply_checkboxes_from_config(self.config)  # ★ 替换了原来的 20 行

        self.color_combo.setCurrentText(self.config.get('image_caption_color', 'purple'))

        for cb in self.checkboxes.values():
            cb.blockSignals(False)

    def _match_profile(self) -> int:
        """尝试匹配预设方案，返回方案编号(1-based)，0表示未匹配"""
        profiles = RepairProfile.get_builtin_profiles()
        matched = RepairProfile.match_config(self.config)
        
        if matched is None:
            return 0
        
        try:
            return profiles.index(matched) + 1
        except ValueError:
            return 0

    def _reset_default(self):
        """恢复默认配置"""
        from .processor import DEFAULT_REPAIR_CONFIG
        import copy
        self.config = copy.deepcopy(DEFAULT_REPAIR_CONFIG)
        self._clear_profile_selection()
        self._load_config()

    def _on_ok(self):
        """确定按钮：将 UI 状态写入 config"""
        if 'formula_config' not in self.config:
            self.config['formula_config'] = {}

        fc = self.config['formula_config']

        # 顶层配置
        self.config['clean_extra_newlines'] = self.checkboxes['clean_newlines'].isChecked()
        self.config['add_space_after_inline'] = self.checkboxes['add_space_after_inline'].isChecked()
        self.config['inline_to_display'] = self.checkboxes['inline_to_display'].isChecked()
        self.config['image_caption_enabled'] = self.checkboxes['image_caption'].isChecked()
        self.config['escape_isolated_dollars'] = self.checkboxes['escape_isolated_dollars'].isChecked()

        # 公式级配置
        fc['subsup_fix'] = self.checkboxes['subsup_fix'].isChecked()
        fc['func_normalize'] = self.checkboxes['func_normalize'].isChecked()
        fc['matrix_newline_remove'] = self.checkboxes['matrix_newline_remove'].isChecked()
        fc['bracket_check'] = self.checkboxes['bracket_check'].isChecked()
        fc['markdown_escape_inline'] = self.checkboxes['markdown_escape_inline'].isChecked()
        fc['matrix_add_multiplication'] = self.checkboxes['matrix_add_multiplication'].isChecked()
        fc['dl_commands_to_text'] = self.checkboxes['dl_commands_to_text'].isChecked()
        fc['remove_size_commands'] = self.checkboxes['remove_size_commands'].isChecked()
        fc['bm_to_vec'] = self.checkboxes['bm_to_vec'].isChecked()
        fc['respect_macros'] = self.checkboxes['respect_macros'].isChecked()
        self.config['fix_encoding'] = self.checkboxes['fix_encoding'].isChecked()

        # 保留非复选框字段
        # fc['escape_mode'] = self.config.get('formula_config', {}).get('escape_mode', 'standard')
        # fc['bm_strict_mode'] = self.config.get('formula_config', {}).get('bm_strict_mode', True)

        self.config['image_caption_color'] = self.color_combo.currentText()
        self.accept()

    def get_config(self) -> Dict[str, Any]:
        """获取最终的配置字典"""
        return self.config


# ==================== 元信息 ====================
__author__ = "YQJ"
__version__ = "1.2.0"
__date__ = "2026.05.09"