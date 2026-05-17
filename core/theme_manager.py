#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
统一主题管理器
整合三个程序的主题配置，提供统一的主题切换和 EPUB CSS 生成功能
"""

import re
import logging
from typing import Dict, Any, Optional

from PyQt6.QtCore import QObject, pyqtSignal


# 模块级日志记录器
logger = logging.getLogger(__name__)


class Theme:
    """主题配置类
    
    封装单套主题的配色方案和 Qt 样式表生成逻辑。
    配色键名语义:
        primary/secondary: 主/辅色调
        success/warning/error: 语义色（成功/警告/错误）
        bg_main/bg_widget/bg_input: 背景色（主窗口/组件/输入框）
        text_primary/text_secondary: 前景色（主/次文本）
        border/hover: 边框/悬停色
    """
    
    # 预定义主题配色方案
    THEMES: Dict[str, Dict[str, str]] = {
        "light": {
            "name": "浅色主题",
            "primary": "#3498db",
            "primary_dark": "#2980b9",
            "secondary": "#e74c3c",
            "secondary_dark": "#c0392b",
            "success": "#27ae60",
            "warning": "#f39c12",
            "error": "#e74c3c",
            "bg_main": "#f5f5f5",
            "bg_widget": "#ffffff",
            "bg_input": "#ffffff",
            "text_primary": "#2c3e50",
            "text_secondary": "#7f8c8d",
            "border": "#dcdcdc",
            "hover": "#e8e8e8"
        },
        "dark": {
            "name": "深色主题",
            "primary": "#3498db",
            "primary_dark": "#2980b9",
            "secondary": "#e74c3c",
            "secondary_dark": "#c0392b",
            "success": "#27ae60",
            "warning": "#f39c12",
            "error": "#e74c3c",
            "bg_main": "#2b2b2b",
            "bg_widget": "#1e1e1e",
            "bg_input": "#1e1e1e",
            "text_primary": "#e0e0e0",
            "text_secondary": "#aaaaaa",
            "border": "#555555",
            "hover": "#3a3a3a"
        },
        "blue": {
            "name": "蓝色主题",
            "primary": "#2196F3",
            "primary_dark": "#1976D2",
            "secondary": "#f44336",
            "secondary_dark": "#d32f2f",
            "success": "#4CAF50",
            "warning": "#FF9800",
            "error": "#f44336",
            "bg_main": "#E3F2FD",
            "bg_widget": "#ffffff",
            "bg_input": "#ffffff",
            "text_primary": "#1565C0",
            "text_secondary": "#64B5F6",
            "border": "#90CAF9",
            "hover": "#BBDEFB"
        },
        "green": {
            "name": "绿色主题",
            "primary": "#4CAF50",
            "primary_dark": "#388E3C",
            "secondary": "#f44336",
            "secondary_dark": "#d32f2f",
            "success": "#4CAF50",
            "warning": "#FF9800",
            "error": "#f44336",
            "bg_main": "#E8F5E9",
            "bg_widget": "#ffffff",
            "bg_input": "#ffffff",
            "text_primary": "#2E7D32",
            "text_secondary": "#81C784",
            "border": "#A5D6A7",
            "hover": "#C8E6C9"
        },
        "orange": {
            "name": "橙色主题",
            "primary": "#e67e22",
            "primary_dark": "#d35400",
            "secondary": "#e74c3c",
            "secondary_dark": "#c0392b",
            "success": "#27ae60",
            "warning": "#f39c12",
            "error": "#e74c3c",
            "bg_main": "#FFF3E0",
            "bg_widget": "#ffffff",
            "bg_input": "#ffffff",
            "text_primary": "#E65100",
            "text_secondary": "#FFB74D",
            "border": "#FFCC80",
            "hover": "#FFE0B2"
        },
        "purple": {
            "name": "紫色主题",
            "primary": "#9b59b6",
            "primary_dark": "#7d3c98",
            "secondary": "#e74c3c",
            "secondary_dark": "#c0392b",
            "success": "#27ae60",
            "warning": "#f39c12",
            "error": "#e74c3c",
            "bg_main": "#F3E5F5",
            "bg_widget": "#ffffff",
            "bg_input": "#ffffff",
            "text_primary": "#6A1B9A",
            "text_secondary": "#CE93D8",
            "border": "#E1BEE7",
            "hover": "#F3E5F5"
        }
    }
    
    # CSS 颜色注入键名白名单（防止通过主题键注入任意 CSS）
    _CSS_INJECTION_KEYS = {
        'primary', 'primary_dark', 'primary_light',
        'secondary', 'secondary_dark',
        'success', 'warning', 'error',
        'bg_main', 'bg_widget', 'bg_input',
        'text_primary', 'text_secondary',
        'border', 'hover'
    }
    
    def __init__(self, theme_name: str = "light"):
        """初始化主题
        
        Args:
            theme_name: 主题名称，必须在 THEMES 中存在
            
        Raises:
            ValueError: 主题名称不存在时抛出
        """
        if theme_name not in self.THEMES:
            logger.warning(f"未知主题 '{theme_name}'，回退到 'light'")
            theme_name = "light"
        
        self.theme_name = theme_name
        self.colors = self.THEMES[theme_name]
    
    def get_stylesheet(self) -> str:
        """生成当前主题的 Qt 样式表
        
        Returns:
            str: Qt 样式表字符串
        """
        c = self.colors
        
        return f"""
            QMainWindow {{
                background-color: {c['bg_main']};
            }}
            
            QWidget {{
                color: {c['text_primary']};
            }}
            
            QGroupBox {{
                font-weight: bold;
                border: 1px solid {c['border']};
                border-radius: 5px;
                margin-top: 12px;
                padding-top: 10px;
                background-color: transparent;
            }}
            
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
                background-color: {c['bg_main']};
            }}
            
            QPushButton {{
                background-color: {c['primary']};
                color: white;
                border: none;
                padding: 6px 15px;
                border-radius: 4px;
                font-weight: bold;
            }}
            
            QPushButton:hover {{
                background-color: {c['primary_dark']};
            }}
            
            QPushButton:disabled {{
                background-color: #bdc3c7;
            }}
            
            QPushButton#stopBtn {{
                background-color: {c['secondary']};
            }}
            
            QPushButton#stopBtn:hover {{
                background-color: {c['secondary_dark']};
            }}
            
            /* 导航栏处理按钮 - 开始 */
            QPushButton#navProcessBtn {{
                background-color: {c['success']};
                color: white;
                border: none;
                padding: 10px 15px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 12pt;
            }}
            
            QPushButton#navProcessBtn:hover {{
                background-color: #219a52;
            }}
            
            QPushButton#navProcessBtn:disabled {{
                background-color: #bdc3c7;
            }}
            
            /* 导航栏处理按钮 - 停止 */
            QPushButton#navStopBtn {{
                background-color: {c['secondary']};
                color: white;
                border: none;
                padding: 10px 15px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 12pt;
            }}
            
            QPushButton#navStopBtn:hover {{
                background-color: {c['secondary_dark']};
            }}
            
            QPushButton#navStopBtn:disabled {{
                background-color: #bdc3c7;
            }}
            
            /* 模块提示标签 */
            QLabel#moduleHint {{
                padding: 8px 5px;
                background-color: {c['hover']};
                border-radius: 4px;
                font-size: 9pt;
                color: {c['text_primary']};
            }}

            QPushButton#processBtn {{
                background-color: {c['success']};
            }}
            
            QPushButton#processBtn:hover {{
                background-color: #219a52;
            }}
            
            /* 导航按钮样式 */
            QPushButton.nav-button {{
                background-color: transparent;
                color: {c['text_primary']};
                text-align: left;
                padding: 12px 15px;
                border-radius: 8px;
                font-weight: normal;
                margin: 2px 5px;
            }}
            
            QPushButton.nav-button:hover {{
                background-color: {c['hover']};
            }}
            
            QPushButton.nav-button.active {{
                background-color: {c['primary']};
                color: white;
            }}
            
            QListWidget {{
                background-color: {c['bg_widget']};
                border: 1px solid {c['border']};
                border-radius: 4px;
                padding: 5px;
                alternate-background-color: {c['hover']};
            }}
            
            QListWidget::item:selected {{
                background-color: {c['primary']};
                color: white;
            }}
            
            QListWidget::item:hover {{
                background-color: {c['hover']};
            }}
            
            QTextEdit {{
                background-color: {c['bg_widget']};
                border: 1px solid {c['border']};
                border-radius: 4px;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 10pt;
            }}
            
            QLabel#infoLabel {{
                color: {c['text_secondary']};
                font-size: 9pt;
            }}
            
            QSpinBox, QComboBox, QLineEdit {{
                background-color: {c['bg_input']};
                border: 1px solid {c['border']};
                border-radius: 4px;
                padding: 5px;
            }}
            
            QSpinBox:hover, QComboBox:hover, QLineEdit:hover {{
                border: 1px solid {c['primary']};
            }}
            
            QSpinBox:focus, QComboBox:focus, QLineEdit:focus {{
                border: 2px solid {c['primary']};
            }}
            
            QProgressBar {{
                border: 1px solid {c['border']};
                border-radius: 4px;
                text-align: center;
                background-color: {c['bg_widget']};
            }}
            
            QProgressBar::chunk {{
                background-color: {c['primary']};
                border-radius: 3px;
            }}
            
            QRadioButton, QCheckBox {{
                spacing: 8px;
            }}
            
            QMenuBar {{
                background-color: {c['bg_widget']};
                border-bottom: 1px solid {c['border']};
            }}
            
            QMenuBar::item:selected {{
                background-color: {c['primary']};
                color: white;
            }}
            
            QMenu {{
                background-color: {c['bg_widget']};
                border: 1px solid {c['border']};
            }}
            
            QMenu::item:selected {{
                background-color: {c['primary']};
                color: white;
            }}
            
            QMenu::separator {{
                height: 1px;
                background-color: {c['border']};
                margin: 4px 0;
            }}
            
            QStatusBar {{
                background-color: {c['bg_widget']};
                border-top: 1px solid {c['border']};
            }}
            
            QScrollBar:vertical {{
                background-color: {c['bg_widget']};
                width: 12px;
                border-radius: 6px;
            }}
            
            QScrollBar::handle:vertical {{
                background-color: {c['border']};
                border-radius: 6px;
                min-height: 20px;
            }}
            
            QScrollBar::handle:vertical:hover {{
                background-color: {c['primary']};
            }}
            
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            
            QScrollBar:horizontal {{
                background-color: {c['bg_widget']};
                height: 12px;
                border-radius: 6px;
            }}
            
            QScrollBar::handle:horizontal {{
                background-color: {c['border']};
                border-radius: 6px;
                min-width: 20px;
            }}
            
            QScrollBar::handle:horizontal:hover {{
                background-color: {c['primary']};
            }}
            
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px;
            }}
            
            QToolTip {{
                background-color: {c['bg_widget']};
                border: 1px solid {c['border']};
                border-radius: 4px;
                padding: 4px;
            }}
            
            QSplitter::handle {{
                background-color: {c['border']};
            }}
            
            QSplitter::handle:hover {{
                background-color: {c['primary']};
            }}
        """


class ThemeManager(QObject):
    """主题管理器
    
    负责:
        1. 管理 6 套 UI 主题的切换
        2. 提供 10 种颜色预设（供 MD 转 EPUB 等模块使用）
        3. 生成 EPUB 的 CSS 样式（朴素/简洁两种风格）
        
    使用信号 theme_changed 通知主题切换。
    """
    
    theme_changed = pyqtSignal(str)  # 主题名称变化信号
    
    # 颜色预设（用于 MD 转 EPUB 等模块）
    COLOR_PRESETS: Dict[str, Dict[str, str]] = {
        'blue':   {'name': '蓝色', 'color': '#3498db', 'dark': '#2980b9'},
        'green':  {'name': '绿色', 'color': '#27ae60', 'dark': '#1e8449'},
        'purple': {'name': '紫色', 'color': '#9b59b6', 'dark': '#7d3c98'},
        'orange': {'name': '橙色', 'color': '#e67e22', 'dark': '#d35400'},
        'red':    {'name': '红色', 'color': '#e74c3c', 'dark': '#c0392b'},
        'teal':   {'name': '青色', 'color': '#1abc9c', 'dark': '#16a085'},
        'pink':   {'name': '粉色', 'color': '#e84393', 'dark': '#d63384'},
        'gray':   {'name': '灰色', 'color': '#7f8c8d', 'dark': '#6c7a7a'},
        'dark':   {'name': '深色', 'color': '#34495e', 'dark': '#2c3e50'},
        'brown':  {'name': '棕色', 'color': '#8B4513', 'dark': '#6B3410'},
    }
    
    # hex 颜色正则（6 位，大小写不敏感）
    _HEX_COLOR_PATTERN = re.compile(r'^#[0-9a-fA-F]{6}$')
    
    def __init__(self, initial_theme: str = "light"):
        """初始化主题管理器
        
        Args:
            initial_theme: 初始主题名称
        """
        super().__init__()
        self._current_theme = initial_theme
        self._theme = Theme(initial_theme)
    
    # ==================== 主题属性 ====================
    
    @property
    def current_theme(self) -> str:
        """当前主题名称"""
        return self._current_theme
    
    @property
    def theme(self) -> Theme:
        """当前 Theme 实例"""
        return self._theme
    
    @property
    def colors(self) -> Dict[str, str]:
        """当前主题配色字典（便捷访问）"""
        return self._theme.colors
    
    # ==================== 查询方法 ====================
    
    def get_available_themes(self) -> Dict[str, str]:
        """获取所有可用主题
        
        Returns:
            Dict[str, str]: {主题ID: 主题显示名称}
        """
        return {k: v["name"] for k, v in Theme.THEMES.items()}
    
    def get_color_presets(self) -> Dict[str, Dict[str, str]]:
        """获取颜色预设（10 种）
        
        Returns:
            Dict[str, Dict[str, str]]: {预设ID: {name, color, dark}}
        """
        return self.COLOR_PRESETS
    
    # ==================== 主题切换 ====================
    
    def set_theme(self, theme_name: str):
        """切换主题
        
        Args:
            theme_name: 目标主题名称
            
        如果 theme_name 不存在，记录警告并使用 light 回退。
        """
        if theme_name not in Theme.THEMES:
            logger.warning(f"尝试切换到未知主题 '{theme_name}'，已回退到 'light'")
            theme_name = "light"
        
        if theme_name != self._current_theme:
            self._current_theme = theme_name
            self._theme = Theme(theme_name)
            self.theme_changed.emit(theme_name)
            logger.debug(f"主题已切换至: {theme_name}")
    
    def get_stylesheet(self) -> str:
        """获取当前主题的 Qt 样式表
        
        Returns:
            str: Qt 样式表字符串
        """
        return self._theme.get_stylesheet()
    
    # ==================== 颜色工具方法 ====================
    
    @staticmethod
    def _darken_color(hex_color: str, factor: float = 0.2) -> str:
        """使颜色变暗
        
        Args:
            hex_color: 输入颜色（支持 #RGB 或 #RRGGBB 格式）
            factor: 变暗系数（0~1，越大越暗）
            
        Returns:
            str: 变暗后的 #RRGGBB 颜色值
        """
        hex_color = hex_color.lstrip('#')
        if len(hex_color) == 3:
            hex_color = ''.join(c * 2 for c in hex_color)
        
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        
        r = max(0, int(r * (1 - factor)))
        g = max(0, int(g * (1 - factor)))
        b = max(0, int(b * (1 - factor)))
        
        return f"#{r:02x}{g:02x}{b:02x}"
    
    @staticmethod
    def _lighten_color(hex_color: str, factor: float = 0.3) -> str:
        """使颜色变亮
        
        Args:
            hex_color: 输入颜色（支持 #RGB 或 #RRGGBB 格式）
            factor: 变亮系数（0~1，越大越亮）
            
        Returns:
            str: 变亮后的 #RRGGBB 颜色值
        """
        hex_color = hex_color.lstrip('#')
        if len(hex_color) == 3:
            hex_color = ''.join(c * 2 for c in hex_color)
        
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        
        r = min(255, int(r + (255 - r) * factor))
        g = min(255, int(g + (255 - g) * factor))
        b = min(255, int(b + (255 - b) * factor))
        
        return f"#{r:02x}{g:02x}{b:02x}"
    
    @classmethod
    def _validate_hex_color(cls, color: str) -> bool:
        """校验颜色值是否为合法的 6 位 hex 格式
        
        防止在 CSS 生成时注入非颜色内容。
        
        Args:
            color: 待校验的颜色字符串
            
        Returns:
            bool: 是否为合法的 #RRGGBB 格式
        """
        if not isinstance(color, str):
            return False
        return bool(cls._HEX_COLOR_PATTERN.match(color))
    
    @classmethod
    def _safe_color(cls, color: str, default: str = "#3498db") -> str:
        """安全获取颜色值，非法输入返回默认色
        
        Args:
            color: 待校验的颜色值
            default: 校验失败时的默认颜色
            
        Returns:
            str: 合法的 #RRGGBB 颜色值
        """
        if cls._validate_hex_color(color):
            return color
        logger.warning(f"非法颜色值 '{color}' 已被替换为默认色 '{default}'")
        return default
    
    # ==================== EPUB CSS 生成 ====================
    
    def get_css_for_epub(self, style_type: str = "clean", primary_color: Optional[str] = None) -> str:
        """获取 EPUB CSS 样式，优先外部文件，回退到内置
        
        Args:
            style_type: "clean" 或 "plain"
            primary_color: 自定义主色调
        """
        from core.css_manager import CssManager
        
        # 构建颜色上下文
        if primary_color is not None:
            safe_primary = self._safe_color(primary_color)
            c = {
                'primary': safe_primary,
                'primary_dark': self._darken_color(safe_primary, 0.2),
                'primary_light': self._lighten_color(safe_primary, 0.3),
                'border': '#cccccc',
            }
        else:
            c = self.colors.copy()
            c['primary_light'] = self._lighten_color(c['primary'], 0.3)
        
        # 优先使用外部 CSS 模板（资源文件）
        manager = CssManager()
        return manager.load(style_type, c)
    
    def get_css_with_color(self, style_type: str = "clean", primary_color: Optional[str] = None) -> str:
        """获取带自定义主色的 CSS 样式（get_css_for_epub 的别名）
        
        保留此方法以兼容旧调用方式。
        
        Args:
            style_type: 排版风格
            primary_color: 自定义主色调
            
        Returns:
            str: EPUB CSS 样式字符串
        """
        return self.get_css_for_epub(style_type, primary_color)
    
    # ==================== CSS 模板（私有方法） ====================
    
    @staticmethod
    def _get_css_clean(c: Dict[str, str]) -> str:
        """生成简洁风格 CSS（白色容器+彩色边框，无阴影圆角）
        
        Args:
            c: 颜色字典
            
        Returns:
            str: 简洁风格 CSS
        """
        return f"""/* EPUB 排版核心样式 - 简洁风格 */
