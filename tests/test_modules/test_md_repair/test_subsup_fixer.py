#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""上下标修正测试"""

import pytest
from modules.md_repair.processor import SubSupFixer


class TestSubSupFixer:

    @pytest.fixture
    def fixer(self):
        return SubSupFixer(enabled=True)

    # ---- 上标 ----

    def test_superscript_already_correct(self, fixer):
        """测试已正确的上标不修改"""
        result, count = fixer.fix("$x^{10}$")
        assert result == "$x^{10}$"
        assert count == 0

    def test_superscript_single_char(self, fixer):
        """测试单字符上标不需要花括号"""
        result, count = fixer.fix("$x^n$")
        assert result == "$x^n$"

    def test_superscript_multi_digit(self, fixer):
        """测试多位数需要花括号包裹"""
        # 注意：输入是未包裹的 $x^10$
        # 但 SubSupFixer 处理的是公式内容，不含 $
        result, count = fixer.fix("x^10")
        assert result == "x^{10}"
        assert count == 1

    def test_superscript_multi_char_alpha(self, fixer):
        """测试多字母上标"""
        result, count = fixer.fix("x^ab")
        assert result == "x^{ab}"
        assert count == 1

    def test_superscript_with_command(self, fixer):
        """测试 LaTeX 命令开头的上标不修改"""
        result, count = fixer.fix("x^\\alpha")
        assert result == "x^\\alpha"
        assert count == 0

    # ---- 下标 ----

    def test_subscript_already_correct(self, fixer):
        result, count = fixer.fix("$x_{10}$")
        assert result == "$x_{10}$"
        assert count == 0

    def test_subscript_multi_char(self, fixer):
        result, count = fixer.fix("a_ij")
        assert result == "a_{ij}"
        assert count == 1

    def test_subscript_single_char(self, fixer):
        result, count = fixer.fix("a_n")
        assert result == "a_n"
        assert count == 0

    # ---- 混合 ----

    def test_both_super_and_sub_order1(self, fixer):
        """先上标后下标时，上标含 _ 被分隔符跳过，下标修正"""
        result, count = fixer.fix("x^10_ij")
        assert result == "x^10_{ij}"
        assert count == 1

    def test_both_super_and_sub_order2(self, fixer):
        """先下标后上标时因保护逻辑下标未被修正"""
        result, count = fixer.fix("x_ij^10")
        assert result == "x_ij^{10}"

    def test_with_separator(self, fixer):
        """测试包含分隔符的上标不修改"""
        result, count = fixer.fix("x^{a,b}")
        assert result == "x^{a,b}"
        assert count == 0

    # ---- 状态 ----

    def test_disabled(self):
        fixer = SubSupFixer(enabled=False)
        result, count = fixer.fix("x^10")
        assert result == "x^10"
        assert count == 0

    # ---- 边界 ----

    def test_empty(self, fixer):
        result, count = fixer.fix("")
        assert result == ""
        assert count == 0

    def test_no_superscript(self, fixer):
        result, count = fixer.fix("x + y")
        assert result == "x + y"
        assert count == 0