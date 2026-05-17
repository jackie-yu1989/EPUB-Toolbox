#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MD公式修复 - 核心处理逻辑（增强版 v4.3.4）
集成自独立版 md_formula_fixer.py

包含：
- 枚举和数据类（RiskLevel, FormulaChange, RepairProfile）
- 辅助系统（MacroScanner, FormulaContext, FeatureHelpDatabase）
- 原子修复器（11个独立修复器）
- 公式修复引擎（ConfigurableFormulaFixer, FormulaPreviewer）
- 文档处理器（MarkdownFormulaProcessor）
- 标题提取器（MarkdownTitleExtractor）
"""

import os
import re
import time
import uuid
import difflib
import traceback
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Optional, Dict, Any, Set, Pattern
from enum import Enum
from dataclasses import dataclass, field
from functools import lru_cache
from core.config_keys import MDRepairKey

# 模块级日志记录器
logger = logging.getLogger(__name__)


# ==================== 模块级预编译正则 ====================

# FormulaContext 使用
_RE_SUM_PROD = re.compile(r'\\(sum|prod|bigcup|bigcap|bigoplus|bigotimes)')
_RE_INTEGRAL = re.compile(r'\\(int|iint|iiint|oint)')

# MarkdownEscaper 使用
_RE_LATEX_COMMAND = re.compile(r'\\(?:[a-zA-Z]+|.)')

# SubSupFixer 使用
_RE_SUPERSCRIPT = re.compile(r'(\S)\^([^\s{]+)')
_RE_SUBSCRIPT = re.compile(r'(\S)_([^\s{]+)')
_RE_BRACKET_PROTECT = re.compile(r'\{[^{}]*\}')
_RE_SEPARATORS = re.compile(r'[,;:=<>+\-*/\\\(\)\[\]|&!\^\{\}]')
_RE_ALPHANUM = re.compile(r'^[a-zA-Z0-9]+$')

# BracketChecker 使用
_RE_LEFT_BRACKETS = [
    re.compile(r'\\left\('), re.compile(r'\\left\['), re.compile(r'\\left\\\{'),
    re.compile(r'\\left\.'), re.compile(r'\\left\|')
]
_RE_RIGHT_BRACKETS = [
    re.compile(r'\\right\)'), re.compile(r'\\right\]'), re.compile(r'\\right\\\}'),
    re.compile(r'\\right\.'), re.compile(r'\\right\|')
]

# FormulaPreviewer 使用
_RE_DISPLAY_FORMULA = re.compile(r'\$\$(.*?)\$\$', re.DOTALL)
_RE_INLINE_FORMULA = re.compile(r'(?<!\$)\$(?!\$)(.*?)(?<!\$)\$(?!\$)', re.DOTALL)

# MarkdownFormulaProcessor 使用
_RE_FENCE_POSITION = re.compile(r'(?:^|\n)```')
_RE_INLINE_CODE = re.compile(r'`([^`\n]+)`')
_RE_PROTECTED_PLACEHOLDER = re.compile(r'^__PROTECTED_\d+__$')
_RE_EXTRA_NEWLINES = re.compile(r'\n{3,}')

# DollarSignEscaper 使用
_RE_TABLE_ROW = re.compile(r'^\|.+\|$', re.MULTILINE)
_RE_DISPLAY_SAVE = re.compile(r'\$\$.*?\$\$', re.DOTALL)
_RE_INLINE_SAVE = re.compile(r'\$[^$\n]+?\$')
_RE_CODE_BLOCK_SAVE = re.compile(r'```.*?```', re.DOTALL)
_RE_INLINE_CODE_SAVE = re.compile(r'`[^`\n]+`')
_RE_IS_FORMULA_CONTENT = re.compile(r'^\d+(\.\d+)?$')

# MarkdownTitleExtractor 使用
_RE_YAML_BOUNDARY = re.compile(r'^[-+]{3}\s*\n(.*?)\n[-+]{3}\s*\n', re.DOTALL)
_RE_ILLEGAL_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# ConfigurableFormulaFixer 使用
_RE_BM_BRACE = re.compile(r'\\bm\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}')
_RE_BM_BRACE_SIMPLE = re.compile(r'\\bm\{([^}]*?)\}', re.DOTALL)
_RE_BM_SPACE = re.compile(r'\\bm\s+([a-zA-Z])')
_RE_BM_NO_SPACE = re.compile(r'\\bm([a-zA-Z])')

# 矩阵相关
_MATRIX_ENVS = ['matrix', 'pmatrix', 'bmatrix', 'Bmatrix',
                'vmatrix', 'Vmatrix', 'smallmatrix']
_MATRIX_ENV_PATTERN = '|'.join(_MATRIX_ENVS)
_RE_MATRIX_BEGIN = re.compile(r'\\begin\{(?:' + _MATRIX_ENV_PATTERN + r')\}')
_RE_MATRIX_END = re.compile(r'\\end\{(?:' + _MATRIX_ENV_PATTERN + r')\}')

# 深度学习命令
_MATH_INDICATORS = frozenset([
    '\\', '^', '_', '{', '}', '+', '-', '*', '/', '=',
    '\\sin', '\\cos', '\\log', '\\frac', '\\sum', '\\int',
    '\\alpha', '\\beta',
])

# 尺寸命令
_SIZE_COMMANDS = ['\\large', '\\Large', '\\small', '\\footnotesize', '\\tiny']


# ==================== 枚举和数据类 ====================

class RiskLevel(Enum):
    """风险等级枚举"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def icon(self) -> str:
        return {"low": "🟢", "medium": "🟡", "high": "🔴"}[self.value]

    @property
    def color(self) -> str:
        return {"low": "#27ae60", "medium": "#e67e22", "high": "#e74c3c"}[self.value]

    @property
    def description(self) -> str:
        return {
            "low": "低风险，推荐始终开启",
            "medium": "中等风险，建议按需开启",
            "high": "高风险，可能改变原意"
        }[self.value]


@dataclass
class FormulaChange:
    """公式变更记录"""
    original: str
    fixed: str
    changes: List[str]
    risk_level: str
    formula_type: str

