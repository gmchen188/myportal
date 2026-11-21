# -*- coding: utf-8 -*-
r"""myPortal 汇报 PPT 生成器 —— python-pptx 直接构建。

视觉遵循 gmche 已确认的偏好：
  · 硅谷/互联网现代化：深蓝主 #1E40AF + 浅蓝辅 #3B82F6 + 红/橙强调 #D97706 / #C81E1E
  · 右侧栏必须是「图 + 文字」组合，禁止纯文字栏
  · 中文 Microsoft YaHei（不要 PingFang SC）
  · 宁可砍行也不溢出：slide 7.5in 高，安全区 y <= 7.0
"""

from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "demo" / "screenshots"
OUT = ROOT / "Docx" / "myPortal 项目汇报 V1.0.pptx"

# ── 设计令牌 ───────────────────────────────────────────────────────────────
NAVY = RGBColor(0x1E, 0x40, 0xAF)     # 主色
NAVY_DEEP = RGBColor(0x0F, 0x17, 0x2A)  # 封面 / 分隔
BLUE = RGBColor(0x3B, 0x82, 0xF6)     # 辅色
CYAN = RGBColor(0x06, 0xB6, 0xD4)
AMBER = RGBColor(0xD9, 0x77, 0x06)    # 强调
RED = RGBColor(0xC8, 0x1E, 0x1E)      # 严重
GREEN = RGBColor(0x04, 0x78, 0x57)
VIOLET = RGBColor(0x7C, 0x3A, 0xED)
SLATE = RGBColor(0x33, 0x41, 0x55)    # 正文
MUTED = RGBColor(0x64, 0x74, 0x8B)    # 次要文字
LINE = RGBColor(0xDB, 0xEA, 0xFE)     # 边框
BG = RGBColor(0xF8, 0xFA, 0xFC)       # 页面底
CARD = RGBColor(0xFF, 0xFF, 0xFF)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

SEV = {
    "critical": (RGBColor(0xB9, 0x1C, 0x1C), RGBColor(0xFE, 0xF2, 0xF2), RGBColor(0xFE, 0xCA, 0xCA)),
    "high": (RGBColor(0xC2, 0x41, 0x0C), RGBColor(0xFF, 0xF7, 0xED), RGBColor(0xFE, 0xD7, 0xAA)),
    "medium": (RGBColor(0xB4, 0x53, 0x09), RGBColor(0xFF, 0xFB, 0xEB), RGBColor(0xFD, 0xE6, 0x8A)),
    "low": (RGBColor(0x1D, 0x4E, 0xD8), RGBColor(0xEF, 0xF6, 0xFF), RGBColor(0xBF, 0xDB, 0xFE)),
    "ok": (RGBColor(0x15, 0x80, 0x3D), RGBColor(0xF0, 0xFD, 0xF4), RGBColor(0xBB, 0xF7, 0xD0)),
}

FONT = "Microsoft YaHei"
MONO = "Consolas"

W, H = 13.333, 7.5          # 英寸（float）—— rect() 内部会转 EMU
SAFE_BOTTOM = 6.95   # 安全区下边界


# ── 基础绘制工具 ───────────────────────────────────────────────────────────
def blank(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(W), Inches(H))
    bg.fill.solid()
    bg.fill.fore_color.rgb = BG
    bg.line.fill.background()
    bg.shadow.inherit = False
    return s


def rect(s, x, y, w, h, fill=None, line=None, lw=1.0, shape=MSO_SHAPE.RECTANGLE, radius=None):
    sp = s.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    if fill is None:
        sp.fill.background()
    else:
        sp.fill.solid()
        sp.fill.fore_color.rgb = fill
    if line is None:
        sp.line.fill.background()
    else:
        sp.line.color.rgb = line
        sp.line.width = Pt(lw)
    sp.shadow.inherit = False
    if radius is not None and shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        try:
            sp.adjustments[0] = radius
        except Exception:
            pass
    return sp


def _set_run_font(r, name, size, bold, color):
    f = r.font
    f.name = name
    f.size = Pt(size)
    f.bold = bold
    f.color.rgb = color
    # 显式写 latin/ea/cs —— 否则中文会落到回退字体，Windows Office 里字形不一致
    from pptx.oxml.ns import qn
    rPr = r._r.get_or_add_rPr()
    for tag in ("a:latin", "a:ea", "a:cs"):
        el = rPr.find(qn(tag))
        if el is None:
            el = rPr.makeelement(qn(tag), {})
            rPr.append(el)
        el.set("typeface", name)


def text(s, x, y, w, h, runs, size=12, color=SLATE, bold=False, align=PP_ALIGN.LEFT,
         anchor=MSO_ANCHOR.TOP, spacing=1.22, space_after=0, font=FONT):
    """写入一段文字。

    ``runs`` 可以是 str，也可以是 [(文本, 覆盖属性), ...] ——
    **列表里的每一项是同一段内的 run，不是新段落**。
    这一点必须明确：早先把列表当成「每项一段」，
    于是「加粗小标题 + 正文」被拆成两行并互相压字。
    真要分段请传 ``lines=[...]``。
    """
    tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0

    items = [(runs, {})] if isinstance(runs, str) else runs
    p = tf.paragraphs[0]
    p.alignment = items[0][1].get("align", align) if items else align
    p.line_spacing = items[0][1].get("spacing", spacing) if items else spacing
    p.space_after = Pt(items[0][1].get("space_after", space_after) if items else space_after)
    for t, ov in items:
        chunks = str(t).split("\n")
        for ci, chunk in enumerate(chunks):
            if ci > 0:                       # 段内换行 → 软回车
                p._p.append(p._p.makeelement(
                    "{http://schemas.openxmlformats.org/drawingml/2006/main}br", {}))
            if chunk == "":
                continue
            r = p.add_run()
            r.text = chunk
            _set_run_font(r, ov.get("font", font), ov.get("size", size),
                          ov.get("bold", bold), ov.get("color", color))
    return tb


def header(s, title, kicker=None, num=None):
    """页眉：左侧强调竖条 + 标题 + 细分隔线"""
    rect(s, 0.55, 0.46, 0.055, 0.42, fill=AMBER)
    if kicker:
        text(s, 0.72, 0.40, 8.0, 0.24, kicker, size=10.5, color=AMBER, bold=True)
        text(s, 0.72, 0.63, 9.6, 0.42, title, size=23, color=NAVY, bold=True)
    else:
        text(s, 0.72, 0.44, 9.6, 0.46, title, size=23, color=NAVY, bold=True,
             anchor=MSO_ANCHOR.MIDDLE)
    rect(s, 0.55, 1.20, 12.23, 0.012, fill=LINE)
    if num:
        text(s, 12.1, 0.48, 0.7, 0.3, num, size=11, color=MUTED, align=PP_ALIGN.RIGHT, font=MONO)


