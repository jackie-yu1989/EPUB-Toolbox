#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""图片处理器测试"""

import pytest
from pathlib import Path
from modules.md2epub.processor import ImageProcessor


class TestImageProcessor:

    @pytest.fixture
    def img_dir(self, temp_dir):
        d = temp_dir / "images"
        d.mkdir()
        return d

    def test_no_images(self, temp_dir, img_dir):
        """测试无图片的 Markdown"""
        content = "## 标题\n\n没有图片。\n"
        processor = ImageProcessor(temp_dir / "dummy.md", img_dir)
        result, count, files = processor.process_markdown_images(content)

        assert result == content
        assert count == 0
        assert files == []

    def test_skip_web_images(self, temp_dir, img_dir):
        """测试跳过网络图片"""
        content = "![web](https://example.com/img.png)"
        processor = ImageProcessor(temp_dir / "dummy.md", img_dir)
        result, count, files = processor.process_markdown_images(content)

        assert "https://" in result
        assert count == 0

    def test_local_image_not_found(self, temp_dir, img_dir):
        """测试本地图片不存在时删除引用"""
        content = "![missing](missing.png)"
        processor = ImageProcessor(temp_dir / "dummy.md", img_dir)
        result, count, files = processor.process_markdown_images(content)

        # 图片引用应被移除
        assert "missing.png" not in result
        assert "!" not in result

    def test_local_image_found(self, temp_dir, img_dir):
        """测试本地图片存在时复制"""
        # 创建测试图片
        img_path = temp_dir / "test.png"
        img_path.write_bytes(b"\x89PNG\r\n\x1a\n")

        content = f"![test]({img_path.name})"
        processor = ImageProcessor(temp_dir / "dummy.md", img_dir)
        result, count, files = processor.process_markdown_images(content)

        assert count == 1
        assert len(files) == 1
        assert "images/" in result