@dataclass
class RepairProfile:
    """修复配置方案"""
    name: str
    description: str
    config: Dict[str, Any]

    # ★ 比较配置的关键字段列表
    _TOP_LEVEL_KEYS = MDRepairKey.TOP_LEVEL_KEYS
    
    _FORMULA_CONFIG_KEYS = MDRepairKey.FORMULA_CONFIG_KEYS

    @classmethod
    def get_builtin_profiles(cls) -> List['RepairProfile']:
        """获取内置预设方案"""
        return [
            cls(
                name="🟢 安全模式",
                description="仅低风险修复：格式化、语法修正。适合重要文档",
                config={
                    'clean_extra_newlines': True,
                    'add_space_after_inline': True,
                    'subsup_fix': True,
                    'func_normalize': True,
                    'matrix_newline_remove': True,
                    'bracket_check': True,
                    'markdown_escape_inline': False, # markdown符号转义，不开启
                    'matrix_add_multiplication': False,
                    'dl_commands_to_text': False,
                    'remove_size_commands': False,
                    'bm_to_vec': False,
                    'inline_to_display': False,
                    'image_caption_enabled': False,
                    'respect_macros': True,
                    'escape_mode': 'off',
                    'fix_encoding': True,
                    'escape_isolated_dollars': True,
                    'bm_strict_mode': True,
                }
            ),
            cls(
                name="🟡 标准模式",
                description="平衡安全与效果，适合日常使用",
                config={
                    'clean_extra_newlines': True,
                    'add_space_after_inline': True,
                    'subsup_fix': True,
                    'func_normalize': False,
                    'matrix_newline_remove': True,
                    'bracket_check': False,
                    'markdown_escape_inline': False, # markdown符号转义，不开启
                    'matrix_add_multiplication': True,
                    'dl_commands_to_text': True,
                    'remove_size_commands': True,
                    'bm_to_vec': True,
                    'inline_to_display': True,
                    'image_caption_enabled': True,
                    'respect_macros': True,
                    'escape_mode': 'standard',
                    'fix_encoding': False,
                    'escape_isolated_dollars': True,
                    'bm_strict_mode': True,
                }
            ),
            cls(
                name="🟣 知乎发布",
                description="针对知乎平台优化：增强转义、添加间距",
                config={
                    'clean_extra_newlines': True,
                    'add_space_after_inline': True,
                    'subsup_fix': True,
                    'func_normalize': True,
                    'matrix_newline_remove': True,
                    'bracket_check': True,
                    'markdown_escape_inline': False, # markdown符号转义，不开启
                    'matrix_add_multiplication': True,
                    'dl_commands_to_text': True,
                    'remove_size_commands': True,
                    'bm_to_vec': False,
                    'inline_to_display': False,
                    'image_caption_enabled': False,
                    'respect_macros': True,
                    'escape_mode': 'zhihu',
                    'fix_encoding': True,
                    'escape_isolated_dollars': True,
                    'bm_strict_mode': True,
                }
            ),
            cls(
                name="🔵 学术论文",
                description="仅语法修正，保留所有数学语义",
                config={
                    'clean_extra_newlines': True,
                    'add_space_after_inline': False,
                    'subsup_fix': True,
                    'func_normalize': True,
                    'matrix_newline_remove': True,
                    'bracket_check': True,
                    'markdown_escape_inline': False, # markdown符号转义，不开启
                    'matrix_add_multiplication': False,
                    'dl_commands_to_text': False,
                    'remove_size_commands': False,
                    'bm_to_vec': False,
                    'inline_to_display': False,
                    'image_caption_enabled': False,
                    'respect_macros': True,
                    'escape_mode': 'off',
                    'fix_encoding': True,
                    'escape_isolated_dollars': False,
                    'bm_strict_mode': True,
                }
            ),
        ]

    # ★ 新增：配置匹配方法
    @classmethod
    def match_config(cls, config: Dict[str, Any]) -> Optional['RepairProfile']:
        """将给定配置与内置预设方案匹配
        
        遍历所有内置方案，比较 5 个顶层配置项 + 13 个公式配置项。
        
        Args:
            config: 完整的修复配置字典（含 top-level 和 formula_config 嵌套）
            
        Returns:
            匹配到的 RepairProfile，无匹配返回 None
            
        Example:
            matched = RepairProfile.match_config(my_config)
            if matched:
                print(f"当前配置匹配: {matched.name}")
        """
        profiles = cls.get_builtin_profiles()
        
        for profile in profiles:
            pc = profile.config
            
            # 比较顶层配置
            top_match = all(
                config.get(k) == pc.get(k)
                for k in cls._TOP_LEVEL_KEYS
            )
            if not top_match:
                continue
            
            # 比较公式配置
            fc = config.get('formula_config', {})
            formula_match = all(
                fc.get(k) == pc.get(k)
                for k in cls._FORMULA_CONFIG_KEYS
            )
            if formula_match:
                return profile
        
        return None


# ==================== 功能说明数据库 ====================

class FeatureHelpDatabase:
    """功能说明数据库（缓存结果）"""
    
    _cached_features: Optional[Dict[str, Dict[str, Any]]] = None

    @classmethod
    def get_all_features(cls) -> Dict[str, Dict[str, Any]]:
        """获取所有功能的详细说明（带缓存）"""
        if cls._cached_features is not None:
            return cls._cached_features
        
        cls._cached_features = {
            'clean_newlines': {
                'name': '多余换行清理', 'icon': '🧹', 'risk': 'low',
                'category': '格式与语法修复',
                'trigger': '文档中出现3个以上连续空行',
                'action': '将3个以上连续空行简化为2个空行',
                'example_before': '段落一\n\n\n\n段落二',
                'example_after': '段落一\n\n段落二',
                'why': 'Markdown中两个空行即可表示段落分隔，多余空行会让文档显得松散。',
                'problem': '几乎无风险。仅在作者故意使用多个空行表示特殊排版时有轻微影响。',
                'recommendation': '✅ 推荐始终开启',
            },
            'add_space_after_inline': {
                'name': '行内公式后添加空格', 'icon': '📏', 'risk': 'low',
                'category': '格式与语法修复',
                'trigger': '行内公式 $...$ 后紧跟中文字符',
                'action': '在公式结尾的 $ 与中文字符之间添加一个空格',
                'example_before': '$x+y$是方程的解',
                'example_after': '$x+y$ 是方程的解',
                'why': '知乎等平台的渲染器在公式后紧跟中文时可能解析失败。',
                'problem': '几乎无风险。仅在极少数情况下轻微改变排版。',
                'recommendation': '✅ 发布到知乎等内容平台时推荐开启',
            },
            'subsup_fix': {
                'name': '上下标范围修正', 'icon': '↗️', 'risk': 'low',
                'category': '格式与语法修复',
                'trigger': '公式中的上下标后跟多个字符但未用花括号包裹',
                'action': '自动添加花括号',
                'example_before': '$x^10$ → 显示为 x¹0',
                'example_after': '$x^{10}$ → 正确显示为 x¹⁰',
                'why': 'LaTeX规定上下标只作用于其后一个字符。',
                'problem': '极少数情况作者可能故意写x^2y表示x²乘以y。',
                'recommendation': '✅ 强烈推荐始终开启',
            },
            'func_normalize': {
                'name': '函数名正体化', 'icon': '📝', 'risk': 'low',
                'category': '格式与语法修复',
                'trigger': '公式中出现应使用正体的数学函数名',
                'action': '自动添加 \\ 前缀',
                'example_before': '$sin(x) + log(y)$',
                'example_after': '$\\sin(x) + \\log(y)$',
                'why': '数学排版规范要求函数名使用正体。',
                'problem': '正常使用场景风险极低。',
                'recommendation': '✅ 推荐开启，符合学术排版标准',
            },
            'matrix_newline_remove': {
                'name': '矩阵末尾换行移除', 'icon': '🧮', 'risk': 'low',
                'category': '格式与语法修复',
                'trigger': '矩阵环境最后一行后有多余的 \\\\',
                'action': '移除末尾多余的换行符',
                'example_before': '\\begin{pmatrix}\na & b \\\\\nc & d \\\\\n\\end{pmatrix}',
                'example_after': '\\begin{pmatrix}\na & b \\\\\nc & d\n\\end{pmatrix}',
                'why': '矩阵最后一行后面不应该有换行符。',
                'problem': '几乎无风险。',
                'recommendation': '✅ 推荐开启',
            },
            'bracket_check': {
                'name': '括号配对检查', 'icon': '🔍', 'risk': 'low',
                'category': '格式与语法修复',
                'trigger': '公式中存在 \\left 和 \\right 命令',
                'action': '检测括号配对，自动补全缺失的 \\right.',
                'example_before': '\\left( \\frac{1}{2}',
                'example_after': '\\left( \\frac{1}{2} \\right.',
                'why': '\\left和\\right必须成对出现。',
                'problem': '自动补全位置可能不是预期位置。',
                'recommendation': '✅ 推荐开启',
            },
            'markdown_escape_inline': {
                'name': 'Markdown符号转义', 'icon': '🛡️', 'risk': 'medium',
                'category': '语义增强',
                'trigger': '行内公式中存在 _ 或 * 等Markdown语法符号',
                'action': '添加反斜杠转义',
                'example_before': '$x_i$（可能被识别为斜体）',
                'example_after': '$x\\_i$ 或 $x_{i}$',
                'why': 'Markdown解析器会抢夺公式里的特殊符号。',
                'problem': '在已正确使用花括号的公式中转义是多余的。',
                'recommendation': '⚠️ 在知乎等内容平台发布时推荐开启',
            },
            'matrix_add_multiplication': {
                'name': '矩阵间自动添加乘号', 'icon': '✖️', 'risk': 'medium',
                'category': '语义增强',
                'trigger': '两个矩阵环境之间直接相邻',
                'action': '插入 \\times 符号',
                'example_before': '\\end{pmatrix}\\begin{pmatrix}',
                'example_after': '\\end{pmatrix} \\times \\begin{pmatrix}',
                'why': '两个矩阵相邻通常表示矩阵乘法。',
                'problem': '如果作者故意表示拼接或其他非乘法操作，会误加乘号。',
                'recommendation': '⚠️ 建议预览确认后再应用',
            },
            'dl_commands_to_text': {
                'name': '深度学习命令转文本', 'icon': '🤖', 'risk': 'medium',
                'category': '安全保护',
                'trigger': '公式中包含自定义命令（如\\ReLU、\\Softmax等）',
                'action': '转换为\\text{命令名}形式',
                'example_before': '$\\ReLU(x)$',
                'example_after': '$\\text{ReLU}(x)$',
                'why': '这些命令不是标准LaTeX命令。',
                'problem': '如果作者已定义这些命令，转换后会失效。建议配合「智能识别用户自定义命令」使用。',
                'recommendation': '⚠️ 建议开启。如果文档中使用了 \\newcommand 等自定义命令，强烈建议同时开启「智能识别用户自定义命令」。',
            },
            'remove_size_commands': {
                'name': '移除尺寸命令', 'icon': '📐', 'risk': 'medium',
                'category': '语义增强',
                'trigger': '公式中存在\\large、\\Large、\\small等',
                'action': '移除字号命令',
                'example_before': '$\\large (x + y)$',
                'example_after': '$(x + y)$',
                'why': '通常来自复制粘贴时的残留。',
                'problem': '如果作者故意使用会被误移除。',
                'recommendation': '⚠️ 建议预览确认后再应用',
            },
            'bm_to_vec': {
                'name': '\\bm → \\vec 转换', 'icon': '🔄', 'risk': 'high',
                'category': '高级转换',
                'trigger': '公式中包含\\bm{...}命令',
                'action': '智能判断后转换为\\vec{...}（矩阵环境中的\\bm不会被转换）',
                'example_before': '$\\bm{x}$（非矩阵环境）',
                'example_after': '$\\vec{x}$',
                'why': '部分文档用\\bm表示向量。',
                'problem': '🔴 <b>高风险！</b>\\bm表示粗体，\\vec表示向量箭头，语义不同。开启严格模式后仅在非矩阵环境且上下文为向量运算时转换。',
                'recommendation': '🔴 <b>非必要不开启</b>。开启后建议使用严格模式',
            },
            'inline_to_display': {
                'name': '独立行内公式转块级', 'icon': '📦', 'risk': 'high',
                'category': '高级转换',
                'trigger': '行内公式$...$单独占一行',
                'action': '转换为块级$$...$$',
                'example_before': '文字\n\n$E = mc^2$\n\n继续',
                'example_after': '文字\n\n$$E = mc^2$$\n\n继续',
                'why': '单独成行的公式通常应该块级显示。',
                'problem': '🔴 <b>高风险！</b>可能改变段落结构和排版意图。',
                'recommendation': '🔴 <b>非必要不开启</b>',
            },
            'image_caption': {
                'name': '图片标题样式化', 'icon': '🖼️', 'risk': 'high',
                'category': '用户定制',
                'trigger': '图片Markdown语法下方的*斜体文字*',
                'action': '转换为居中HTML样式标题',
                'example_before': '![图片](image.png)\n\n*这是标题*',
                'example_after': '![图片](image.png)\n<p style="...">这是标题</p>',
                'why': '纯Markdown的图片标题样式有限，使用HTML可以实现更丰富的样式效果。',
                'problem': '🔴 <b>高风险！</b>将纯Markdown替换为HTML，<b>不可逆</b>。HTML可能不被所有平台支持。',
                'recommendation': '🔴 <b>默认关闭，谨慎使用</b>。仅适合发布到支持HTML的平台。',
            },
            'respect_macros': {
                'name': '智能识别用户自定义命令', 'icon': '🧠', 'risk': 'low',
                'category': '安全保护',
                'trigger': '处理开始前自动扫描文档',
                'action': '扫描文档中的 \\newcommand、\\renewcommand、\\def 等定义。如果发现用户已定义了某个命令，后续处理中跳过该命令，保留原样。',
                'example_before': '用户定义 \\newcommand{\\ReLU}{...} 后，工具准备将 \\ReLU 转为 \\text{ReLU}',
                'example_after': '检测到用户已定义 \\ReLU，跳过转换，保留用户原有定义',
                'why': '避免覆盖用户的自定义宏定义。',
                'problem': '扫描范围有限（仅扫描文件前 64KB），如果宏定义在文档很后面的位置可能扫描不到。',
                'recommendation': '✅ 推荐始终开启。',
            },
            'fix_encoding': {
                'name': '编码问题修复', 'icon': '🔤', 'risk': 'low',
                'category': '格式与语法修复',
                'trigger': '公式中存在 \\x0a、\\x0d 等编码转义序列',
                'action': '修复编码问题，如将 \\x0a 转义为正确的形式',
                'example_before': '公式中出现 \\x0a 导致渲染异常',
                'example_after': '修复为 \\\\x0a 避免被误解析',
                'why': '某些编辑器或复制粘贴过程会产生编码问题，导致LaTeX渲染失败。',
                'problem': '正常使用场景风险极低。',
                'recommendation': '✅ 推荐始终开启',
            },
            'escape_isolated_dollars': {
                'name': '非公式美元符号转义', 'icon': '💲', 'risk': 'low',
                'category': '安全保护',
                'trigger': '文本中出现非公式内容的 $ 符号（如价格 $100）',
                'action': '检测并转义非公式内容的孤立 $ 符号',
                'example_before': '价格是 $100，不是公式',
                'example_after': '价格是 \\$100，不是公式',
                'why': '不必要的 $ 符号可能被Markdown解析器识别为公式边界，导致格式错乱。',
                'problem': '极少数情况下可能误转义合法的公式符号。',
                'recommendation': '✅ 推荐开启',
            },
        }
        return cls._cached_features


