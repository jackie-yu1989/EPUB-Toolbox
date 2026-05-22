#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MD转EPUB工具 - 独立版本
将 Markdown 文件转换为精美 EPUB 电子书
"""

import sys
import os
import re
import time
import shutil
import tempfile
import zipfile
import subprocess
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from enum import Enum

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QListWidget, QListWidgetItem, QTextEdit,
    QProgressBar, QFileDialog, QGroupBox, QRadioButton, QCheckBox,
    QSpinBox, QComboBox, QLineEdit, QGridLayout, QMessageBox,
    QStatusBar, QFrame, QSplitter, QScrollArea, QButtonGroup
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSettings, QUrl
from PyQt6.QtGui import (
    QFont, QColor, QTextCursor, QDragEnterEvent, QDropEvent
)


# ==================== 元信息 ====================
__author__ = "YQJ"
__version__ = "2.1.0"
__date__ = "2026.04.28"
__app_name__ = "MD转EPUB工具"


# ==================== 通用工具函数 ====================

def find_executable(name: str) -> Optional[str]:
    """查找可执行文件路径"""
    import shutil
    exe_path = shutil.which(name)
    if exe_path:
        return exe_path
    if sys.platform == 'win32':
        if name == 'ebook-convert':
            common_paths = [
                r'C:\Program Files\Calibre2\ebook-convert.exe',
                r'C:\Program Files (x86)\Calibre2\ebook-convert.exe',
                os.path.expanduser(r'~\AppData\Local\Programs\Calibre\ebook-convert.exe'),
            ]
            for path in common_paths:
                if Path(path).exists():
                    return path
    if name in ['mmdc', '@mermaid-js/mermaid-cli']:
        npx_path = shutil.which('npx')
        if npx_path:
            return npx_path
    return None


# 静默启动信息（隐藏控制台窗口）
_STARTUP_INFO = None
if sys.platform == 'win32':
    _STARTUP_INFO = subprocess.STARTUPINFO()
    _STARTUP_INFO.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    _STARTUP_INFO.wShowWindow = subprocess.SW_HIDE


# ==================== 文件状态枚举 ====================
class FileStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    
    @property
    def icon(self) -> str:
        icons = {
            FileStatus.PENDING: "⏳",
            FileStatus.PROCESSING: "🔄",
            FileStatus.SUCCESS: "✅",
            FileStatus.FAILED: "❌"
        }
        return icons.get(self, "📄")


# ==================== 可拖拽文件列表 ====================
class DropFileListWidget(QListWidget):
    files_added = pyqtSignal(list)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.file_paths: Dict[int, Path] = {}
        self.file_status: Dict[int, FileStatus] = {}
        self.completed_files: set = set()
    
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()
    
    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()
    
    def dropEvent(self, event: QDropEvent):
        md_files = []
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if not path.exists():
                continue
            if path.is_file() and path.suffix.lower() == '.md':
                md_files.append(path)
            elif path.is_dir():
                for ext in ['.md', '.MD']:
                    for fp in path.rglob(f"*{ext}"):
                        md_files.append(fp)
        if md_files:
            md_files = list(dict.fromkeys(md_files))
            self.files_added.emit(md_files)
            event.acceptProposedAction()
        else:
            event.ignore()
    
    def reset_all_status(self):
        for path in self.file_paths.values():
            self.update_status(path, FileStatus.PENDING)

    def add_file(self, file_path: Path) -> bool:
        if file_path in self.file_paths.values():
            return False
        index = self.count()
        self.file_paths[index] = file_path
        self.file_status[index] = FileStatus.PENDING
        item = QListWidgetItem(f"{FileStatus.PENDING.icon} {file_path.name}")
        item.setToolTip(str(file_path))
        self.addItem(item)
        return True
    
    def add_files(self, files: List[Path]) -> int:
        added = 0
        for f in files:
            if str(f.absolute()) in self.completed_files:
                continue
            if self.add_file(f):
                added += 1
        return added
    
    def remove_selected(self) -> List[Path]:
        removed = []
        for item in sorted(self.selectedItems(), key=lambda x: self.row(x), reverse=True):
            row = self.row(item)
            if row in self.file_paths:
                removed.append(self.file_paths[row])
                self.completed_files.discard(str(self.file_paths[row].absolute()))
                del self.file_paths[row]
                del self.file_status[row]
            self.takeItem(row)
        self._reindex()
        return removed
    
    def clear_all(self):
        self.clear()
        self.file_paths.clear()
        self.file_status.clear()
        self.completed_files.clear()
    
    def update_status(self, file_path: Path, status: FileStatus):
        colors = {
            FileStatus.SUCCESS: QColor(39, 174, 96),
            FileStatus.FAILED: QColor(231, 76, 60),
            FileStatus.PROCESSING: QColor(52, 152, 219),
            FileStatus.PENDING: QColor(128, 128, 128)
        }
        for index, path in self.file_paths.items():
            if path == file_path:
                self.file_status[index] = status
                if status == FileStatus.SUCCESS:
                    self.completed_files.add(str(file_path.absolute()))
                item = self.item(index)
                if item:
                    base_name = file_path.name
                    for old_icon in ["⏳", "🔄", "✅", "❌"]:
                        base_name = base_name.replace(f"{old_icon} ", "")
                    item.setText(f"{status.icon} {base_name}")
                    item.setForeground(colors.get(status, QColor(0, 0, 0)))
                break
    
    def get_all_files(self) -> List[Path]:
        return list(self.file_paths.values())
    
    def get_pending_files(self) -> List[Path]:
        return [path for idx, path in self.file_paths.items() 
                if self.file_status[idx] == FileStatus.PENDING]
    
    def get_files_by_status(self, status: FileStatus) -> List[Path]:
        return [path for idx, path in self.file_paths.items() 
                if self.file_status.get(idx) == status]
    
    def _reindex(self):
        new_paths = {}
        new_status = {}
        for i in range(self.count()):
            item = self.item(i)
            item_text = item.text()
            for idx, path in self.file_paths.items():
                if path.name in item_text:
                    new_paths[i] = path
                    new_status[i] = self.file_status[idx]
                    break
        self.file_paths = new_paths
        self.file_status = new_status


# ==================== EPUB 构建核心逻辑 ====================

def escape(text: str, xml: bool = False) -> str:
    """转义HTML/XML特殊字符"""
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')
    return text.replace("'", '&apos;' if xml else '&#39;')


def extract_frontmatter(content: str) -> Tuple[Dict[str, str], str]:
    """提取YAML Frontmatter元数据"""
    metadata = {}
    if not content.startswith('---'):
        return metadata, content
    lines = content.split('\n')
    try:
        end = lines.index('---', 1)
        frontmatter_lines = lines[1:end]
        remaining = '\n'.join(lines[end + 1:])
        for line in frontmatter_lines:
            line = line.strip()
            if ':' in line and not line.startswith('#'):
                key, value = line.split(':', 1)
                key, value = key.strip().lower(), value.strip()
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                metadata[key] = value
    except ValueError:
        return metadata, content
    return metadata, remaining


def build_epub(html: str, output: Path, work_dir: Path, title: str, toc: list, 
               image_files: list, css: str) -> bool:
    """构建EPUB文件"""
    epub_root = work_dir / 'epub'
    epub_root.mkdir(exist_ok=True)
    (epub_root / 'OEBPS').mkdir(exist_ok=True)
    (epub_root / 'OEBPS' / 'images').mkdir(exist_ok=True)
    (epub_root / 'META-INF').mkdir(exist_ok=True)
    
    # content.html
    content_html = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><meta charset="UTF-8"/><title>{escape(title)}</title>
<link rel="stylesheet" type="text/css" href="style.css"/></head>
<body><div class="container">{html}</div></body></html>'''
    (epub_root / 'OEBPS' / 'content.html').write_text(content_html, encoding='utf-8')
    (epub_root / 'OEBPS' / 'style.css').write_text(css, encoding='utf-8')
    
    # 图片
    img_src = work_dir / "images"
    img_dest = epub_root / 'OEBPS' / 'images'
    if img_src.exists() and image_files:
        for img_file in image_files:
            src = img_src / img_file
            if src.exists():
                shutil.copy2(src, img_dest / img_file)
    
    # OPF
    manifest_items = [
        '<item id="html" href="content.html" media-type="application/xhtml+xml"/>',
        '<item id="css" href="style.css" media-type="text/css"/>',
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
    ]
    for img_file in image_files:
        ext = Path(img_file).suffix.lower()
        mime_map = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
                    '.gif': 'image/gif', '.svg': 'image/svg+xml'}
        mime_type = mime_map.get(ext, 'image/png')
        manifest_items.append(f'<item id="img_{Path(img_file).stem}" href="images/{img_file}" media-type="{mime_type}"/>')
    
    opf = f'''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:title>{escape(title)}</dc:title><dc:creator>MD2EPUB</dc:creator>
<dc:language>zh-CN</dc:language><dc:date>{datetime.now().strftime("%Y-%m-%d")}</dc:date>
<meta property="dcterms:modified">{datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")}</meta>
</metadata>
<manifest>{chr(10).join(f'    {item}' for item in manifest_items)}</manifest>
<spine toc="ncx"><itemref idref="html"/></spine></package>'''
    (epub_root / 'OEBPS' / 'content.opf').write_text(opf, encoding='utf-8')
    
    # NCX
    max_level = max((t['level'] for t in toc), default=1) if toc else 1
    ncx = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN" "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
<head><meta name="dtb:uid" content="bookid"/><meta name="dtb:depth" content="{max_level}"/>
<meta name="dtb:totalPageCount" content="0"/><meta name="dtb:maxPageNumber" content="0"/></head>
<docTitle><text>{escape(title, True)}</text></docTitle><navMap>'''
    for i, t in enumerate(toc, 1):
        ncx += f'<navPoint id="navpoint-{i}" playOrder="{i}"><navLabel><text>{escape(t["title"], True)}</text></navLabel><content src="content.html#{t["anchor"]}"/></navPoint>'
    if not toc:
        ncx += '<navPoint id="navpoint-1" playOrder="1"><navLabel><text>内容</text></navLabel><content src="content.html"/></navPoint>'
    ncx += '</navMap></ncx>'
    (epub_root / 'OEBPS' / 'toc.ncx').write_text(ncx, encoding='utf-8')
    
    # container.xml
    container = '''<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'''
    (epub_root / 'META-INF' / 'container.xml').write_text(container, encoding='utf-8')
    (epub_root / 'mimetype').write_text('application/epub+zip')
    
    # 打包
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
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


class ImageProcessor:
    """图片处理器"""
    def __init__(self, md_file: Path, img_dir: Path):
        self.md_file = md_file
        self.img_dir = img_dir
        self.image_files: List[str] = []
        self.processed_count = 0
    
    def process_markdown_images(self, content: str) -> Tuple[str, int, List[str]]:
        pattern = r'!\[([^\]]*)\]\(([^)\s]+|<[^>]+>)\)'
        matches = list(re.finditer(pattern, content))
        if not matches:
            return content, 0, []
        new_content = content
        for match in reversed(matches):
            alt_text, img_path = match.group(1), match.group(2).strip()
            if img_path.startswith('<') and img_path.endswith('>'):
                img_path = img_path[1:-1]
            if img_path.startswith(('http://', 'https://')):
                continue
            img_src = self._resolve_image_path(img_path)
            if not img_src:
                new_content = new_content[:match.start()] + new_content[match.end():]
                continue
            img_name = self._copy_image(img_src)
            if not img_name:
                new_content = new_content[:match.start()] + new_content[match.end():]
                continue
            new_content = new_content[:match.start()] + f'![{alt_text}](images/{img_name})' + new_content[match.end():]
        return new_content, self.processed_count, self.image_files
    
    def _resolve_image_path(self, img_path: str) -> Optional[Path]:
        img_src = (self.md_file.parent / img_path).resolve()
        if not img_src.exists():
            assets_path = self.md_file.parent / "assets" / Path(img_path).name
            if assets_path.exists():
                img_src = assets_path
        return img_src if img_src.exists() else None
    
    def _copy_image(self, src_path: Path) -> Optional[str]:
        try:
            img_name = src_path.name
            if img_name in self.image_files:
                base, ext = os.path.splitext(img_name)
                counter = 1
                while f"{base}_{counter}{ext}" in self.image_files:
                    counter += 1
                img_name = f"{base}_{counter}{ext}"
            shutil.copy2(src_path, self.img_dir / img_name)
            self.image_files.append(img_name)
            self.processed_count += 1
            return img_name
        except Exception:
            return None


class MarkdownTitleExtractor:
    """从YAML提取文件名"""
    ILLEGAL_CHARS = r'[<>:"/\\|?*\x00-\x1f]'
    
    def extract_title(self, md_file: Path) -> Optional[str]:
        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                content = f.read(16384)
            match = re.search(r'^[-+]{3}\s*\n(.*?)\n[-+]{3}\s*\n', content, re.DOTALL)
            if not match:
                return None
            yaml_content = match.group(1)
            for field in ['title', '标题', 'name', 'slug', '文件名']:
                pattern = rf'^{re.escape(field)}:\s*["\'\u201c\u201d\u2018\u2019]?(.+?)["\'\u201c\u201d\u2018\u2019]?\s*$'
                m = re.search(pattern, yaml_content, re.MULTILINE | re.IGNORECASE)
                if m:
                    return m.group(1).strip()
            return None
        except Exception:
            return None
    
    def sanitize(self, title: str, max_length: int = 100) -> str:
        if not title:
            return "untitled"
        safe = re.sub(self.ILLEGAL_CHARS, '_', title).strip('. _-')
        safe = re.sub(r'[\s_]+', '_', safe)
        if len(safe) > max_length:
            safe = safe[:max_length].rstrip('._-')
        return safe or "untitled"
    
    def get_unique_name(self, directory: Path, base: str, ext: str = '.md') -> str:
        name = f"{base}{ext}"
        if not (directory / name).exists():
            return name
        counter = 1
        while True:
            name = f"{base}_{counter}{ext}"
            if not (directory / name).exists():
                return name
            counter += 1
    
    def generate_name(self, md_file: Path, output_dir: Path, target_ext: str = '.epub') -> Tuple[str, bool, Optional[str]]:
        title = self.extract_title(md_file)
        if title:
            safe = self.sanitize(title)
            if safe and safe != "untitled":
                name = self.get_unique_name(output_dir, safe, target_ext)
                return name, True, title
        name = f"{md_file.stem}{target_ext}"
        return name, False, None


# ==================== CSS 样式 ====================

COLOR_PRESETS = {
    '蓝色': '#3498db', '绿色': '#27ae60', '紫色': '#9b59b6',
    '橙色': '#e67e22', '红色': '#e74c3c', '青色': '#1abc9c',
    '粉色': '#e84393', '灰色': '#7f8c8d', '深色': '#34495e', '棕色': '#8B4513',
}

def get_css_stereo(primary_color: str = '#3498db') -> str:
    return f"""/* EPUB 排版 - 立体风格 */
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-size:100%;line-height:1.5;color:#2c3e50;background:#fafafa;margin:0;padding:2.5px;font-family:"Iowan Old Style","Sitka Text",Palatino,"Times New Roman","PingFang SC","Microsoft YaHei",serif}}
.container{{max-width:900px;margin:0 auto;background:#fff;padding:0;box-shadow:0 2px 10px rgba(0,0,0,0.05)}}
.article-title{{font-size:2.2em;font-weight:bold;text-align:center;margin:0.5em 0 0.3em;color:#1a1a1a;border-bottom:3px solid {primary_color};padding-bottom:0.3em}}
h1{{font-size:1.7em;border-bottom:3px solid {primary_color};padding-bottom:0.4em;color:#2c3e50}}
h2{{font-size:1.4em;border-left:4px solid {primary_color};padding-left:0.5em;color:#34495e}}
h3{{font-size:1.2em;color:#3b6e8f}}
p{{margin:1em 0;text-align:justify;text-indent:2em}}
code{{font-family:"Fira Code",Consolas,monospace;background:#f4f4f4;padding:0.2em 0.4em;border-radius:3px;font-size:0.9em;color:#e74c3c}}
pre{{background:#2d2d2d;border-left:4px solid {primary_color};padding:1.1em;margin:1.4em 0;overflow-x:auto;border-radius:0 4px 4px 0;color:#f8f8f2}}
pre code{{background:none;padding:0;color:inherit}}
blockquote{{border-left:3px solid {primary_color};margin:1.4em 0;padding-left:1.2em;color:#555;font-style:italic}}
table{{width:100%;border-collapse:collapse;margin:1.5em 0}}
th,td{{border:1px solid #ddd;padding:8px 12px;text-align:left}}
th{{background:{primary_color};color:#fff}}
img{{display:block;margin:1.6em auto;max-width:100%;height:auto;border-radius:6px;box-shadow:0 2px 8px rgba(0,0,0,0.06)}}
"""

def get_css_plain(primary_color: str = '#3498db') -> str:
    return f"""/* EPUB 排版 - 朴素风格 */
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-size:100%;line-height:1.5;color:#000;background:#fff;margin:0;padding:2.5px;font-family:"Iowan Old Style","Sitka Text",Palatino,"Times New Roman","PingFang SC","Microsoft YaHei",serif}}
.container{{max-width:100%;margin:0 auto;background:#fff;padding:0}}
.article-title{{font-size:2.2em;font-weight:bold;text-align:center;margin:0.5em 0 0.3em;color:#000;border-bottom:1px solid #ccc;padding-bottom:0.3em}}
h1{{font-size:1.7em;border-bottom:1px solid #ccc;padding-bottom:0.4em}}
h2{{font-size:1.4em;border-left:3px solid {primary_color};padding-left:0.5em}}
h3{{font-size:1.2em}}
p{{margin:0.8em 0;text-align:justify;text-indent:2em}}
code{{font-family:"Fira Code",Consolas,monospace;background:#f5f5f5;padding:0.2em 0.4em;border-radius:3px;font-size:0.9em;color:#c00;border:1px solid #e0e0e0}}
pre{{background:#f8f8f8;border-left:3px solid {primary_color};padding:0.8em 1em;margin:1em 0;overflow-x:auto;color:#000;border:1px solid #e0e0e0}}
pre code{{background:none;padding:0;color:inherit;border:none}}
blockquote{{border-left:3px solid #ccc;margin:1em 0;padding-left:1em;color:#333;font-style:italic}}
table{{width:100%;border-collapse:collapse;margin:1.2em 0}}
th,td{{border:1px solid #ccc;padding:6px 10px;text-align:left}}
th{{background:{primary_color};color:#fff}}
img{{display:block;margin:1.2em auto;max-width:100%;height:auto}}
"""


# ==================== Pandoc 转换核心 ====================

def convert_markdown_to_epub(md_file: Path, output_epub: Path, work_dir: Path, 
                            css: str, log_callback=None) -> Tuple[bool, str]:
    """使用Pandoc模式转换Markdown到EPUB"""
    pandoc = find_executable("pandoc")
    if not pandoc:
        return False, "未找到 pandoc，请先安装 pandoc"
    
    img_dir = work_dir / "images"
    img_dir.mkdir(exist_ok=True)
    
    try:
        if log_callback:
            log_callback("📖 读取Markdown文件...")
        
        content = md_file.read_text(encoding='utf-8')
        metadata, content = extract_frontmatter(content)
        
        img_processor = ImageProcessor(md_file, img_dir)
        content, img_count, image_files = img_processor.process_markdown_images(content)
        if log_callback:
            log_callback(f"✅ 图片处理完成: {img_count}个")
        
        # Mermaid处理
        mermaid_pattern = r'```(?:mermaid|Mermaid)\s*\n(.*?)\n```'
        mermaid_ok = find_executable("mmdc") or find_executable("npx")
        mermaid_files = []
        if mermaid_ok:
            matches = list(re.finditer(mermaid_pattern, content, re.DOTALL | re.IGNORECASE))
            for i, m in enumerate(reversed(matches), 1):
                img_name = f"mermaid_{i:03d}.png"
                img_path = img_dir / img_name
                code = m.group(1).strip()
                with tempfile.NamedTemporaryFile(mode='w', suffix='.mmd', delete=False, encoding='utf-8') as f:
                    f.write(code)
                tmp_file = f.name
                try:
                    cmd = find_executable("mmdc") or [find_executable("npx"), "@mermaid-js/mermaid-cli"]
                    if cmd:
                        subprocess.run(cmd + ["-i", tmp_file, "-o", str(img_path), "--backgroundColor", "white", "--scale", "2"],
                                     capture_output=True, timeout=60, startupinfo=_STARTUP_INFO)
                        content = content.replace(m.group(0), f'<div class="mermaid-container"><img src="images/{img_name}" class="mermaid-img" alt="Mermaid图表"/></div>')
                        mermaid_files.append(img_name)
                except Exception:
                    content = content.replace(m.group(0), '<p>⚠️ Mermaid图表渲染失败</p>')
                finally:
                    Path(tmp_file).unlink(missing_ok=True)
            image_files.extend(mermaid_files)
            if log_callback:
                log_callback(f"✅ Mermaid图表: {len(mermaid_files)}个")
        else:
            content = re.sub(mermaid_pattern, '', content, flags=re.DOTALL | re.IGNORECASE)
        
        temp_md = work_dir / "temp.md"
        temp_md.write_text(content, encoding='utf-8')
        
        if log_callback:
            log_callback("🔄 运行pandoc转换...")
        
        html_file = work_dir / "temp.html"
        cmd = [pandoc, str(temp_md), '-o', str(html_file),
               '-f', 'markdown', '-t', 'html5', '--mathml', '--standalone',
               '--wrap=preserve', '--resource-path', str(md_file.parent)]
        
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                              timeout=120, cwd=str(work_dir), startupinfo=_STARTUP_INFO)
        if result.returncode != 0:
            return False, f"pandoc错误: {result.stderr}"
        
        html_content = html_file.read_text(encoding='utf-8')
        body_match = re.search(r'<body[^>]*>(.*?)</body>', html_content, re.DOTALL)
        html = body_match.group(1) if body_match else html_content
        
        if log_callback:
            log_callback("🧹 清理残留标记...")
        
        # 清理
        for pat in [r'!\[[^\]]*\]\([^)]*\)', r'\./assets/[^\s<>"\'()]+']:
            html = re.sub(pat, '', html, flags=re.DOTALL)
        html = re.sub(r'<img([^>]+?)>', r'<div style="text-align:center;margin:1.5em 0"><img\1 style="max-width:100%;height:auto;border-radius:4px;box-shadow:0 2px 8px rgba(0,0,0,0.1)"/></div>', html)
        
        # 标题
        final_title = metadata.get('title', '')
        if not final_title:
            final_title = "未命名文档"
        title_html = f'<div class="article-header"><h1 class="article-title">{escape(final_title)}</h1></div>'
        html = title_html + html
        
        # 目录
        toc = []
        for m in re.finditer(r'<h([1-4])[^>]*>(.*?)</h\1>', html, re.IGNORECASE):
            level, title_text = int(m.group(1)), re.sub(r'<[^>]+>', '', m.group(2)).strip()
            if title_text:
                anchor = re.sub(r'[^\w一-鿿]+', '-', title_text.lower()).strip('-')
                toc.append({'level': level, 'title': title_text, 'anchor': anchor})
        
        if log_callback:
            log_callback("🛠️ 构建EPUB...")
        
        if build_epub(html, output_epub, work_dir, final_title, toc, image_files + mermaid_files, css):
            return True, "转换成功"
        return False, "EPUB构建失败"
        
    except subprocess.TimeoutExpired:
        return False, "pandoc转换超时"
    except Exception as e:
        return False, str(e)


# ==================== 工作线程 ====================
class ConversionWorker(QThread):
    progress_updated = pyqtSignal(int, str, int, int)
    file_status_signal = pyqtSignal(Path, str)
    log_message = pyqtSignal(str, str)
    finished_all = pyqtSignal(list)
    
    def __init__(self, files: List[Path], output_mode: str, output_dir: Path = None,
                 css: str = "", max_workers: int = 4, keep_temp: bool = False,
                 rename_by_title: bool = False, auto_open: bool = False):
        super().__init__()
        self.files = files
        self.output_mode = output_mode
        self.output_dir = output_dir
        self.css = css
        self.max_workers = max_workers
        self.keep_temp = keep_temp
        self.rename_by_title = rename_by_title
        self.auto_open = auto_open
        self._is_running = True
        self.results = []
        self.temp_roots = set()
        self.title_extractor = MarkdownTitleExtractor() if rename_by_title else None
    
    def stop(self):
        self._is_running = False
    
    def run(self):
        total = len(self.files)
        self.results = []
        
        self.log_message.emit(f"开始转换 {total} 个文件，并行数: {self.max_workers}", "INFO")
        
        # 预处理文件名
        file_output_map = {}
        rename_count = 0
        
        for f in self.files:
            out_dir = self.output_dir if self.output_mode == "custom" else f.parent
            out_dir.mkdir(parents=True, exist_ok=True)
            
            if self.rename_by_title and self.title_extractor:
                name, title_used, extracted = self.title_extractor.generate_name(f, out_dir, '.epub')
                if title_used:
                    rename_count += 1
                    self.log_message.emit(f"📝 将重命名: {f.name} → {name}", "INFO")
            else:
                name = f"{f.stem}.epub"
                title_used, extracted = False, None
            
            output_path = out_dir / name
            output_path = self._get_unique_path(output_path)
            file_output_map[f] = (output_path, title_used, extracted)
        
        start = time.time()
        completed = 0
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {}
            for f in self.files:
                if not self._is_running:
                    break
                self.file_status_signal.emit(f, 'processing')
                output_path, _, _ = file_output_map[f]
                temp_root = (self.output_dir if self.output_mode == "custom" else f.parent) / ".epub_temp"
                self.temp_roots.add(temp_root)
                temp_root.mkdir(parents=True, exist_ok=True)
                work_dir = temp_root / f"{f.stem}_{int(time.time()*1000)}"
                
                def log_cb(msg):
                    self.log_message.emit(f"   {msg}", "INFO")
                
                future = executor.submit(self._convert_file, f, output_path, work_dir, log_cb)
                futures[future] = f
            
            for future in as_completed(futures):
                if not self._is_running:
                    break
                f = futures[future]
                completed += 1
                
                try:
                    success, msg, elapsed = future.result(timeout=300)
                    output_path, title_used, extracted = file_output_map[f]
                    
                    if success:
                        self.file_status_signal.emit(f, 'success')
                        result = {'file': str(f), 'output': str(output_path), 'status': 'success',
                                  'title_used': title_used, 'original_name': f.name, 'new_name': output_path.name}
                        log_msg = f"✅ [{completed}/{total}] {f.name} → {output_path.name} ({elapsed:.1f}秒)"
                        if title_used:
                            log_msg += f"\n   📝 已重命名（标题: {extracted}）"
                        self.log_message.emit(log_msg, "SUCCESS")
                    else:
                        self.file_status_signal.emit(f, 'failed')
                        result = {'file': str(f), 'status': 'failed', 'message': msg}
                        self.log_message.emit(f"❌ [{completed}/{total}] {f.name}: {msg}", "ERROR")
                    self.results.append(result)
                except Exception as e:
                    self.file_status_signal.emit(f, 'failed')
                    self.log_message.emit(f"❌ {f.name}: {e}", "ERROR")
                    self.results.append({'file': str(f), 'status': 'failed', 'message': str(e)})
                
                self.progress_updated.emit(int(completed/total*100), f"转换中... {completed}/{total}", completed, total)
        
        elapsed = time.time() - start
        self.log_message.emit(f"总耗时: {elapsed:.1f}秒", "INFO")
        
        if self._is_running and self.auto_open:
            self._smart_open()
        
        self.finished_all.emit(self.results)
    
    def _convert_file(self, md_file: Path, output_epub: Path, work_dir: Path, log_cb) -> Tuple[bool, str, float]:
        start = time.time()
        work_dir.mkdir(parents=True, exist_ok=True)
        try:
            success, msg = convert_markdown_to_epub(md_file, output_epub, work_dir, self.css, log_cb)
            return success, msg, time.time() - start
        except Exception as e:
            return False, str(e), time.time() - start
    
    def _get_unique_path(self, path: Path) -> Path:
        if not path.exists():
            try:
                path.touch(exist_ok=False)
                return path
            except FileExistsError:
                pass
        parent, stem, suffix = path.parent, path.stem, path.suffix
        counter = 1
        while counter <= 100:
            new = parent / f"{stem}_{counter}{suffix}"
            if not new.exists():
                try:
                    new.touch(exist_ok=False)
                    return new
                except FileExistsError:
                    pass
            counter += 1
        import uuid
        return parent / f"{stem}_{uuid.uuid4().hex[:8]}{suffix}"
    
    def _smart_open(self):
        dirs = set(f.parent for f in self.files)
        lst = list(dirs)
        if len(lst) == 1:
            self._open_folder(lst[0])
        elif len(lst) <= 3:
            for d in lst:
                self._open_folder(d)
    
    def _open_folder(self, folder: Path):
        if sys.platform == 'win32':
            os.startfile(str(folder))
        elif sys.platform == 'darwin':
            subprocess.run(['open', str(folder)])
        else:
            subprocess.run(['xdg-open', str(folder)])


# ==================== 主窗口 ====================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{__app_name__} v{__version__}")
        self.setMinimumSize(850, 600)
        self.resize(950, 680)
        
        self.settings = QSettings("MD2EPUB", "Settings")
        self.output_dir: Optional[Path] = None
        self.worker: Optional[ConversionWorker] = None
        
        self._setup_ui()
    
    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # ====== 左侧：设置面板（使用滚动区域） ======
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setSpacing(0)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(10)
        scroll_layout.setContentsMargins(10, 10, 10, 10)
        
        # 文件列表
        file_group = QGroupBox("📁 选择Markdown文件 (支持拖拽)")
        file_layout = QVBoxLayout(file_group)
        self.file_list = DropFileListWidget()
        self.file_list.files_added.connect(self._on_files_added)
        file_layout.addWidget(self.file_list)
        
        btn_layout = QHBoxLayout()
        for text, slot in [("➕ 添加文件", self._add_files), ("📂 添加文件夹", self._add_folder),
                        ("❌ 移除选中", self._remove_selected), ("🗑️ 清空全部", self._clear_all)]:
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            btn_layout.addWidget(btn)

        self.cb_force_reprocess = QCheckBox("忽略状态")
        self.cb_force_reprocess.setToolTip(
            "默认情况下，已经转换过的文件不会再次转换。\n"
            "勾选此项后，将重新转换列表中的所有文件。")
        btn_layout.addWidget(self.cb_force_reprocess)

        btn_layout.addStretch()
        file_layout.addLayout(btn_layout)
        scroll_layout.addWidget(file_group)
        
        # 输出设置
        out_group = QGroupBox("📂 输出设置")
        out_layout = QVBoxLayout(out_group)
        mode_layout = QHBoxLayout()
        self.out_source = QRadioButton("与源文件同目录")
        self.out_custom = QRadioButton("统一输出到:")
        self.out_source.setChecked(True)
        mode_layout.addWidget(self.out_source)
        mode_layout.addWidget(self.out_custom)
        mode_layout.addStretch()
        out_layout.addLayout(mode_layout)
        
        dir_layout = QHBoxLayout()
        self.out_dir_edit = QLineEdit()
        self.out_dir_edit.setEnabled(False)
        self.out_dir_edit.setPlaceholderText("请选择输出目录")
        dir_layout.addWidget(self.out_dir_edit)
        browse_btn = QPushButton("浏览...")
        browse_btn.setEnabled(False)
        browse_btn.clicked.connect(self._select_output_dir)
        dir_layout.addWidget(browse_btn)
        out_layout.addLayout(dir_layout)
        self.out_custom.toggled.connect(lambda c: (self.out_dir_edit.setEnabled(c), browse_btn.setEnabled(c)))
        scroll_layout.addWidget(out_group)
        
        # 转换选项
        opt_group = QGroupBox("⚙️ 转换选项")
        opt_layout = QGridLayout()
        opt_layout.setVerticalSpacing(8)
        
        # CSS样式
        opt_layout.addWidget(QLabel("CSS样式:"), 0, 0)
        self.css_plain = QRadioButton("朴素样式")
        self.css_stereo = QRadioButton("立体样式")

        self.css_plain.setChecked(True)
        
        css_hlayout = QHBoxLayout()
        css_hlayout.addWidget(self.css_plain)
        css_hlayout.addWidget(self.css_stereo)

        css_hlayout.addStretch()
        opt_layout.addLayout(css_hlayout, 0, 1, 1, 2)
        
        # 主题颜色
        opt_layout.addWidget(QLabel("主题颜色:"), 1, 0)
        self.color_combo = QComboBox()
        self.color_combo.setFixedWidth(100)
        for name in COLOR_PRESETS.keys():
            self.color_combo.addItem(name)
        self.color_combo.setCurrentText('蓝色')
        opt_layout.addWidget(self.color_combo, 1, 1)
        
        # 颜色预览
        self.color_preview = QLabel("预览")
        self.color_preview.setFixedSize(50, 25)
        self.color_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._update_color_preview()
        self.color_combo.currentTextChanged.connect(self._update_color_preview)
        opt_layout.addWidget(self.color_preview, 1, 2)
        
        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #dcdcdc; margin: 5px 0;")
        opt_layout.addWidget(sep, 2, 0, 1, 3)
        
        # 并行线程数
        opt_layout.addWidget(QLabel("并行线程数:"), 3, 0)
        self.worker_spin = QSpinBox()
        self.worker_spin.setRange(1, 16)
        self.worker_spin.setValue(min(os.cpu_count() or 4, 6))
        self.worker_spin.setFixedWidth(80)
        opt_layout.addWidget(self.worker_spin, 3, 1)
        cpu_label = QLabel(f"(CPU: {os.cpu_count() or 4}核)")
        cpu_label.setStyleSheet("color: #888; font-size: 9pt;")
        opt_layout.addWidget(cpu_label, 3, 2)
        
        # 保留临时文件
        self.cb_keep_temp = QCheckBox("保留临时文件（用于调试）")
        self.cb_keep_temp.setToolTip("勾选后转换过程的中间文件将被保留")
        opt_layout.addWidget(self.cb_keep_temp, 4, 0, 1, 3)
        
        # 自动打开
        self.cb_auto_open = QCheckBox("转换完成后打开输出目录")
        opt_layout.addWidget(self.cb_auto_open, 5, 0, 1, 3)
        
        # YAML标题重命名
        self.cb_rename = QCheckBox("使用YAML标题重命名输出文件")
        self.cb_rename.setToolTip(
            "勾选后，程序将读取Markdown文件的YAML头部信息，\n"
            "提取title字段作为输出EPUB文件名。\n"
            "未找到标题时使用原文件名。"
        )
        opt_layout.addWidget(self.cb_rename, 6, 0, 1, 3)
        
        opt_layout.setColumnStretch(3, 1)
        opt_group.setLayout(opt_layout)
        scroll_layout.addWidget(opt_group)
        
        # 控制按钮
        ctrl_layout = QHBoxLayout()
        self.process_btn = QPushButton("🚀 开始转换")
        self.process_btn.setStyleSheet(
            "background-color: #27ae60; color: white; font-weight: bold; "
            "padding: 10px 25px; border-radius: 6px; font-size: 12pt;"
        )
        self.process_btn.clicked.connect(self._start)
        ctrl_layout.addStretch()
        ctrl_layout.addWidget(self.process_btn)
        self.stop_btn = QPushButton("⏹️ 停止转换")
        self.stop_btn.setStyleSheet(
            "background-color: #e74c3c; color: white; font-weight: bold; "
            "padding: 10px 25px; border-radius: 6px; font-size: 12pt;"
        )
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        ctrl_layout.addWidget(self.stop_btn)
        ctrl_layout.addStretch()
        scroll_layout.addLayout(ctrl_layout)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumHeight(22)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet("""
            QProgressBar { border: 1px solid #dcdcdc; border-radius: 4px; text-align: center; }
            QProgressBar::chunk { background-color: #27ae60; border-radius: 3px; }
        """)
        scroll_layout.addWidget(self.progress_bar)
        
        # 底部弹性空间
        scroll_layout.addStretch()
        
        scroll.setWidget(scroll_content)
        left_layout.addWidget(scroll)
        
        # ====== 右侧：日志面板 ======
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(5, 5, 5, 5)
        
        log_header = QLabel("📋 转换日志")
        log_header.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        right_layout.addWidget(log_header)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 10))
        right_layout.addWidget(self.log_text)
        
        log_toolbar = QHBoxLayout()
        clear_btn = QPushButton("🗑️ 清空")
        clear_btn.clicked.connect(lambda: self.log_text.clear())
        log_toolbar.addWidget(clear_btn)
        save_btn = QPushButton("💾 保存")
        save_btn.clicked.connect(self._save_log)
        log_toolbar.addWidget(save_btn)
        log_toolbar.addStretch()
        right_layout.addLayout(log_toolbar)
        
        main_splitter.addWidget(left)
        main_splitter.addWidget(right)
        main_splitter.setSizes([500, 450])
        
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(main_splitter)
        
        # 状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_label = QLabel("就绪")
        self.status_bar.addWidget(self.status_label)
        self.file_count_label = QLabel("已选择 0 个文件")
        self.status_bar.addPermanentWidget(self.file_count_label) 

    def _update_color_preview(self):
        """更新颜色预览"""
        color_name = self.color_combo.currentText()
        color_code = COLOR_PRESETS.get(color_name, '#3498db')
        r, g, b = int(color_code[1:3], 16), int(color_code[3:5], 16), int(color_code[5:7], 16)
        brightness = (r * 299 + g * 587 + b * 114) / 1000
        text_color = "white" if brightness < 128 else "#333333"
        self.color_preview.setStyleSheet(f"""
            background-color: {color_code};
            border-radius: 4px;
            color: {text_color};
            font-weight: bold;
            font-size: 9pt;
        """)
        self.color_preview.setText(color_name[:4])

    # ====== 文件操作 ======
    def _on_files_added(self, files: List[Path]):
        added = self.file_list.add_files(files)
        if added > 0:
            self._log(f"添加了 {added} 个文件")
        self._update_count()
    
    def _add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "选择Markdown文件", "", "Markdown文件 (*.md);;所有文件 (*.*)")
        if files:
            added = self.file_list.add_files([Path(f) for f in files])
            self._log(f"添加了 {added} 个文件")
            self._update_count()
    
    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择包含Markdown文件的文件夹")
        if folder:
            path = Path(folder)
            md_files = list(path.rglob("*.md")) + list(path.rglob("*.MD"))
            added = self.file_list.add_files(md_files)
            self._log(f"从文件夹添加了 {added} 个文件")
            self._update_count()
    
    def _remove_selected(self):
        removed = self.file_list.remove_selected()
        if removed:
            self._log(f"移除了 {len(removed)} 个文件")
        self._update_count()
    
    def _clear_all(self):
        self.file_list.clear_all()
        self._log("已清空文件列表")
        self._update_count()
    
    def _update_count(self):
        self.file_count_label.setText(f"已选择 {self.file_list.count()} 个文件")
    
    def _select_output_dir(self):
        directory = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if directory:
            self.output_dir = Path(directory)
            self.out_dir_edit.setText(str(self.output_dir))
    
    # ====== 处理逻辑 ======
    def _start(self):
        if self.cb_force_reprocess.isChecked():
            all_files = self.file_list.get_all_files()
            if not all_files:
                QMessageBox.warning(self, "警告", "请先添加文件")
                return
            self.file_list.reset_all_status()
            files = self.file_list.get_all_files()
            self._log(f"🔄 忽略状态模式：将重新转换全部 {len(files)} 个文件", "INFO")
        else:
            files = self.file_list.get_pending_files()
        if not files:
            all_files = self.file_list.get_all_files()
            if all_files:
                failed = self.file_list.get_files_by_status(FileStatus.FAILED)
                if failed:
                    reply = QMessageBox.question(self, "提示", f"有 {len(failed)} 个文件失败，是否重试？",
                                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                    if reply == QMessageBox.StandardButton.Yes:
                        for f in failed:
                            self.file_list.update_status(f, FileStatus.PENDING)
                        files = failed
                    else:
                        return
                else:
                    QMessageBox.information(self, "提示", "所有文件都已转换完成！")
                    return
            else:
                QMessageBox.warning(self, "警告", "请先添加文件")
                return
        
        pandoc = find_executable("pandoc")
        if not pandoc:
            QMessageBox.critical(self, "错误", "未检测到 pandoc，无法进行转换\n请访问 https://pandoc.org/ 下载安装")
            return
        
        if self.out_custom.isChecked() and not self.output_dir:
            QMessageBox.warning(self, "警告", "请选择输出目录")
            return
        
        reply = QMessageBox.question(self, "确认", f"即将转换 {len(files)} 个文件，是否继续？",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        self.process_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        
        output_mode = "custom" if self.out_custom.isChecked() else "source"
        output_dir = self.output_dir if output_mode == "custom" else None
        
        primary_color = COLOR_PRESETS.get(self.color_combo.currentText(), '#3498db')
        css = get_css_stereo(primary_color) if self.css_stereo.isChecked() else get_css_plain(primary_color)
        
        self.worker = ConversionWorker(
            files=files, output_mode=output_mode, output_dir=output_dir,
            css=css, max_workers=self.worker_spin.value(),
            keep_temp=self.cb_keep_temp.isChecked(),
            rename_by_title=self.cb_rename.isChecked(),
            auto_open=self.cb_auto_open.isChecked()
        )
        self.worker.progress_updated.connect(self._on_progress)
        self.worker.file_status_signal.connect(self._on_file_status)
        self.worker.log_message.connect(self._log)
        self.worker.finished_all.connect(self._on_finished)
        self.worker.start()
    
    def _stop(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self._log("正在停止转换...", "WARNING")
            self.stop_btn.setEnabled(False)

        if self.cb_force_reprocess.isChecked():
            self.cb_force_reprocess.setChecked(False)            
    
    def _on_progress(self, value: int, msg: str, completed: int, total: int):
        self.progress_bar.setValue(value)
        self.status_label.setText(f"{msg} - {completed}/{total}")
    
    def _on_file_status(self, file_path: Path, status: str):
        status_map = {'processing': FileStatus.PROCESSING, 'success': FileStatus.SUCCESS,
                      'failed': FileStatus.FAILED, 'pending': FileStatus.PENDING}
        self.file_list.update_status(file_path, status_map.get(status, FileStatus.PENDING))
    
    def _on_finished(self, results: list):
        self.process_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setValue(100)
        
        success = sum(1 for r in results if r['status'] == 'success')
        failed = len(results) - success
        
        self._log("")
        self._log(f"转换完成！成功: {success}, 失败: {failed}", "SUCCESS" if failed == 0 else "WARNING")
        
        if self.cb_rename.isChecked():
            renamed = sum(1 for r in results if r.get('title_used'))
            if renamed > 0:
                self._log(f"📝 YAML重命名: {renamed} 个", "INFO")
        
        self.status_label.setText(f"完成 - 成功: {success}, 失败: {failed}")
        QMessageBox.information(self, "完成", f"转换任务已完成！\n\n成功: {success} 个\n失败: {failed} 个")
    
    def _log(self, msg: str, level: str = "INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        icons = {"INFO": "ℹ️", "SUCCESS": "✅", "WARNING": "⚠️", "ERROR": "❌"}
        colors = {"INFO": "#2c3e50", "SUCCESS": "#27ae60", "WARNING": "#e67e22", "ERROR": "#e74c3c"}
        self.log_text.setTextColor(QColor(colors.get(level, "#2c3e50")))
        self.log_text.append(f"[{timestamp}] {icons.get(level, '📝')} {msg}")
        self.log_text.moveCursor(QTextCursor.MoveOperation.End)
    
    def _save_log(self):
        text = self.log_text.toPlainText()
        if not text:
            QMessageBox.information(self, "提示", "没有日志内容")
            return
        name = f"md2epub_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        path, _ = QFileDialog.getSaveFileName(self, "保存日志", name, "文本文件 (*.txt)")
        if path:
            Path(path).write_text(text, encoding='utf-8')
            self._log(f"日志已保存: {path}", "SUCCESS")


# ==================== 主入口 ====================
def main():
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setApplicationVersion(__version__)
    app.setStyle('Fusion')
    
    # 检查依赖
    if not find_executable("pandoc"):
        QMessageBox.warning(None, "依赖缺失",
            "未检测到 Pandoc！\n\nMD转EPUB功能需要 Pandoc 支持。\n请访问 https://pandoc.org/ 下载安装。\n\n程序仍可启动，但转换功能不可用。")
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()