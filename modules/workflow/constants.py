#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工作流模块 - 常量定义
集中管理步骤标识、模式标识，消除硬编码字符串
"""

class StepKey:
    """步骤标识常量"""
    REPAIR = "repair"
    MD2EPUB = "md2epub"
    EPUB2PDF = "epub2pdf"
    EPUB2DOCX = "epub2docx"
    
    # 所有步骤的列表（按执行顺序），用于自动遍历
    ALL_STEPS = [REPAIR, MD2EPUB, EPUB2PDF, EPUB2DOCX]

class ModeKey:
    """工作流模式标识常量"""
    REPAIR_TO_EPUB = "repair_to_epub"
    MD_TO_PDF = "md_to_pdf"
    MD_TO_DOCX = "md_to_docx"
    FULL_TO_PDF = "full_to_pdf"
    FULL_TO_DOCX = "full_to_docx"

# ==================== 元信息 ====================
__author__ = "YQJ"
__version__ = "1.0.0"
__date__ = "2026.05.23"