# ==================== 辅助系统 ====================

class MacroScanner:
    """预扫描用户自定义宏定义（带 LRU 缓存）
    
    扫描文件中的 \\newcommand、\\renewcommand、\\def、
    \\DeclareMathOperator、\\providecommand 等命令。
    缓存上限 128 个文件，限制扫描前 64KB。
    """
    
    SCAN_LIMIT = 65536  # 扫描前 64KB
    _CACHE_MAXSIZE = 128
    
    NEWCOMMAND_PATTERN = (
        r'\\(?:newcommand|renewcommand|def|DeclareMathOperator)'
        r'\{?\\([a-zA-Z]+)\}?'
    )
    _RE_NEWCOMMAND = re.compile(NEWCOMMAND_PATTERN)
    _RE_PROVIDECOMMAND = re.compile(r'\\providecommand\{?\\([a-zA-Z]+)\}?')
    
    def __init__(self):
        self._cache: Dict[str, Tuple[str, ...]] = {}
        self._access_order: List[str] = []
    
    def scan_file(self, file_path: Path) -> List[str]:
        """扫描文件获取用户自定义命令列表
        
        使用简单 LRU 缓存，最多保留 128 个文件的扫描结果。
        仅扫描文件前 SCAN_LIMIT 字节（默认 64KB）。
        """
        key = str(file_path.absolute())
        
        # 命中缓存 → 更新访问顺序
        if key in self._cache:
            self._touch_cache(key)
            return list(self._cache[key])
        
        # 扫描文件
        commands = self._do_scan(file_path)
        
        # 存入缓存（带 LRU 淘汰）
        self._cache[key] = tuple(commands)
        self._access_order.append(key)
        self._evict_if_needed()
        
        return commands
    
    def _do_scan(self, file_path: Path) -> List[str]:
        """实际扫描文件"""
        commands = []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read(self.SCAN_LIMIT)
            
            for match in self._RE_NEWCOMMAND.finditer(content):
                cmd = match.group(1)
                if cmd not in commands:
                    commands.append(cmd)
            
            for match in self._RE_PROVIDECOMMAND.finditer(content):
                cmd = match.group(1)
                if cmd not in commands:
                    commands.append(cmd)
        except Exception as e:
            logger.debug(f"宏扫描失败: {file_path} - {e}")
        
        return commands
    
    def _touch_cache(self, key: str):
        """更新缓存访问顺序"""
        if key in self._access_order:
            self._access_order.remove(key)
        self._access_order.append(key)
    
    def _evict_if_needed(self):
        """淘汰最旧的缓存条目"""
        while len(self._access_order) > self._CACHE_MAXSIZE:
            oldest = self._access_order.pop(0)
            self._cache.pop(oldest, None)


