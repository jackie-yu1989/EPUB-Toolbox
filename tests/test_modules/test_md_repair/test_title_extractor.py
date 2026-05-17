#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""标题提取器测试"""

import pytest
from modules.md_repair.processor import MarkdownTitleExtractor


class TestTitleExtractor:

    @pytest.fixture
    def extractor(self):
        return MarkdownTitleExtractor()

    # ---- 标题提取 ----

    def test_extract_title(self, extractor, sample_md_with_yaml):
        """测试从 YAML 提取标题"""
        title = extractor.extract_title(sample_md_with_yaml)
        assert title == "我的文章"

    def test_extract_custom_field(self, extractor, temp_dir):
        """测试自定义字段名"""
        content = "---\n标题: 自定义\n---\n正文"
        file_path = temp_dir / "custom_field.md"
        file_path.write_text(content, encoding='utf-8')

        title = extractor.extract_title(file_path, fields=['标题'])
        assert title == "自定义"

    def test_extract_no_match(self, extractor, sample_md_no_frontmatter):
        """测试无 Frontmatter 时返回 None"""
        title = extractor.extract_title(sample_md_no_frontmatter)
        assert title is None

    # ---- 文件名安全化 ----

    def test_sanitize_basic(self, extractor):
        """测试空格替换为下划线"""
        result = extractor.sanitize("Hello World")
        assert result == "Hello_World"

    def test_sanitize_illegal_chars(self, extractor):
        """测试非法字符被替换"""
        result = extractor.sanitize("hello:world?")
        assert ":" not in result
        assert "?" not in result

    def test_sanitize_windows_illegal(self, extractor):
        """测试 Windows 非法文件名字符"""
        result = extractor.sanitize("test<file>.md")
        assert "<" not in result
        assert ">" not in result

    def test_sanitize_too_long(self, extractor):
        """测试超长标题截断"""
        long_title = "a" * 150
        result = extractor.sanitize(long_title, max_length=100)
        assert len(result) <= 100

    def test_sanitize_empty(self, extractor):
        """测试空标题返回 untitled"""
        result = extractor.sanitize("")
        assert result == "untitled"

    def test_sanitize_result_not_empty(self, extractor):
        """测试纯非法字符也返回有效名称"""
        result = extractor.sanitize("???")
        assert result == "untitled"

    # ---- 唯一文件名 ----

    def test_get_unique_name_no_conflict(self, extractor, temp_dir):
        """测试无冲突时返回原名"""
        name = extractor.get_unique_name(temp_dir, "new_file")
        assert name == "new_file.md"

    def test_get_unique_name_with_conflict(self, extractor, temp_dir):
        """测试有冲突时添加序号"""
        (temp_dir / "exist.md").touch()
        name = extractor.get_unique_name(temp_dir, "exist")
        assert name == "exist_1.md"

    # ---- 综合 ----

    def test_generate_name_with_title(self, extractor, sample_md_with_yaml):
        """测试从文件生成带标题的名称"""
        name, used, title = extractor.generate_name(
            sample_md_with_yaml, sample_md_with_yaml.parent
        )
        assert used is True
        assert title == "我的文章"
        assert "untitled" not in name
        assert name.endswith(".md")

    def test_generate_name_without_title(self, extractor, sample_md_no_frontmatter):
        """测试无标题时使用文件名"""
        name, used, title = extractor.generate_name(
            sample_md_no_frontmatter,
            sample_md_no_frontmatter.parent
        )
        assert used is False
        assert title is None
        assert "_fixed.md" in name