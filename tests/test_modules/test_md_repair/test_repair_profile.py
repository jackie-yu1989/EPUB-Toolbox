#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""预设方案匹配测试 — 验证 match_config 防止回归"""

import copy
import pytest
from modules.md_repair.processor import RepairProfile


class TestRepairProfileMatch:
    """预设方案匹配逻辑测试"""

    # ---- 辅助方法 ----

    def _build_config_from_profile(self, profile):
        """从 RepairProfile 构建标准 config 字典"""
        config = copy.deepcopy(profile.config)

        # 补齐顶层配置
        config['clean_extra_newlines'] = profile.config['clean_extra_newlines']
        config['add_space_after_inline'] = profile.config['add_space_after_inline']
        config['inline_to_display'] = profile.config['inline_to_display']
        config['image_caption_enabled'] = profile.config['image_caption_enabled']
        config['escape_isolated_dollars'] = profile.config['escape_isolated_dollars']
        config['fix_encoding'] = profile.config['fix_encoding']

        # 补齐 formula_config
        config['formula_config'] = {
            k: profile.config[k]
            for k in RepairProfile._FORMULA_CONFIG_KEYS
        }

        return config

    # ---- 自匹配测试 ----

    def test_safe_mode_self_match(self):
        """安全模式应能匹配自身"""
        profile = RepairProfile.get_builtin_profiles()[0]
        config = self._build_config_from_profile(profile)
        matched = RepairProfile.match_config(config)

        assert matched is not None, "安全模式未能匹配自身"
        assert matched.name == "🟢 安全模式"

    def test_standard_mode_self_match(self):
        """标准模式应能匹配自身"""
        profile = RepairProfile.get_builtin_profiles()[1]
        config = self._build_config_from_profile(profile)
        matched = RepairProfile.match_config(config)

        assert matched is not None, "标准模式未能匹配自身"
        assert matched.name == "🟡 标准模式"

    def test_zhihu_mode_self_match(self):
        """知乎发布模式应能匹配自身"""
        profile = RepairProfile.get_builtin_profiles()[2]
        config = self._build_config_from_profile(profile)
        matched = RepairProfile.match_config(config)

        assert matched is not None, "知乎发布模式未能匹配自身"
        assert matched.name == "🟣 知乎发布"

    def test_academic_mode_self_match(self):
        """学术论文模式应能匹配自身"""
        profile = RepairProfile.get_builtin_profiles()[3]
        config = self._build_config_from_profile(profile)
        matched = RepairProfile.match_config(config)

        assert matched is not None, "学术论文模式未能匹配自身"
        assert matched.name == "🔵 学术论文"

    def test_all_four_profiles_self_match(self):
        """一次性验证所有 4 个预设都能自匹配"""
        for profile in RepairProfile.get_builtin_profiles():
            config = self._build_config_from_profile(profile)
            matched = RepairProfile.match_config(config)

            assert matched is not None, (
                f"方案 '{profile.name}' 未能自匹配"
            )
            assert matched.name == profile.name, (
                f"方案名不匹配：期望 '{profile.name}'，实际 '{matched.name}'"
            )

    # ---- 不匹配测试 ----

    def test_custom_config_no_match(self):
        """自定义配置不应匹配任何方案"""
        config = {
            'clean_extra_newlines': False,  # 与所有预设都不同
            'add_space_after_inline': True,
            'inline_to_display': True,
            'image_caption_enabled': True,
            'escape_isolated_dollars': True,
            'fix_encoding': True,
            'formula_config': {},
        }
        matched = RepairProfile.match_config(config)
        assert matched is None

    def test_partial_match_fails(self):
        """部分匹配不应返回方案"""
        profile = RepairProfile.get_builtin_profiles()[0]
        config = self._build_config_from_profile(profile)

        # 修改一个字段
        config['formula_config']['subsup_fix'] = (
            not profile.config['subsup_fix']
        )

        matched = RepairProfile.match_config(config)
        assert matched is None

    # ---- 边界测试 ----

    def test_empty_config_no_match(self):
        """空配置不应匹配"""
        matched = RepairProfile.match_config({})
        assert matched is None

    def test_config_without_formula_config(self):
        """缺少 formula_config 的配置"""
        config = {
            'clean_extra_newlines': True,
            'add_space_after_inline': True,
            'inline_to_display': False,
            'image_caption_enabled': False,
            'escape_isolated_dollars': True,
            'fix_encoding': True,
        }
        matched = RepairProfile.match_config(config)
        assert matched is None  # 缺少 formula_config，无法匹配