TOTAL = 13


def footer(s, n=None):
    """页脚。页码按当前页序自动计算 —— 手工维护计数器会全篇停在 01。"""
    idx = n if n is not None else len(s.part.package.presentation_part.presentation.slides._sldIdLst)
    text(s, 0.55, 7.06, 8.0, 0.24, "myPortal · 多租户 Fortinet 安全运营门户", size=9, color=MUTED)
    text(s, 11.6, 7.06, 1.18, 0.24, f"{idx:02d} / {TOTAL}", size=9, color=MUTED,
         align=PP_ALIGN.RIGHT, font=MONO)


def card(s, x, y, w, h, fill=CARD, line=LINE, accent=None, radius=0.06):
    c = rect(s, x, y, w, h, fill=fill, line=line, lw=1.0,
             shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=radius)
    if accent:
        rect(s, x, y, 0.045, h, fill=accent)
    return c


def pic_frame(s, path, x, y, w, h, caption=None):
    """浏览器窗口样式的截图外框"""
    rect(s, x, y, w, h, fill=RGBColor(0xE2, 0xE8, 0xF0), line=LINE,
         shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.02)
    rect(s, x, y, w, 0.24, fill=RGBColor(0xF1, 0xF5, 0xF9))
    for i, c in enumerate([RED, AMBER, GREEN]):
        rect(s, x + 0.09 + i * 0.15, y + 0.075, 0.085, 0.085, fill=c, shape=MSO_SHAPE.OVAL)
    rect(s, x + 0.62, y + 0.055, w - 0.78, 0.13, fill=WHITE, line=LINE,
         shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.3)
    p = s.shapes.add_picture(str(path), Inches(x + 0.012), Inches(y + 0.25),
                             width=Inches(w - 0.024))
    avail = h - 0.25
    if p.height > Inches(avail):
        ratio = Inches(avail) / p.height
        p.height = Inches(avail)
        p.width = int(p.width * ratio)
        p.left = Emu(int(Inches(x + 0.012) + (Inches(w - 0.024) - p.width) / 2))
    if caption:
        text(s, x, y + h + 0.05, w, 0.22, caption, size=9.5, color=MUTED)
    return p


def kpi_tile(s, x, y, w, h, value, unit, label, tone=NAVY, tint=None):
    """大数字 tile —— 右侧栏的「图」元素"""
    card(s, x, y, w, h, fill=tint or CARD, line=LINE, accent=tone)
    text(s, x + 0.22, y + 0.18, w - 0.4, 0.48, value,
         size=30, bold=True, color=tone, font=MONO, spacing=1.0)
    if unit:
        text(s, x + 0.24, y + 0.70, w - 0.4, 0.22, unit, size=9.5, color=MUTED, spacing=1.0)
    text(s, x + 0.24, y + (0.94 if unit else 0.70), w - 0.4, 0.44, label,
         size=10, color=SLATE, spacing=1.18)


def severity_bar(s, x, y, w, h, segs):
    """堆叠条 —— 右侧栏的「图」元素"""
    total = sum(v for _, v, _ in segs)
    cx = x
    for label, v, color in segs:
        seg = w * v / total
        rect(s, cx, y, seg, h, fill=color)
        cx += seg
    # 图例按实际字宽推进，放不下就换行 —— 挤在一行会超出栏宽
    lx, ly = x, y + h + 0.10
    for label, v, color in segs:
        txt = f"{label} {v}"
        adv = sum(0.135 if ord(c) > 0x2E80 else 0.075 for c in txt)
        item_w = 0.2 + adv + 0.16
        if lx > x and lx + item_w > x + w:      # 换行
            lx, ly = x, ly + 0.26
        rect(s, lx, ly + 0.03, 0.13, 0.13, fill=color,
             shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.3)
        text(s, lx + 0.2, ly, item_w, 0.2, txt, size=9.5, color=MUTED)
        lx += item_w
    return ly + 0.26


def pill_matrix(s, x, y, w, items, cols=2, rh=0.34, gap=0.12):
    """严重度 pill 矩阵 —— 右侧栏的「图」元素"""
    cw = (w - gap * (cols - 1)) / cols
    for i, (name, tone, val) in enumerate(items):
        r, c = divmod(i, cols)
        fg, bg, bd = SEV[tone]
        px = x + c * (cw + gap)
        py = y + r * (rh + gap)
        rect(s, px, py, cw, rh, fill=bg, line=bd, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.35)
        rect(s, px + 0.11, py + rh / 2 - 0.045, 0.09, 0.09, fill=fg, shape=MSO_SHAPE.OVAL)
        text(s, px + 0.27, py + 0.075, cw - 0.85, 0.2, name, size=9.5, color=fg, bold=True)
        text(s, px + cw - 0.52, py + 0.07, 0.42, 0.2, str(val), size=9.5, color=fg,
             bold=True, align=PP_ALIGN.RIGHT, font=MONO)


def bullet(s, x, y, w, items, size=11.5, color=SLATE, gap=0.42, marker=AMBER,
           bold_head=True):
    """要点列表：方形标记 + 文字"""
    cy = y
    for it in items:
        head, body = (it if isinstance(it, tuple) else (None, it))
        rect(s, x, cy + 0.075, 0.075, 0.075, fill=marker)
        runs = []
        if head:
            runs.append((head, {"bold": bold_head, "color": NAVY, "size": size}))
            runs.append(("　", {}))
        runs.append((body, {"color": color, "size": size}))
        tb = text(s, x + 0.22, cy, w - 0.22, gap, runs, size=size, spacing=1.3)
        # 行数估算：CJK 全角约 1 个字宽，拉丁约 0.55 —— 用保守值，宁可多留白也不溢出
        body_w = sum(1.0 if ord(c) > 0x2E80 else 0.55 for c in ((head or "") + body))
        chars_per_line = max(8.0, (w - 0.22) * 72.0 / size)
        est = max(1, int(body_w / chars_per_line) + 1)
        # 行高换算：字号单位是 pt，要除以 72 才是英寸 —— 直接乘会把 10.5 当成 10.5 英寸
        cy += max(gap, (size / 72.0) * 1.35 * est + 0.06)
    return cy


