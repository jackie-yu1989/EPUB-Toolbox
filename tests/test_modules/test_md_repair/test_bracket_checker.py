#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""括号配对检查测试"""

import pytest
from modules.md_repair.processor import BracketChecker


class TestBracketChecker:

    @pytest.fixture
    def checker(self):
        return BracketChecker(enabled=True)

    # ---- \\left/\\right 配对 ----

    def test_missing_right(self, checker):
        """测试缺失 \\right 时自动补全"""
        result, logs = checker.check_and_fix("\\left( x")
        assert "\\right." in result
        assert len(logs) > 0

    def test_balanced_left_right(self, checker):
        """测试配对正确时不修改"""
        result, logs = checker.check_and_fix("\\left( x \\right)")
        assert result == "\\left( x \\right)"
        assert logs == []

    def test_multiple_left_right(self, checker):
        """测试多个 \\left \\right 配对"""
        result, logs = checker.check_and_fix(
            "\\left( x \\right) \\left[ y \\right]"
        )
        assert result == "\\left( x \\right) \\left[ y \\right]"

    def test_extra_right(self, checker):
        """测试多余的 \\right"""
        result, logs = checker.check_and_fix(
            "\\left( x \\right) \\right]"
        )
        assert len(logs) > 0
        assert "多余的" in logs[0]

    # ---- 花括号配对 ----

    def test_balanced_braces(self, checker):
        result, logs = checker.check_and_fix("{x + y}")
        assert result == "{x + y}"
        assert logs == []

    def test_extra_closing_brace(self, checker):
        result, logs = checker.check_and_fix("{x}}")
        assert len(logs) > 0
        assert "多余的右花括号" in logs[0]

    def test_unclosed_brace(self, checker):
        result, logs = checker.check_and_fix("{{x}")
        assert len(logs) > 0
        assert "未闭合" in logs[0]

    def test_escaped_braces(self, checker):
        """测试转义的花括号不影响配对"""
        result, logs = checker.check_and_fix("\\{x\\}")
        assert "未闭合" not in "".join(logs)
        assert "多余的" not in "".join(logs)

    # ---- 状态 ----

    def test_disabled(self):
        checker = BracketChecker(enabled=False)
        result, logs = checker.check_and_fix("\\left( x")
        assert result == "\\left( x"
        assert logs == []

    # ---- 边界 ----

    def test_empty(self, checker):
        result, logs = checker.check_and_fix("")
        assert result == ""
        assert logs == []

    def test_no_brackets(self, checker):
        result, logs = checker.check_and_fix("x + y = z")
        assert result == "x + y = z"
        assert logs == []