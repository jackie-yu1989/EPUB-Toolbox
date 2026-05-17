#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CSS 管理器
从外部 CSS 模板文件加载 EPUB 样式，支持颜色变量注入和自动发现
"""

import re
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class CssStyleInfo:
    """CSS 风格元信息"""
    key: str                        # 文件名（不含扩展名），如 "clean", "plain"
    name: str                       # 显示名称
    description: str = ""           # 描述文本
    order: int = 99                 # 排序权重，数字越小越靠前
    is_builtin: bool = False        # 是否为内置样式
    is_default: bool = False        # ★ 是否为默认选中样式


class CssManager:
    """EPUB CSS 模板管理器
    
    职责：
        1. 扫描 resources/css/ 目录，自动发现所有可用 CSS 风格
        2. 加载 CSS 模板文件并将颜色变量替换为实际颜色值
        3. CSS 文件不存在时回退到内置样式
        
    使用示例：
        manager = CssManager()
        
        # 获取所有可用风格
        styles = manager.discover_styles()
        
        # 加载指定风格
        css = manager.load("clean", {"primary": "#3498db", "border": "#ccc"})
    """
    
    def __init__(self, css_dir: Optional[Path] = None):
        """初始化 CSS 管理器
        
        Args:
            css_dir: CSS 模板文件目录，默认 resources/css/
        """
        if css_dir is None:
            css_dir = Path(__file__).parent.parent / "resources" / "css"
        self._css_dir = css_dir
        self._cache: Dict[str, str] = {}
    
    # ==================== 风格发现 ====================
    
    def discover_styles(self) -> List[CssStyleInfo]:
        """扫描 resources/css/ 目录，返回所有可用风格
        
        Returns:
            List[CssStyleInfo]: 按 order 排序的风格列表
        """
        styles = []
        
        if not self._css_dir.exists():
            return self._get_builtin_styles()
        
        for css_file in sorted(self._css_dir.glob("*.css")):
            info = self._parse_style_info(css_file)
            if info:
                styles.append(info)
        
        if not styles:
            return self._get_builtin_styles()
        
        styles.sort(key=lambda s: s.order)
        return styles
    
    def _parse_style_info(self, css_file: Path) -> Optional[CssStyleInfo]:
        """解析 CSS 文件头部的元信息
        
        元信息格式（CSS 注释）：
            /* @name: 风格名称 */
            /* @description: 风格描述 */
            /* @order: 排序权重 */
            /* @default: true */         ← 新增
        """
        key = css_file.stem
        
        try:
            content = css_file.read_text(encoding='utf-8')
        except Exception as e:
            logger.warning(f"读取 CSS 文件失败: {css_file} - {e}")
            return None
        
        name = key
        description = ""
        order = 99
        is_default = False              # ★ 新增
        
        for line in content.split('\n')[:30]:
            match = re.match(r'/\*\s*@(\w+):\s*(.+?)\s*\*/', line)
            if match:
                meta_key, meta_value = match.groups()
                if meta_key == 'name':
                    name = meta_value.strip()
                elif meta_key == 'description':
                    description = meta_value.strip()
                elif meta_key == 'order':
                    try:
                        order = int(meta_value.strip())
                    except ValueError:
                        pass
                elif meta_key == 'default':                # ★ 新增
                    is_default = meta_value.strip().lower() == 'true'
            elif line.strip() and not line.strip().startswith('/*'):
                break
        
        is_builtin = key in ('clean', 'plain')
        
        return CssStyleInfo(
            key=key,
            name=name,
            description=description,
            order=order,
            is_builtin=is_builtin,
            is_default=is_default                        # ★ 新增
        )
    
    def _get_builtin_styles(self) -> List[CssStyleInfo]:
        """内置风格（CSS 目录不存在时回退）"""
        return [
            CssStyleInfo("plain", "朴素样式", "白底黑字极简排版，适合 Kindle 等墨水屏设备", 1, True, True),
            CssStyleInfo("clean", "简洁样式", "白色容器+彩色边框，无阴影圆角，适合现代阅读器", 2, True, False),
        ]
    
    # ==================== CSS 加载与注入 ====================
    
    def load(self, style: str, colors: Dict[str, str]) -> str:
        """加载 CSS 模板并注入颜色变量
        
        查找顺序：resources/css/{style}.css → 内置回退
        
        Args:
            style: 风格名称（对应 CSS 文件名，不含 .css 扩展名）
            colors: 颜色变量字典，如 {"primary": "#3498db", "border": "#ccc"}
            
        Returns:
            str: 注入颜色后的完整 CSS 字符串
        """
        css_file = self._css_dir / f"{style}.css"
        
        if not css_file.exists():
            logger.debug(f"CSS 文件不存在: {css_file}，回退到内置样式")
            return self._get_fallback(style, colors)
        
        cache_key = str(css_file)
        if cache_key not in self._cache:
            try:
                self._cache[cache_key] = css_file.read_text(encoding='utf-8')
                logger.debug(f"已加载 CSS 模板: {css_file}")
            except Exception as e:
                logger.warning(f"读取 CSS 文件失败: {e}")
                return self._get_fallback(style, colors)
        
        return self._inject_colors(self._cache[cache_key], colors)
    
    def _inject_colors(self, template: str, colors: Dict[str, str]) -> str:
        """安全注入颜色变量
        
        Args:
            template: CSS 模板字符串
            colors: 颜色变量字典
            
        Returns:
            str: 注入后的 CSS
        """
        result = template
        for key, value in colors.items():
            if key.startswith('_'):
                continue
            result = result.replace(f'{{{key}}}', value)
        return result
    
    def _get_fallback(self, style: str, colors: Dict[str, str]) -> str:
        """回退到内置 CSS 样式"""
        from core.theme_manager import ThemeManager
        tm = ThemeManager()
        
        if style == "plain":
            return tm.get_css_for_epub("plain", colors.get('primary'))
        else:
            return tm.get_css_for_epub("clean", colors.get('primary'))
    
    def clear_cache(self):
        """清除 CSS 模板缓存"""
        self._cache.clear()
        logger.debug("CSS 模板缓存已清除")


# ==================== 元信息 ====================
__author__ = "YQJ"
__version__ = "1.2.0"
__date__ = "2026.05.03"