# ═══════════════════════════════════════════════════════════════════════════
def build():
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(W), Inches(H)

    # ── 01 封面 ────────────────────────────────────────────────────────────
    s = blank(prs)
    rect(s, 0, 0, W, H, fill=NAVY_DEEP)
    rect(s, 0, 0, 0.28, H, fill=AMBER)
    # 装饰：右上网格圆
    for i, (cx, cy, d, col) in enumerate([(10.2, 0.9, 3.6, RGBColor(0x1E, 0x3A, 0x8A)),
                                          (11.4, 2.6, 2.4, RGBColor(0x1E, 0x40, 0xAF))]):
        rect(s, cx, cy, d, d, fill=col, shape=MSO_SHAPE.OVAL)
    text(s, 1.05, 1.72, 9.2, 0.34, "BINQSOFT　·　船舶网络安全与韧性平台",
         size=12, color=CYAN, bold=True)
    text(s, 1.05, 2.16, 9.4, 0.92, "myPortal",
         size=54, color=WHITE, bold=True, spacing=1.0)
    text(s, 1.05, 3.16, 9.4, 0.52, "多租户 Fortinet 安全运营门户",
         size=25, color=WHITE, bold=True, spacing=1.0)
    rect(s, 1.05, 3.92, 1.5, 0.045, fill=AMBER)
    text(s, 1.05, 4.26, 8.4, 0.78,
         "叠加在 FortiSIEM 之上的运营层 —— 把设备、事件与 IACS UR 合规条款，"
         "按租户、按船重新组织，交给一个看板。",
         size=13.5, color=RGBColor(0xBF, 0xDB, 0xFE), spacing=1.5)
    # 底部三个统计条
    for i, (v, u, l) in enumerate([("12", "艘", "在管船舶"), ("428", "个", "CBS 资产"),
                                   ("78.3K", "", "日均事件 EPS")]):
        bx = 1.05 + i * 2.35
        rect(s, bx, 5.42, 2.12, 0.95, fill=RGBColor(0x1E, 0x29, 0x4B),
             shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.1)
        text(s, bx + 0.20, 5.52, 1.85, 0.42, v,
             size=23, color=WHITE, bold=True, font=MONO, spacing=1.0)
        text(s, bx + 0.20, 5.98, 1.85, 0.24, (u + "　" if u else "") + l,
             size=10, color=RGBColor(0x93, 0xC5, 0xFD), spacing=1.0)
    text(s, 1.05, 6.72, 9.0, 0.28, "版本 V1.0　|　2026-11-18　|　BinQsoft 船舶网络安全与韧性平台",
         size=10.5, color=MUTED)

    # ── 02 汇报提纲 ───────────────────────────────────────────────────────
    s = blank(prs)
    header(s, "汇报提纲", "AGENDA", "02")
    items = [("01", "问题", "FortiSIEM 原生门户的三个结构性缺陷"),
             ("02", "定位", "叠加层架构：数据来自 SIEM，语义来自船舶"),
             ("03", "界面", "七个关键界面的实际效果（可点击原型）"),
             ("04", "隔离", "多租户双道防线与授权模型"),
             ("05", "验证", "实机探测发现的两个真实缺陷"),
             ("06", "路线", "16 周实施节奏与验收口径")]
    for i, (num, t, sub) in enumerate(items):
        col, row = divmod(i, 3)
        x = 0.55 + col * 4.14
        y = 1.62 + row * 1.72
        card(s, x, y, 3.9, 1.44, accent=NAVY if col == 0 else BLUE)
        text(s, x + 0.26, y + 0.22, 1.0, 0.4, num, size=25, color=LINE, bold=True, font=MONO)
        text(s, x + 1.15, y + 0.26, 2.5, 0.3, t, size=15, color=NAVY, bold=True)
        text(s, x + 1.15, y + 0.66, 2.55, 0.62, sub, size=10.5, color=MUTED, spacing=1.32)
    text(s, 0.55, 5.30, 12.2, 0.28, "配套交付物", size=11.5, color=NAVY, bold=True)
    for i, (f, d) in enumerate([("产品设计方案 V1.0.docx", "37 页 · 9 章 · 数据契约与模块设计"),
                                ("项目开发计划 V1.0.docx", "39 页 · 30 个任务 · M0–M8 里程碑"),
                                ("demo/index.html", "23 个界面 · 可点击原型 · 离线可用")]):
        bx = 0.55 + i * 4.14
        card(s, bx, 5.62, 3.9, 0.92, fill=CARD, line=LINE)
        text(s, bx + 0.22, 5.78, 3.5, 0.26, f, size=11, color=NAVY, bold=True, font=MONO)
        text(s, bx + 0.22, 6.08, 3.5, 0.32, d, size=9.5, color=MUTED)
    footer(s)

    # ── 03 问题 ────────────────────────────────────────────────────────────
    s = blank(prs)
    header(s, "FortiSIEM 原生门户的三个结构性缺陷", "问题陈述", "03")
    text(s, 0.55, 1.38, 12.2, 0.28,
         "不是界面不好看的问题，是产品形态的问题 —— 补界面解决不了，只能自建运营层。",
         size=12, color=MUTED)
    probs = [
        ("没有多租户运营视图",
         "SP 模式提供了 Organization 级数据隔离，但没有「一个运营人员同时看 N 个租户」的界面。"
         "要么开 N 个标签页，要么放弃 SIEM 门户自己写工具。", "01", NAVY),
        ("没有面向船队的语义",
         "核心对象是船、CBS、安全区域与 IACS UR 的 12 个管理维度。"
         "SIEM 的 CMDB 不知道「推进系统属于哪个安全区域」。", "02", BLUE),
        ("没有合规视角",
         "船级社检验要的是「某船某模块的完整台账 + 流程文档 + 证据包」，"
         "需要台账模型、文档模板与证据链，而不是事件时间线。", "03", VIOLET),
    ]
    for i, (t, d, num, col) in enumerate(probs):
        x = 0.55 + i * 4.14
        card(s, x, 1.82, 3.9, 2.42, accent=col)
        text(s, x + 0.26, 2.04, 0.8, 0.4, num, size=22, color=LINE, bold=True, font=MONO)
        text(s, x + 0.26, 2.52, 3.4, 0.34, t, size=14.5, color=NAVY, bold=True)
        text(s, x + 0.26, 2.98, 3.4, 1.10, d, size=10.5, color=SLATE, spacing=1.42)
    # 结论条
    rect(s, 0.55, 4.46, 12.23, 0.86, fill=RGBColor(0xEF, 0xF6, 0xFF),
         line=RGBColor(0xBF, 0xDB, 0xFE), shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.1)
    rect(s, 0.55, 4.46, 0.05, 0.86, fill=NAVY)
    text(s, 0.86, 4.62, 11.7, 0.56,
         [("定位：", {"bold": True, "color": NAVY, "size": 12.5}),
          ("myPortal 不是 SIEM 的替代品，而是叠加在 FortiSIEM 之上的运营层 —— "
           "SIEM 负责采集、检测、事件关联；门户负责按租户、按船、按条款重新组织。",
           {"color": SLATE, "size": 12.5})], spacing=1.4)
    # 底部：数据来源与工作量对比
    text(s, 0.55, 5.52, 6.0, 0.26, "为什么不能靠配置解决", size=11.5, color=NAVY, bold=True)
    bullet(s, 0.55, 5.84, 5.9, [
        ("改不了数据模型", "「船 / CBS / 安全区域」不是 FortiSIEM 的对象"),
        ("改不了证据链", "台账快照 + 审计日志 → 证据包需门户侧组装"),
    ], size=10.5, gap=0.34)
    text(s, 6.95, 5.52, 5.8, 0.26, "自建能拿到什么", size=11.5, color=NAVY, bold=True)
    bullet(s, 6.95, 5.84, 5.8, [
        ("租户维度运营", "跨租户聚合视图 + 单租户收敛"),
        ("船队维度语义", "CBS / 安全区域 / UR 条款成为一等公民"),
    ], size=10.5, gap=0.34, marker=GREEN)
    footer(s)

    # ── 04 架构 ────────────────────────────────────────────────────────────
    s = blank(prs)
    header(s, "总体架构：三层，数据与语义分离", "产品定位", "04")
    layers = [
        ("浏览器 SPA", "React 18 · TypeScript · Vite · Tailwind · shadcn/ui",
         "看板编排 · 图表插件 · AI 助手 · i18next · UR 合规模块", NAVY, 1.02),
        ("FastAPI 门户后端", "连接器 · 作用域 · 目录 · 通知 · NLQ · 审计 · 门户侧 MCP",
         "单一凭据工厂 · 元数据驱动注册表 · 固定工具目录 · 只追加审计", BLUE, 2.36),
        ("Fortinet 设备", "FortiSIEM 7.5.1 · FortiAnalyzer 7.6.5 · FortiDeceptor",
         "REST + 原生 MCP（17 工具）· flatui_proxy · 候选路径回退", CYAN, 3.70),
    ]
    for name, stack, detail, col, y in layers:
        card(s, 0.55, y, 8.1, 1.18, fill=CARD, line=LINE, accent=col)
        text(s, 0.85, y + 0.20, 2.5, 0.3, name, size=13.5, color=NAVY, bold=True)
        text(s, 0.85, y + 0.58, 7.6, 0.24, stack, size=10, color=col, font=MONO)
        text(s, 0.85, y + 0.84, 7.6, 0.24, detail, size=10, color=MUTED)
        if y < 3.7:
            text(s, 4.4, y + 1.16, 0.5, 0.22, "▼", size=10, color=LINE)
    # 右侧栏：图 + 文字组合
    text(s, 9.05, 1.02, 3.7, 0.26, "连接器实测状态", size=11.5, color=NAVY, bold=True)
    rows = [("FortiSIEM 7.5.1", "172.16.20.48", "17 工具", "ok"),
            ("FortiAnalyzer 7.6.5", "172.16.21.12", "flatui", "ok"),
            ("FortiDeceptor", "未提供设备", "待确认", "warn")]
    for i, (nme, host, tag, st) in enumerate(rows):
        y = 1.36 + i * 0.66
        card(s, 9.05, y, 3.73, 0.56, fill=CARD, line=LINE)
        fg, bg, bd = SEV["ok"] if st == "ok" else SEV["medium"]
        rect(s, 9.24, y + 0.22, 0.11, 0.11, fill=fg, shape=MSO_SHAPE.OVAL)
        text(s, 9.45, y + 0.10, 2.2, 0.22, nme, size=10.5, color=NAVY, bold=True)
        text(s, 9.45, y + 0.32, 2.2, 0.2, host, size=8.5, color=MUTED, font=MONO)
        text(s, 11.72, y + 0.17, 0.92, 0.22, tag, size=8.5, color=fg, bold=True,
             align=PP_ALIGN.RIGHT, font=MONO)
    text(s, 9.05, 3.48, 3.7, 0.26, "门户自有库只存「自己产生的」", size=11.5, color=NAVY, bold=True)
    for i, t in enumerate(["看板布局 · 告警规则 · 通知通道", "审计日志 · 巡检记录 · NLQ 历史"]):
        y = 3.80 + i * 0.42
        rect(s, 9.05, y, 3.73, 0.34, fill=RGBColor(0xEF, 0xF6, 0xFF),
             line=RGBColor(0xBF, 0xDB, 0xFE), shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.25)
        text(s, 9.22, y + 0.075, 3.4, 0.2, t, size=9.5, color=NAVY)
    text(s, 9.05, 4.72, 3.7, 0.26, "事件与设备明细不复制", size=11.5, color=NAVY, bold=True)
    text(s, 9.05, 5.04, 3.73, 0.9,
         "需要时实时查，避免双写与漂移。门户只存自己产生的数据 —— "
         "每一个数字都能追到接口来源。",
         size=10, color=MUTED, spacing=1.4)
    footer(s)

    # ── 05 界面预览：船队总览 ─────────────────────────────────────────────
    s = blank(prs)
    header(s, "界面预览 · 船队总览面板", "可点击原型", "05")
    pic_frame(s, SHOTS / "02-船队总览面板.png", 0.55, 1.46, 8.55, 5.32)
    text(s, 9.35, 1.46, 3.43, 0.26, "关键指标", size=11.5, color=NAVY, bold=True)
    kpi_tile(s, 9.35, 1.78, 1.64, 1.30, "78.3", "K　日均事件 EPS", "近 7 日实测", NAVY)
    kpi_tile(s, 11.14, 1.78, 1.64, 1.30, "40", "天　许可证到期", "10 项组件", AMBER,
             tint=RGBColor(0xFF, 0xFB, 0xEB))
    text(s, 9.35, 3.22, 3.43, 0.26, "事件严重度分布", size=11.5, color=NAVY, bold=True)
    severity_bar(s, 9.35, 3.56, 3.43, 0.30, [
        ("严重", 3, SEV["critical"][0]), ("高危", 11, SEV["high"][0]),
        ("中危", 37, SEV["medium"][0]), ("低危", 52, SEV["low"][0]),
        ("提示", 19, SEV["neutral"][0]) if "neutral" in SEV else ("提示", 19, MUTED)])
    text(s, 9.35, 4.42, 3.43, 0.26, "Top10 高风险设备", size=11.5, color=NAVY, bold=True)
    top = [("172.16.0.57", 51.07, "high"), ("fortisiem751…", 36.37, "high"),
           ("DC01.goad.lab", 22.10, "medium")]
    for i, (nm, sc, tone) in enumerate(top):
        y = 4.76 + i * 0.40
        text(s, 9.35, y, 1.95, 0.2, nm, size=9.5, color=SLATE, font=MONO)
        bw = 1.05 * (sc / 51.07)
        rect(s, 11.32, y + 0.035, bw, 0.14, fill=SEV[tone][0],
             shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.4)
        text(s, 12.40, y, 0.38, 0.2, f"{sc:.2f}", size=9, color=MUTED,
             align=PP_ALIGN.RIGHT, font=MONO)
    text(s, 9.35, 6.06, 3.43, 0.66,
         "数据来源：MCP get_top_10_risky_devices_incidents（实机探测值）",
         size=9, color=MUTED, spacing=1.35)
    footer(s)

    # ── 06 界面预览：OT + 拓扑 ────────────────────────────────────────────
    s = blank(prs)
    header(s, "界面预览 · OT 安全态势与网络拓扑", "可点击原型", "06")
    pic_frame(s, SHOTS / "11-网络拓扑大图.png", 0.55, 1.46, 6.05, 3.72)
    pic_frame(s, SHOTS / "10-船舶详情.png", 6.78, 1.46, 6.0, 3.72)
    text(s, 0.55, 5.38, 12.2, 0.26, "为什么拓扑要区分「已核验」与「待确认」", size=11.5,
         color=NAVY, bold=True)
    text(s, 0.55, 5.70, 6.0, 0.8,
         "SOC Essential 的业务要求是「工程复核后发布基线，标明已核验和待确认连接」。"
         "连线状态本身就是检验证据的一部分，不能等到出事才补。",
         size=10.5, color=SLATE, spacing=1.42)
    pill_matrix(s, 6.95, 5.66, 5.83, [
        ("已核验连接", "ok", "8 条"), ("待确认连接", "medium", "2 条"),
        ("异常路径", "critical", "1 条"), ("CBS 节点", "low", "11 个")], cols=2)
    footer(s)

    # ── 06b 漏洞管理 ──────────────────────────────────────────────────────
    s = blank(prs)
    header(s, "界面预览 · 漏洞管理（按资产组织）", "可点击原型", "07")
    pic_frame(s, SHOTS / "18-漏洞管理.png", 0.55, 1.46, 8.55, 5.32)
    text(s, 9.35, 1.46, 3.43, 0.26, "为什么 OT 的修复建议不一样", size=11.5, color=NAVY, bold=True)
    text(s, 9.35, 1.78, 3.43, 0.72,
         "互联网侧可以直接打补丁；CBS 不行。", size=12.5, color=NAVY, bold=True, spacing=1.35)
    text(s, 9.35, 2.48, 3.43, 1.10,
         "II / III 类 CBS 有实时性要求，在线打补丁可能影响功能。"
         "多数条目只能落在「仅可缓解」或「不可修复」，"
         "此时真正的工作是：边界白名单 + 基线比对 + 变更管控 + 检验证据登记。",
         size=10, color=SLATE, spacing=1.42)
    text(s, 9.35, 3.72, 3.43, 0.26, "修复可行性分布", size=11.5, color=NAVY, bold=True)
    fix_rows = [("可立即修复", 8, GREEN), ("需安排变更", 3, BLUE),
                ("仅可缓解", 5, AMBER), ("不可修复", 3, RED)]
    for i, (nm, cnt, col) in enumerate(fix_rows):
        y = 4.06 + i * 0.42
        rect(s, 9.35, y + 0.05, 0.11, 0.11, fill=col, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.3)
        text(s, 9.54, y, 1.75, 0.2, nm, size=10.5, color=SLATE)
        text(s, 11.30, y, 1.48, 0.2, f"{cnt} 条", size=10.5, color=col, bold=True,
             align=PP_ALIGN.RIGHT, font=MONO)
    text(s, 9.35, 5.86, 3.43, 0.86,
         "排序依据是「资产关键度 × 可达性」，不是漏洞数量 —— "
         "23 台办公终端上的中危项数量上排第一，"
         "却排在推进系统控制器之后。",
         size=10, color=MUTED, spacing=1.4)
    footer(s)

    # ── 07 界面预览：AI 助手 + 合规 ───────────────────────────────────────
    s = blank(prs)
    header(s, "界面预览 · AI 助手与 UR 合规", "可点击原型", "08")
    pic_frame(s, SHOTS / "06-AI助手.png", 0.55, 1.46, 6.05, 3.72)
    pic_frame(s, SHOTS / "07-UR合规模块.png", 6.78, 1.46, 6.0, 3.72)
    text(s, 0.55, 5.38, 12.2, 0.26, "AI 助手的能力边界 —— 这是设计里最关键的一条", size=11.5,
         color=NAVY, bold=True)
    card(s, 0.55, 5.70, 6.0, 1.10, fill=RGBColor(0xF0, 0xFD, 0xF4),
         line=RGBColor(0xBB, 0xF7, 0xD0), accent=GREEN)
    text(s, 0.85, 5.86, 5.6, 0.22, "模型能做的", size=10.5, color=GREEN, bold=True)
    text(s, 0.85, 6.14, 5.6, 0.56,
         "理解问句 · 选择工具 · 填写参数 · 组织答案 · 给出引用",
         size=10, color=SLATE, spacing=1.4)
    card(s, 6.78, 5.70, 6.0, 1.10, fill=RGBColor(0xFE, 0xF2, 0xF2),
         line=RGBColor(0xFE, 0xCA, 0xCA), accent=RED)
    text(s, 7.08, 5.86, 5.6, 0.22, "模型不能做的", size=10.5, color=RED, bold=True)
    text(s, 7.08, 6.14, 5.6, 0.56,
         "生成 SQL · 指定租户 · 决定过滤条件 · 决定能读哪张表",
         size=10, color=SLATE, spacing=1.4)
    footer(s)

    # ── 08 多租户隔离 ──────────────────────────────────────────────────────
    s = blank(prs)
    header(s, "多租户隔离：两道防线，缺一不可", "安全模型", "09")
    # 第一道
    card(s, 0.55, 1.46, 6.0, 2.16, accent=NAVY)
    text(s, 0.85, 1.66, 1.0, 0.26, "第一道", size=10, color=AMBER, bold=True)
    text(s, 0.85, 1.92, 5.4, 0.3, "上游强制 —— 凭据即边界", size=14, color=NAVY, bold=True)
    text(s, 0.85, 2.30, 5.4, 0.62,
         "每个租户用自己的 FortiSIEM Organization 签发的 Token。"
         "FortiSIEM 在数据层就只返回该组织的数据。",
         size=10.5, color=SLATE, spacing=1.42)
    severity_bar(s, 0.85, 3.02, 5.35, 0.16, [
        ("租户 A", 1, NAVY), ("租户 B", 1, BLUE), ("租户 C", 1, CYAN)])
    # 第二道
    card(s, 6.78, 1.46, 6.0, 2.16, accent=BLUE)
    text(s, 7.08, 1.66, 1.0, 0.26, "第二道", size=10, color=AMBER, bold=True)
    text(s, 7.08, 1.92, 5.4, 0.3, "门户兜底 —— 默认拒绝", size=14, color=NAVY, bold=True)
    text(s, 7.08, 2.30, 5.4, 0.62,
         "按上游报告的组织名匹配；带不出组织归属的记录一律排除；"
         "过滤发生在分页之前。",
         size=10.5, color=SLATE, spacing=1.42)
    severity_bar(s, 7.08, 3.02, 5.35, 0.16, [
        ("已归属", 3, GREEN), ("无归属→排除", 2, RED)])
    # 反例警告
    rect(s, 0.55, 3.80, 12.23, 0.78, fill=RGBColor(0xFE, 0xF2, 0xF2),
         line=RGBColor(0xFE, 0xCA, 0xCA), shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.1)
    rect(s, 0.55, 3.80, 0.05, 0.78, fill=RED)
    text(s, 0.86, 3.94, 11.7, 0.52,
         [("如果只有一道会出事：", {"bold": True, "color": RED, "size": 11.5}),
          ("把 super-global Token 误配给某个租户，该租户会看到整台设备的所有资产与事件 —— "
           "只是被重新贴上了他自己的 tenant_id。不报错，数字看起来还很合理。",
           {"color": SLATE, "size": 11.5})], spacing=1.38)
    # 四条实现规则
    text(s, 0.55, 4.78, 12.2, 0.26, "四条实现规则", size=11.5, color=NAVY, bold=True)
    rules = [("按名匹配，不按 ID", "上游报的是名字\nacme 要匹配 acme (3)"),
             ("默认拒绝", "无组织归属的记录\n在作用域生效时排除"),
             ("过滤在截断之前", "先取全量再过滤再分页\n否则挤掉本租户自己的记录"),
             ("报告被过滤掉了什么", "每个响应带 filtered_out 计数\n运维要能区分边界在工作还是配错了")]
    for i, (t, d) in enumerate(rules):
        x = 0.55 + i * 3.10
        card(s, x, 5.10, 2.93, 1.52, fill=CARD, line=LINE)
        rect(s, x + 0.20, 5.28, 0.26, 0.26, fill=NAVY, shape=MSO_SHAPE.OVAL)
        text(s, x + 0.20, 5.325, 0.26, 0.2, str(i + 1), size=9.5, color=WHITE,
             bold=True, align=PP_ALIGN.CENTER)
        text(s, x + 0.56, 5.30, 2.2, 0.24, t, size=10.5, color=NAVY, bold=True)
        text(s, x + 0.20, 5.72, 2.55, 0.72, d, size=9, color=MUTED, spacing=1.35)
    footer(s)

    # ── 09 实机验证发现 ────────────────────────────────────────────────────
    s = blank(prs)
    header(s, "实机验证发现的两个真实缺陷", "为什么要连真机", "10")
    text(s, 0.55, 1.38, 12.2, 0.28,
         "对照 172.16.20.48 与 172.16.21.12 逐条探测，发现了两处「测试全绿、真机失灵」的问题。",
         size=11.5, color=MUTED)
    # 缺陷一
    card(s, 0.55, 1.80, 6.0, 3.30, accent=RED)
    text(s, 0.85, 1.98, 5.4, 0.3, "缺陷一 · 四处表名在设备上不存在", size=13.5,
         color=NAVY, bold=True)
    text(s, 0.85, 2.34, 5.4, 0.56,
         "代码引用 phoenix_incident / phoenix_device / phoenix_license / phoenix_risk / "
         "phoenix_ueba_risk，真机实测一律返回 Table not allowed。",
         size=10, color=SLATE, spacing=1.38)
    text(s, 0.85, 2.98, 5.4, 0.22, "真表名", size=9.5, color=NAVY, bold=True)
    text(s, 0.85, 3.22, 5.4, 0.26, "ph_incident · ph_device · ph_sys_domain · ph_drq_rule · events",
         size=9.5, color=GREEN, font=MONO)
    rect(s, 0.85, 3.62, 5.4, 1.28, fill=RGBColor(0xFE, 0xF2, 0xF2),
         line=RGBColor(0xFE, 0xCA, 0xCA), shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06)
    text(s, 1.02, 3.76, 5.06, 0.24, "为什么致命", size=10, color=RED, bold=True)
    text(s, 1.02, 4.02, 5.06, 0.78,
         "NLQ 的表白名单只有那五个错名 —— AI 助手的结构化事件日志查询每次调用都被自己的白名单挡下来，"
         "而界面上看起来完全正常。要等用户真正提问时才会暴露。",
         size=9.5, color=SLATE, spacing=1.38)
    # 缺陷二
    card(s, 6.78, 1.80, 6.0, 3.30, accent=AMBER)
    text(s, 7.08, 1.98, 5.4, 0.3, "缺陷二 · mock 与真机契约漂移", size=13.5, color=NAVY, bold=True)
    text(s, 7.08, 2.34, 5.4, 0.56,
         "现有 mock 服务了真机上 404 的路径、用错表名、用 query 而真机要 sql —— "
         "三处偏差让「mock 全绿」与「真机可用」完全脱钩。",
         size=10, color=SLATE, spacing=1.38)
    text(s, 7.08, 2.98, 5.4, 0.22, "三处偏差", size=9.5, color=NAVY, bold=True)
    for i, (a, b) in enumerate([("服务了真机上 404 的路径", "mock 应返回 404"),
                                ("表名用 phoenix_*", "应与真机一致"),
                                ("MCP 参数名 query", "真机要求 sql")]):
        y = 3.24 + i * 0.34
        rect(s, 7.08, y + 0.075, 0.08, 0.08, fill=AMBER)
        text(s, 7.26, y, 2.6, 0.22, a, size=9.5, color=SLATE)
        text(s, 9.95, y, 2.6, 0.22, b, size=9.5, color=GREEN)
    rect(s, 7.08, 4.34, 5.4, 0.56, fill=RGBColor(0xFF, 0xFB, 0xEB),
         line=RGBColor(0xFD, 0xE6, 0x8A), shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08)
    text(s, 7.26, 4.44, 5.06, 0.4,
         "mock 模式恰好是默认 —— 一个从没连过真机的连接器，可以带着一份完美的测试报告交付。",
         size=9.5, color=SLATE, spacing=1.32)
    # 结论
    rect(s, 0.55, 5.30, 12.23, 1.42, fill=RGBColor(0xEF, 0xF6, 0xFF),
         line=RGBColor(0xBF, 0xDB, 0xFE), shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06)
    text(s, 0.85, 5.46, 11.7, 0.26, "因此开发计划里加了两条硬性要求", size=11.5,
         color=NAVY, bold=True)
    for i, (t, d) in enumerate([
        ("表名从实机探测结果派生", "不再手写常量 —— 手写常量就是这次出问题的根因（M0-4）"),
        ("mock ↔ 真机字段集合一致性测试", "同一组查询分别打两侧，断言字段集合一致（M0-3）")]):
        x = 0.85 + i * 6.0
        rect(s, x, 5.80, 0.24, 0.24, fill=NAVY, shape=MSO_SHAPE.OVAL)
        text(s, x, 5.845, 0.24, 0.2, str(i + 1), size=9, color=WHITE, bold=True,
             align=PP_ALIGN.CENTER)
        text(s, x + 0.36, 5.80, 5.4, 0.24, t, size=10.5, color=NAVY, bold=True)
        text(s, x + 0.36, 6.08, 5.4, 0.44, d, size=9.5, color=MUTED, spacing=1.3)
    footer(s)

    # ── 10 实施路线 ────────────────────────────────────────────────────────
    s = blank(prs)
    header(s, "16 周实施节奏", "实施路线", "11")
    # 周期与《项目开发计划》一致：M1–M5 各 2 周，M6 3 周，M7/M8 各 1 周
    ms = [("M0", "基座与契约", 1, 1, NAVY), ("M1", "多租户与认证", 2, 2, NAVY),
          ("M2", "看板与组件目录", 4, 2, BLUE), ("M3", "资产·许可·拓扑", 6, 2, BLUE),
          ("M4", "AI 助手", 8, 2, BLUE), ("M5", "告警与通知", 10, 2, VIOLET),
          ("M6", "UR 合规模块", 12, 3, VIOLET), ("M7", "i18n·审计·巡检", 15, 1, CYAN),
          ("M8", "验收与交付", 16, 1, GREEN)]
    x0, wcol = 2.05, 10.73
    # 标签防重叠：相邻里程碑的名字会挤在一起，按实际字宽检测后错行排布
    def _w_of(txt, size=9.5):
        return sum((size / 72.0) if ord(c) > 0x2E80 else (size / 72.0) * 0.55
                   for c in txt)

    prev_right = -99
    for i, (mid, name, wk, dur, col) in enumerate(ms):
        x = x0 + (wk - 1) / 16 * wcol
        w = dur / 16 * wcol
        rect(s, x, 1.66, w - 0.06, 0.42, fill=col, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.16)
        text(s, x, 1.755, w - 0.06, 0.24, mid, size=10.5, color=WHITE, bold=True,
             align=PP_ALIGN.CENTER, font=MONO)
        lw = _w_of(name) + 0.16
        lx = x + w / 2 - lw / 2
        row = 0 if lx >= prev_right + 0.06 else 1     # 与前一个标签重叠则下移一行
        ly = 2.16 + row * 0.46
        text(s, x - 0.20, ly, w + 0.30, 0.44, name, size=9.5, color=SLATE,
             align=PP_ALIGN.CENTER, spacing=1.25)
        if row == 0:
            prev_right = lx + lw
    # 周刻度
    for wk in range(0, 17, 4):
        x = x0 + wk / 16 * wcol
        text(s, x - 0.2, 3.06, 0.5, 0.2, f"W{wk+1}", size=8.5, color=MUTED,
             align=PP_ALIGN.CENTER, font=MONO)
        rect(s, x, 3.26, 0.008, 0.18, fill=LINE)
    # 关键路径
    text(s, 0.55, 3.30, 12.2, 0.26, "关键路径与前置依赖", size=11.5, color=NAVY, bold=True)
    rect(s, 0.55, 3.60, 12.23, 0.72, fill=RGBColor(0xFF, 0xFB, 0xEB),
         line=RGBColor(0xFD, 0xE6, 0x8A), shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.1)
    rect(s, 0.55, 3.60, 0.05, 0.72, fill=AMBER)
    text(s, 0.86, 3.70, 11.7, 0.54,
         [("设备侧 SP 改造是外部依赖，不在仓库内：", {"bold": True, "color": AMBER, "size": 11.5}),
          ("需在 172.16.20.48 上创建 Organization、组织内 Full Admin 用户、分配 Collector，"
           "由该用户签发 Token。M1 第一天就需要 —— 建议本周就推。",
           {"color": SLATE, "size": 11.5})], spacing=1.38)
    # 验收口径
    text(s, 0.55, 4.50, 12.2, 0.26, "验收口径（不是「看起来正常」）", size=11.5, color=NAVY, bold=True)
    acc = [("空看板 ≠ 验收通过", "每个组件都要在有数据的载荷下渲染过"),
           ("对着实机验收", "mock 模式恰好掩盖字段名错、缺键、载荷不全"),
           ("明确记录证据来自哪次运行", "浏览器可能连的是另一个源"),
           ("按用户的方式导航", "访问令牌只在内存，整页加载会丢会话")]
    for i, (t, d) in enumerate(acc):
        col, row = divmod(i, 2)
        x = 0.55 + col * 6.23
        y = 4.82 + row * 0.86
        card(s, x, y, 6.0, 0.74, fill=CARD, line=LINE)
        rect(s, x, y, 0.045, 0.74, fill=GREEN)
        text(s, x + 0.24, y + 0.14, 5.6, 0.24, t, size=11, color=NAVY, bold=True)
        text(s, x + 0.24, y + 0.42, 5.6, 0.24, d, size=9.5, color=MUTED)
    footer(s)

    # ── 11 交付物 ──────────────────────────────────────────────────────────
    s = blank(prs)
    header(s, "交付物与验收口径", "交付清单", "12")
    text(s, 0.55, 1.38, 12.2, 0.28, "三份交付物已就绪，界面原型可当场演示。",
         size=11.5, color=MUTED)
    items = [
        ("产品设计方案 V1.0.docx", "37 页 · 9 章 · 2 附录",
         "定位与目标 · 总体架构 · 数据源契约（实机验证）· 多租户安全模型 · 功能设计 · "
         "设计系统 · 数据模型 · API 契约 · 实施路线 · GitHub 参照", NAVY),
        ("项目开发计划 V1.0.docx", "39 页 · 6 章 · 30 个任务",
         "M0–M8 九个里程碑 · 每任务写到文件路径与验证命令 · 测试金字塔与十条守卫 · "
         "15 条风险登记册 · 需求到证据的追溯矩阵", BLUE),
        ("demo/index.html", "23 个界面 · 单文件 · 离线可用",
         "登录 · 船队总览 · OT 态势 · 拓扑大图 · 四类 Top10 · 资产清单 · 船舶详情 · "
         "许可证 · AI 助手 · 巡检 · 租户与用户 · 告警规则配置 · 通知通道 · 审计日志 · UR 合规",
         VIOLET),
    ]
    for i, (f, meta, d, col) in enumerate(items):
        y = 1.80 + i * 1.42
        card(s, 0.55, y, 8.1, 1.24, accent=col)
        text(s, 0.88, y + 0.16, 5.0, 0.26, f, size=12.5, color=NAVY, bold=True, font=MONO)
        text(s, 0.88, y + 0.46, 5.0, 0.22, meta, size=9.5, color=col, bold=True)
        text(s, 0.88, y + 0.72, 7.5, 0.44, d, size=9.5, color=MUTED, spacing=1.32)
    # 右侧：证据
    text(s, 9.05, 1.80, 3.73, 0.26, "已验证的证据", size=11.5, color=NAVY, bold=True)
    for i, (v, u, l, tone) in enumerate([("17", "个工具", "FortiSIEM 原生 MCP 实测枚举", NAVY),
                                          ("5", "张表", "PostgreSQL + ClickHouse 实测可查", BLUE),
                                          ("12", "个组件", "FAZ 许可证载荷实测", VIOLET),
                                          ("23", "个界面", "浏览器逐屏验证，零报错", GREEN)]):
        x = 9.05 + (i % 2) * 1.90
        y = 2.14 + (i // 2) * 1.28
        card(s, x, y, 1.78, 1.14, accent=tone)
        text(s, x + 0.20, y + 0.16, 1.5, 0.4,
             [(v, {"size": 22, "bold": True, "color": tone, "font": MONO}),
              (u, {"size": 9, "color": MUTED})])
        text(s, x + 0.20, y + 0.62, 1.5, 0.44, l, size=8.5, color=MUTED, spacing=1.3)
    text(s, 9.05, 4.86, 3.73, 0.26, "尚需外部配合", size=11.5, color=NAVY, bold=True)
    for i, t in enumerate(["设备侧 SP 改造（本周）", "FortiDeceptor 设备与凭据",
                           "LLM 端点与五类通道接入信息"]):
        y = 5.18 + i * 0.46
        rect(s, 9.05, y + 0.085, 0.09, 0.09, fill=AMBER)
        text(s, 9.26, y, 3.5, 0.26, t, size=10.5, color=SLATE)
    footer(s)

    # ── 12 需要决策 ────────────────────────────────────────────────────────
    s = blank(prs)
    header(s, "需要决策的三件事", "下一步", "13")
    decisions = [
        ("01", "设备侧 SP 改造", "本周内完成",
         "在 172.16.20.48 创建 Organization、组织内 Full Admin 用户、分配 Collector，"
         "由该用户签发 Token。", "M1 的前置条件，不做则隔离无法端到端验证", RED),
        ("02", "FortiDeceptor 接入", "本周内确认",
         "提供设备地址与凭据。完整 REST 表面自 6.7.5 起需账号，公开文档无法核实。",
         "本期按非硬依赖设计，不阻塞主线", AMBER),
        ("03", "LLM 与通知通道接入", "开工前到位",
         "OpenAI 兼容端点的 base_url / model / Key，以及五类通道各自的接入信息。",
         "AI 助手与告警投递都依赖它", BLUE),
    ]
    for i, (num, t, when, d, why, col) in enumerate(decisions):
        x = 0.55 + i * 4.14
        card(s, x, 1.52, 3.9, 3.34, accent=col)
        text(s, x + 0.26, 1.72, 1.0, 0.4, num, size=22, color=LINE, bold=True, font=MONO)
        text(s, x + 0.26, 2.16, 3.4, 0.32, t, size=14, color=NAVY, bold=True)
        rect(s, x + 0.26, 2.56, 1.55, 0.30, fill=RGBColor(0xFF, 0xFB, 0xEB),
             line=RGBColor(0xFD, 0xE6, 0x8A), shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.35)
        text(s, x + 0.26, 2.615, 1.55, 0.2, when, size=9, color=AMBER, bold=True,
             align=PP_ALIGN.CENTER)
        text(s, x + 0.26, 3.00, 3.4, 0.86, d, size=10, color=SLATE, spacing=1.42)
        rect(s, x + 0.26, 3.96, 3.4, 0.72, fill=RGBColor(0xF1, 0xF5, 0xF9),
             shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08)
        text(s, x + 0.44, 4.08, 3.05, 0.5, why, size=9, color=MUTED, spacing=1.32)
    # 结尾
    rect(s, 0.55, 5.16, 12.23, 1.44, fill=NAVY_DEEP,
         shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.05)
    text(s, 0.95, 5.38, 11.6, 0.36,
         [("下一步：", {"bold": True, "color": AMBER, "size": 14}),
          ("按 M0 开工 —— 基座迁移、契约测试固化、FAZ 连接器重写、失效表名修正，四件事互不依赖可并行。",
           {"color": WHITE, "size": 14})], spacing=1.3)
    text(s, 0.95, 5.92, 11.6, 0.5,
         "M0 的完成标志：连接器契约测试对着实机全绿；四处失效表名已修正（否则 AI 助手在真机上全哑）；"
         "mock 与真机保真度测试通过。",
         size=11, color=RGBColor(0x93, 0xC5, 0xFD), spacing=1.4)
    footer(s)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(OUT))
    print(f"saved: {OUT}")
    print(f"slides: {len(prs.slides.__iter__.__self__._sldIdLst)}")


if __name__ == "__main__":
    build()
