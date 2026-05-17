#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
配置键常量 — 单一数据源，所有模块统一引用
消除魔法字符串散落各处的问题

使用方式:
    from core.config_keys import SettingsDomain, MDRepairKey, SettingsKey
    
    settings = QSettings(SettingsDomain.EPUB_TOOLBOX, SettingsDomain.MD_REPAIR)
    value = settings.value(MDRepairKey.CONFIG_V4)
"""


# ==================== QSettings 域名常量 ====================

class SettingsDomain:
    """QSettings 组织名/应用名"""
    EPUB_TOOLBOX = "EPUBToolbox"
    MD_REPAIR = "MDRepair"
    WORKFLOW = "Workflow"
    SETTINGS = "Settings"


# ==================== MD 修复配置键 ====================

class MDRepairKey:
    """MD 公式修复 — 配置键名
    
    覆盖范围：
        - QSettings 存储键名
        - 顶层配置字典 key
        - formula_config 嵌套字典 key
    """
    
    # ---- QSettings 存储键 ----
    CONFIG_V4 = "md_repair_config_v4"
    
    # ---- 顶层配置键 ----
    CLEAN_EXTRA_NEWLINES = "clean_extra_newlines"
    ADD_SPACE_AFTER_INLINE = "add_space_after_inline"
    INLINE_TO_DISPLAY = "inline_to_display"
    IMAGE_CAPTION_ENABLED = "image_caption_enabled"
    IMAGE_CAPTION_COLOR = "image_caption_color"
    ESCAPE_ISOLATED_DOLLARS = "escape_isolated_dollars"
    FIX_ENCODING = "fix_encoding"
    
    # ---- 嵌套公式配置键 ----
    FORMULA_CONFIG = "formula_config"
    
    SUBSUP_FIX = "subsup_fix"
    FUNC_NORMALIZE = "func_normalize"
    MATRIX_NEWLINE_REMOVE = "matrix_newline_remove"
    BRACKET_CHECK = "bracket_check"
    MARKDOWN_ESCAPE_INLINE = "markdown_escape_inline"
    MATRIX_ADD_MULTIPLICATION = "matrix_add_multiplication"
    DL_COMMANDS_TO_TEXT = "dl_commands_to_text"
    REMOVE_SIZE_COMMANDS = "remove_size_commands"
    BM_TO_VEC = "bm_to_vec"
    RESPECT_MACROS = "respect_macros"
    ESCAPE_MODE = "escape_mode"
    BM_STRICT_MODE = "bm_strict_mode"
    
    # ---- 不再使用的键（保留以兼容旧数据读取） ----
    # DL_COMMANDS_LIST = "dl_commands_list"  # 内置默认列表，不再从配置读取
    
    # ---- 顶层配置字段名列表（供预设方案匹配等功能使用） ----
    TOP_LEVEL_KEYS = [
        CLEAN_EXTRA_NEWLINES,
        ADD_SPACE_AFTER_INLINE,
        INLINE_TO_DISPLAY,
        IMAGE_CAPTION_ENABLED,
        ESCAPE_ISOLATED_DOLLARS,
        FIX_ENCODING,
    ]
    
    # ---- 公式级配置字段名列表 ----
    FORMULA_CONFIG_KEYS = [
        SUBSUP_FIX,
        FUNC_NORMALIZE,
        MATRIX_NEWLINE_REMOVE,
        BRACKET_CHECK,
        MARKDOWN_ESCAPE_INLINE,
        MATRIX_ADD_MULTIPLICATION,
        DL_COMMANDS_TO_TEXT,
        REMOVE_SIZE_COMMANDS,
        BM_TO_VEC,
        ESCAPE_MODE,
        RESPECT_MACROS,
        BM_STRICT_MODE,
    ]


# ==================== 主窗口设置键 ====================

class SettingsKey:
    """主窗口 — QSettings 键名"""
    
    SPLITTER_SIZES = "splitter_sizes"
    LOG_PANEL_PINNED = "log_panel_pinned"
    LOG_PANEL_VISIBLE = "log_panel_visible"
    CLOSE_TO_TRAY = "close_to_tray"
    STARTUP_MODULE = "startup_module"


# ==================== 元信息 ====================
__author__ = "YQJ"
__version__ = "1.0.0"
__date__ = "2026.05.08"