body {{
    font-size: 100%;
    line-height: 1.5;
    color: #2c3e50;
    background: #fafafa;
    margin: 0;
    padding: 2.5px;
    font-family: "Iowan Old Style", "Sitka Text", Palatino, "Times New Roman", "PingFang SC", "Microsoft YaHei", serif;
}}

.container {{
    max-width: 900px;
    margin: 0 auto;
    background: #fff;
    padding: 0rem;
}}

.article-title {{
    font-size: 2.2em;
    font-weight: bold;
    text-align: center;
    margin: 0.5em 0 0.3em;
    color: #1a1a1a;
    line-height: 1.3;
    border-bottom: 3px solid {c['primary']};
    padding-bottom: 0.3em;
}}

.article-subtitle {{
    font-size: 1.1em;
    text-align: center;
    color: #666;
    margin: 0 0 1.5em 0;
    font-style: normal;
    border-bottom: 1px solid #e0e0e0;
    padding-bottom: 0.5em;
}}

h1, h2, h3, h4, h5, h6 {{
    font-weight: 600;
    margin: 1.8em 0 0.8em;
    color: #1a1a1a;
    line-height: 1.3;
}}

h1 {{
    font-size: 1.7em;
    border-bottom: 3px solid {c['primary']};
    padding-bottom: 0.4em;
    color: #2c3e50;
}}

