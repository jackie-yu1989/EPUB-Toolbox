#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
测试共享夹具和工具函数
"""

import sys
import tempfile
from pathlib import Path
import pytest


# 添加项目根目录到 Python 路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def temp_dir():
    """创建临时目录，测试结束后自动清理"""
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def sample_md_file(temp_dir):
    """创建示例 Markdown 文件"""
    content = """---
title: 测试文档
author: 张三
date: 2026-01-01
---

# 第一章

这是一个段落，包含公式 $x^2 + y^2 = z^2$。

## 第一节

矩阵公式：
$$
\\begin{pmatrix}
a & b \\\\
c & d
\\end{pmatrix}
$$

代码块：
​```python
print("hello")
```
"""
    file_path = temp_dir / "test.md"
    file_path.write_text(content, encoding='utf-8')
    return file_path


@pytest.fixture
def sample_md_with_yaml(temp_dir):
    """创建包含 YAML Frontmatter 的示例文件"""
    content = """---
title: 我的文章
author: 李四
subtitle: 副标题
date: 2026-05-01
tags: [python, latex]
---

正文内容
"""
    file_path = temp_dir / "with_yaml.md"
    file_path.write_text(content, encoding='utf-8')
    return file_path


@pytest.fixture
def sample_md_no_frontmatter(temp_dir):
    """创建无 Frontmatter 的示例文件"""
    content = """# 直接正文

没有 YAML 头部信息。
"""
    file_path = temp_dir / "no_yaml.md"
    file_path.write_text(content, encoding='utf-8')
    return file_path


# ==================== MD 修复配置 ====================

@pytest.fixture
def safe_config():
    """安全模式配置（所有低风险功能开启）"""
    from modules.md_repair.processor import ConfigurableFormulaFixer
    return {
        'clean_extra_newlines': True,
        'add_space_after_inline': True,
        'inline_to_display': False,
        'image_caption_enabled': False,
        'image_caption_color': 'purple',
        'escape_isolated_dollars': True,
        'fix_encoding': True,
        'formula_config': ConfigurableFormulaFixer.get_default_config(),
    }


@pytest.fixture
def full_config():
    """全功能开启配置"""
    from modules.md_repair.processor import ConfigurableFormulaFixer
    return {
        'clean_extra_newlines': True,
        'add_space_after_inline': True,
        'inline_to_display': True,
        'image_caption_enabled': True,
        'image_caption_color': 'blue',
        'escape_isolated_dollars': True,
        'fix_encoding': True,
        'formula_config': {
            'bm_to_vec': True,
            'remove_size_commands': True,
            'matrix_newline_remove': True,
            'matrix_add_multiplication': True,
            'dl_commands_to_text': True,
            'dl_commands_list': ConfigurableFormulaFixer.DEFAULT_DL_COMMANDS,
            'markdown_escape_inline': True,
            'func_normalize': True,
            'subsup_fix': True,
            'bracket_check': True,
            'respect_macros': True,
            'escape_mode': 'standard',
            'bm_strict_mode': True,
        },
    }