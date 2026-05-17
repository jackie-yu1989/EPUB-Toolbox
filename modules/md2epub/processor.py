#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MD转EPUB - 核心处理逻辑
基于 Pandoc 转换引擎 + 自建 EPUB 打包器

性能优化特性：
- 正则表达式集中管理 + 预编译（EpubRegexPatterns）
- 图片名称 Set 查找（O(1) 替代 O(n)）
"""

import re
import sys
import shutil
import subprocess
import tempfile
import zipfile
import os
import logging
from pathlib import Path
from datetime import datetime
from typing import Tuple, List, Optional, Dict, Any, Set

from core.utils import find_executable


# 模块级日志记录器
logger = logging.getLogger(__name__)


# ==================== 正则表达式集中管理 + 预编译 ====================

class EpubRegexPatterns:
    """MD转EPUB模块的正则表达式预编译
    
    设计原则：
        1. 所有正则预编译为类属性（只编译一次）
        2. 命名语义化，避免魔法字符串散落
    """
    
    # ---- 图片匹配 ----
    IMAGE_PATTERN = re.compile(r'!\[([^\]]*)\]\(([^)\s]+|<[^>]+>)\)')
    
    # ---- Mermaid 图表 ----
    MERMAID_BLOCK = re.compile(r'```(?:mermaid|Mermaid)\s*\n(.*?)\n```', re.DOTALL | re.IGNORECASE)
    
    # ---- YAML Frontmatter（支持 --- 和 +++ 两种分隔符） ----
    YAML_FRONTMATTER = re.compile(r'^[-+]{3}\s*\n(.*?)\n[-+]{3}\s*\n', re.DOTALL)
    
    # ---- HTML body 提取 ----
    BODY_TAG = re.compile(r'<body[^>]*>(.*?)</body>', re.DOTALL)
    
    # ---- 标题匹配（用于目录提取） ----
    HEADING = re.compile(r'<h([1-4])(?:[^>]*id="([^"]+)")?[^>]*>(.*?)</h\1>', re.DOTALL | re.IGNORECASE)
    
    # ---- 清理残留图片标记（仅安全的模式） ----
    RESIDUAL_IMAGE = re.compile(r'!\[[^\]]*\]\([^)]*\)', re.DOTALL)
    RESIDUAL_IMAGE_PARTIAL = re.compile(r'!\[[^\]]*\]\([^)]*')
    
    # ---- 多重换行清理 ----
    MULTI_NEWLINE = re.compile(r'\n\s*\n\s*\n')
    
    # ---- 图片增强 ----
    IMG_TAG = re.compile(r'<img([^>]+?)>')
    IMG_ALT = re.compile(r'alt="([^"]+)"')
    
    # ---- 首行缩进保护（表格/代码块/列表不缩进） ----
    TABLE_TAG = re.compile(r'<table[^>]*>.*?</table>', re.DOTALL)
    PRE_TAG = re.compile(r'<pre[^>]*>.*?</pre>', re.DOTALL)
    LI_TAG = re.compile(r'<li[^>]*>.*?</li>', re.DOTALL)
    PARAGRAPH = re.compile(r'<p([^>]*)>')
    
    # ---- 标题锚点清理 ----
    ANCHOR_CLEAN = re.compile(r'[^\w\u4e00-\u9fff]+')
    
    # ---- HTML 标签清理 ----
    HTML_TAG = re.compile(r'<[^>]+>')
    
    # ---- 数字/字母拆分（用于文件名去重） ----
    NUMBER_LETTER = re.compile(r'^(\d+)([a-zA-Z]+)$')


# ★ 创建静默启动信息（Windows 下隐藏控制台窗口）
_STARTUP_INFO = None
if sys.platform == 'win32':
    _STARTUP_INFO = subprocess.STARTUPINFO()
    _STARTUP_INFO.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    _STARTUP_INFO.wShowWindow = subprocess.SW_HIDE


# ==================== 命令工具函数 ====================

def find_cmd(name: str) -> Optional[List[str]]:
    """查找可执行命令，优先直接调用，其次通过 npx
    
    Args:
        name: 命令名（如 'mmdc'）
        
    Returns:
        Optional[List[str]]: 命令列表，未找到返回 None
    """
    if p := shutil.which(name):
        return [p]
    if npx := shutil.which("npx"):
        return [npx, name]
    return None


def run_cmd(cmd: List[str], cwd: Optional[Path] = None, timeout: int = 30) -> Tuple[bool, Optional[str]]:
    """运行命令并返回结果
    
    Args:
        cmd: 命令列表
        cwd: 工作目录
        timeout: 超时秒数
        
    Returns:
        Tuple[bool, Optional[str]]: (是否成功, 失败时的错误信息)
    """
    try:
        subprocess.run(
            cmd, check=True, capture_output=True, text=True,
            timeout=timeout, cwd=cwd,
            startupinfo=_STARTUP_INFO
        )
        return True, None
    except subprocess.TimeoutExpired:
        return False, f"命令超时 ({timeout}s)"
    except subprocess.CalledProcessError as e:
        error_detail = e.stderr[:200] if e.stderr else f"返回码 {e.returncode}"
        return False, error_detail
    except FileNotFoundError:
        return False, f"命令未找到: {cmd[0]}"
    except Exception as e:
        return False, str(e)


# ==================== HTML/XML 工具函数 ====================

def escape(text: str, xml: bool = False) -> str:
    """转义 HTML/XML 特殊字符
    
    Args:
        text: 原始文本
        xml: True 时使用 XML 实体（&apos;），否则使用 HTML 实体（&#39;）
        
    Returns:
        str: 转义后的文本
    """
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')
    return text.replace("'", '&apos;' if xml else '&#39;')


# ==================== YAML Frontmatter 提取 ====================

def extract_frontmatter(content: str) -> Tuple[Dict[str, str], str]:
    """提取 YAML Frontmatter 元数据（支持 --- 和 +++ 分隔符）
    
    Args:
        content: Markdown 全文内容
        
    Returns:
        Tuple[Dict[str, str], str]: (元数据字典, 去除 frontmatter 后的正文)
    """
    metadata = {}
    
    # 使用预编译正则检测 YAML 分隔符
    match = EpubRegexPatterns.YAML_FRONTMATTER.match(content)
    if not match:
        return metadata, content
    
    lines = content.split('\n')
    try:
        end = lines.index(lines[0], 1)  # 找到闭合的分隔符行
        frontmatter_lines = lines[1:end]
        remaining_content = '\n'.join(lines[end + 1:])
        
        for line in frontmatter_lines:
            line = line.strip()
            if ':' in line and not line.startswith('#'):
                key, value = line.split(':', 1)
                key = key.strip().lower()
                value = value.strip()
                # 去除引号
                if (value.startswith('"') and value.endswith('"')) or \
                   (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]
                metadata[key] = value
                
    except (ValueError, IndexError):
        return metadata, content
    
    return metadata, remaining_content


# ==================== HTML 后处理 ====================

def clean_residual_image_markers(html_content: str) -> str:
    """清理 HTML 中可能残留的 Markdown 图片标记符号
    
    只清理完整/不完整的 Markdown 图片语法残留，
    不清理裸路径（避免误删正文内容）。
    
    Args:
        html_content: Pandoc 转换后的 HTML
        
    Returns:
        str: 清理后的 HTML
    """
    # 使用预编译正则
    patterns = [
        EpubRegexPatterns.RESIDUAL_IMAGE,
        EpubRegexPatterns.RESIDUAL_IMAGE_PARTIAL,
    ]
    
    for pattern in patterns:
        html_content = pattern.sub('', html_content)
    
    # 压缩多余空行
    html_content = EpubRegexPatterns.MULTI_NEWLINE.sub('\n\n', html_content)
    return html_content


def add_first_line_indent(html_content: str, indent_size: str = '2em') -> str:
    """为 HTML 中的段落添加首行缩进，排除表格/代码块/列表
    
    Args:
        html_content: HTML 内容
        indent_size: 缩进大小（CSS 单位）
        
    Returns:
        str: 处理后的 HTML
    """
    def add_no_indent_class(match):
        """给特定元素内的 <p> 添加 no-indent 类"""
        content = match.group(0)
        content = EpubRegexPatterns.PARAGRAPH.sub(r'<p\1 class="no-indent">', content)
        return content
    
    # 表格、代码块、列表项内的段落不缩进
    html_content = EpubRegexPatterns.TABLE_TAG.sub(add_no_indent_class, html_content)
    html_content = EpubRegexPatterns.PRE_TAG.sub(add_no_indent_class, html_content)
    html_content = EpubRegexPatterns.LI_TAG.sub(add_no_indent_class, html_content)
    
    return html_content


def insert_article_title(html_content: str, metadata: Dict[str, str]) -> Tuple[str, str]:
    """在 HTML 内容开头插入文章标题
    
    Args:
        html_content: HTML 内容
        metadata: 元数据字典（title/author/subtitle/date）
        
    Returns:
        Tuple[str, str]: (处理后的 HTML, 提取的标题文本)
    """
    title = metadata.get('title', '')
    author = metadata.get('author', '')
    subtitle = metadata.get('subtitle', '')
    date = metadata.get('date', '')
    
    if not title:
        return html_content, "未命名文档"
    
    # 构建标题区域 HTML
    title_html = '<div class="article-header">\n'
    title_html += f'<h1 class="article-title">{escape(title)}</h1>\n'
    
    if subtitle:
        title_html += f'<div class="article-subtitle">（{escape(subtitle)}）</div>\n'
    
    if author or date:
        info_parts = []
        if author:
            info_parts.append(f'作者：{escape(author)}')
        if date:
            info_parts.append(f'日期：{escape(date)}')
        title_html += (
            f'<div class="article-author">'
            f'{" | ".join(info_parts)}</div>\n'
        )
    
    title_html += (
        '</div>\n'
        '<hr style="margin: 1em 0 2em 0; border: none; height: 1px; '
        'background: linear-gradient(to right, transparent, #3498db, transparent);" />\n\n'
    )
    
    # 插入到 <body> 内容开头
    body_match = EpubRegexPatterns.BODY_TAG.search(html_content)
    if body_match:
        body_content = body_match.group(1)
        new_body_content = title_html + body_content
        html_content = (
            html_content[:body_match.start(1)] + 
            new_body_content + 
            html_content[body_match.end(1):]
        )
    else:
        html_content = title_html + html_content
    
    return html_content, title


def enhance_html_images(html: str) -> str:
    """增强 HTML 中的图片样式：居中显示 + 阴影 + alt 文本作标题
    
    Args:
        html: HTML 内容
        
    Returns:
        str: 处理后的 HTML
    """
    # 包裹 <img> 到居中容器并添加样式
    html = EpubRegexPatterns.IMG_TAG.sub(
        r'<div style="text-align:center; margin:1.5em 0;">'
        r'<img\1 style="max-width:100%; height:auto; border-radius:4px; '
        r'box-shadow:0 2px 8px rgba(0,0,0,0.1);" /></div>',
        html
    )
    
    # 为有 alt 文本的图片添加标题
    def add_caption(match):
        attrs = match.group(1)
        alt_match = EpubRegexPatterns.IMG_ALT.search(attrs)
        if alt_match and alt_match.group(1):
            caption = (
                f'<div style="font-size:0.85em; color:#666; margin-top:0.5em; '
                f'text-align:center;">{alt_match.group(1)}</div>'
            )
            return f'<img{attrs}>{caption}'
        return f'<img{attrs}>'
    
    html = EpubRegexPatterns.IMG_TAG.sub(add_caption, html)
    return html


# ==================== 目录提取 ====================

def extract_toc_from_html(html: str) -> list:
    """从 HTML 标题标签提取目录结构
    
    Args:
        html: HTML 内容
        
    Returns:
        list: 目录项列表 [{'level': int, 'title': str, 'anchor': str}, ...]
    """
    toc = []
    counts = {}
    
    for match in EpubRegexPatterns.HEADING.finditer(html):
        level = int(match.group(1))
        title = EpubRegexPatterns.HTML_TAG.sub('', match.group(3)).strip()
        anchor = match.group(2)
        
        if not title:
            continue
        
        # 生成锚点 ID
        if not anchor:
            anchor = EpubRegexPatterns.ANCHOR_CLEAN.sub('-', title.lower()).strip('-')
            if not anchor:
                anchor = f'section-{level}'
        
        # 处理重复锚点
        if anchor in counts:
            counts[anchor] += 1
            anchor = f"{anchor}-{counts[anchor]}"
        else:
            counts[anchor] = 1
        
        toc.append({'level': level, 'title': title, 'anchor': anchor})
    
    return toc


# ==================== EPUB 打包 ====================

def build_epub(html: str, output: Path, work_dir: Path, title: str, 
               toc: list, image_files: list, css: str) -> bool:
    """构建 EPUB 文件（ZIP 打包）
    
    生成符合 EPUB 3.0 标准的电子书，同时包含 NCX 目录以兼容 EPUB 2.0 阅读器。
    
    Args:
        html: 正文 HTML 内容
        output: 输出 EPUB 文件路径
        work_dir: 工作目录
        title: 书名
        toc: 目录结构
        image_files: 图片文件名列表
        css: CSS 样式字符串
        
    Returns:
        bool: 打包是否成功
    """
    epub_root = work_dir / 'epub'
    epub_root.mkdir(exist_ok=True)
    (epub_root / 'OEBPS').mkdir(exist_ok=True)
    (epub_root / 'OEBPS' / 'images').mkdir(exist_ok=True)
    (epub_root / 'META-INF').mkdir(exist_ok=True)
    
    # ---- content.html ----
    content_html = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
    <meta charset="UTF-8"/>
    <title>{escape(title)}</title>
    <link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
    <div class="container">
        {html}
    </div>
</body>
</html>'''
    (epub_root / 'OEBPS' / 'content.html').write_text(content_html, encoding='utf-8')
    
    # ---- style.css ----
    (epub_root / 'OEBPS' / 'style.css').write_text(css, encoding='utf-8')
    
    # ---- 复制图片 ----
    img_src = work_dir / "images"
    img_dest = epub_root / 'OEBPS' / 'images'
    if img_src.exists() and image_files:
        for img_file in image_files:
            src = img_src / img_file
            if src.exists():
                shutil.copy2(src, img_dest / img_file)
    
    # ---- content.opf ----
    manifest_items = [
        '<item id="html" href="content.html" media-type="application/xhtml+xml"/>',
        '<item id="css" href="style.css" media-type="text/css"/>',
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
    ]
    
    mime_map = {
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.png': 'image/png', '.gif': 'image/gif', '.svg': 'image/svg+xml'
    }
    for img_file in image_files:
        ext = Path(img_file).suffix.lower()
        mime_type = mime_map.get(ext, 'image/png')
        manifest_items.append(
            f'<item id="img_{Path(img_file).stem}" '
            f'href="images/{img_file}" media-type="{mime_type}"/>'
        )
    
    opf = f'''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
    <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
        <dc:title>{escape(title)}</dc:title>
        <dc:creator>MD2EPUB</dc:creator>
        <dc:language>zh-CN</dc:language>
        <dc:date>{datetime.now().strftime("%Y-%m-%d")}</dc:date>
        <meta property="dcterms:modified">{datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")}</meta>
    </metadata>
    <manifest>
        {chr(10).join(f'    {item}' for item in manifest_items)}
    </manifest>
    <spine toc="ncx">
        <itemref idref="html"/>
    </spine>
</package>'''
    (epub_root / 'OEBPS' / 'content.opf').write_text(opf, encoding='utf-8')
    
    # ---- toc.ncx (EPUB 2.0 兼容) ----
    max_level = max((t['level'] for t in toc), default=1) if toc else 1
    ncx = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN" 
  "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
    <head>
        <meta name="dtb:uid" content="bookid"/>
        <meta name="dtb:depth" content="{max_level}"/>
        <meta name="dtb:totalPageCount" content="0"/>
        <meta name="dtb:maxPageNumber" content="0"/>
    </head>
    <docTitle><text>{escape(title, True)}</text></docTitle>
    <navMap>'''
    
    for i, t in enumerate(toc, 1):
        ncx += f'''
    <navPoint id="navpoint-{i}" playOrder="{i}">
        <navLabel><text>{escape(t['title'], True)}</text></navLabel>
        <content src="content.html#{t['anchor']}"/>
    </navPoint>'''
    
    if not toc:
        ncx += '''
    <navPoint id="navpoint-1" playOrder="1">
        <navLabel><text>内容</text></navLabel>
        <content src="content.html"/>
    </navPoint>'''
    
    ncx += '''
    </navMap>
</ncx>'''
    (epub_root / 'OEBPS' / 'toc.ncx').write_text(ncx, encoding='utf-8')
    
    # ---- container.xml ----
    container = '''<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
    <rootfiles>
        <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
    </rootfiles>
</container>'''
    (epub_root / 'META-INF' / 'container.xml').write_text(container, encoding='utf-8')
    
    # ---- mimetype ----
    (epub_root / 'mimetype').write_text('application/epub+zip')
    
    # ---- ZIP 打包 ----
    try:
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
            # mimetype 必须是第一个条目且不压缩
            zinfo = zipfile.ZipInfo('mimetype')
            zinfo.compress_type = zipfile.ZIP_STORED
            z.writestr(zinfo, 'application/epub+zip')
            
            for root, _, files in os.walk(epub_root):
                for file in files:
                    if file == 'mimetype':
                        continue
                    full_path = Path(root) / file
                    arcname = full_path.relative_to(epub_root)
                    z.write(full_path, arcname)
        return True
    except Exception as e:
        logger.error(f"EPUB 打包失败: {e}")
        return False


# ==================== 图片处理器 ====================

class ImageProcessor:
    """Markdown 图片处理器
    
    负责解析 Markdown 中的本地图片引用、复制图片到临时目录、
    处理重名冲突。
    使用 Set 进行 O(1) 图片名查找。
    """
    
    def __init__(self, md_file: Path, img_dir: Path):
        """初始化图片处理器
        
        Args:
            md_file: Markdown 源文件路径
            img_dir: 图片输出目录
        """
        self.md_file = md_file
        self.img_dir = img_dir
        self.image_files: List[str] = []
        self.processed_count = 0
        self._image_names: Set[str] = set()  # ★ O(1) 查找
    
    def process_markdown_images(self, content: str) -> Tuple[str, int, List[str]]:
        """处理 Markdown 中的图片引用
        
        Args:
            content: Markdown 内容
            
        Returns:
            Tuple[str, int, List[str]]: (处理后的内容, 图片数量, 图片文件名列表)
        """
        matches = list(EpubRegexPatterns.IMAGE_PATTERN.finditer(content))
        
        if not matches:
            return content, 0, []
        
        new_content = content
        for match in reversed(matches):
            alt_text = match.group(1)
            img_path = match.group(2).strip()
            
            # 处理 <url> 格式
            if img_path.startswith('<') and img_path.endswith('>'):
                img_path = img_path[1:-1]
            
            # 跳过网络图片
            if img_path.startswith(('http://', 'https://')):
                continue
            
            # 解析本地路径并复制
            img_src = self._resolve_image_path(img_path)
            if not img_src:
                new_content = new_content[:match.start()] + new_content[match.end():]
                continue
            
            img_name = self._copy_image(img_src)
            if not img_name:
                new_content = new_content[:match.start()] + new_content[match.end():]
                continue
            
            new_img_ref = f'![{alt_text}](images/{img_name})'
            new_content = new_content[:match.start()] + new_img_ref + new_content[match.end():]
        
        return new_content, self.processed_count, self.image_files
    
    def _resolve_image_path(self, img_path: str) -> Optional[Path]:
        """解析图片的完整路径
        
        Args:
            img_path: 相对路径
            
        Returns:
            Optional[Path]: 完整路径，未找到返回 None
        """
        img_src = (self.md_file.parent / img_path).resolve()
        
        if not img_src.exists():
            # 回退到 assets 目录
            assets_path = self.md_file.parent / "assets" / Path(img_path).name
            if assets_path.exists():
                img_src = assets_path
        
        return img_src if img_src.exists() else None
    
    def _copy_image(self, src_path: Path) -> Optional[str]:
        """复制图片到目标目录，处理重名冲突
        
        Args:
            src_path: 源图片路径
            
        Returns:
            Optional[str]: 复制后的文件名，失败返回 None
        """
        try:
            img_name = src_path.name
            
            # ★ 使用 Set 进行 O(1) 重名检查
            if img_name in self._image_names:
                base, ext = os.path.splitext(img_name)
                counter = 1
                while f"{base}_{counter}{ext}" in self._image_names:
                    counter += 1
                img_name = f"{base}_{counter}{ext}"
            
            dest_path = self.img_dir / img_name
            shutil.copy2(src_path, dest_path)
            
            self._image_names.add(img_name)
            self.image_files.append(img_name)
            self.processed_count += 1
            
            return img_name
        except Exception as e:
            logger.warning(f"图片复制失败: {src_path} - {e}")
            return None


# ==================== Mermaid 渲染 ====================

def render_mermaid_to_images(
    content: str, img_dir: Path, log_callback=None
) -> Tuple[str, int, List[str]]:
    """渲染 Mermaid 图表为图片
    
    Args:
        content: Markdown 内容
        img_dir: 图片输出目录
        log_callback: 可选的日志回调函数
        
    Returns:
        Tuple[str, int, List[str]]: (处理后的内容, 渲染数量, 图片文件名列表)
    """
    matches = list(EpubRegexPatterns.MERMAID_BLOCK.finditer(content))
    
    if not matches:
        return content, 0, []
    
    cmd = find_cmd("mmdc") or find_cmd("@mermaid-js/mermaid-cli")
    if not cmd:
        if log_callback:
            log_callback("⚠️ 未找到 Mermaid 渲染器，跳过图表")
        return EpubRegexPatterns.MERMAID_BLOCK.sub('', content), 0, []
    
    new_content = content
    count = 0
    image_files = []
    
    for i, m in enumerate(reversed(matches), 1):
        img_name = f"mermaid_{i:03d}.png"
        img_path = img_dir / img_name
        mermaid_code = m.group(1).strip()
        
        # 写入临时 .mmd 文件
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.mmd', delete=False, encoding='utf-8'
        ) as f:
            f.write(mermaid_code)
            tmp_path = f.name
        
        try:
            success, error_msg = run_cmd(
                cmd + ["-i", tmp_path, "-o", str(img_path),
                       "--backgroundColor", "white", "--scale", "2"]
            )
            if success:
                img_tag = (
                    f'<div class="mermaid-container">'
                    f'<img src="images/{img_name}" class="mermaid-img" alt="Mermaid图表" />'
                    f'</div>'
                )
                new_content = new_content[:m.start()] + img_tag + new_content[m.end():]
                count += 1
                image_files.append(img_name)
            else:
                if log_callback:
                    log_callback(f"⚠️ Mermaid 渲染失败: {error_msg}")
                fallback = (
                    '<div class="mermaid-container">'
                    '<p class="formula-fallback">⚠️ Mermaid图表渲染失败</p>'
                    '</div>'
                )
                new_content = new_content[:m.start()] + fallback + new_content[m.end():]
        except Exception as e:
            logger.warning(f"Mermaid 渲染异常: {e}")
            fallback = (
                '<div class="mermaid-container">'
                '<p class="formula-fallback">⚠️ Mermaid图表渲染失败</p>'
                '</div>'
            )
            new_content = new_content[:m.start()] + fallback + new_content[m.end():]
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    
    return new_content, count, image_files


# ==================== 主转换函数 ====================

def convert_markdown_to_epub(
    md_file: Path, output_epub: Path, work_dir: Path,
    css: str, log_callback=None,
    use_yaml_title: bool = True
) -> Tuple[bool, str]:
    """将 Markdown 文件转换为 EPUB 电子书
    
    Args:
        md_file: Markdown 源文件路径
        output_epub: 输出 EPUB 文件路径
        work_dir: 临时工作目录
        css: EPUB CSS 样式字符串
        log_callback: 可选的日志回调函数
        
    Returns:
        Tuple[bool, str]: (是否成功, 消息)
    """
    pandoc = find_executable("pandoc")
    if not pandoc:
        return False, "未找到 Pandoc，请先安装 Pandoc"
    
    pandoc_cmd = [pandoc]
    
    img_dir = work_dir / "images"
    img_dir.mkdir(exist_ok=True)
    
    try:
        # 1. 读取 Markdown
        if log_callback:
            log_callback("📖 读取 Markdown 文件...")
        
        content = md_file.read_text(encoding='utf-8')
        
        # 2. 提取 YAML 元数据
        metadata, content = extract_frontmatter(content)
        
        # 3. 处理图片
        img_processor = ImageProcessor(md_file, img_dir)
        content, img_count, image_files = img_processor.process_markdown_images(content)
        if log_callback:
            log_callback(f"✅ 图片处理完成: {img_count}个")
        
        # 4. 处理 Mermaid 图表
        mermaid_ok = find_executable("mmdc") is not None or find_executable("npx") is not None
        if mermaid_ok:
            content, mermaid_count, mermaid_files = render_mermaid_to_images(
                content, img_dir, log_callback
            )
            image_files.extend(mermaid_files)
            if log_callback:
                log_callback(f"✅ Mermaid图表: {mermaid_count}个")
        else:
            content = EpubRegexPatterns.MERMAID_BLOCK.sub('', content)
            if log_callback:
                log_callback("⚠️ 未找到 Mermaid 渲染器，已移除图表代码块")
        
        # 5. 写入临时 Markdown
        temp_md = work_dir / "temp.md"
        temp_md = temp_md.resolve()
        temp_md.write_text(content, encoding='utf-8')
        
        # 6. Pandoc 转换
        if log_callback:
            log_callback("🔄 运行 Pandoc 转换...")
        
        html_file = work_dir / "temp.html"
        # 使用短路径（Windows）或确保路径不含特殊字符
        temp_md_str = str(temp_md.resolve())
        html_file_str = str(html_file.resolve())
        cmd = [
            pandoc_cmd[0], temp_md_str, '-o', html_file_str,
            '-f', 'markdown', '-t', 'html5',
            '--mathml', '--standalone', '--wrap=preserve',
            '--resource-path', str(md_file.parent)
        ]
        
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding='utf-8', errors='replace',
            timeout=120, cwd=str(work_dir.resolve()),
            startupinfo=_STARTUP_INFO
        )
        if result.returncode != 0:
            stderr_full = result.stderr.strip() if result.stderr else ""
            stdout_full = result.stdout.strip() if result.stdout else ""
            error_detail = stderr_full or stdout_full or "未知错误"
            cmd_str = ' '.join(cmd)
            logger.debug(f"Pandoc CMD: {cmd_str}")
            logger.debug(f"Pandoc returncode: {result.returncode}")
            logger.debug(f"Pandoc stderr: {stderr_full}")
            logger.debug(f"Pandoc stdout: {stdout_full}")
            return False, f"Pandoc 错误 (code={result.returncode}): {error_detail[:200]}"
        
        # 7. HTML 后处理
        html_content = html_file.read_text(encoding='utf-8')
        body_match = EpubRegexPatterns.BODY_TAG.search(html_content)
        html = body_match.group(1) if body_match else html_content
        
        if log_callback:
            log_callback("🧹 清理残留标记...")
        
        html = clean_residual_image_markers(html)
        html = enhance_html_images(html)
        html = add_first_line_indent(html, indent_size='2em')
        
        # 8. 插入标题
        # html, final_title = insert_article_title(html, metadata)
        
        if use_yaml_title:
            html, final_title = insert_article_title(html, metadata)
        else:
            # 使用文件名作为标题
            final_title = md_file.stem
            # 不在正文中插入标题区域

        # 9. 提取目录
        toc = extract_toc_from_html(html)
        
        # 10. 构建 EPUB
        if log_callback:
            log_callback("🛠️ 构建 EPUB...")
        
        if build_epub(html, output_epub, work_dir, final_title, toc, image_files, css):
            return True, "转换成功"
        return False, "EPUB 构建失败"
        
    except subprocess.TimeoutExpired:
        return False, "Pandoc 转换超时（120秒）"
    except Exception as e:
        logger.error(f"转换异常: {md_file.name} - {e}")
        return False, str(e)


# ==================== 元信息 ====================
__author__ = "YQJ"
__version__ = "1.3.0"
__date__ = "2026.05.17"