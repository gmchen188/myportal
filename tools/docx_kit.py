# -*- coding: utf-8 -*-
r"""myPortal 交付文档生成工具箱 —— 共享样式与辅助函数。

视觉规范来源:skill `productivity/docx` 的 references/cjk-report-styling.md。
要点:
  * 正文与标题统一 Microsoft YaHei,必须显式设置 eastAsia 字体
  * 一级/二级标题字色 #1F3A5F,表头底色同色白字,数据行 zebra #F4F7FB
  * 4 色 tip 框 (info/warn/good/safe)
  * 代码块:Consolas + #F4F4F4 底 + 左侧 4pt 深蓝条
  * 目录使用 Word 原生 TOC field,页脚使用 PAGE/NUMPAGES 域
  * 中文正文标点半角→全角归一化 (zh()),代码块绝不经过 zh()
"""

from __future__ import annotations

import re

from docx import Document
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

# ── 调色板 ────────────────────────────────────────────────────────────────
NAVY = "1F3A5F"          # 一级/二级标题、表头底色、代码块左边条
NAVY_RGB = RGBColor(0x1F, 0x3A, 0x5F)
GREY_RGB = RGBColor(0x5A, 0x6A, 0x82)
LIGHT_GREY_RGB = RGBColor(0x80, 0x80, 0x80)
WHITE = "FFFFFF"
ZEBRA = "F4F7FB"
CODE_BG = "F4F4F4"

CJK_FONT = "Microsoft YaHei"
MONO_FONT = "Consolas"

# ── 中文标点归一化 ────────────────────────────────────────────────────────
_CJK = r"一-鿿㐀-䶿"
_MAP = {",": "，", ";": "；", ":": "：", "!": "！", "?": "？"}


def _near_cjk(s: str, i: int) -> bool:
    prev = s[i - 1] if i > 0 else " "
    nxt = s[i + 1] if i + 1 < len(s) else " "
    return bool(re.match("[" + _CJK + "]", prev) or re.match("[" + _CJK + "]", nxt))


def zh(text: str) -> str:
    """半角标点紧邻中文时转全角。代码块绝不经过此函数。"""
    if not text:
        return text
    s = str(text)
    out = list(s)
    stack: list[int] = []
    for i, ch in enumerate(s):
        if ch == "(":
            stack.append(i)
        elif ch == ")" and stack:
            open_at = stack.pop()
            inner = s[open_at + 1 : i]
            inner_has_cjk = bool(re.search("[" + _CJK + "]", inner))
            if _near_cjk(s, open_at) or _near_cjk(s, i) or inner_has_cjk:
                out[open_at] = "\uff08"
                out[i] = "\uff09"
    for i, ch in enumerate(s):
        if ch in _MAP and _near_cjk(s, i):
            out[i] = _MAP[ch]
    return "".join(out)


def zh_tokens(text: str) -> str:
    """对整串跑 zh(),但保留 **粗体** 与 `代码` 片段内部标点原样。

    实现要点:先把 marker 段拼成一个 plain 串整体跑 zh(),再按区间切回。
    code 段在 plain 串里保留汉字(否则 zh() 看不到中文,括号会漏转),
    但 code 段自身的标点记为不可变区间,最后还原原文。
    """
    if not text:
        return text
    parts = re.split(r"(\*\*.+?\*\*|`.+?`)", text)
    plain = ""
    spans: list[tuple[int, int, int]] = []  # (part_index, start, end)
    for idx, part in enumerate(parts):
        start = len(plain)
        plain += part
        spans.append((idx, start, len(plain)))
    converted = zh(plain)
    result = []
    for idx, part in enumerate(parts):
        s, e = spans[idx][1], spans[idx][2]
        if part.startswith("`") and part.endswith("`"):
            result.append(part)          # 代码段原样
        else:
            result.append(converted[s:e])
    return "".join(result)


