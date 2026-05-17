#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
工具函数模块
提供跨平台的依赖检查、文件操作和路径处理工具
"""

import os
import sys
import shutil
import subprocess
import logging
from pathlib import Path
from typing import Optional, Tuple


# 模块级日志记录器
logger = logging.getLogger(__name__)

# ★ 创建静默启动信息（Windows 下隐藏控制台窗口）
_STARTUP_INFO = None
if sys.platform == 'win32':
    _STARTUP_INFO = subprocess.STARTUPINFO()
    _STARTUP_INFO.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    _STARTUP_INFO.wShowWindow = subprocess.SW_HIDE


# ==================== 依赖检查 ====================

def find_executable(name: str) -> Optional[str]:
    """查找可执行文件路径
    
    先在系统 PATH 中查找，失败后在常见安装路径中回退查找。
    
    Args:
        name: 可执行文件名（如 'pandoc', 'ebook-convert'）
        
    Returns:
        Optional[str]: 可执行文件完整路径，未找到返回 None
    """
    # 1. 系统 PATH 查找
    exe_path = shutil.which(name)
    if exe_path:
        return exe_path
    
    # 2. Windows 常见路径回退查找
    if sys.platform == 'win32':
        exe_path = _find_executable_windows_fallback(name)
        if exe_path:
            return exe_path
    
    # 3. npx 后缀回退（用于 Mermaid CLI）
    if name in ('mmdc', '@mermaid-js/mermaid-cli'):
        npx_path = shutil.which('npx')
        if npx_path:
            return npx_path
    
    logger.debug(f"未找到可执行文件: {name}")
    return None


def _find_executable_windows_fallback(name: str) -> Optional[str]:
    """Windows 平台专用：在常见安装路径中回退查找
    
    Args:
        name: 可执行文件名
        
    Returns:
        Optional[str]: 找到的路径，未找到返回 None
    """
    fallback_paths = {
        'ebook-convert': [
            r'C:\Program Files\Calibre2\ebook-convert.exe',
            r'C:\Program Files (x86)\Calibre2\ebook-convert.exe',
            os.path.expanduser(r'~\AppData\Local\Programs\Calibre\ebook-convert.exe'),
        ],
        'pandoc': [
            r'C:\Program Files\Pandoc\pandoc.exe',
            os.path.expanduser(r'~\AppData\Local\Pandoc\pandoc.exe'),
        ],
    }
    
    if name in fallback_paths:
        for path in fallback_paths[name]:
            if Path(path).exists():
                logger.debug(f"在回退路径中找到 {name}: {path}")
                return path
    
    return None


def _run_command(cmd: list, timeout: int = 10) -> Tuple[int, str, str]:
    """执行命令并捕获输出
    
    Args:
        cmd: 命令列表（如 ['pandoc', '--version']）
        timeout: 超时秒数
        
    Returns:
        Tuple[int, str, str]: (返回码, stdout, stderr)
        
    Raises:
        subprocess.TimeoutExpired: 命令超时
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            startupinfo=_STARTUP_INFO
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError:
        return -1, "", "命令未找到"
    except subprocess.TimeoutExpired:
        logger.warning(f"命令超时 ({timeout}s): {' '.join(cmd)}")
        raise


def check_pandoc() -> Tuple[bool, str]:
    """检查 Pandoc 是否可用
    
    Returns:
        Tuple[bool, str]: (是否可用, 版本信息或错误描述)
    """
    pandoc = find_executable('pandoc')
    if not pandoc:
        return False, "未找到 Pandoc，请安装后重试"
    
    try:
        returncode, stdout, stderr = _run_command([pandoc, '--version'])
        if returncode == 0:
            version_line = stdout.split('\n')[0] if stdout else "未知版本"
            return True, version_line
        return False, f"Pandoc 无法正常运行 (返回码: {returncode})"
    except subprocess.TimeoutExpired:
        return False, "Pandoc 版本检查超时"
    except Exception as e:
        logger.error(f"Pandoc 检查异常: {e}")
        return False, str(e)


