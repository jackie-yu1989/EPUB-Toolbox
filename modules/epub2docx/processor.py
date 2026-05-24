#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
EPUB转DOCX - 核心处理逻辑
基于 Calibre ebook-convert 命令行工具 + XML 级后处理
★ 更新：匹配 utils.py v3.0.0
"""

import time
import sys
import subprocess
import logging
from pathlib import Path
from typing import Tuple, Optional, Callable

from core.utils import find_executable

logger = logging.getLogger(__name__)

_STARTUP_INFO = None
if sys.platform == 'win32':
    _STARTUP_INFO = subprocess.STARTUPINFO()
    _STARTUP_INFO.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    _STARTUP_INFO.wShowWindow = subprocess.SW_HIDE

CALIBRE_DOCX_ARGS = [
    "--docx-no-toc",
    "--pretty-print",
]


def convert_epub_to_docx(
    epub_file: Path,
    output_docx: Path,
    page_size: str = "a4",
    fix_soft_breaks: bool = True,
    auto_typography: bool = True,           # ★ 是否启用排版预设
    font_preset: str = "academic",          # ★ 排版预设 (academic/official/business/none)
    log_callback: Optional[Callable] = None
) -> Tuple[bool, str, float]:
    """转换单个 EPUB 文件到 DOCX

    Args:
        epub_file: 输入的 EPUB 文件路径
        output_docx: 输出的 DOCX 文件路径
        page_size: 页面尺寸 (a4/letter/b5/a5)
        fix_soft_breaks: 是否修复软回车
        auto_typography: 是否启用排版预设
        font_preset: 排版预设 (academic/official/business/none)
        log_callback: 日志回调函数

    Returns:
        Tuple[bool, str, float]: (是否成功, 消息, 耗时秒数)
    """
    start_time = time.time()

    def log(msg):
        if log_callback:
            log_callback(msg)
        logger.info(msg)

    ebook_convert = find_executable('ebook-convert')
    if not ebook_convert:
        return False, "未找到 ebook-convert（Calibre 未安装）", 0

    cmd = [
        ebook_convert,
        str(epub_file),
        str(output_docx),
        f"--docx-page-size={page_size}",
        *CALIBRE_DOCX_ARGS,
    ]

    log(f"⚙️ 执行 Calibre 转换: {epub_file.name}")

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
            log("✅ Calibre 基础转换完成，开始后处理...")

            # 后处理 A：软回车修复
            if fix_soft_breaks:
                try:
                    from .utils import fix_soft_line_breaks
                    fix_soft_line_breaks(output_docx, log_callback)
                except Exception as e:
                    log(f"⚠️ 软回车修复异常: {e}")

            # 后处理 B：排版预设应用
            if auto_typography and font_preset != "none":
                try:
                    from .utils import apply_style_preset
                    apply_style_preset(output_docx, font_preset, log_callback)
                except Exception as e:
                    log(f"⚠️ 排版预设应用异常: {e}")

            log(f"🎉 转换及后处理完成 (耗时 {elapsed:.1f}s)")
            return True, "转换成功", elapsed
        else:
            error_msg = result.stderr[:200] if result.stderr else "未知错误"
            log(f"❌ Calibre 转换失败: {error_msg}")
            return False, error_msg, elapsed

    except subprocess.TimeoutExpired:
        log(f"⏱️ 转换超时: {epub_file.name} (300s)")
        return False, "转换超时（超过300秒）", time.time() - start_time
    except Exception as e:
        logger.error(f"转换异常: {epub_file.name} - {e}")
        return False, str(e), time.time() - start_time


# ==================== 元信息 ====================
__author__ = "YQJ"
__version__ = "1.2.0"
__date__ = "2026.05.24"