class FormulaContext:
    """公式上下文信息
    
    分析单个公式的环境特征，供高级功能（如 \\bm→\\vec 转换）做决策。
    """
    
    def __init__(self):
        self.contains_matrix = False
        self.contains_sum = False
        self.contains_integral = False
        self.matrix_row_count = 0
        self.surrounding_text = ""
        self.is_standalone = False
    
    @classmethod
    def from_formula(cls, formula: str, surrounding_text: str = "") -> 'FormulaContext':
        """从公式文本构建上下文"""
        ctx = cls()
        
        # 检测矩阵环境
        for env in _MATRIX_ENVS:
            if f'\\begin{{{env}}}' in formula:
                ctx.contains_matrix = True
                rows = len(re.findall(r'\\\\', formula))
                ctx.matrix_row_count = rows + 1 if rows > 0 else 1
                break
        
        # 检测求和/积分符号（使用预编译正则）
        ctx.contains_sum = bool(_RE_SUM_PROD.search(formula))
        ctx.contains_integral = bool(_RE_INTEGRAL.search(formula))
        
        # 检测是否独立行
        if surrounding_text:
            ctx.surrounding_text = surrounding_text
            stripped = surrounding_text.strip()
            if not stripped or '\n' not in stripped:
                ctx.is_standalone = True
        
        return ctx


# ==================== 原子修复器（共11个） ====================

class FormulaEncodingFixer:
    """修复公式中的编码问题"""
    
    SPECIAL_CHAR_FIXES = {
        '\x00': '',
        '\r\n': '\n',
        '\r': '\n',
    }
    _RE_HEX_ESCAPE = re.compile(r'(?<!\\)\\x[0-9a-fA-F]{2}')
    
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
    
    def fix_encoding(self, formula: str) -> Tuple[str, int]:
        """修复单个公式的编码问题"""
        if not self.enabled:
            return formula, 0
        
        fixed_formula = formula
        fix_count = 0
        
        for char, replacement in self.SPECIAL_CHAR_FIXES.items():
            if char in fixed_formula:
                old = fixed_formula
                fixed_formula = fixed_formula.replace(char, replacement)
                if old != fixed_formula:
                    fix_count += 1
        
        def fix_hex_escape(match):
            nonlocal fix_count
            fix_count += 1
            return '\\\\' + match.group(0).lstrip('\\')
        
        fixed_formula = self._RE_HEX_ESCAPE.sub(fix_hex_escape, fixed_formula)
        
        return fixed_formula, fix_count
    
    def fix_text(self, text: str) -> Tuple[str, int]:
        """修复全文编码（保护公式后处理）"""
        if not self.enabled:
            return text, 0
        
        formulas = []
        def save_formula(m):
            formulas.append(m.group(0))
            return f'__FORMULA_{len(formulas)-1}__'
        
        text = _RE_DISPLAY_SAVE.sub(save_formula, text)
        text = _RE_INLINE_SAVE.sub(save_formula, text)
        
        total_fixes = 0
        for char, replacement in self.SPECIAL_CHAR_FIXES.items():
            if char in text:
                old = text
                text = text.replace(char, replacement)
                if old != text:
                    total_fixes += 1
        
        for i, formula in enumerate(formulas):
            text = text.replace(f'__FORMULA_{i}__', formula)
        
        return text, total_fixes


class DollarSignEscaper:
    """检测并转义非公式内容的孤立 $ 符号"""
    
    _RE_PROTECTED_LINE = re.compile(r'^__(?:TABLE_ROW|CODE_BLOCK)_\d+__$')
    
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
    
    def escape(self, text: str) -> Tuple[str, int]:
        """转义全文中的孤立美元符号"""
        if not self.enabled:
            return text, 0
        
        protected_formulas = []
        protected_blocks = []
        escape_count = 0
        
        # 步骤0: 处理表格行
        def fix_table_row(m):
            nonlocal escape_count
            row = m.group(0)
            
            table_formulas = []
            def save_tf(fm):
                table_formulas.append(fm.group(0))
                return f'__TF_{len(table_formulas)-1}__'
            row = _RE_INLINE_SAVE.sub(save_tf, row)
            
            new_row = []
            for ch in row:
                if ch == '$':
                    new_row.append(r'\$')
                    escape_count += 1
                else:
                    new_row.append(ch)
            row = ''.join(new_row)
            
            for i, fm in enumerate(table_formulas):
                row = row.replace(f'__TF_{i}__', fm)
            
            protected_blocks.append(row)
            return f'__TABLE_ROW_{len(protected_blocks)-1}__'
        
        text = _RE_TABLE_ROW.sub(fix_table_row, text)
        
        # 步骤1: 保护块级公式
        def save_display(m):
            protected_formulas.append(m.group(0))
            return f'__DISPLAY_FORMULA_{len(protected_formulas)-1}__'
        text = _RE_DISPLAY_SAVE.sub(save_display, text)
        
        # 步骤2: 保护行内公式
        def save_inline(m):
            protected_formulas.append(m.group(0))
            return f'__INLINE_FORMULA_{len(protected_formulas)-1}__'
        text = _RE_INLINE_SAVE.sub(save_inline, text)
        
        # 步骤3: 保护代码块
        def save_code(m):
            protected_blocks.append(m.group(0))
            return f'__CODE_BLOCK_{len(protected_blocks)-1}__'
        text = _RE_CODE_BLOCK_SAVE.sub(save_code, text)
        text = _RE_INLINE_CODE_SAVE.sub(save_code, text)
        
        # 步骤4: 处理剩余文本中的孤立 $
        lines = text.split('\n')
        new_lines = []
        
        for line in lines:
            if self._RE_PROTECTED_LINE.match(line):
                new_lines.append(line)
                continue
            
            new_line = []
            for i, ch in enumerate(line):
                if ch == '$':
                    if self._is_truly_isolated(line, i):
                        new_line.append(r'\$')
                        escape_count += 1
                    else:
                        new_line.append(ch)
                else:
                    new_line.append(ch)
            
            new_lines.append(''.join(new_line))
        
        text = '\n'.join(new_lines)
        
        # 步骤5: 恢复
        for i, formula in enumerate(protected_formulas):
            text = text.replace(f'__DISPLAY_FORMULA_{i}__', formula)
            text = text.replace(f'__INLINE_FORMULA_{i}__', formula)
        
        for i, block in enumerate(protected_blocks):
            text = text.replace(f'__TABLE_ROW_{i}__', block)
            text = text.replace(f'__CODE_BLOCK_{i}__', block)
        
        return text, escape_count
    
    def _is_truly_isolated(self, line: str, pos: int) -> bool:
        """判断 $ 是否真正孤立"""
        if pos > 0 and line[pos - 1] == '\\':
            return False
        
        all_positions = [i for i, ch in enumerate(line)
                        if ch == '$' and (i == 0 or line[i - 1] != '\\')]
        
        if len(all_positions) >= 2 and pos in all_positions:
            idx = all_positions.index(pos)
            if idx % 2 == 0 and idx + 1 < len(all_positions):
                next_pos = all_positions[idx + 1]
                content = line[pos + 1:next_pos]
                if self._is_formula_content(content):
                    return False
            elif idx % 2 == 1:
                return False
        
        return True
    
    @staticmethod
    def _is_formula_content(content: str) -> bool:
        """判断内容是否像数学公式"""
        if not content.strip():
            return False
        if _RE_IS_FORMULA_CONTENT.match(content.strip()):
            return False
        
        return any(ind in content for ind in _MATH_INDICATORS)


class MarkdownEscaper:
    """Markdown符号转义器"""
    
    STANDARD_MAP = {'_': r'\_', '*': r'\*'}
    ZHIHU_MAP = {'_': r'\_', '*': r'\*', '#': r'\#',
                 '~': r'\textasciitilde{}', '&': r'\&'}
    
    def __init__(self, mode: str = 'standard'):
        self.mode = mode
        if mode == 'zhihu':
            self.escape_map = self.ZHIHU_MAP
        elif mode == 'standard':
            self.escape_map = self.STANDARD_MAP
        else:
            self.escape_map = {}
    
    @property
    def enabled(self) -> bool:
        return self.mode != 'off' and len(self.escape_map) > 0
    
    def escape_formula(self, formula: str) -> Tuple[str, int]:
        """转义单个行内公式"""
        if not self.enabled:
            return formula, 0
        
        count = 0
        
        # 保护LaTeX命令（使用预编译正则）
        protected_ranges = []
        for m in _RE_LATEX_COMMAND.finditer(formula):
            protected_ranges.append((m.start(), m.end()))
        
        # 保护花括号块
        brace_depth = 0
        brace_start = -1
        for i, ch in enumerate(formula):
            if ch == '{' and (i == 0 or formula[i - 1] != '\\'):
                if brace_depth == 0:
                    brace_start = i - 1 if (i > 0 and formula[i - 1] in '_^') else i
                brace_depth += 1
            elif ch == '}' and (i == 0 or formula[i - 1] != '\\'):
                brace_depth -= 1
                if brace_depth == 0 and brace_start >= 0:
                    protected_ranges.append((brace_start, i + 1))
                    brace_start = -1
        
        # 合并保护区间
        protected_ranges.sort()
        merged = []
        for start, end in protected_ranges:
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        
        # 只转义保护区外的符号
        new_chars = []
        i = 0
        for start, end in merged:
            while i < start:
                if formula[i] in self.escape_map:
                    new_chars.append(self.escape_map[formula[i]])
                    count += 1
                else:
                    new_chars.append(formula[i])
                i += 1
            new_chars.append(formula[start:end])
            i = end
        
        while i < len(formula):
            if formula[i] in self.escape_map:
                new_chars.append(self.escape_map[formula[i]])
                count += 1
            else:
                new_chars.append(formula[i])
            i += 1
        
        return ''.join(new_chars), count