h2 {{
    font-size: 1.4em;
    border-left: 3px solid {c['primary']};
    padding-left: 0.5em;
    color: #34495e;
}}

h3 {{
    font-size: 1.2em;
    color: #3b6e8f;
}}

p {{
    margin: 1em 0;
    text-align: justify;
    text-indent: 2em;
}}

p.no-indent {{
    text-indent: 0;
}}

li p {{
    text-indent: 0;
    margin: 0.5em 0;
}}

ul, ol {{
    margin: 1em 0;
    padding-left: 1.4em;
}}

li {{
    margin-bottom: 0.4em;
}}

code {{
    font-family: "Fira Code", Consolas, monospace;
    background: #f4f4f4;
    padding: 0.2em 0.4em;
    border-radius: 3px;
    font-size: 0.9em;
    color: #e74c3c;
}}

pre {{
    background: #2d2d2d;
    border-left: 4px solid {c['primary']};
    padding: 1.1em 1em;
    margin: 1.4em 0;
    overflow-x: auto;
    border-radius: 0 4px 4px 0;
    font-size: 0.9em;
    color: #f8f8f2;
}}

pre code {{
    background: none;
    padding: 0;
    color: inherit;
}}

blockquote {{
    border-left: 3px solid {c['primary']};
    margin: 1.4em 0;
    padding-left: 1.2em;
    color: #555;
    font-style: italic;
}}