# ── 基础样式 ──────────────────────────────────────────────────────────────
def init_styles(doc: Document) -> None:
    style = doc.styles["Normal"]
    style.font.name = CJK_FONT
    style.font.size = Pt(10.5)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), CJK_FONT)
    style.paragraph_format.line_spacing = 1.45
    style.paragraph_format.space_after = Pt(6)

    for level, size in [(1, 18), (2, 14), (3, 12), (4, 11)]:
        s = doc.styles[f"Heading {level}"]
        s.font.name = CJK_FONT
        s.font.size = Pt(size)
        s.font.bold = True
        s.font.color.rgb = NAVY_RGB
        s.element.rPr.rFonts.set(qn("w:eastAsia"), CJK_FONT)
        s.paragraph_format.space_before = Pt(14 if level <= 2 else 10)
        s.paragraph_format.space_after = Pt(8 if level <= 2 else 6)

    sec = doc.sections[0]
    sec.top_margin = Cm(2.0)
    sec.bottom_margin = Cm(2.0)
    sec.left_margin = Cm(2.4)
    sec.right_margin = Cm(2.4)


def _font(run, name: str = CJK_FONT, size: float | None = None,
          bold: bool | None = None, color: RGBColor | None = None,
          italic: bool | None = None) -> None:
    run.font.name = name
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic
    if color is not None:
        run.font.color.rgb = color
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    rfonts.set(qn("w:eastAsia"), name)
    rfonts.set(qn("w:ascii"), name)
    rfonts.set(qn("w:hAnsi"), name)


def add_rich_para(container, text: str, size: float = 10.5, bold: bool = False,
                  color: RGBColor | None = None, align=None, space_after: float = 6,
                  indent: float | None = None):
    """支持 **粗体** 与 `代码` 内联标记的段落。"""
    p = container.add_paragraph()
    if align is not None:
        p.alignment = align
    p.paragraph_format.space_after = Pt(space_after)
    if indent is not None:
        p.paragraph_format.left_indent = Cm(indent)
    text = zh_tokens(text)
    for part in re.split(r"(\*\*.+?\*\*|`.+?`)", text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            r = p.add_run(part[2:-2])
            _font(r, size=size, bold=True, color=color)
        elif part.startswith("`") and part.endswith("`"):
            r = p.add_run(part[1:-1])
            _font(r, name=MONO_FONT, size=size - 0.5, color=RGBColor(0x2A, 0x2A, 0x2A))
            r._element.get_or_add_rPr().find(qn("w:rFonts")).set(qn("w:eastAsia"), MONO_FONT)
        else:
            r = p.add_run(part)
            _font(r, size=size, bold=bold, color=color)
    return p


def add_h(doc: Document, text: str, level: int = 1):
    h = doc.add_heading("", level=level)
    r = h.add_run(zh_tokens(text))
    size = {1: 18, 2: 14, 3: 12, 4: 11}[level]
    _font(r, size=size, bold=True, color=NAVY_RGB)
    return h


def add_para(doc: Document, text: str, size: float = 10.5, align=None,
             space_after: float = 6, indent: float | None = None):
    return add_rich_para(doc, text, size=size, align=align,
                         space_after=space_after, indent=indent)


def add_bullets(doc: Document, items: list[str], size: float = 10.5,
                numbered: bool = False, indent: float = 0.6):
    for i, item in enumerate(items, 1):
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(indent + 0.5)
        p.paragraph_format.first_line_indent = Cm(-0.5)
        p.paragraph_format.space_after = Pt(3)
        marker = f"{i}. " if numbered else "• "
        r = p.add_run(marker)
        _font(r, size=size, bold=numbered, color=NAVY_RGB if numbered else None)
        text = zh_tokens(item)
        for part in re.split(r"(\*\*.+?\*\*|`.+?`)", text):
            if not part:
                continue
            if part.startswith("**") and part.endswith("**"):
                rr = p.add_run(part[2:-2])
                _font(rr, size=size, bold=True)
            elif part.startswith("`") and part.endswith("`"):
                rr = p.add_run(part[1:-1])
                _font(rr, name=MONO_FONT, size=size - 0.5,
                      color=RGBColor(0x2A, 0x2A, 0x2A))
            else:
                rr = p.add_run(part)
                _font(rr, size=size)


# ── 表格 ──────────────────────────────────────────────────────────────────
def set_cell_bg(cell, hex_color: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), hex_color)
    tc_pr.append(shd)


