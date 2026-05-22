"""DOCX 后处理工具 - 将软回车 (^l) 转换为硬段落 (^p) | 生产级稳定版"""
from pathlib import Path
from docx import Document
from docx.oxml.ns import qn
from lxml import etree
import copy

def fix_soft_line_breaks(docx_path: Path, log_callback=None) -> bool:
    try:
        if log_callback: log_callback("🔧 开始转换软回车为硬段落 (^l → ^p)...")
        doc = Document(docx_path)
        modified_count = 0

        for paragraph in doc.paragraphs:
            p_elem = paragraph._element
            br_nodes = p_elem.findall(f'.//{qn("w:br")}')
            if not br_nodes: continue

            parent_tag = p_elem.getparent().tag
            is_in_body = parent_tag == qn('w:body')

            for br in reversed(br_nodes):
                run = br.getparent()
                if run is None or run.tag != qn('w:r'): continue
                if is_in_body:
                    _split_paragraph_at_br(p_elem, br, run)
                else:
                    run.remove(br)
                modified_count += 1

        if modified_count > 0:
            doc.save(docx_path)
            if log_callback: log_callback(f"✅ 成功处理 {modified_count} 处换行符（拆分/清理）")
            return True
        if log_callback: log_callback("ℹ️ 文档结构规范，无需处理")
        return False
    except Exception as e:
        if log_callback: log_callback(f"⚠️ 后处理跳过: {type(e).__name__}")
        return False

def _split_paragraph_at_br(p_elem, br, run):
    new_p = etree.SubElement(p_elem.getparent(), qn('w:p'))
    pPr = p_elem.find(qn('w:pPr'))
    if pPr is not None:
        new_pPr = copy.deepcopy(pPr)
        numPr = new_pPr.find(qn('w:numPr'))
        if numPr is not None: new_pPr.remove(numPr)  # 移除列表编号防错乱
        new_p.append(new_pPr)

    new_r = etree.SubElement(new_p, qn('w:r'))
    rPr = run.find(qn('w:rPr'))
    if rPr is not None: new_r.append(copy.deepcopy(rPr))

    run_children = list(run)
    try:
        idx = run_children.index(br)
        for child in run_children[idx + 1:]: new_r.append(child)
    except ValueError: pass

    p_children = list(p_elem)
    try:
        r_idx = p_children.index(run)
        for r in p_children[r_idx + 1:]:
            if r.tag == qn('w:r'): new_p.append(r)
    except ValueError: pass

    if br.getparent() is not None: br.getparent().remove(br)
    p_elem.addnext(new_p)