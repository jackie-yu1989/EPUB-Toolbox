#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
配置键常量 — 单一数据源，所有模块统一引用
消除魔法字符串散落各处的问题

使用方式:
    from core.config_keys import SettingsDomain, MDRepairKey, SettingsKey, EPUB2DocxKey, EPUB2PdfKey, MD2EpubKey, WorkflowKey
    
    settings = QSettings(SettingsDomain.EPUB_TOOLBOX, SettingsDomain.SETTINGS)
    value = settings.value(WorkflowKey.CONFIG)
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


# ==================== EPUB转Word 配置键 ====================

class EPUB2DocxKey:
    """EPUB转Word — QSettings 存储键与配置字段名"""
    
    # QSettings 存储键
    CONFIG = "epub2docx_config"
    
    # 配置字段名
    PAGE_SIZE = "page_size"
    FIX_SOFT_BREAKS = "fix_soft_breaks"
    MAX_THREADS = "max_threads"
    AUTO_OPEN = "auto_open"
    OUTPUT_DIR = "output_dir"
    TYPOGRAPHY_PRESET = "typography_preset" # 排版预设


# ==================== EPUB转PDF 配置键 ====================

class EPUB2PdfKey:
    """EPUB转PDF — QSettings 存储键与配置字段名"""
    
    # QSettings 存储键
    CONFIG = "epub2pdf_config"
    
    # 配置字段名
    MARGINS = "margins"
    SHOW_PAGE_NUMBERS = "show_page_numbers"
    MAX_THREADS = "max_threads"
    AUTO_OPEN = "auto_open"
    OUTPUT_DIR = "output_dir"


# ==================== MD转EPUB 配置键 ====================

class MD2EpubKey:
    """MD转EPUB — QSettings 存储键与配置字段名"""
    
    # QSettings 存储键
    CONFIG = "md2epub_config"
    
    # 配置字段名
    CSS_STYLE = "css_style"
    COLOR_KEY = "color_key"
    MAX_THREADS = "max_threads"
    KEEP_TEMP = "keep_temp"
    AUTO_OPEN = "auto_open"
    RENAME_WITH_TITLE = "rename_with_title"
    USE_YAML_TITLE = "use_yaml_title"
    OUTPUT_DIR = "output_dir"


# ==================== 组合工作流配置键 ====================

class WorkflowKey:
    """组合工作流 — QSettings 存储键与配置字段名"""
    
    # QSettings 存储键
    CONFIG = "workflow_config"
    
    # 配置字段名
    MODE = "mode"
    STEP_WORKERS = "step_workers"
    RENAME_BY_TITLE = "rename_by_title"
    USE_YAML_TITLE = "use_yaml_title"
    KEEP_INTERMEDIATE = "keep_intermediate"
    AUTO_OPEN = "auto_open"
    SHOW_PAGE_NUMBERS = "show_page_numbers"
    OUTPUT_DIR = "output_dir"
    EPUB_CSS_STYLE = "epub_css_style"
    EPUB_COLOR_KEY = "epub_color_key"
    PDF_PRESET_KEY = "pdf_preset_key"

    # ★ Word 设置键
    DOCX_PAGE_SIZE = "docx_page_size"
    DOCX_FIX_SOFT_BREAKS = "docx_fix_soft_breaks"
    DOCX_PRESET = "docx_preset"   

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
__version__ = "1.3.0"
__date__ = "2026.05.23"