class FunctionNameNormalizer:
    """函数名正体化"""
    
    STANDARD_FUNCTIONS = frozenset({
        'sin', 'cos', 'tan', 'cot', 'sec', 'csc',
        'arcsin', 'arccos', 'arctan', 'arccot', 'arcsec', 'arccsc',
        'sinh', 'cosh', 'tanh', 'coth', 'sech', 'csch',
        'exp', 'log', 'ln', 'lg', 'det', 'gcd', 'lcm',
        'lim', 'limsup', 'liminf', 'sup', 'inf',
        'max', 'min', 'argmax', 'argmin',
        'dim', 'ker', 'deg', 'hom', 'Pr', 'arg', 'Re', 'Im',
        'mod', 'bmod', 'pmod', 'binom',
    })
    
    # 按长度降序排序（一次性计算）
    _SORTED_FUNCTIONS = sorted(STANDARD_FUNCTIONS, key=len, reverse=True)
    # 预编译所有替换正则
    _FUNC_PATTERNS: Dict[str, Pattern] = {}
    
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        if not self._FUNC_PATTERNS:
            for func in self._SORTED_FUNCTIONS:
                self._FUNC_PATTERNS[func] = re.compile(
                    rf'(?<!\\)\b{re.escape(func)}\b'
                )
    
    def normalize(self, formula: str) -> Tuple[str, int]:
        """标准化公式中的函数名"""
        if not self.enabled:
            return formula, 0
        
        count = 0
        for func in self._SORTED_FUNCTIONS:
            pattern = self._FUNC_PATTERNS[func]
            replacement = rf'\\{func}'
            new_formula, n = pattern.subn(replacement, formula)
            if n > 0:
                formula = new_formula
                count += n
        
        return formula, count


class SubSupFixer:
    """上下标范围修正"""
    
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
    
    def fix(self, formula: str) -> Tuple[str, int]:
        """修正公式中的上下标"""
        if not self.enabled:
            return formula, 0
        
        count = 0
        
        # 保护已有花括号块
        protected_brackets = []
        def save_bracket(m):
            protected_brackets.append(m.group(0))
            return f'__BRACKET_{len(protected_brackets) - 1}__'
        
        formula = _RE_BRACKET_PROTECT.sub(save_bracket, formula)
        
        # 处理上标（使用预编译正则）
        def fix_sup(match):
            nonlocal count
            prefix, sup_content = match.group(1), match.group(2)
            
            if _RE_SEPARATORS.search(sup_content):
                return match.group(0)
            if len(sup_content) == 1 or sup_content.startswith('\\'):
                return match.group(0)
            if _RE_ALPHANUM.match(sup_content) and len(sup_content) > 1:
                if re.match(r'^\d+[a-zA-Z]', sup_content):
                    digits = re.match(r'^(\d+)', sup_content).group(1)
                    letters = sup_content[len(digits):]
                    count += 1
                    return f'{prefix}^{{{digits}}}{letters}'
                count += 1
                return f'{prefix}^{{{sup_content}}}'
            return match.group(0)
        
        formula = _RE_SUPERSCRIPT.sub(fix_sup, formula)
        
        # 处理下标
        def fix_sub(match):
            nonlocal count
            prefix, sub_content = match.group(1), match.group(2)
            
            if _RE_SEPARATORS.search(sub_content):
                return match.group(0)
            if len(sub_content) == 1 or sub_content.startswith('\\'):
                return match.group(0)
            if _RE_ALPHANUM.match(sub_content) and len(sub_content) > 1:
                count += 1
                return f'{prefix}_{{{sub_content}}}'
            return match.group(0)
        
        formula = _RE_SUBSCRIPT.sub(fix_sub, formula)
        
        # 恢复保护块
        for i, bracket in enumerate(protected_brackets):
            formula = formula.replace(f'__BRACKET_{i}__', bracket)
        
        return formula, count


class BracketChecker:
    """括号配对检查"""
    
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
    
    def check_and_fix(self, formula: str) -> Tuple[str, List[str]]:
        """检查并修复括号配对"""
        if not self.enabled:
            return formula, []

        logs = []

        formula, left_logs = self._fix_left_right(formula)
        if left_logs:
            logs.extend(left_logs)

        formula, brace_logs = self._fix_braces(formula)
        if brace_logs:
            logs.extend(brace_logs)

        return formula, logs
    
    def _fix_left_right(self, formula: str) -> Tuple[str, List[str]]:
        """修复 \\left/\\right 配对"""
        left_count = sum(len(pat.findall(formula)) for pat in _RE_LEFT_BRACKETS)
        right_count = sum(len(pat.findall(formula)) for pat in _RE_RIGHT_BRACKETS)
        
        if left_count > right_count:
            formula = formula.rstrip() + ' \\right.'
            return formula, [f"补全缺失的\\right. (left:{left_count}, right:{right_count})"]
        elif right_count > left_count:
            return formula, [f"检测到{right_count - left_count}处多余的\\right，请手动检查"]
        
        return formula, []
    
    def _fix_braces(self, formula: str) -> Tuple[str, List[str]]:
        """检测花括号配对"""
        stack = []
        for i, ch in enumerate(formula):
            if ch == '{' and (i == 0 or formula[i - 1] != '\\'):
                stack.append(i)
            elif ch == '}' and (i == 0 or formula[i - 1] != '\\'):
                if stack:
                    stack.pop()
                else:
                    return formula, [f"检测到多余的右花括号在位置{i}"]
        
        if stack:
            return formula, [f"检测到{len(stack)}个未闭合的左花括号"]
        
        return formula, []


class ImageCaptionOptimizer:
    """图片标题样式化"""
    
    COLOR_SCHEMES = {
        'purple': '#9b59b6', 'blue': "#4181ab", 'red': '#e74c3c',
        'green': '#27ae60', 'orange': '#e67e22', 'black': '#000000',
        'dark_purple': '#800080', 'medium_purple': '#9370DB',
        'light_purple': '#c39bd3', 'teal': '#1abc9c', 'navy': '#2c3e50'
    }
    _RE_IMAGE = re.compile(r'!\[[^\]]*\]\([^)]+\)')
    
    def __init__(self, color_scheme: str = 'purple', enabled: bool = True):
        self.enabled = enabled
        self.color_code = self.COLOR_SCHEMES.get(color_scheme, '#9b59b6')
    
    def optimize(self, text: str) -> Tuple[str, int]:
        """优化图片标题"""
        if not self.enabled:
            return text, 0
        
        lines = text.split('\n')
        new_lines = []
        i = 0
        count = 0
        
        while i < len(lines):
            current_line = lines[i]
            
            if self._RE_IMAGE.search(current_line):
                j = i + 1
                while j < len(lines) and lines[j].strip() == '':
                    j += 1
                
                if j < len(lines):
                    next_line = lines[j].strip()
                    caption_match = re.match(r'^\*([^*]+)\*$', next_line)
                    
                    if caption_match:
                        caption = caption_match.group(1).strip()
                        new_lines.append(current_line)
                        new_lines.append(
                            f'<p style="text-align: center; '
                            f'margin-top: 0.5em; margin-bottom: 1em;">'
                            f'<strong style="color: {self.color_code};">'
                            f'{caption}</strong></p>'
                        )
                        i = j + 1
                        count += 1
                        continue
            
            new_lines.append(current_line)
            i += 1
        
        return '\n'.join(new_lines), count


