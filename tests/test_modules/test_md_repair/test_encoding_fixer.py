#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""编码修复器测试"""

import pytest
from modules.md_repair.processor import FormulaEncodingFixer


class TestEncodingFixer:

    @pytest.fixture
    def fixer(self):
        """创建启用状态的修复器"""
        return FormulaEncodingFixer(enabled=True)

    def test_carriage_return(self, fixer):
        """测试 \\r\\n 替换为 \\n"""
        result, count = fixer.fix_encoding("a\r\nb")
        assert result == "a\nb"
        assert count > 0

    def test_carriage_return_only(self, fixer):
        """测试单独 \\r 替换为 \\n"""
        result, count = fixer.fix_encoding("a\rb")
        assert result == "a\nb"
        assert count > 0

    def test_null_byte(self, fixer):
        """测试空字节 \\x00 被移除"""
        result, count = fixer.fix_encoding("a\x00b")
        assert result == "ab"
        assert count > 0

    def test_hex_escape(self, fixer):
        """测试十六进制转义序列被正确转义"""
        result, count = fixer.fix_encoding(r"\x0a")
        assert "\\\\x0a" in result
        assert count > 0

    def test_multiple_hex_escapes(self, fixer):
        """测试多个十六进制转义序列"""
        result, count = fixer.fix_encoding(r"\x0a\x0d")
        assert result.count("\\\\x") == 2
        assert count >= 2

    def test_hex_escape_already_escaped(self, fixer):
        """测试已正确转义的序列不被重复处理"""
        result, count = fixer.fix_encoding(r"\\x0a")
        assert result == r"\\x0a"
        assert count == 0

    def test_no_issues(self, fixer):
        """测试无问题的公式原样返回"""
        result, count = fixer.fix_encoding("$x + y$")
        assert result == "$x + y$"
        assert count == 0

    def test_disabled(self):
        """测试禁用时不修改"""
        fixer = FormulaEncodingFixer(enabled=False)
        result, count = fixer.fix_encoding("a\x00b")
        assert result == "a\x00b"
        assert count == 0

    def test_fix_text_protects_formulas(self):
        """测试 fix_text 方法保护公式内容"""
        fixer = FormulaEncodingFixer(enabled=True)
        text, count = fixer.fix_text("$a\x00b$")
        # 公式内的控制字符应被保护
        assert "$a\x00b$" in text