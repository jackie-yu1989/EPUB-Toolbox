#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""函数名正体化测试"""

import pytest
from modules.md_repair.processor import FunctionNameNormalizer


class TestFunctionNormalizer:

    @pytest.fixture
    def norm(self):
        return FunctionNameNormalizer(enabled=True)

    # ---- 基本函数名 ----

    def test_sin(self, norm):
        result, count = norm.normalize("$sin(x)$")
        assert result == "$\\sin(x)$"
        assert count == 1

    def test_cos(self, norm):
        result, count = norm.normalize("$cos(x)$")
        assert result == "$\\cos(x)$"

    def test_tan(self, norm):
        result, count = norm.normalize("$tan(x)$")
        assert result == "$\\tan(x)$"

    def test_log(self, norm):
        result, count = norm.normalize("$log(x)$")
        assert result == "$\\log(x)$"

    def test_ln(self, norm):
        result, count = norm.normalize("$ln(x)$")
        assert result == "$\\ln(x)$"

    def test_exp(self, norm):
        result, count = norm.normalize("$exp(x)$")
        assert result == "$\\exp(x)$"

    def test_lim(self, norm):
        result, count = norm.normalize("$lim x$")
        assert "\\lim" in result

    def test_max_min(self, norm):
        result, count = norm.normalize("$max(x, y)$")
        assert "\\max" in result

    # ---- 多个函数 ----

    def test_multiple_functions(self, norm):
        result, count = norm.normalize("$sin(x) + cos(y) + log(z)$")
        assert "\\sin" in result
        assert "\\cos" in result
        assert "\\log" in result
        assert count >= 3

    # ---- 已正确的不重复处理 ----

    def test_already_normalized(self, norm):
        """测试已正体化的不被重复处理"""
        result, count = norm.normalize("$\\sin(x)$")
        assert result == "$\\sin(x)$"
        assert count == 0

    def test_multiple_already_normalized(self, norm):
        result, count = norm.normalize("$\\sin(x) + \\cos(x)$")
        assert result == "$\\sin(x) + \\cos(x)$"
        assert count == 0

    # ---- 非公式文本 ----

    def test_function_in_text(self, norm):
        """测试普通文本中的函数名同样被正体化（当前实现行为）"""
        result, count = norm.normalize("sin is a function")
        assert result == "\\sin is a function"
        assert count == 1

    # ---- 状态 ----

    def test_disabled(self):
        norm = FunctionNameNormalizer(enabled=False)
        result, count = norm.normalize("$sin(x)$")
        assert result == "$sin(x)$"
        assert count == 0

    # ---- 全部标准函数 ----

    def test_all_standard_functions(self, norm):
        """测试所有 46 个标准函数名都能被识别"""
        failures = []
        for func in FunctionNameNormalizer.STANDARD_FUNCTIONS:
            result, count = norm.normalize(f"${func}(x)$")
            if f"\\{func}" not in result:
                failures.append(func)

        assert len(failures) == 0, (
            f"以下函数未被正体化: {', '.join(failures)}"
        )

    # ---- 边界情况 ----

    def test_empty_formula(self, norm):
        result, count = norm.normalize("")
        assert result == ""
        assert count == 0

    def test_no_function_names(self, norm):
        result, count = norm.normalize("$x + y = z$")
        assert result == "$x + y = z$"
        assert count == 0

    def test_function_as_subscript(self, norm):
        """测试函数名作为下标时的处理"""
        result, count = norm.normalize("$x_{max}$")
        # max 在下标中，应该被正体化
        assert "\\max" in result