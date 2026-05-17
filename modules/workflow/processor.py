#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
工作流模块 - 编排引擎
串联 MD修复 → MD转EPUB → EPUB转PDF 的自动处理流程
"""

import sys
import os
import time
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any, Callable


def run_repair_step(
    input_file: Path,
    output_dir: Path,
    config: Dict[str, Any],
    log_callback: Callable = None,
    output_filename: str = None
) -> Tuple[bool, str, Optional[Path]]:
    """执行 MD公式修复 步骤
    
    Returns:
        (成功, 消息, 输出文件路径)
    """
    try:
        from modules.md_repair.processor import MarkdownFormulaProcessor
        
        if log_callback:
            log_callback(f"🔧 修复公式: {input_file.name}")
        
        processor = MarkdownFormulaProcessor(
            input_file=input_file,
            output_dir=output_dir,
            config=config
        )
        
        # ★ 支持自定义输出文件名
        if output_filename is None:
            output_filename = f"{input_file.stem}_fixed.md"
        
        _, output_path = processor.process(output_filename=output_filename)
        
        if output_path.exists():
            return True, "公式修复完成", output_path
        else:
            return False, "修复后文件未生成", None
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, f"公式修复失败: {e}", None

def run_md2epub_step(
    input_file: Path,
    output_dir: Path,
    css: str,
    log_callback: Callable = None,
    output_epub: Path = None,
    use_yaml_title: bool = True        # ★ 新增
) -> Tuple[bool, str, Optional[Path]]:
    """执行 MD转EPUB 步骤
    
    Returns:
        (成功, 消息, 输出文件路径)
    """
    try:
        from modules.md2epub.processor import convert_markdown_to_epub
        import tempfile
        import shutil
        
        if log_callback:
            log_callback(f"📖 转换EPUB: {input_file.name}")
        
        # 创建临时工作目录
        work_dir = Path(tempfile.mkdtemp(prefix='epub_workflow_'))
        
        try:
            # ★ 支持自定义输出路径
            if output_epub is None:
                output_epub = output_dir / input_file.with_suffix('.epub').name
            
            # 防覆盖
            if output_epub.exists():
                base_stem = output_epub.stem
                counter = 1
                while output_epub.exists():
                    output_epub = output_dir / f"{base_stem}_{counter}.epub"
                    counter += 1
            
            def step_log(msg):
                if log_callback:
                    log_callback(f"   {msg}")
            
            success, msg = convert_markdown_to_epub(
                input_file, output_epub, work_dir, css, step_log,
                use_yaml_title=use_yaml_title       # ★ 新增
            )
            
            if success and output_epub.exists():
                return True, "EPUB转换完成", output_epub
            else:
                return False, f"EPUB转换失败: {msg}", None
                
        finally:
            # 清理临时目录
            shutil.rmtree(work_dir, ignore_errors=True)
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, f"EPUB转换失败: {e}", None

def run_epub2pdf_step(
    input_file: Path,
    output_dir: Path,
    margins: Dict[str, int],
    log_callback: Callable = None,
    output_pdf: Path = None,
    show_page_numbers: bool = False
) -> Tuple[bool, str, Optional[Path]]:
    """执行 EPUB转PDF 步骤
    
    Returns:
        (成功, 消息, 输出文件路径)
    """
    try:
        from modules.epub2pdf.processor import convert_epub_to_pdf
        
        if log_callback:
            log_callback(f"📄 转换PDF: {input_file.name}")
        
        # ★ 支持自定义输出路径
        if output_pdf is None:
            output_pdf = output_dir / input_file.with_suffix('.pdf').name
        
        # 防覆盖
        if output_pdf.exists():
            base_stem = output_pdf.stem
            counter = 1
            while output_pdf.exists():
                output_pdf = output_dir / f"{base_stem}_{counter}.pdf"
                counter += 1
        
        success, msg, elapsed = convert_epub_to_pdf(
            input_file, output_pdf, margins,
            show_page_numbers=show_page_numbers
        )
        
        if success and output_pdf.exists():
            return True, f"PDF转换完成 ({elapsed:.1f}秒)", output_pdf
        else:
            return False, f"PDF转换失败: {msg}", None
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, f"PDF转换失败: {e}", None
    
# ==================== 元信息 ====================
__author__ = "YQJ"
__version__ = "1.1.1"
__date__ = "2026.05.17"