blockquote p {{
    text-indent: 2em;
}}

table {{
    width: 100%;
    border-collapse: collapse;
    margin: 1.5em 0;
}}

th, td {{
    border: 1px solid #ddd;
    padding: 8px 12px;
    text-align: left;
}}

th {{
    background: {c['primary']};
    color: #fff;
}}

img {{
    display: block;
    margin: 1.6em auto;
    max-width: 100%;
    height: auto;
}}

.mermaid-container {{
    margin: 1.5em 0;
    text-align: center;
}}

.mermaid-img {{
    max-width: 100%;
    height: auto;
    border: 1px solid #e0e0e0;
}}

math {{
    font-family: "Latin Modern Math", "STIX Two Math", "Cambria Math", serif;
    font-size: 1.05em;
}}

@media print {{
    body {{
        background: white;
        padding: 0;
    }}
    .container {{
        padding: 0;
    }}
}}

@media (max-width: 768px) {{
    .container {{
        padding: 1rem;
    }}
    h1 {{
        font-size: 1.5em;
    }}
    h2 {{
        font-size: 1.3em;
    }}
    pre {{
        font-size: 0.8em;
    }}
    p {{
        text-indent: 1.5em;
    }}
    .article-title {{
        font-size: 1.8em;
    }}
}}"""
    
    @staticmethod
    def _get_css_plain(c: Dict[str, str]) -> str:
        """生成朴素风格 CSS（白底黑字+极简排版，适合墨水屏）
        
        Args:
            c: 颜色字典
            
        Returns:
            str: 朴素风格 CSS
        """
        return f"""/* EPUB 排版核心样式 - 紧凑白底黑字版 */