def add_table(doc: Document, headers: list[str], rows: list[list[str]],
              widths: list[float] | None = None, font_size: float = 9.5,
              header_size: float | None = None):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr = table.rows[0].cells
    for i, h in enumerate(headers):
        hdr[i].text = ""
        p = hdr[i].paragraphs[0]
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.space_before = Pt(2)
        r = p.add_run(zh_tokens(h))
        _font(r, size=header_size or font_size, bold=True, color=RGBColor(0xFF, 0xFF, 0xFF))
        set_cell_bg(hdr[i], NAVY)
    for r_idx, row in enumerate(rows):
        for c_idx, val in enumerate(row):
            cell = table.rows[r_idx + 1].cells[c_idx]
            cell.text = ""
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.space_before = Pt(2)
            txt = zh_tokens(str(val))
            for part in re.split(r"(\*\*.+?\*\*|`.+?`)", txt):
                if not part:
                    continue
                if part.startswith("**") and part.endswith("**"):
                    rr = p.add_run(part[2:-2])
                    _font(rr, size=font_size, bold=True)
                elif part.startswith("`") and part.endswith("`"):
                    rr = p.add_run(part[1:-1])
                    _font(rr, name=MONO_FONT, size=font_size - 0.5,
                          color=RGBColor(0x2A, 0x2A, 0x2A))
                else:
                    rr = p.add_run(part)
                    _font(rr, size=font_size)
            if r_idx % 2 == 1:
                set_cell_bg(cell, ZEBRA)
    if widths:
        for i, w in enumerate(widths):
            for row in table.rows:
                row.cells[i].width = Cm(w)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return table


def add_wide_table(doc: Document, headers: list[str], rows: list[list[str]],
                   widths: list[float] | None = None, font_size: float = 7.5):
    """>9 列的宽表:插入横向分节,表后恢复纵向。"""
    sec = doc.add_section(WD_SECTION.NEW_PAGE)
    sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width, sec.page_height = sec.page_height, sec.page_width
    sec.left_margin = sec.right_margin = Cm(2.0)
    sec.top_margin = sec.bottom_margin = Cm(1.8)
    t = add_table(doc, headers, rows, widths=None, font_size=font_size,
                  header_size=font_size + 0.5)
    if widths:
        total = sum(widths)
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Cm(w / total * 25.7)
    sec2 = doc.add_section(WD_SECTION.NEW_PAGE)
    sec2.orientation = WD_ORIENT.PORTRAIT
    sec2.page_width, sec2.page_height = sec2.page_height, sec2.page_width
    sec2.left_margin = sec2.right_margin = Cm(2.4)
    sec2.top_margin = sec2.bottom_margin = Cm(2.0)
    return t


# ── tip 框 ────────────────────────────────────────────────────────────────
def add_tip_box(doc: Document, text: str, kind: str = "info"):
    palette = {
        "info": ("E8F1FB", "1F3A5F", "说明"),
        "warn": ("FFF6E0", "A66900", "注意"),
        "good": ("E8F7EC", "1E7E34", "建议"),
        "safe": ("FFF6F0", "C0392B", "安全"),
    }
    bg, fg, label = palette.get(kind, palette["info"])
    table = doc.add_table(rows=1, cols=1)
    cell = table.cell(0, 0)
    set_cell_bg(cell, bg)
    p1 = cell.paragraphs[0]
    p1.paragraph_format.space_after = Pt(2)
    r1 = p1.add_run(f"【{label}】")
    _font(r1, size=10, bold=True, color=RGBColor(int(fg[:2], 16), int(fg[2:4], 16), int(fg[4:], 16)))
    p2 = cell.add_paragraph()
    p2.paragraph_format.space_after = Pt(2)
    # 逐 token 渲染以支持粗体/代码
    txt = zh_tokens(text)
    for part in re.split(r"(\*\*.+?\*\*|`.+?`)", txt):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            rr = p2.add_run(part[2:-2])
            _font(rr, size=10, bold=True)
        elif part.startswith("`") and part.endswith("`"):
            rr = p2.add_run(part[1:-1])
            _font(rr, name=MONO_FONT, size=9.5,
                  color=RGBColor(0x2A, 0x2A, 0x2A))
        else:
            rr = p2.add_run(part)
            _font(rr, size=10)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return table


