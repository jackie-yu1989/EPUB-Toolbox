#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
EPUB转PDF - 核心处理逻辑
基于 Calibre ebook-convert 命令行工具
"""

import time
import sys
import subprocess
import logging
from pathlib import Path
from typing import Tuple, Dict

from core.utils import find_executable


# 模块级日志记录器
logger = logging.getLogger(__name__)

# ★ 静默启动信息（Windows 下隐藏控制台窗口）
_STARTUP_INFO = None
if sys.platform == 'win32':
    _STARTUP_INFO = subprocess.STARTUPINFO()
    _STARTUP_INFO.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    _STARTUP_INFO.wShowWindow = subprocess.SW_HIDE


def convert_epub_to_pdf(
    epub_file: Path, 
    output_pdf: Path, 
    margins: Dict[str, int],
    show_page_numbers: bool = False
) -> Tuple[bool, str, float]:
    """转换单个 EPUB 文件到 PDF
    
    Args:
        epub_file: 输入的 EPUB 文件路径
        output_pdf: 输出的 PDF 文件路径
        margins: 页边距字典，包含 top/bottom/left/right/font_size
        
    Returns:
        Tuple[bool, str, float]: (是否成功, 消息, 耗时秒数)
    """
    start_time = time.time()
    
    ebook_convert = find_executable('ebook-convert')
    if not ebook_convert:
        return False, "未找到 ebook-convert（Calibre 未安装）", 0
    
    # 构建 Calibre 命令
    cmd = [
        ebook_convert,
        str(epub_file),
        str(output_pdf),
        f"--margin-top={margins.get('top', 0)}",
        f"--margin-bottom={margins.get('bottom', 0)}",
        f"--margin-left={margins.get('left', 0)}",
        f"--margin-right={margins.get('right', 0)}",
        f"--pdf-default-font-size={margins.get('font_size', 12)}",
        "--pdf-mono-font-size=10",
    ]

    # ★ 页码控制 — 使用 Calibre 默认格式
    if show_page_numbers:
        cmd.append("--pdf-page-numbers")
    
    try:
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True, 
            timeout=300,
            encoding='utf-8',
            errors='replace',
            startupinfo=_STARTUP_INFO
        )
        elapsed = time.time() - start_time
        
        if result.returncode == 0:
            logger.debug(f"转换成功: {epub_file.name} → {output_pdf.name} ({elapsed:.1f}s)")
            return True, "转换成功", elapsed
        else:
            error_msg = result.stderr[:200] if result.stderr else "未知错误"
            logger.warning(f"转换失败: {epub_file.name} - {error_msg}")
            return False, error_msg, elapsed
            
    except subprocess.TimeoutExpired:
        logger.warning(f"转换超时: {epub_file.name} (300s)")
        return False, "转换超时（超过300秒）", time.time() - start_time
    except Exception as e:
        logger.error(f"转换异常: {epub_file.name} - {e}")
        return False, str(e), time.time() - start_time


# ==================== 页边距预设配置 ====================

PRESETS = {
    "1": {"name": "极限紧凑版", "top": 0, "bottom": 0, "left": 0, "right": 0, "font_size": 12},
    "2": {"name": "左右紧凑版", "top": 10, "bottom": 10, "left": 0, "right": 0, "font_size": 12},
    "3": {"name": "上下紧凑版", "top": 0, "bottom": 0, "left": 10, "right": 10, "font_size": 12},
    "4": {"name": "对称装订版", "top": 10, "bottom": 10, "left": 10, "right": 10, "font_size": 12}
}


# ==================== 元信息 ====================
__author__ = "YQJ"
__version__ = "1.1.1"
__date__ = "2026.05.17"