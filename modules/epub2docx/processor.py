#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EPUB转DOCX - 核心处理逻辑
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

def convert_epub_to_docx(
    epub_file: Path,
    output_docx: Path,
    page_size: str = "a4",
    fix_soft_breaks: bool = True
) -> Tuple[bool, str, float]:
    """转换单个 EPUB 文件到 DOCX

    Args:
        epub_file: 输入的 EPUB 文件路径
        output_docx: 输出的 DOCX 文件路径
        page_size: 页面尺寸 (a4/letter/b5/a5)
        fix_soft_breaks: 是否修复软回车

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
        str(output_docx),
        f"--docx-page-size={page_size}",
        "--docx-no-toc",
        "--pretty-print",
    ]

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
            # 后处理：修复软回车
            if fix_soft_breaks:
                try:
                    from .utils import fix_soft_line_breaks
                    fix_soft_line_breaks(output_docx)
                    logger.debug(f"已修复软回车: {output_docx.name}")
                except Exception as e:
                    logger.warning(f"软回车修复失败: {e}")

            logger.debug(f"转换成功: {epub_file.name} → {output_docx.name} ({elapsed:.1f}s)")
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

# ==================== 元信息 ====================
__author__ = "YQJ"
__version__ = "1.0.0"
__date__ = "2026.05.22"