* {{
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}}

body {{
    font-size: 100%;
    line-height: 1.5;
    color: #000000;
    background: #ffffff;
    margin: 0;
    padding: 2.5px;
    font-family: "Iowan Old Style", "Sitka Text", Palatino, "Times New Roman", "PingFang SC", "Microsoft YaHei", serif;
}}

.container {{
    max-width: 100%;
    margin: 0 auto;
    background: #ffffff;
    padding: 0rem;
}}

.article-title {{
    font-size: 2.2em;
    font-weight: bold;
    text-align: center;
    margin: 0.5em 0 0.3em;
    color: #000000;
    line-height: 1.3;
    border-bottom: 1px solid #cccccc;
    padding-bottom: 0.3em;
}}

.article-subtitle {{
    font-size: 1.1em;
    text-align: center;
    color: #555555;
    margin: 0 0 1.5em 0;
    font-style: normal;
    border-bottom: 1px solid #eeeeee;
    padding-bottom: 0.5em;
}}

h1, h2, h3, h4, h5, h6 {{
    font-weight: 600;
    margin: 1.8em 0 0.8em;
    color: #000000;
    line-height: 1.3;
}}

h1 {{
    font-size: 1.7em;
    border-bottom: 1px solid #cccccc;
    padding-bottom: 0.4em;
}}

