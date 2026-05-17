#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
流水线状态管理 — 统一数据结构与 key 解析

解决 pipeline_states 的 key 分裂问题：
    - 同一个文件的三个步骤状态散落在 .md / _fixed.md / .epub 三个不同的 key 下
    - 通过 resolve_source_file() 统一反推原始 .md 文件路径
    - 通过 make_pipeline_key() 统一 key 生成规则

使用方式：
    from modules.workflow.pipeline_state import resolve_source_file, make_pipeline_key
    
    key = make_pipeline_key(any_file_path)  # 永远是原始 .md 的绝对路径
"""

from pathlib import Path


def resolve_source_file(file_path: Path) -> Path:
    """从任意步骤产物路径反推原始 .md 文件

    核心逻辑（按优先级）：
    1. 已经是原始 .md → 直接返回
    2. _fixed.md → 去掉 _fixed 后缀，查找同名原始 .md
    3. .epub → 替换扩展名为 .md，查找同名原始 .md
    4. 兜底 → 返回自身（不应到达此处）

    Examples:
        resolve_source_file(Path("/path/论文.md"))       → /path/论文.md
        resolve_source_file(Path("/path/论文_fixed.md")) → /path/论文.md
        resolve_source_file(Path("/path/论文.epub"))     → /path/论文.md
        resolve_source_file(Path("/path/深度学习研究_fixed.md")) → /path/深度学习研究.md
    """
    path = file_path.resolve()
    suffix = path.suffix
    stem = path.stem

    # 规则1：原始 .md 文件（不是 _fixed.md）
    if suffix == '.md' and not stem.endswith('_fixed'):
        return path

    # 规则2：_fixed.md → 去掉 _fixed 后缀
    if suffix == '.md' and stem.endswith('_fixed'):
        original_stem = stem[:-6]  # 去掉末尾的 '_fixed'
        candidate = path.with_name(original_stem + '.md')
        if candidate.exists():
            return candidate
        # YAML 重命名场景：原始文件可能被重命名过，但 stem 应与 _fixed 的 stem 相同
        # "深度学习研究_fixed.md" → 原始文件必为 "深度学习研究.md"
        # 即使该文件被移动/删除，也返回这个路径（后续操作会自行处理不存在的情况）
        return candidate

    # 规则3：.epub → 替换扩展名
    if suffix == '.epub':
        candidate = path.with_suffix('.md')
        if candidate.exists():
            return candidate
        return candidate  # 回退

    # 规则4：完全兜底（不应到达此处）
    return path


def make_pipeline_key(file_path: Path) -> str:
    """生成 pipeline_states 的统一 key

    规则：始终使用原始 .md 文件的绝对路径

    Args:
        file_path: 任意步骤的文件路径（可以是原始 .md、_fixed.md、.epub）

    Returns:
        str: 原始 .md 文件的绝对路径字符串
    """
    source = resolve_source_file(file_path)
    return str(source)


def make_pipeline_key_from_str(file_path_str: str) -> str:
    """从字符串路径生成统一 key（兼容旧代码）

    Args:
        file_path_str: 文件路径字符串

    Returns:
        str: 原始 .md 文件的绝对路径字符串
    """
    return make_pipeline_key(Path(file_path_str))

# ==================== 元信息 ====================
__author__ = "YQJ"
__version__ = "1.0.0"
__date__ = "2026.05.09"