# ==================== 公式修复引擎 ====================

class ConfigurableFormulaFixer:
    """可配置的公式修复器"""
    
    DEFAULT_DL_COMMANDS = [
        'LayerNorm', 'Linear', 'ReLU', 'GELU', 'SiLU', 'Swish',
        'Softmax', 'Sigmoid', 'Tanh', 'Dropout', 'BatchNorm',
        'InstanceNorm', 'GroupNorm', 'RMSNorm', 'LSTM', 'GRU',
        'Attention', 'MultiHeadAttention', 'Transformer',
        'Encoder', 'Decoder', 'Embedding', 'PositionalEncoding',
        'MLP', 'CNN', 'RNN', 'FFN', 'MHA', 'MSE', 'MAE',
        'CrossEntropy', 'BCE', 'Adam', 'SGD', 'AdamW'
    ]
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config if config is not None else self.get_default_config()
        
        escape_mode = self.config.get('escape_mode', 'standard')
        self.escaper = MarkdownEscaper(mode=escape_mode)
        self.normalizer = FunctionNameNormalizer(
            enabled=self.config.get('func_normalize', False))
        self.subsup_fixer = SubSupFixer(
            enabled=self.config.get('subsup_fix', False))
        self.bracket_checker = BracketChecker(
            enabled=self.config.get('bracket_check', False))
        self.macro_scanner = MacroScanner()
        self.encoding_fixer = FormulaEncodingFixer(
            enabled=self.config.get('fix_encoding', False))
    
    @staticmethod
    def get_default_config() -> Dict[str, Any]:
        """获取默认配置（所有功能关闭，用户需手动启用或选择预设方案）"""
        return {
            'bm_to_vec': False,
            'remove_size_commands': False,
            'matrix_newline_remove': False,
            'matrix_add_multiplication': False,
            'dl_commands_to_text': False,
            'dl_commands_list': ConfigurableFormulaFixer.DEFAULT_DL_COMMANDS,
            'markdown_escape_inline': False,
            'func_normalize': False,
            'subsup_fix': False,
            'bracket_check': False,
            'respect_macros': False,
            'escape_mode': 'off',
            'bm_strict_mode': True,
        }
    
    def _smart_bm_to_vec(self, formula: str, context: FormulaContext = None) -> Tuple[str, int]:
        """智能 \\bm → \\vec 转换"""
        if not self.config.get('bm_to_vec') or '\\bm' not in formula:
            return formula, 0
        
        if context and context.contains_matrix:
            return formula, 0
        
        bm_contents = re.findall(r'\\bm\{([^}]*?)\}', formula)
        bm_single = re.findall(r'\\bm\s+([a-zA-Z])', formula)
        bm_single2 = re.findall(r'\\bm([a-zA-Z])', formula)
        
        all_bm_targets = bm_contents + bm_single + bm_single2
        
        if not all_bm_targets:
            return self._apply_bm_to_vec(formula)
        
        vector_indicators = [
            '\\vec', '\\cdot', '\\times', '\\sum', '\\int', '\\partial',
            '\\nabla', '\\mathbf', '\\hat', '\\bar', '\\tilde',
        ]
        
        all_single_letter = all(
            len(t.strip()) <= 1 and (t.strip().isalpha() if t.strip() else False)
            for t in all_bm_targets
        )
        
        has_vector_context = any(ind in formula for ind in vector_indicators)
        
        should_convert = (
            (has_vector_context and all_single_letter) or
            (all_single_letter and len(all_bm_targets) == 1) or
            (has_vector_context and not self.config.get('bm_strict_mode', True))
        )
        
        if should_convert:
            return self._apply_bm_to_vec(formula)
        
        return formula, 0
    
    def _apply_bm_to_vec(self, formula: str) -> Tuple[str, int]:
        """执行 \\bm 到 \\vec 的实际替换"""
        count_before = len(re.findall(r'\\bm', formula))
        
        formula = _RE_BM_BRACE.sub(r'\\vec{\1}', formula)
        formula = _RE_BM_BRACE_SIMPLE.sub(r'\\vec{\1}', formula)
        formula = _RE_BM_SPACE.sub(r'\\vec{\1}', formula)
        formula = _RE_BM_NO_SPACE.sub(r'\\vec{\1}', formula)
        
        count_after = len(re.findall(r'\\bm', formula))
        return formula, count_before - count_after
    
    def fix_formula(self, formula: str, is_display: bool = False,
                    context=None, user_macros: List[str] = None) -> Tuple[str, List[str]]:
        """执行公式的完整修复流程"""
        logs = []
        if user_macros is None:
            user_macros = []
        
        # ★ 标记是否有实质性修改（用于控制第 10 步空白规范化）
        modified = False
        
        # 0. 编码问题修复
        formula, cnt = self.encoding_fixer.fix_encoding(formula)
        if cnt > 0:
            logs.append(f"编码修复: {cnt}处")
            modified = True
        
        # 1. 括号配对检查
        formula, bracket_logs = self.bracket_checker.check_and_fix(formula)
        if bracket_logs:
            logs.extend(bracket_logs)
            modified = True
        
        # 2. 上下标修正
        formula, cnt = self.subsup_fixer.fix(formula)
        if cnt > 0:
            logs.append(f"上下标修正: {cnt}处")
            modified = True
        
        # 3. 函数名正体化
        formula, cnt = self.normalizer.normalize(formula)
        if cnt > 0:
            logs.append(f"函数名正体化: {cnt}处")
            modified = True
        
        # 4. Markdown符号转义（仅行内公式）
        if not is_display and self.config.get('markdown_escape_inline', False):
            formula, cnt = self.escaper.escape_formula(formula)
            if cnt > 0:
                mode_label = {'standard': '标准', 'zhihu': '知乎增强', 'off': '关闭'}.get(
                    self.config.get('escape_mode', 'standard'), '标准')
                logs.append(f"Markdown转义({mode_label}): {cnt}处")
                modified = True
        
        # 5. \\bm → \\vec 智能转换
        formula, cnt = self._smart_bm_to_vec(formula, context)
        if cnt > 0:
            logs.append(f"\\bm→\\vec: {cnt}处")
            modified = True
        
        # 6. 移除尺寸命令
        if self.config.get('remove_size_commands', False):
            for cmd in _SIZE_COMMANDS:
                if cmd in formula:
                    formula = re.sub(rf'{re.escape(cmd)}\s*\(', '(', formula)
                    formula = re.sub(rf'{re.escape(cmd)}\b', '', formula)
                    logs.append(f"移除: {cmd}")
                    modified = True
        
        # 7. 矩阵末尾换行移除
        if self.config.get('matrix_newline_remove', False) and any(
                env in formula for env in _MATRIX_ENVS):
            old = formula
            formula = re.sub(r'\\\\+(\s*\\\])', r'\1', formula)
            formula = re.sub(r'\\\\+(\s*\$\$)', r'\1', formula)
            for env in _MATRIX_ENVS:
                formula = re.sub(rf'\\\\+(\s*\\end{{{env}}})', r'\1', formula)
            formula = re.sub(r'\\\\+\s*$', '', formula)
            if formula != old:
                logs.append("移除矩阵末尾换行")
                modified = True
        
        # 8. 矩阵间添加乘号
        if self.config.get('matrix_add_multiplication', False) and any(
                env in formula for env in _MATRIX_ENVS):
            pattern = r'(' + _RE_MATRIX_END.pattern + r')\s+(' + _RE_MATRIX_BEGIN.pattern + r')'
            cnt_list = [0]
            def add_times(m):
                if r'\times' not in m.group(0):
                    cnt_list[0] += 1
                    return m.group(1) + r' \times ' + m.group(2)
                return m.group(0)
            formula = re.sub(pattern, add_times, formula)
            if cnt_list[0] > 0:
                logs.append(f"添加矩阵乘号: {cnt_list[0]}处")
                modified = True
        
        # 9. 深度学习命令转文本
        if self.config.get('dl_commands_to_text', False):
            dl_list = self.config.get('dl_commands_list', self.DEFAULT_DL_COMMANDS)
            for cmd in dl_list:
                if self.config.get('respect_macros', True) and cmd in user_macros:
                    continue
                pattern = rf'\\{cmd}\b(?!\w)'
                if re.search(pattern, formula):
                    formula = re.sub(pattern, rf'\\text{{{cmd}}}', formula)
                    logs.append(f"{cmd}→\\text")
                    modified = True
        
        # 10. 空白字符规范化（★ 仅在有关键修改时才执行）
        if modified:
            formula = re.sub(r'[ \t]+', ' ', formula)
            formula = re.sub(r'[ \t]+\n', '\n', formula)
            formula = re.sub(r'\n[ \t]+', '\n', formula)
            formula = formula.strip()
        
        return formula, logs