h2 {{
    font-size: 1.4em;
    border-left: 3px solid {c['primary']};
    padding-left: 0.5em;
}}

h3 {{
    font-size: 1.2em;
    color: #000000;
}}

p {{
    margin: 0.8em 0;
    text-align: justify;
    text-indent: 2em;
}}

p.no-indent {{
    text-indent: 0;
}}

li p {{
    text-indent: 0;
    margin: 0.3em 0;
}}

ul, ol {{
    margin: 0.8em 0;
    padding-left: 1.4em;
}}

li {{
    margin-bottom: 0.3em;
}}

code {{
    font-family: "Fira Code", Consolas, monospace;
    background: #f5f5f5;
    padding: 0.2em 0.4em;
    border-radius: 3px;
    font-size: 0.9em;
    color: #cc0000;
    border: 1px solid #e0e0e0;
}}

pre {{
    background: #f8f8f8;
    border-left: 3px solid {c['primary']};
    padding: 0.8em 1em;
    margin: 1em 0;
    overflow-x: auto;
    border-radius: 0 4px 4px 0;
    font-size: 0.9em;
    color: #000000;
    border: 1px solid #e0e0e0;
}}

pre code {{
    background: none;
    padding: 0;
    color: inherit;
    border: none;
}}

blockquote {{
    border-left: 3px solid #cccccc;
    margin: 1em 0;
    padding-left: 1em;
    color: #333333;
    font-style: italic;
}}

