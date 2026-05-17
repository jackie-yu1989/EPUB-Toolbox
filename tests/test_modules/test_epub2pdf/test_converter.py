#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""EPUB 转 PDF 核心函数测试"""

import pytest
from modules.epub2pdf.processor import PRESETS


class TestPresets:
    """页边距预设配置测试"""

    def test_all_presets_exist(self):
        """测试 4 个预设都存在"""
        for key in ["1", "2", "3", "4"]:
            assert key in PRESETS, f"缺少预设 key={key}"

    def test_preset_has_required_fields(self):
        """测试每个预设包含必要字段"""
        required = ["name", "top", "bottom", "left", "right", "font_size"]
        for key, preset in PRESETS.items():
            for field in required:
                assert field in preset, (
                    f"预设 {preset.get('name', key)} 缺少字段 {field}"
                )

    def test_margins_non_negative(self):
        """测试边距值不为负数"""
        for key, preset in PRESETS.items():
            for field in ["top", "bottom", "left", "right"]:
                assert preset[field] >= 0, (
                    f"预设 {preset['name']} 的 {field} 为负数"
                )

    def test_font_size_reasonable(self):
        """测试字号在合理范围内"""
        for key, preset in PRESETS.items():
            assert 8 <= preset["font_size"] <= 72, (
                f"预设 {preset['name']} 的字号不合理: {preset['font_size']}"
            )

    def test_preset_names_unique(self):
        """测试预设名称唯一"""
        names = [p["name"] for p in PRESETS.values()]
        assert len(names) == len(set(names)), "预设名称重复"