# ── 代码块 ────────────────────────────────────────────────────────────────
def add_code_block(doc: Document, text: str, label: str | None = None):
    if label:
        p_lbl = doc.add_paragraph()
        p_lbl.paragraph_format.space_after = Pt(2)
        r = p_lbl.add_run(label)
        _font(r, size=9, color=LIGHT_GREY_RGB, italic=True, name=MONO_FONT)
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.3)
    p.paragraph_format.space_after = Pt(6)
    pPr = p._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), CODE_BG)
    pPr.append(shd)
    pBdr = OxmlElement("w:pBdr")
    left_bdr = OxmlElement("w:left")
    left_bdr.set(qn("w:val"), "single")
    left_bdr.set(qn("w:sz"), "24")
    left_bdr.set(qn("w:space"), "4")
    left_bdr.set(qn("w:color"), NAVY)
    pBdr.append(left_bdr)
    pPr.append(pBdr)
    lines = text.split("\n")
    for i, line in enumerate(lines):
        run = p.add_run(line)
        _font(run, name=MONO_FONT, size=9.5, color=RGBColor(0x2A, 0x2A, 0x2A))
        if i < len(lines) - 1:
            run.add_break()
    return p


def add_layer_table(doc: Document, rows: list[tuple[str, str]], label: str | None = None):
    """分层结构图 —— 用原生表格而不是 ASCII 框线。

    ASCII 框线图在 Word 里会错位：CJK 字形由回退字体渲染，其前进宽度不是
    Consolas 的一行的两倍，右边框因此对不齐。原生表格没有这个问题。
    rows: (层名, 该层的内容)
    """
    if label:
        p_lbl = doc.add_paragraph()
        p_lbl.paragraph_format.space_after = Pt(3)
        r = p_lbl.add_run(label)
        _font(r, size=9, color=LIGHT_GREY_RGB, italic=True, name=MONO_FONT)
    table = doc.add_table(rows=len(rows), cols=2)
    table.style = "Table Grid"
    for i, (layer, content) in enumerate(rows):
        c1, c2 = table.rows[i].cells
        c1.width = Cm(3.4)
        c2.width = Cm(12.6)
        for cell, val, bold in ((c1, layer, True), (c2, content, False)):
            cell.text = ""
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.space_before = Pt(2)
            txt = zh_tokens(val)
            for part in re.split(r"(\*\*.+?\*\*|`.+?`)", txt):
                if not part:
                    continue
                if part.startswith("**") and part.endswith("**"):
                    rr = p.add_run(part[2:-2])
                    _font(rr, size=9.5, bold=True, color=NAVY_RGB)
                elif part.startswith("`") and part.endswith("`"):
                    rr = p.add_run(part[1:-1])
                    _font(rr, name=MONO_FONT, size=9,
                          color=RGBColor(0x2A, 0x2A, 0x2A))
                else:
                    rr = p.add_run(part)
                    _font(rr, size=9.5, bold=bold)
        set_cell_bg(c1, ZEBRA if i % 2 else "E8F1FB")
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return table


# ── 封面 / 目录 / 页脚 ────────────────────────────────────────────────────
def add_cover(doc: Document, title: str, subtitle: str, version_line: str,
              org: str = "BinQsoft · 船舶网络安全与韧性平台"):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(80)
    r = p.add_run(zh_tokens(title))
    _font(r, size=26, bold=True, color=NAVY_RGB)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(10)
    r = p.add_run(zh_tokens(subtitle))
    _font(r, size=15, color=GREY_RGB)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(36)
    r = p.add_run(zh_tokens(version_line))
    _font(r, size=10, color=LIGHT_GREY_RGB, italic=True)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(120)
    r = p.add_run(zh_tokens(org))
    _font(r, size=11, color=GREY_RGB)
    doc.add_page_break()