blockquote p {{
    text-indent: 2em;
}}

table {{
    width: 100%;
    border-collapse: collapse;
    margin: 1.2em 0;
}}

th, td {{
    border: 1px solid #cccccc;
    padding: 6px 10px;
    text-align: left;
}}

th {{
    background: {c['primary']};
    color: #ffffff;
    font-weight: bold;
}}

img {{
    display: block;
    margin: 1.2em auto;
    max-width: 100%;
    height: auto;
}}

.mermaid-container {{
    margin: 1.2em 0;
    text-align: center;
}}

.mermaid-img {{
    max-width: 100%;
    height: auto;
    border: 1px solid #e0e0e0;
}}

math {{
    font-family: "Latin Modern Math", "STIX Two Math", "Cambria Math", serif;
    font-size: 1.05em;
}}

@media print {{
    body {{
        background: white;
        padding: 0;
    }}
    .container {{
        padding: 0;
    }}
}}

@media (max-width: 768px) {{
    .container {{
        padding: 0.3rem;
    }}
    h1 {{
        font-size: 1.5em;
    }}
    h2 {{
        font-size: 1.3em;
    }}
    pre {{
        font-size: 0.8em;
    }}
    p {{
        text-indent: 1.5em;
    }}
    .article-title {{
        font-size: 1.8em;
    }}
}}"""


# ==================== 元信息 ====================
__author__ = "YQJ"
__version__ = "1.1.0"
__date__ = "2026.05.01"