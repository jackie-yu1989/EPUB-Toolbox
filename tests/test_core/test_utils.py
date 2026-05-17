#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
核心工具函数测试
"""

import pytest
from modules.md2epub.processor import (
    escape, extract_frontmatter
)
from core.utils import format_file_size


class TestEscape:
    """HTML/XML 转义函数测试"""

    def test_html_basic(self):
        """测试基本 HTML 转义"""
        assert escape("<div>") == "&lt;div&gt;"
        assert escape('a "quote"') == "a &quot;quote&quot;"
        assert escape("a & b") == "a &amp; b"

    def test_html_apostrophe(self):
        """测试 HTML 模式下的单引号转义"""
        result = escape("it's", xml=False)
        assert result == "it&#39;s"

    def test_xml_apostrophe(self):
        """测试 XML 模式下的单引号转义"""
        result = escape("it's", xml=True)
        assert result == "it&apos;s"

    def test_multiple_special_chars(self):
        """测试多个特殊字符同时转义"""
        result = escape('<a href="x">a & b</a>')
        expected = "&lt;a href=&quot;x&quot;&gt;a &amp; b&lt;/a&gt;"
        assert result == expected

    def test_no_special_chars(self):
        """测试无特殊字符时原样返回"""
        assert escape("hello world") == "hello world"

    def test_empty_string(self):
        """测试空字符串"""
        assert escape("") == ""


class TestExtractFrontmatter:
    """YAML Frontmatter 提取测试"""

    def test_basic_yaml(self):
        """测试基本 YAML 分隔符 ---"""
        content = "---\ntitle: Hello\n---\n\n正文内容"
        meta, body = extract_frontmatter(content)
        assert meta == {"title": "Hello"}
        assert body == "\n正文内容"

    def test_plus_yaml(self):
        """测试 +++ YAML 分隔符"""
        content = "+++\ntitle: Test\n+++\n\n正文"
        meta, body = extract_frontmatter(content)
        assert meta == {"title": "Test"}

    def test_multiple_fields(self):
        """测试多个字段"""
        content = "---\ntitle: 文章\nauthor: 张三\ndate: 2026-01-01\n---\n正文"
        meta, body = extract_frontmatter(content)
        assert meta["title"] == "文章"
        assert meta["author"] == "张三"
        assert meta["date"] == "2026-01-01"

    def test_quoted_values(self):
        """测试引号包裹的值"""
        content = '---\ntitle: "Hello World"\n---\n正文'
        meta, _ = extract_frontmatter(content)
        assert meta["title"] == "Hello World"

    def test_single_quoted_values(self):
        """测试单引号包裹的值"""
        content = "---\ntitle: 'Hello'\n---\n正文"
        meta, _ = extract_frontmatter(content)
        assert meta["title"] == "Hello"

    def test_no_frontmatter(self):
        """测试无 Frontmatter 的文档"""
        content = "直接正文内容"
        meta, body = extract_frontmatter(content)
        assert meta == {}
        assert body == "直接正文内容"

    def test_empty_content(self):
        """测试空内容"""
        meta, body = extract_frontmatter("")
        assert meta == {}
        assert body == ""

    def test_malformed_frontmatter(self):
        """测试不完整的 Frontmatter"""
        content = "---\ntitle: Bad\n正文"
        meta, body = extract_frontmatter(content)
        assert body == content


class TestFormatFileSize:
    """文件大小格式化测试"""

    def test_bytes(self):
        assert format_file_size(0) == "0.0 B"
        assert format_file_size(500) == "500.0 B"

    def test_kilobytes(self):
        assert format_file_size(1024) == "1.0 KB"
        assert format_file_size(1536) == "1.5 KB"

    def test_megabytes(self):
        assert format_file_size(1048576) == "1.0 MB"

    def test_gigabytes(self):
        assert format_file_size(1073741824) == "1.0 GB"

    def test_negative(self):
        assert format_file_size(-1) == "0 B"