#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""工作流处理器测试"""

import pytest
from pathlib import Path


class TestWorkflowProcessorImports:
    """测试工作流步骤函数可正确导入"""

    def test_import_repair_step(self):
        """测试修复步骤导入"""
        from modules.workflow.processor import run_repair_step
        assert callable(run_repair_step)

    def test_import_md2epub_step(self):
        """测试 MD转EPUB 步骤导入"""
        from modules.workflow.processor import run_md2epub_step
        assert callable(run_md2epub_step)

    def test_import_epub2pdf_step(self):
        """测试 EPUB转PDF 步骤导入"""
        from modules.workflow.processor import run_epub2pdf_step
        assert callable(run_epub2pdf_step)

    def test_repair_step_basic(self, temp_dir, sample_md_file, safe_config):
        """测试修复步骤基本执行"""
        from modules.workflow.processor import run_repair_step

        success, msg, output = run_repair_step(
            sample_md_file,
            temp_dir,
            safe_config,
        )

        assert success is True
        assert output is not None
        assert output.exists()
        assert output.suffix == ".md"