def check_calibre() -> Tuple[bool, str]:
    """检查 Calibre (ebook-convert) 是否可用
    
    Returns:
        Tuple[bool, str]: (是否可用, 版本信息或错误描述)
    """
    ebook_convert = find_executable('ebook-convert')
    if not ebook_convert:
        return False, "未找到 Calibre (ebook-convert)，请安装后重试"
    
    try:
        returncode, stdout, stderr = _run_command([ebook_convert, '--version'])
        if returncode == 0:
            return True, stdout
        return False, f"ebook-convert 无法正常运行 (返回码: {returncode})"
    except subprocess.TimeoutExpired:
        return False, "ebook-convert 版本检查超时"
    except Exception as e:
        logger.error(f"Calibre 检查异常: {e}")
        return False, str(e)


def check_mermaid() -> Tuple[bool, str]:
    """检查 Mermaid 渲染器是否可用
    
    优先检测 mmdc，其次检测 npx 方式。
    
    Returns:
        Tuple[bool, str]: (是否可用, 状态描述)
    """
    # 优先检测直接安装的 mmdc
    mmdc = find_executable('mmdc')
    if mmdc:
        try:
            returncode, stdout, stderr = _run_command([mmdc, '--version'], timeout=5)
            if returncode == 0:
                return True, f"mmdc {stdout}"
        except subprocess.TimeoutExpired:
            return False, "mmdc 版本检查超时"
        except Exception:
            pass  # mmdc 存在但无法运行，继续尝试 npx
    
    # 回退检测 npx
    npx = find_executable('npx')
    if npx:
        return True, "通过 npx 可用（首次使用将自动下载 @mermaid-js/mermaid-cli）"
    
    return False, "未找到 Mermaid 渲染器，请安装 mmdc 或 npx"


# ==================== 文件系统操作 ====================

def open_file_location(file_path: Path):
    """在文件管理器中打开文件所在位置并选中文件
    
    跨平台实现：
        Windows: explorer /select,<path>
        macOS:   open -R <path>
        Linux:   xdg-open <folder>（不支持选中文件，仅打开文件夹）
    
    Args:
        file_path: 文件路径
    """
    folder = str(file_path.parent)
    
    if sys.platform == 'win32':
        subprocess.run(['explorer', '/select,', str(file_path)], shell=True)
    elif sys.platform == 'darwin':
        subprocess.run(['open', '-R', str(file_path)])
    else:
        # Linux 不支持原生"选中文件"，回退到打开文件夹
        subprocess.run(['xdg-open', folder])


def open_folder(folder_path: Path):
    """在文件管理器中打开文件夹
    
    跨平台实现：
        Windows: explorer <folder>
        macOS:   open <folder>
        Linux:   xdg-open <folder>
    
    Args:
        folder_path: 文件夹路径
    """
    folder = str(folder_path)
    
    if sys.platform == 'win32':
        subprocess.run(['explorer', folder], shell=True)
    elif sys.platform == 'darwin':
        subprocess.run(['open', folder])
    else:
        subprocess.run(['xdg-open', folder])


def format_file_size(size_bytes: int) -> str:
    """格式化文件大小为人类可读字符串
    
    Args:
        size_bytes: 文件大小（字节）
        
    Returns:
        str: 格式化后的大小字符串（如 "1.5 MB"）
    """
    if size_bytes < 0:
        return "0 B"
    
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    size = float(size_bytes)
    unit_index = 0
    
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    
    return f"{size:.1f} {units[unit_index]}"


def get_unique_filename(file_path: Path) -> Path:
    """获取唯一的文件名（如果存在则添加序号后缀）
    
    避免覆盖已有文件，自动生成 file_1.txt, file_2.txt 等。
    最多尝试 1000 次，防止无限循环。
    
    Args:
        file_path: 原始文件路径
        
    Returns:
        Path: 唯一的文件路径（不存在冲突）
        
    Raises:
        RuntimeError: 超过最大尝试次数时抛出
    """
    if not file_path.exists():
        return file_path
    
    parent = file_path.parent
    stem = file_path.stem
    suffix = file_path.suffix
    
    for counter in range(1, 1001):
        new_path = parent / f"{stem}_{counter}{suffix}"
        if not new_path.exists():
            return new_path
    
    raise RuntimeError(f"无法为 {file_path} 生成唯一文件名（已尝试 1000 次）")


def ensure_directory(path: Path) -> Path:
    """确保目录存在，不存在则递归创建
    
    Args:
        path: 目录路径
        
    Returns:
        Path: 传入的路径（确保存在后返回）
    """
    path.mkdir(parents=True, exist_ok=True)
    return path


# ==================== 元信息 ====================
__author__ = "YQJ"
__version__ = "1.1.0"
__date__ = "2026.05.01"