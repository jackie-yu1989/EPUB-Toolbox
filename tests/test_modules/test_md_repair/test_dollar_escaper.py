#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""美元符号转义器测试"""

import pytest
from modules.md_repair.processor import DollarSignEscaper


class TestDollarEscaper:

    @pytest.fixture
    def escaper(self):
        return DollarSignEscaper(enabled=True)

    def test_price_dollar(self, escaper):
        """测试价格美元符号被转义"""
        result, count = escaper.escape("价格是 $100")
        assert "\\$100" in result
        assert count > 0

    def test_formula_protected(self, escaper):
        """测试公式内的美元符号不被转义"""
        result, count = escaper.escape("公式 $x + y$ 正确")
        assert "$x + y$" in result
        assert "\\$x" not in result

    def test_display_formula_protected(self, escaper):
        """测试块级公式不被转义"""
        result, count = escaper.escape("$$\nE = mc^2\n$$")
        assert "$$" in result
        assert "\\$\\$" not in result

    def test_code_block_protected(self, escaper):
        """测试代码块内的美元符号不被转义"""
        result, count = escaper.escape("```\n$var = 1\n```")
        assert "$var" in result

    def test_mixed_content(self, escaper):
        """测试混合内容：公式 + 价格"""
        result, count = escaper.escape("公式 $x$ 和价格 $100")
        assert "$x$" in result
        assert "\\$100" in result

    def test_disabled(self):
        """测试禁用时不修改"""
        escaper = DollarSignEscaper(enabled=False)
        result, count = escaper.escape("价格 $100")
        assert result == "价格 $100"
        assert count == 0

    def test_empty_text(self, escaper):
        """测试空文本"""
        result, count = escaper.escape("")
        assert result == ""
        assert count == 0