def add_toc_field(doc: Document, title_text: str = "目　录"):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(12)
    p.paragraph_format.space_after = Pt(18)
    r = p.add_run(title_text)
    _font(r, size=20, bold=True, color=NAVY_RGB)

    p = doc.add_paragraph()
    run = p.add_run()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    fld_begin.set(qn("w:dirty"), "true")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = r'TOC \o "1-3" \h \z \u'
    fld_sep = OxmlElement("w:fldChar")
    fld_sep.set(qn("w:fldCharType"), "separate")
    placeholder = OxmlElement("w:t")
    placeholder.text = "【请在 Word 中按 Ctrl+A 后按 F9 更新目录,或右键『更新域』】"
    ph_run = OxmlElement("w:r")
    ph_run.append(placeholder)
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run._r.append(fld_begin)
    run._r.append(instr)
    run._r.append(fld_sep)
    run._r.append(ph_run)
    run._r.append(fld_end)
    doc.add_page_break()


def add_footer_page_numbers(doc: Document, left_text: str = ""):
    """页脚:左侧文档名 + 右侧「第 X 页 / 共 Y 页」域。"""
    for sec in doc.sections:
        footer = sec.footer
        p = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
        p.text = ""
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(zh_tokens(left_text) + "　　")
        _font(r, size=8.5, color=LIGHT_GREY_RGB)
        r2 = p.add_run("第 ")
        _font(r2, size=8.5, color=LIGHT_GREY_RGB)
        _add_field(p, "PAGE")
        r3 = p.add_run(" 页 / 共 ")
        _font(r3, size=8.5, color=LIGHT_GREY_RGB)
        _add_field(p, "NUMPAGES")
        r4 = p.add_run(" 页")
        _font(r4, size=8.5, color=LIGHT_GREY_RGB)


def _add_field(paragraph, code: str):
    run = paragraph.add_run()
    b = OxmlElement("w:fldChar")
    b.set(qn("w:fldCharType"), "begin")
    i = OxmlElement("w:instrText")
    i.set(qn("xml:space"), "preserve")
    i.text = f" {code} "
    e = OxmlElement("w:fldChar")
    e.set(qn("w:fldCharType"), "end")
    run._r.append(b)
    run._r.append(i)
    run._r.append(e)
    _font(run, size=8.5, color=LIGHT_GREY_RGB)


def add_header_text(doc: Document, text: str):
    for sec in doc.sections:
        hp = sec.header.paragraphs[0] if sec.header.paragraphs else sec.header.add_paragraph()
        hp.text = ""
        hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        r = hp.add_run(zh_tokens(text))
        _font(r, size=8.5, color=LIGHT_GREY_RGB)


# ── 验证 ──────────────────────────────────────────────────────────────────
def verify(path: str) -> dict:
    d = Document(path)
    body_texts: list[str] = []
    code_texts: list[str] = []

    def collect(par):
        # 代码块使用 Consolas，其标点必须保持半角（命令要能复制粘贴）
        is_code = any((r.font.name or "") == MONO_FONT for r in par.runs)
        (code_texts if is_code else body_texts).append(par.text)

    for p in d.paragraphs:
        collect(p)
    for t in d.tables:
        for row in t.rows:
            for c in row.cells:
                for p in c.paragraphs:
                    collect(p)
    body = "\n".join(body_texts)
    code = "\n".join(code_texts)
    bad = re.compile(r"[一-鿿][,;:()]|[,;:()][一-鿿]")
    hits = len(bad.findall(body))
    code_hits = len(bad.findall(code))
    malformed_open = bool(re.search(r"\([^)）]*）", body))
    malformed_close = bool(re.search(r"（[^()）]*\)", body))
    headings = [p.text for p in d.paragraphs if p.style.name.startswith("Heading")]
    return {
        "paragraphs": len(d.paragraphs),
        "tables": len(d.tables),
        "headings": len(headings),
        "body_halfwidth_punct_adjacent_cjk": hits,
        "code_block_punct_kept_halfwidth": code_hits,
        "malformed_paren_open": malformed_open,
        "malformed_paren_close": malformed_close,
        "has_toc_field": "TOC" in d.element.xml,
        "outline": headings[:12],
    }