class FormulaPreviewer:
    """公式预检预览器"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.fixer = ConfigurableFormulaFixer(config.get('formula_config', {}))
        self.macro_scanner = MacroScanner()
    
    def preview(self, text: str, file_path: Path = None) -> List[FormulaChange]:
        """预检全文公式，返回所有变更"""
        changes = []
        
        user_macros = []
        if file_path and self.config.get('formula_config', {}).get('respect_macros', True):
            user_macros = self.macro_scanner.scan_file(file_path)
        
        # 处理块级公式（使用预编译正则）
        for m in _RE_DISPLAY_FORMULA.finditer(text):
            original = m.group(1).strip()
            context = FormulaContext.from_formula(original, '')
            fixed, logs = self.fixer.fix_formula(
                original, is_display=True, context=context, user_macros=user_macros)
            
            if original != fixed:
                changes.append(FormulaChange(
                    original=original, fixed=fixed, changes=logs,
                    risk_level=self._assess_risk(logs), formula_type='display'))
        
        # 处理行内公式（使用预编译正则）
        for m in _RE_INLINE_FORMULA.finditer(text):
            original = m.group(1).strip()
            context = FormulaContext.from_formula(original, '')
            fixed, logs = self.fixer.fix_formula(
                original, is_display=False, context=context, user_macros=user_macros)
            
            if original != fixed:
                changes.append(FormulaChange(
                    original=original, fixed=fixed, changes=logs,
                    risk_level=self._assess_risk(logs), formula_type='inline'))
        
        return changes
    
    @staticmethod
    def _assess_risk(logs: List[str]) -> str:
        """根据日志关键词评估风险等级"""
        high_risk_kw = ['\\bm→\\vec', '转块级']
        medium_risk_kw = ['乘号', '\\text', '移除尺寸',
                         'Markdown转义', '知乎增强']
        
        for log in logs:
            for kw in high_risk_kw:
                if kw in log:
                    return 'high'
        for log in logs:
            for kw in medium_risk_kw:
                if kw in log:
                    return 'medium'
        
        return 'low'


# ==================== 文档处理器 ====================

class MarkdownFormulaProcessor:
    """Markdown公式处理器 - 增强版"""
    
    def __init__(self, input_file: Path, output_dir: Path = None,
                 config: Dict[str, Any] = None):
        self.input_file = input_file
        self.output_dir = output_dir or input_file.parent
        self.config = config or {}
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.caption_optimizer = ImageCaptionOptimizer(
            color_scheme=self.config.get('image_caption_color', 'purple'),
            enabled=self.config.get('image_caption_enabled', True))
        
        self.formula_fixer = ConfigurableFormulaFixer(
            self.config.get('formula_config', {}))
        
        self.dollar_escaper = DollarSignEscaper(
            enabled=self.config.get('escape_isolated_dollars', True))
        
        self.encoding_fixer = FormulaEncodingFixer(
            enabled=self.config.get('fix_encoding', True))
        
        self.stats = {
            'total_formulas': 0, 'fixed_formulas': 0,
            'inline_formulas': 0, 'display_formulas': 0,
            'converted_to_display': 0, 'matrix_formulas': 0,
            'image_captions_fixed': 0, 'func_normalized': 0,
            'subsup_fixed': 0, 'markdown_escaped': 0,
            'bracket_fixed': 0, 'bm_converted': 0,
            'encoding_fixed': 0, 'dollar_escaped': 0,
            'fix_logs': []
        }
    
    def process(self, output_filename: str = None) -> Tuple[str, Path]:
        """处理文件"""
        with open(self.input_file, 'r', encoding='utf-8') as f:
            text = f.read()
        
        if not text:
            raise ValueError(f"文件为空: {self.input_file}")
        
        if self._is_all_disabled():
            if not output_filename:
                output_filename = f"{self.input_file.stem}_fixed.md"
            output_path = self.output_dir / output_filename
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(text)
            return text, output_path
        
        # 编码修复（文档级）
        try:
            text, encoding_count = self.encoding_fixer.fix_text(text)
            if encoding_count > 0:
                self.stats['encoding_fixed'] += encoding_count
        except Exception as e:
            logger.warning(f"编码修复失败: {e}")
        
        # 转义孤立美元符号
        try:
            text, dollar_count = self.dollar_escaper.escape(text)
            if dollar_count > 0:
                self.stats['dollar_escaped'] += dollar_count
        except Exception as e:
            logger.warning(f"美元符号转义失败: {e}")
        
        # 图片标题优化
        try:
            text, caption_count = self.caption_optimizer.optimize(text)
            self.stats['image_captions_fixed'] = caption_count
        except Exception as e:
            logger.warning(f"图片标题优化失败: {e}")
        
        # 公式处理
        try:
            text = self._process_formulas(text)
        except Exception as e:
            logger.error(f"公式处理失败: {e}")
            traceback.print_exc()
        
        if text is None:
            raise ValueError("处理后的文本为None，处理失败")
        
        if not output_filename:
            output_filename = f"{self.input_file.stem}_fixed.md"
        
        output_path = self.output_dir / output_filename
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(text)
        
        return text, output_path
    
    def _is_all_disabled(self) -> bool:
        """检查是否所有功能都禁用了"""
        fc = self.config.get('formula_config', {})
        return (
            not self.config.get('image_caption_enabled', False) and
            not self.config.get('clean_extra_newlines', False) and
            not self.config.get('add_space_after_inline', False) and
            not self.config.get('inline_to_display', False) and
            not self.config.get('escape_isolated_dollars', False) and
            not self.config.get('fix_encoding', False) and
            not fc.get('bm_to_vec', False) and
            not fc.get('remove_size_commands', False) and
            not fc.get('matrix_newline_remove', False) and
            not fc.get('matrix_add_multiplication', False) and
            not fc.get('dl_commands_to_text', False) and
            not fc.get('markdown_escape_inline', False) and
            not fc.get('func_normalize', False) and
            not fc.get('subsup_fix', False) and
            not fc.get('bracket_check', False)
        )
    
    # ====== 保护-处理-恢复 ======
    
    def _protect_blocks(self, text: str) -> Tuple[str, List[str]]:
        """保护代码块和行内代码"""
        protected = []
        text = self._protect_fenced_blocks(text, protected)
        text = self._protect_inline_codes(text, protected)
        return text, protected
    
    def _protect_fenced_blocks(self, text: str, protected: List[str]) -> str:
        """保护围栏代码块（使用列表拼接优化大文件性能）"""
        fence_positions = []
        for m in _RE_FENCE_POSITION.finditer(text):
            pos = m.start()
            if text[pos] == '\n':
                pos += 1
            fence_positions.append(pos)
        
        if len(fence_positions) < 2:
            return text
        
        # ★ 使用列表拼接代替字符串切片
        parts = []
        last_end = 0
        i = 0
        
        while i + 1 < len(fence_positions):
            start = fence_positions[i]
            end_line_start = fence_positions[i + 1]
            end_line = text.find('\n', end_line_start)
            if end_line == -1:
                end_line = len(text)
            
            between = text[start:end_line_start]
            if '\n' not in between.strip():
                i += 1
                continue
            
            # 保存前面部分
            parts.append(text[last_end:start])
            
            # 保存代码块替换为占位符
            full_block = text[start:end_line]
            protected.append(full_block)
            parts.append(f'__PROTECTED_{len(protected) - 1}__')
            
            last_end = end_line
            i += 2
        
        # 追加尾部
        parts.append(text[last_end:])
        
        return ''.join(parts)
    
    def _protect_inline_codes(self, text: str, protected: List[str]) -> str:
        """保护行内代码"""
        lines = text.split('\n')
        new_lines = []
        for line in lines:
            new_line = _RE_INLINE_CODE.sub(
                lambda m: self._save_inline(m.group(0), protected),
                line)
            new_lines.append(new_line)
        return '\n'.join(new_lines)
    
    def _save_inline(self, code: str, protected: List[str]) -> str:
        """保存行内代码到保护列表"""
        if _RE_PROTECTED_PLACEHOLDER.match(code):
            return code
        if len(code) <= 2:
            return code
        if code in protected:
            return f'__PROTECTED_{protected.index(code)}__'
        protected.append(code)
        return f'__PROTECTED_{len(protected) - 1}__'
    
    def _restore_blocks(self, text: str, protected: List[str]) -> str:
        """恢复所有保护块"""
        if not protected:
            return text
        for i in range(len(protected) - 1, -1, -1):
            text = text.replace(f'__PROTECTED_{i}__', protected[i])
        return text
    
    def _is_protected_placeholder(self, content: str) -> bool:
        """判断是否为保护占位符"""
        return bool(_RE_PROTECTED_PLACEHOLDER.match(content.strip()))
    
    def _process_formulas(self, text: str) -> str:
        """处理所有公式（核心方法）"""
        if not text:
            return text
        
        user_macros = []
        if self.config.get('respect_macros', True):
            user_macros = self.formula_fixer.macro_scanner.scan_file(self.input_file)
        
        # 1. 保护代码块
        text, protected_blocks = self._protect_blocks(text)
        
        # 2. 处理块级公式
        def safe_process_display(m):
            try:
                content = m.group(1)
                if not content or not content.strip():
                    return m.group(0)
                stripped = content.strip()
                if self._is_protected_placeholder(stripped):
                    return m.group(0)
                
                self.stats['total_formulas'] += 1
                self.stats['display_formulas'] += 1
                
                if any(env in stripped for env in _MATRIX_ENVS):
                    self.stats['matrix_formulas'] += 1
                
                context = FormulaContext.from_formula(stripped, '')
                fixed, logs = self.formula_fixer.fix_formula(
                    stripped, is_display=True, context=context,
                    user_macros=user_macros)
                
                if fixed != stripped and logs:
                    self.stats['fixed_formulas'] += 1
                    self.stats['fix_logs'].append(
                        {'type': 'display', 'logs': logs})
                    self._update_stats(logs)
                
                return f'$$\n{fixed.strip()}\n$$'
            except Exception as e:
                logger.debug(f"块级公式处理异常: {e}")
                return m.group(0)
        
        text = _RE_DISPLAY_FORMULA.sub(safe_process_display, text)
        
        # 3. 逐行处理行内公式
        lines = text.split('\n')
        new_lines = []
        for line in lines:
            if _RE_PROTECTED_PLACEHOLDER.match(line.strip()):
                new_lines.append(line)
                continue
            processed_line = self._process_inline_formulas_in_line(
                line, user_macros)
            new_lines.append(processed_line)
        text = '\n'.join(new_lines)
        
        # 4. 恢复保护块
        text = self._restore_blocks(text, protected_blocks)
        
        # 5. 清理多余换行
        if self.config.get('clean_extra_newlines', True):
            text = _RE_EXTRA_NEWLINES.sub('\n\n', text)
        
        return text
    
    def _process_inline_formulas_in_line(self, line: str,
                                         user_macros: List[str]) -> str:
        """处理一行中的行内公式"""
        def safe_process_inline(m):
            try:
                content = m.group(1)
                if not content or not content.strip():
                    return m.group(0)
                stripped = content.strip()
                if self._is_protected_placeholder(stripped):
                    return m.group(0)
                
                self.stats['total_formulas'] += 1
                
                if any(env in stripped for env in _MATRIX_ENVS):
                    self.stats['matrix_formulas'] += 1
                
                context = FormulaContext.from_formula(stripped, line)
                fixed, logs = self.formula_fixer.fix_formula(
                    stripped, is_display=False, context=context,
                    user_macros=user_macros)
                
                if fixed != stripped and logs:
                    self.stats['fixed_formulas'] += 1
                    self.stats['fix_logs'].append(
                        {'type': 'inline', 'logs': logs})
                    self._update_stats(logs)
                
                # 独立行内公式转块级
                if self.config.get('inline_to_display', False):
                    if self._is_standalone_formula(line, m.start(), m.end()):
                        self.stats['converted_to_display'] += 1
                        self.stats['display_formulas'] += 1
                        return f'\n$$\n{fixed.strip()}\n$$\n'
                
                self.stats['inline_formulas'] += 1
                
                result = f'${fixed}$'
                
                # 行内公式后添加空格
                if self.config.get('add_space_after_inline', False):
                    end_pos = m.end()
                    if (end_pos < len(line) and
                        re.match(r'[\u4e00-\u9fff]', line[end_pos])):
                        result += ' '
                
                return result
            except Exception as e:
                logger.debug(f"行内公式处理异常: {e}")
                return m.group(0)
        
        line = _RE_INLINE_FORMULA.sub(safe_process_inline, line)
        return line
    
    @staticmethod
    def _is_standalone_formula(line: str, start_pos: int, end_pos: int) -> bool:
        """判断行内公式是否单独占一行"""
        before = line[:start_pos]
        after = line[end_pos:]
        return (not before or before.strip() == '') and (not after or after.strip() == '')
    
    def _update_stats(self, logs: List[str]):
        """根据日志更新统计"""
        for log in logs:
            if '上下标修正' in log:
                self.stats['subsup_fixed'] += 1
            elif '函数名正体化' in log:
                self.stats['func_normalized'] += 1
            elif 'Markdown转义' in log:
                self.stats['markdown_escaped'] += 1
            elif '括号' in log:
                self.stats['bracket_fixed'] += 1
            elif '\\bm→\\vec' in log:
                self.stats['bm_converted'] += 1


# ==================== 标题提取器 ====================

class MarkdownTitleExtractor:
    """从Markdown文件的YAML Front Matter中提取标题并生成安全文件名"""
    
    def extract_title(self, md_file: Path,
                      fields: List[str] = None) -> Optional[str]:
        """提取YAML标题"""
        if fields is None:
            fields = ['title', '标题', 'name', 'slug', '文件名']
        
        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                content = f.read(16384)
            
            match = _RE_YAML_BOUNDARY.search(content)
            if not match:
                return None
            
            yaml_content = match.group(1)
            
            for field in fields:
                pattern = (
                    rf'^{re.escape(field)}:\s*'
                    r'["\'\u201c\u201d\u2018\u2019]?'
                    r'(.+?)'
                    r'["\'\u201c\u201d\u2018\u2019]?\s*$'
                )
                m = re.search(pattern, yaml_content,
                             re.MULTILINE | re.IGNORECASE)
                if m:
                    return m.group(1).strip()
            
            return None
        except Exception:
            return None
    
    def sanitize(self, title: str, max_length: int = 100) -> str:
        """安全化文件名"""
        if not title:
            return "untitled"
        
        safe = _RE_ILLEGAL_FILENAME.sub('_', title).strip('. _-')
        safe = re.sub(r'[\s_]+', '_', safe)
        
        if len(safe) > max_length:
            safe = safe[:max_length].rstrip('._-')
        
        return safe or "untitled"
    
    def get_unique_name(self, directory: Path, base: str,
                        ext: str = '.md') -> str:
        """获取唯一文件名"""
        name = f"{base}{ext}"
        if not (directory / name).exists():
            return name
        
        counter = 1
        while True:
            name = f"{base}_{counter}{ext}"
            if not (directory / name).exists():
                return name
            counter += 1
    
    def generate_name(self, md_file: Path, output_dir: Path,
                      fields: List[str] = None) -> Tuple[str, bool, Optional[str]]:
        """生成输出文件名"""
        title = self.extract_title(md_file, fields)
        if title:
            safe = self.sanitize(title)
            if safe and safe != "untitled":
                name = self.get_unique_name(output_dir, safe)
                return name, True, title
        
        return f"{md_file.stem}_fixed.md", False, None


# ==================== 默认配置常量 ====================

DEFAULT_REPAIR_CONFIG = {
    'clean_extra_newlines': False,
    'add_space_after_inline': False,
    'inline_to_display': False,
    'image_caption_enabled': False,
    'image_caption_color': 'purple',
    'escape_isolated_dollars': False,
    'fix_encoding': False,
    'formula_config': ConfigurableFormulaFixer.get_default_config(),
}


# ==================== 元信息 ====================
__author__ = "YQJ"
__version__ = "4.3.7"
__date__ = "2026.05.05"