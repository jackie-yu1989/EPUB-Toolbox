#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
启动动画管理器
管理启动画面的创建、显示和关闭，支持图片/纯色两种模式及自动降级

功能：
    - 可配置开关：通过 enabled 参数控制是否显示启动动画
    - 图片降级：图标加载失败时自动回退到纯色渐变动画
    - 进度文字：支持在启动过程中动态显示加载信息
"""

import logging
from typing import Optional

from PyQt6.QtWidgets import QApplication, QSplashScreen
from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import (
    QPixmap, QColor, QPainter, QFont, QLinearGradient, QPen, QPainterPath
)


logger = logging.getLogger(__name__)


# ==================== 默认尺寸 ====================

DEFAULT_WIDTH = 600
DEFAULT_HEIGHT = 400


class SplashManager:
    """启动动画管理器
    
    职责：
        - 管理启动画面的创建、显示和关闭
        - 支持图片/纯色两种模式，图片加载失败自动降级
        - 支持显示自定义文字（版本号、加载进度等）
        - 支持通过配置关闭动画
    
    使用示例：
        splash = SplashManager(
            icon_path="resources/icon.png",
            title="EPUB工具箱",
            version="1.12.0"
        )
        splash.show_message("正在初始化...")
        ...  # 初始化操作
        splash.finish(main_window)
    """
    
    def __init__(
        self,
        enabled: bool = True,
        duration_ms: int = 0,
        icon_path: Optional[str] = None,
        title: str = "",
        version: str = ""
    ):
        """初始化启动动画管理器
        
        Args:
            enabled: 是否启用动画。设为 False 则跳过所有动画，直接显示主窗口
            duration_ms: 最短显示时长（毫秒），0 表示不强制
            icon_path: 图标文件路径（建议 .png），加载失败则使用纯色渐变
            title: 应用名称（显示在启动画面中央）
            version: 版本号（显示在应用名称下方）
        """
        self._enabled = enabled
        self._duration_ms = duration_ms
        self._icon_path = icon_path
        self._title = title
        self._version = version
        
        self._splash: Optional[QSplashScreen] = None
        self._pixmap: Optional[QPixmap] = None
        self._current_message: str = ""
        
        if self._enabled:
            self._create()
    
    # ==================== 公共方法 ====================
    
    @property
    def is_active(self) -> bool:
        """动画是否处于激活状态（已创建且可见）"""
        return self._splash is not None and self._splash.isVisible()
    
    def show_message(self, message: str):
        """在启动画面上显示加载进度文字
        
        如果动画未启用，此方法不做任何操作。
        
        Args:
            message: 进度文字内容，如 "正在加载模块..."
        """
        if not self._enabled or self._splash is None:
            return
        
        self._current_message = message
        self._render_message()
        QApplication.processEvents()
    
    def finish(self, main_window) -> bool:
        """关闭启动画面并显示主窗口
        
        Args:
            main_window: 应用主窗口实例
            
        Returns:
            bool: True 表示动画正常完成并关闭，False 表示动画被跳过
        """
        if not self._enabled or self._splash is None:
            return False
        
        # 确保最短显示时长（如果设置）
        if self._duration_ms > 0:
            import time
            start = getattr(self, '_start_time', time.time())
            elapsed = (time.time() - start) * 1000
            remaining = self._duration_ms - elapsed
            if remaining > 0:
                QApplication.processEvents()
                # 简单等待，不阻塞事件循环太久
                import threading
                threading.Event().wait(remaining / 1000)
        
        self._splash.finish(main_window)
        self._splash = None
        self._pixmap = None
        return True
    
    # ==================== 内部方法 ====================
    
    def _create(self):
        """创建启动画面"""
        import time
        self._start_time = time.time()
        
        self._pixmap = self._load_or_create_pixmap()
        self._splash = QSplashScreen(self._pixmap)
        
        self._splash.setWindowFlags(
            Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint
        )
        self._splash.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # 居中定位
        screen_geometry = QApplication.primaryScreen().geometry()
        x = (screen_geometry.width() - self._pixmap.width()) // 2
        y = (screen_geometry.height() - self._pixmap.height()) // 2
        self._splash.setGeometry(x, y, self._pixmap.width(), self._pixmap.height())
        
        self._splash.show()
        QApplication.processEvents()
    
    def _load_or_create_pixmap(self) -> QPixmap:
        """加载图片或创建纯色降级画面
        
        优先使用 icon_path 指定的图片，加载失败则创建纯色渐变动画。
        """
        if self._icon_path:
            try:
                pixmap = QPixmap(self._icon_path).scaled(
                    DEFAULT_WIDTH, DEFAULT_HEIGHT,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                if not pixmap.isNull():
                    logger.debug(f"启动画面：已加载图片 {self._icon_path}")
                    return pixmap
            except Exception as e:
                logger.warning(f"加载启动画面图片失败: {e}")
        
        # 降级：纯色渐变动画
        logger.debug("启动画面：使用纯色渐变降级方案")
        return self._create_gradient_pixmap()
    
    def _create_gradient_pixmap(self) -> QPixmap:
        """创建纯色渐变启动画面
        
        Returns:
            QPixmap: 宽度 DEFAULT_WIDTH、高度 DEFAULT_HEIGHT 的渐变色画面
        """
        pixmap = QPixmap(DEFAULT_WIDTH, DEFAULT_HEIGHT)
        pixmap.fill(QColor("#f8f9fa"))
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 渐变背景
        gradient = QLinearGradient(0, 0, DEFAULT_WIDTH, DEFAULT_HEIGHT)
        gradient.setColorAt(0, QColor("#6a11cb"))
        gradient.setColorAt(1, QColor("#2575fc"))
        painter.fillRect(pixmap.rect(), gradient)
        
        # 标题文字
        if self._title:
            title_font = QFont("Microsoft YaHei", 24, QFont.Weight.Bold)
            painter.setFont(title_font)
            painter.setPen(QColor("#ffffff"))
            
            text_rect = pixmap.rect()
            text_rect.moveTop(text_rect.top() - 20)  # 微调上移
            
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignCenter,
                f"{self._title}\n正在启动..."
            )
        
        # 版本号
        if self._version:
            version_font = QFont("Microsoft YaHei", 11)
            painter.setFont(version_font)
            painter.setPen(QColor(255, 255, 255, 180))  # 半透明白色
            
            version_rect = pixmap.rect()
            version_rect.moveTop(version_rect.bottom() - 40)
            version_rect.setHeight(30)
            
            painter.drawText(
                version_rect,
                Qt.AlignmentFlag.AlignCenter,
                f"v{self._version}"
            )
        
        painter.end()
        return pixmap
    
    def _render_message(self):
        """在启动画面上叠加渲染进度文字（透明背景+文字阴影）"""
        if self._splash is None or self._pixmap is None:
            return
        
        display_pixmap = QPixmap(self._pixmap)
        painter = QPainter(display_pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        msg_font = QFont("Microsoft YaHei", 11)
        painter.setFont(msg_font)
        
        msg_rect = display_pixmap.rect()
        msg_rect.setBottom(msg_rect.bottom() - 8)
        
        # 阴影
        painter.setPen(QColor(0, 0, 0, 160))
        shadow_rect = QRect(msg_rect)
        shadow_rect.moveTop(shadow_rect.top() + 1)
        shadow_rect.moveLeft(shadow_rect.left() + 1)
        painter.drawText(
            shadow_rect,
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
            self._current_message
        )
        
        # 主文字
        painter.setPen(QColor("#ffffff"))
        painter.drawText(
            msg_rect,
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
            self._current_message
        )
        
        painter.end()
        
        self._splash.setPixmap(display_pixmap)
        QApplication.processEvents()


# ==================== 元信息 ====================
__author__ = "YQJ"
__version__ = "1.0.0"
__date__ = "2026.05.03"