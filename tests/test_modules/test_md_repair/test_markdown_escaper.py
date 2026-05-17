#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Markdown 符号转义器测试"""

import pytest
from modules.md_repair.processor import MarkdownEscaper


class TestMarkdownEscaper:

    def test_standard_underscore(self):
        """测试标准模式下划线转义"""
        escaper = MarkdownEscaper(mode='standard')
        result, count = escaper.escape_formula("$x_i$")
        assert result in ["$x\\_i$", "$x_{i}$"]  # 两种可能结果

    def test_standard_asterisk(self):
        """测试标准模式星号转义"""
        escaper = MarkdownEscaper(mode='standard')
        result, count = escaper.escape_formula("$a * b$")
        assert result == "$a \\* b$"

    def test_zhihu_extra_symbols(self):
        """测试知乎模式额外转义"""
        escaper = MarkdownEscaper(mode='zhihu')
        result, count = escaper.escape_formula("$a & b$")
        assert "\\&" in result

    def test_latex_command_protected(self):
        """测试 LaTeX 命令不被转义"""
        escaper = MarkdownEscaper(mode='standard')
        result, count = escaper.escape_formula("$\\alpha_i$")
        # \\alpha 应保持完整
        assert "\\alpha" in result

    def test_braces_protected(self):
        """测试花括号内的内容不被转义"""
        escaper = MarkdownEscaper(mode='standard')
        result, count = escaper.escape_formula("$x_{ij}$")
        assert "_{ij}" in result

    def test_off_mode(self):
        """测试关闭模式"""
        escaper = MarkdownEscaper(mode='off')
        result, count = escaper.escape_formula("$x_i$")
        assert result == "$x_i$"
        assert count == 0

    def test_disabled_property(self):
        """测试 enabled 属性"""
        escaper = MarkdownEscaper(mode='off')
        assert escaper.enabled is False
        escaper = MarkdownEscaper(mode='standard')
        assert escaper.enabled is True

    def test_empty_formula(self):
        """测试空公式"""
        escaper = MarkdownEscaper(mode='standard')
        result, count = escaper.escape_formula("")
        assert result == ""
        assert count == 0