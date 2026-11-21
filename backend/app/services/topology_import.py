"""
把资产清单里的设备导入成拓扑节点。

## 为什么需要这个

拓扑图上的方块与资产清单里的设备是两套东西：拓扑图存的是「形状 + 标签」，
资产清单存的是「设备 + IP」。两边对不上，FortiSIEM 拉回来的真实事件就落不到
任何节点上 —— 监控面板整张图都是灰色 unknown。

本模块做的事：**用资产清单里的真实资产补一张拓扑图**，并建立绑定：

    device_monitors       （必需 —— 监控面板的事件归集只认这张表）
    topology.node_bindings（同步写一份，两套数据别打架）

绑定一建好，事件按 natural_id / IP 就能点亮节点颜色。

## 几个关键的取舍

**坐标用绝对值，不写 parent。**
draw.io 里的「区域」通常是父容器，子在区域里、坐标相对父容器。但本项目的拓扑
图里区域与设备是**平级的**：现有的 11 个节点都没有 `parent` 属性，区域靠
「设备中心点落在区域矩形内」来认领设备（见 `services/topology_parse.py`）。

如果照 draw.io 的习惯给新节点写 `parent` + 相对坐标，解析器算出来的绝对位置会
落在区域之外，zone 就丢了 —— 前端渲染会坏（这是硬性验收条件）。

所以：**仿照现有节点写** —— 绝对坐标、无 `parent`，新节点中心点落在目标区域
矩形内，解析器就能把它归到那个区域。

**样式复用，不新造。**
XML 顶部有 mxStyle 样式表（zoneBox / dev / devGw / devDmz / linkGreen ...）。
新节点引用这些**已有的名字**，不新增样式名 —— 样式表是这份 XML 的一部分，
前端按名字渲染。

**图里已经有同名的节点就复用它，不画第二个方块。**
资产清单里那 11 台从拓扑图反推出来的设备（FW-EDGE-01 / CBS-NAV-01 ...）本来
就在图上，只是没绑到真实设备上。给它们补绑定比再画一个同名方块正确得多。

**区域放不下就扩区域；实在放不下才落到「导入设备」区。**
扩区域会动到用户画的框，所以只在扩出来不与别的区域/节点重叠时才扩。资产自己
的区域在这张图里不存在时（资产写的是 Zone 4，图里只有 Zone 0-3），放进一个
自动建的「Zone N · 导入设备」区 —— 一个节点都不该因为「没地方放」而丢掉。

## 幂等

同一个资产重复导入不会产生第二个节点：设备已经在本拓扑的 device_monitors 里
（按 natural_id / IP 判重）就跳过；图里已经有同名的节点就复用那个节点并补上
绑定，不画第二个一模一样的方块。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import Asset, DeviceMonitor, Topology
from .topology_parse import parse_topology

# ── 布局常量 ────────────────────────────────────────────────────────────────
# 与现有拓扑图（船队网络拓扑 V1）的实际排布一致：
#   区域左内边距 40 / 上内边距 108（让开标题与副标题）/ 右内边距 80 / 下内边距 52
#   节点 190×60，列距 245（190+55），行距 120（60+60）
NODE_W = 190
NODE_H = 60
PAD_LEFT = 40
PAD_TOP = 108
PAD_RIGHT = 80
PAD_BOTTOM = 52
COL_GAP = 55
ROW_GAP = 60

# 样式名（来自 XML 顶部的 mxStyle 样式表）
STYLE_ZONE = "zoneBox"
STYLE_TITLE = "zoneTitle"
STYLE_SUB = "zoneSub"
STYLE_LINK_CANDIDATES = ("linkGreen", "linkDash", "linkRed")
STYLE_DEVICE_CANDIDATES = ("dev", "devGw", "devDmz")

# 样式表里没有对应名字时的兜底（仍然是复用既有样式名，不新造名字）
FALLBACK_DEVICE_STYLE = "dev"
FALLBACK_ZONE_STYLE = "rounded=1;arcSize=12;fillColor=#ffffff;strokeColor=#d5e2f5;strokeWidth=2;"
FALLBACK_TITLE_STYLE = "text;html=1;align=left;verticalAlign=middle;fontSize=20;fontStyle=1;fontColor=#1a3d8f;"
FALLBACK_SUB_STYLE = "text;html=1;align=left;verticalAlign=middle;fontSize=15;fontColor=#444444;"
FALLBACK_LINK_STYLE = "edgeStyle=orthogonalEdgeStyle;strokeColor=#1a7a1a;strokeWidth=3;endArrow=none;"

# **没有样式表时**（标准 mxfile 惯例：样式直接内联，不建 mxStyle 表），
# 引用样式**名字**是没有意义的 —— draw.io 找不到就画一个没有任何属性的白方块。
# 这时改用内联样式串（值取自本项目样式表里的同一套定义）。
INLINE_DEVICE_STYLE = "rounded=1;arcSize=18;fillColor=#e8eef9;strokeColor=#d5e2f5;strokeWidth=1;fontSize=15;fontStyle=1;fontColor=#1a3d8f;"
INLINE_ZONE_STYLE = "rounded=1;arcSize=12;fillColor=#ffffff;strokeColor=#d5e2f5;strokeWidth=2;verticalAlign=top;align=left;spacingLeft=24;spacingTop=16;"
INLINE_TITLE_STYLE = "text;html=1;align=left;verticalAlign=middle;fontSize=20;fontStyle=1;fontColor=#1a3d8f;"
INLINE_SUB_STYLE = "text;html=1;align=left;verticalAlign=middle;fontSize=15;fontColor=#444444;"
INLINE_LINK_STYLE = "edgeStyle=orthogonalEdgeStyle;strokeColor=#1a7a1a;strokeWidth=3;endArrow=none;"

# 资产区域的 zone 名在图里找不到时用的兜底区域标题
IMPORT_ZONE_SUFFIX = "导入设备"


class TopologyImportError(Exception):
    """导入过程中的可预期错误（路由层转成 400/404）。"""


# ── 小工具 ──────────────────────────────────────────────────────────────────
def _fmt(v: float) -> str:
    """坐标数字格式化：整数不带小数点，和现有 XML 保持一致。"""
    f = float(v)
    return str(int(f)) if f.is_integer() else str(f)


def _esc(v: str) -> str:
    """XML 属性转义。"""
    return (
        str(v or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _style_ref(style: str) -> str:
    """样式引用补上结尾的分号 —— 和现有 XML 的写法一致（``style="dev;"``）。

    draw.io 自己写出来的样式串也带尾分号。这不是功能差别，是**文件风格统一**：
    同一份 XML 里一半带分号一半不带，用户在 draw.io 里打开再保存时看到的是
    两种写法，容易以为哪里坏了。
    """
    s = (style or "").strip()
    if not s:
        return s
    return s if s.endswith(";") else s + ";"


def _norm_key(s: str | None) -> str:
    """把区域名归一成可比对的 key：'Zone 3' → 'zone3'，'Zone 3 · 岸基' → 'zone3'。"""
    text = (s or "").strip()
    m = re.match(r"^(Zone\s*\d+)", text, re.I)
    if m:
        return re.sub(r"\s+", "", m.group(1)).lower()
    return re.sub(r"\s+", "", text.lower())


def _style_names(xml: str) -> set[str]:
    """抽出 XML 里的 mxStyle 样式名。"""
    return {m.group(1) for m in re.finditer(r"<mxStyle\b[^>]*\bname\s*=\s*\"([^\"]+)\"", xml or "")}


def _cell_ids(xml: str) -> set[str]:
    """抽出所有 mxCell 的 id —— 用来给新 cell 起不冲突的名字。

    用正则而不是 ElementTree：这份 XML 可能没有根元素（display_diagram 工具
    产出的裸片段），也可能带 XML 声明，两种都让 ET 不好整篇解析。
    """
    return {m.group(1) for m in re.finditer(r"<mxCell\b[^>]*\bid\s*=\s*\"([^\"]+)\"", xml or "")}


def _rects_overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def _rect_inside(r: tuple[float, float, float, float], box: tuple[float, float, float, float]) -> bool:
    x, y, w, h = r
    bx, by, bw, bh = box
    return x >= bx and y >= by and x + w <= bx + bw and y + h <= by + bh


def _dev_rect(d: dict[str, Any], fallback_w: float, fallback_h: float) -> tuple[float, float, float, float] | None:
    """一个设备节点的矩形。退化节点（没有尺寸）返回 None —— 不参与占位计算。

    **为什么需要这个**：标准 mxfile 里有 `<mxCell id="0"/>` 和 `<mxCell id="1"/>`
    两个根节点，它们没有几何信息。parse_topology 会把它们当成零尺寸的设备节点
    吐出来（这是解析器的既有行为，不改）。如果把它们当作 190×60 的真节点参与
    占位判断，它们会「卡住」区域扩大的判定 —— 区域明明放得下却扩不了。

    注意 `d.get("w") or fallback_w` 这种写法**不能**用：w=0 是 falsy，会被
    悄悄替换成默认宽度，把一个零尺寸节点变成一个 190 宽的节点。
    """
    w = d.get("w")
    h = d.get("h")
    if w is None:
        w = fallback_w
    if h is None:
        h = fallback_h
    w = float(w)
    h = float(h)
    if w <= 0 or h <= 0:
        return None
    return (float(d.get("x") or 0), float(d.get("y") or 0), w, h)


@dataclass
class _Zone:
    """一个区域（zoneBox）+ 它的几何。"""

    id: str
    x: float
    y: float
    w: float
    h: float
    title: str
    key: str
    synthetic: bool = False
    cells: list[str] = field(default_factory=list)

    @property
    def rect(self) -> tuple[float, float, float, float]:
        return (self.x, self.y, self.w, self.h)


@dataclass
class _Layout:
    """一次导入期间的布局工作区。"""

    zones: dict[str, _Zone]
    devices: list[dict[str, Any]]
    cell_ids: set[str]
    style_names: set[str]
    standard: bool
    next_device_no: int
    next_zone_no: int
    next_edge_no: int
    node_w: float = NODE_W
    node_h: float = NODE_H

    def new_device_id(self) -> str:
        while True:
            self.next_device_no += 1
            cid = f"d{self.next_device_no}"
            if cid not in self.cell_ids:
                self.cell_ids.add(cid)
                return cid

    def new_edge_id(self) -> str:
        while True:
            self.next_edge_no += 1
            cid = f"e{self.next_edge_no}"
            if cid not in self.cell_ids:
                self.cell_ids.add(cid)
                return cid

    def new_zone_id(self) -> str:
        while True:
            self.next_zone_no += 1
            cid = f"z{self.next_zone_no}"
            if cid not in self.cell_ids:
                self.cell_ids.add(cid)
                return cid


# ── XML 生成 ────────────────────────────────────────────────────────────────
def _device_cell_xml(cell_id: str, label: str, style: str, x: float, y: float, w: float, h: float,
                     standard: bool) -> str:
    if standard:
        return (
            f'<mxCell id="{_esc(cell_id)}" value="{_esc(label)}" style="{_esc(_style_ref(style))}" '
            f'vertex="1" parent="1">'
            f'<mxGeometry x="{_fmt(x)}" y="{_fmt(y)}" width="{_fmt(w)}" height="{_fmt(h)}" as="geometry"/>'
            f"</mxCell>"
        )
    return (
        f'<mxCell id="{_esc(cell_id)}" value="{_esc(label)}" style="{_esc(_style_ref(style))}" '
        f'x="{_fmt(x)}" y="{_fmt(y)}" w="{_fmt(w)}" h="{_fmt(h)}"/>'
    )


def _edge_cell_xml(cell_id: str, style: str, source: str, target: str, standard: bool) -> str:
    if standard:
        return (
            f'<mxCell id="{_esc(cell_id)}" style="{_esc(_style_ref(style))}" edge="1" '
            f'source="{_esc(source)}" target="{_esc(target)}" parent="1">'
            f'<mxGeometry relative="1" as="geometry"/></mxCell>'
        )
    return (
        f'<mxCell id="{_esc(cell_id)}" style="{_esc(_style_ref(style))}" '
        f'source="{_esc(source)}" target="{_esc(target)}"/>'
    )


def _zone_cell_xml(cell_id: str, style: str, x: float, y: float, w: float, h: float, standard: bool) -> str:
    if standard:
        return (
            f'<mxCell id="{_esc(cell_id)}" value="" style="{_esc(_style_ref(style))}" vertex="1" parent="1">'
            f'<mxGeometry x="{_fmt(x)}" y="{_fmt(y)}" width="{_fmt(w)}" height="{_fmt(h)}" as="geometry"/>'
            f"</mxCell>"
        )
    return (
        f'<mxCell id="{_esc(cell_id)}" value="" style="{_esc(_style_ref(style))}" '
        f'x="{_fmt(x)}" y="{_fmt(y)}" w="{_fmt(w)}" h="{_fmt(h)}"/>'
    )


def _text_cell_xml(cell_id: str, value: str, style: str, x: float, y: float, w: float, h: float,
                   standard: bool) -> str:
    if standard:
        return (
            f'<mxCell id="{_esc(cell_id)}" value="{_esc(value)}" style="{_esc(_style_ref(style))}" '
            f'vertex="1" parent="1">'
            f'<mxGeometry x="{_fmt(x)}" y="{_fmt(y)}" width="{_fmt(w)}" height="{_fmt(h)}" as="geometry"/>'
            f"</mxCell>"
        )
    return (
        f'<mxCell id="{_esc(cell_id)}" value="{_esc(value)}" style="{_esc(_style_ref(style))}" '
        f'x="{_fmt(x)}" y="{_fmt(y)}" w="{_fmt(w)}" h="{_fmt(h)}"/>'
    )


def _insert_cells(xml: str, cells: list[str]) -> str:
    """把新 cell 插进 XML。

    插进去的位置很要紧 —— 插错地方 draw.io 打开就是一张空图：

      · 标准 mxfile   → 插进 ``<root>`` 里（cell 必须是 root 的子元素）
      · 裸片段        → 追加到末尾（没有层级可言）

    注意 ``</root>`` 要优先于 ``</mxGraphModel>``：标准 mxfile 的结构是
    mxfile > diagram > mxGraphModel > root > mxCell。插到 ``</mxGraphModel>``
    前面就跑到 ``</root>`` **外面**去了 —— parse_topology 照样能读出来（它
    全文 iter），但 draw.io 读不出来。
    """
    if not cells:
        return xml
    block = "\n".join(cells)
    if "</root>" in xml:
        idx = xml.rindex("</root>")
        return xml[:idx] + block + "\n" + xml[idx:]
    if "</mxGraphModel>" in xml:
        idx = xml.rindex("</mxGraphModel>")
        return xml[:idx] + block + "\n" + xml[idx:]
    return xml.rstrip() + "\n" + block + "\n"


def _resize_zone(xml: str, zone_id: str, new_w: float, new_h: float) -> str:
    """改一个区域框的宽高（属性式 w/h 或 mxGeometry 式 width/height 都支持）。"""
    pattern = re.compile(
        r"<mxCell\b[^>]*\bid\s*=\s*\"" + re.escape(zone_id) + r"\"[^>]*?(?:/>|>.*?</mxCell>)",
        re.S,
    )
    m = pattern.search(xml or "")
    if not m:
        return xml
    block = m.group(0)
    head_end = block.find(">")
    head = block[:head_end]
    body = block[head_end:]

    if re.search(r"\bw\s*=", head) and re.search(r"\bh\s*=", head):
        new_head = re.sub(r"\bw\s*=\s*\"[^\"]*\"", f'w="{_fmt(new_w)}"', head)
        new_head = re.sub(r"\bh\s*=\s*\"[^\"]*\"", f'h="{_fmt(new_h)}"', new_head)
        return xml[: m.start()] + new_head + body + xml[m.end():]

    if re.search(r"\bwidth\s*=", body):
        new_body = re.sub(r"\bwidth\s*=\s*\"[^\"]*\"", f'width="{_fmt(new_w)}"', body, count=1)
        new_body = re.sub(r"\bheight\s*=\s*\"[^\"]*\"", f'height="{_fmt(new_h)}"', new_body, count=1)
        return xml[: m.start()] + head + new_body + xml[m.end():]

    return xml


# ── 区域解析与匹配 ──────────────────────────────────────────────────────────
def _zones_from_graph(graph: dict[str, Any]) -> dict[str, _Zone]:
    """从解析结果里取出区域（zoneBox 或「大而空」的框），并算出可用的 key。"""
    zones: dict[str, _Zone] = {}
    for z in graph.get("zones") or []:
        title = (z.get("title") or z.get("label") or z.get("id") or "").strip()
        zones[z["id"]] = _Zone(
            id=z["id"],
            x=float(z.get("x") or 0),
            y=float(z.get("y") or 0),
            w=float(z.get("w") or 0),
            h=float(z.get("h") or 0),
            title=title,
            key=_norm_key(title),
        )
    return zones


def _match_zone(zones: dict[str, _Zone], wanted: str | None) -> _Zone | None:
    """按 id / 区域 key / 区域标题 / 标题片段匹配一个区域。"""
    if not wanted:
        return None
    raw = str(wanted).strip()
    if not raw:
        return None
    for z in zones.values():
        if z.id == raw:
            return z
    key = _norm_key(raw)
    for z in zones.values():
        if z.key and z.key == key:
            return z
    norm = re.sub(r"\s+", "", raw.lower())
    for z in zones.values():
        if re.sub(r"\s+", "", z.title.lower()) == norm:
            return z
    for z in zones.values():
        if norm and norm in re.sub(r"\s+", "", z.title.lower()):
            return z
    return None


def _device_style_for(asset: Asset, style_names: set[str]) -> str:
    """给资产挑一个**已有的**设备样式。

    优先按语义挑（DMZ → devDmz，网关/防火墙 → devGw，其余 → dev），
    样式表里没有就退到表里存在的其它设备样式，绝不新造样式名。

    **样式表整个不存在时**（标准 mxfile 的惯例：样式直接内联），返回内联样式串
    —— 引用一个 draw.io 找不到的名字，画出来是个没有属性的白方块。
    """
    if not style_names:
        return INLINE_DEVICE_STYLE

    haystack = f"{asset.type or ''} {asset.name or ''} {asset.natural_id or ''} {asset.zone or ''}".upper()
    preferred = "dev"
    if "DMZ" in haystack or "隔离" in haystack:
        preferred = "devDmz"
    elif any(k in haystack for k in ("网关", "GATEWAY", "-GW", "防火墙", "FIREWALL", "ROUTER", "路由")):
        preferred = "devGw"

    if preferred in style_names:
        return preferred
    for name in STYLE_DEVICE_CANDIDATES:
        if name in style_names:
            return name
    return FALLBACK_DEVICE_STYLE


def _link_style(style_names: set[str]) -> str:
    if not style_names:
        return INLINE_LINK_STYLE
    for name in STYLE_LINK_CANDIDATES:
        if name in style_names:
            return name
    return FALLBACK_LINK_STYLE


# ── 位置计算 ────────────────────────────────────────────────────────────────
def _free_slot(zone: _Zone, blockers: list[tuple[float, float, float, float]],
               node_w: float, node_h: float) -> tuple[float, float] | None:
    """在区域里找第一个空位（按现有排布：先左右后上下）。"""
    col_pitch = node_w + COL_GAP
    row_pitch = node_h + ROW_GAP
    max_x = zone.x + zone.w - PAD_RIGHT - node_w
    max_y = zone.y + zone.h - PAD_BOTTOM - node_h
    row = 0
    while zone.y + PAD_TOP + row * row_pitch <= max_y:
        col = 0
        while zone.x + PAD_LEFT + col * col_pitch <= max_x:
            x = zone.x + PAD_LEFT + col * col_pitch
            y = zone.y + PAD_TOP + row * row_pitch
            if not any(_rects_overlap((x, y, node_w, node_h), b) for b in blockers):
                return (x, y)
            col += 1
        row += 1
    return None


def _grow_zone(zone: _Zone, layout: _Layout, node_w: float, node_h: float) -> bool:
    """区域放不下时把区域扩一行/一列 —— 但不许撞到别的区域或区域外的节点。"""
    col_pitch = node_w + COL_GAP
    row_pitch = node_h + ROW_GAP

    others = [z.rect for z in layout.zones.values() if z.id != zone.id and z.w > 0]
    devices = [
        r
        for r in (_dev_rect(d, node_w, node_h) for d in layout.devices)
        if r is not None
    ]

    for new_w, new_h in ((zone.w + col_pitch, zone.h), (zone.w, zone.h + row_pitch)):
        if new_w <= 0 or new_h <= 0:
            continue
        rect = (zone.x, zone.y, new_w, new_h)
        if any(_rects_overlap(rect, o) for o in others):
            continue
        # 区域自己框住的节点允许重叠；区域外的节点不许被压到
        stray = [r for r in devices if not _rect_inside(r, zone.rect)]
        if any(_rects_overlap(rect, r) for r in stray):
            continue
        zone.w = new_w
        zone.h = new_h
        return True
    return False


# ── 主流程 ──────────────────────────────────────────────────────────────────
def import_assets_as_nodes(
    db: Session,
    tenant_id: str,
    topology_id: int,
    asset_ids: Iterable[int],
    *,
    zone: str | None = None,
    link_from_node_id: str | None = None,
) -> dict[str, Any]:
    """把资产清单里的设备导入成拓扑节点，并建立 device_monitors 绑定。

    返回::

        {
          "added": 2,                 # 新建的节点数
          "nodes": [...],             # 本次涉及的节点（新节点 + 复用的既有节点）
          "skipped": [...],           # 跳过的资产及原因
          "bound_existing": 1,        # 复用既有节点并补上绑定的数量
          "monitors": 2,              # 新建的 device_monitors 行数
          "warnings": [...],
        }
    """
    topo = db.get(Topology, topology_id)
    if topo is None or topo.tenant_id != tenant_id:
        # 别的租户的拓扑图 —— 一律当不存在，不泄露它存不存在
        raise TopologyImportError("拓扑图不存在")

    raw_ids: list[int] = []
    for aid in asset_ids or []:
        try:
            raw_ids.append(int(aid))
        except (TypeError, ValueError):
            continue
    raw_ids = list(dict.fromkeys(raw_ids))
    if not raw_ids:
        return {
            "added": 0,
            "nodes": [],
            "skipped": [],
            "bound_existing": 0,
            "monitors": 0,
            "warnings": [],
        }

    xml = topo.xml or ""
    graph = parse_topology(xml)
    if graph.get("error"):
        raise TopologyImportError(f"拓扑图 XML 解析失败：{graph['error']}")

    style_names = _style_names(xml)
    ids = _cell_ids(xml)

    layout = _Layout(
        zones=_zones_from_graph(graph),
        devices=list(graph.get("nodes") or []),
        cell_ids=set(ids),
        style_names=style_names,
        standard="<mxGraphModel" in xml,
        next_device_no=_max_suffix(ids, r"^d(\d+)$"),
        next_zone_no=_max_suffix(ids, r"^z(\d+)$"),
        next_edge_no=_max_suffix(ids, r"^e(\d+)$"),
    )
    # 节点尺寸跟随图里已有的节点，保持视觉一致
    # 注意不能用 `d.get("w") or 0`：0 是 falsy，会被吞掉 —— 虽然结果一样是
    # 跳过，但 `or` 的语义在这里容易骗人。显式判断 None。
    widths = [float(d["w"]) for d in layout.devices if d.get("w")]
    heights = [float(d["h"]) for d in layout.devices if d.get("h")]
    if widths:
        layout.node_w = max(widths)
    if heights:
        layout.node_h = max(heights)

    # ── 显式指定的区域：必须存在 ────────────────────────────────────────────
    explicit_zone: _Zone | None = None
    if zone:
        explicit_zone = _match_zone(layout.zones, zone)
        if explicit_zone is None:
            raise TopologyImportError(f"区域不存在：{zone}")

    # ── 本拓扑已有的绑定（幂等判重用）──────────────────────────────────────
    monitors = db.scalars(
        select(DeviceMonitor).where(
            DeviceMonitor.tenant_id == tenant_id,
            DeviceMonitor.topology_id == topology_id,
        )
    ).all()
    bound_nids = {(m.natural_id or "").strip().lower() for m in monitors if (m.natural_id or "").strip()}
    bound_ips = {(m.ip or "").strip() for m in monitors if (m.ip or "").strip()}
    node_of_monitor = {m.node_id: m for m in monitors}

    # ── 取资产（严格按租户过滤）────────────────────────────────────────────
    assets = {
        a.id: a
        for a in db.scalars(
            select(Asset).where(Asset.tenant_id == tenant_id, Asset.id.in_(raw_ids))
        ).all()
    }

    warnings: list[str] = []
    nodes_out: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    new_cells: list[str] = []
    zone_resizes: list[tuple[str, float, float]] = []
    import_zone: _Zone | None = None
    added = 0
    bound_existing = 0
    monitors_created = 0

    def _blockers() -> list[tuple[float, float, float, float]]:
        out = [
            r
            for r in (_dev_rect(d, layout.node_w, layout.node_h) for d in layout.devices)
            if r is not None
        ]
        for n in nodes_out:
            if n.get("x") is not None and not n.get("reused"):
                out.append((n["x"], n["y"], n["w"], n["h"]))
        return out

    def _ensure_import_zone() -> _Zone:
        """建一个专门放「不知道该归哪个区域」的导入设备的区域。

        放在整张图的最下方，不与任何区域重叠 —— 它是导入专用的，不去挤用户
        已经画好的框。
        """
        nonlocal import_zone
        if import_zone is not None:
            return import_zone

        zid = layout.new_zone_id()
        x = min([z.x for z in layout.zones.values() if z.w] or [95.0])
        y = max([z.y + z.h for z in layout.zones.values() if z.h] or [0.0]) + 60
        # 别压到区域外的节点
        while any(
            _rects_overlap((x, y, 555, 340), r)
            for r in (_dev_rect(d, layout.node_w, layout.node_h) for d in layout.devices)
            if r is not None
        ):
            y += 60

        zone_obj = _Zone(id=zid, x=x, y=y, w=555, h=340, title="", key="", synthetic=True)
        # 区域编号取图里没被占用的下一个 Zone N
        used = {_norm_key(z.title) for z in layout.zones.values()}
        n = 0
        for zid_existing in layout.zones:
            m = re.match(r"^z(\d+)$", zid_existing)
            if m:
                n = max(n, int(m.group(1)))
        while True:
            n += 1
            if f"zone{n}" not in used:
                break
        zone_obj.title = f"Zone {n} · {IMPORT_ZONE_SUFFIX}"
        zone_obj.key = _norm_key(zone_obj.title)

        if style_names:
            zstyle = STYLE_ZONE if STYLE_ZONE in style_names else FALLBACK_ZONE_STYLE
            tstyle = STYLE_TITLE if STYLE_TITLE in style_names else FALLBACK_TITLE_STYLE
            sstyle = STYLE_SUB if STYLE_SUB in style_names else FALLBACK_SUB_STYLE
        else:
            # 没有样式表 → 用内联样式（引用一个 draw.io 不认识的名字 = 白方块）
            zstyle, tstyle, sstyle = INLINE_ZONE_STYLE, INLINE_TITLE_STYLE, INLINE_SUB_STYLE

        zone_obj.cells.append(
            _zone_cell_xml(zid, zstyle, zone_obj.x, zone_obj.y, zone_obj.w, zone_obj.h, layout.standard)
        )
        title_id = f"{zid}t"
        zone_obj.cells.append(
            _text_cell_xml(
                title_id, zone_obj.title, tstyle, zone_obj.x + 25, zone_obj.y + 22, 340, 30, layout.standard
            )
        )
        sub_id = f"{zid}s"
        zone_obj.cells.append(
            _text_cell_xml(
                sub_id, "从资产清单导入", sstyle, zone_obj.x + 25, zone_obj.y + 54, 250, 24, layout.standard
            )
        )
        layout.cell_ids.update({zid, title_id, sub_id})

        layout.zones[zid] = zone_obj
        new_cells.extend(zone_obj.cells)
        import_zone = zone_obj
        return zone_obj

    def _place(target: _Zone) -> tuple[float, float] | None:
        """在目标区域里找一个空位；放不下就把区域扩一行/一列再试。"""
        slot = _free_slot(target, _blockers(), layout.node_w, layout.node_h)
        if slot is not None:
            return slot
        if _grow_zone(target, layout, layout.node_w, layout.node_h):
            zone_resizes.append((target.id, target.w, target.h))
            return _free_slot(target, _blockers(), layout.node_w, layout.node_h)
        return None

    for aid in raw_ids:
        asset = assets.get(aid)
        if asset is None:
            skipped.append({"asset_id": aid, "natural_id": None, "name": None, "reason": "资产不存在"})
            continue

        nid = (asset.natural_id or "").strip()
        ip = (asset.ip or "").strip()
        label = (asset.name or "").strip() or nid

        # 1) 已经绑在本拓扑上了 —— 幂等，跳过
        if (nid and nid.lower() in bound_nids) or (ip and ip in bound_ips):
            skipped.append(
                {"asset_id": aid, "natural_id": nid or None, "name": label, "reason": "已绑定到本拓扑"}
            )
            continue

        # 2) 图里已经有同名的节点 —— 复用它，不画第二个方块
        existing = _find_existing_node(layout.devices, nid, label, ip)
        if existing is not None:
            prior = node_of_monitor.get(existing["id"])
            prior_nid = (prior.natural_id or "").strip().lower() if prior else ""
            if prior is not None and prior_nid not in ("", (nid or "").lower()):
                skipped.append(
                    {
                        "asset_id": aid,
                        "natural_id": nid or None,
                        "name": label,
                        "reason": f"节点 {existing['id']} 已绑定到其他设备",
                    }
                )
                continue
            m = prior
            if m is None:
                m = DeviceMonitor(tenant_id=tenant_id, topology_id=topology_id, node_id=existing["id"])
                db.add(m)
                monitors_created += 1
            m.node_label = label
            m.natural_id = nid or m.natural_id
            m.ip = ip or m.ip
            m.channel = "fortisiem"
            m.enabled = True
            node_of_monitor[existing["id"]] = m
            if nid:
                bound_nids.add(nid.lower())
            if ip:
                bound_ips.add(ip)
            bound_existing += 1
            nodes_out.append(
                {
                    "node_id": existing["id"],
                    "label": label,
                    "natural_id": nid or None,
                    "ip": ip or None,
                    "asset_id": aid,
                    "zone": existing.get("zone"),
                    "zone_key": existing.get("zone_key"),
                    "x": existing.get("x"),
                    "y": existing.get("y"),
                    "w": existing.get("w"),
                    "h": existing.get("h"),
                    "style": (existing.get("style_names") or ["dev"])[0],
                    "reused": True,
                }
            )
            continue

        # 3) 新建节点
        target = explicit_zone
        if target is None and asset.zone:
            target = _match_zone(layout.zones, asset.zone)
            if target is None:
                warnings.append(
                    f"资产「{label}」的区域 {asset.zone} 不在这张拓扑图里，已放入{IMPORT_ZONE_SUFFIX}区"
                )
        if target is None:
            target = _ensure_import_zone()

        slot = _place(target)
        if slot is None:
            if target is not import_zone:
                warnings.append(f"区域「{target.title or target.id}」放不下「{label}」，已放入{IMPORT_ZONE_SUFFIX}区")
                target = _ensure_import_zone()
            slot = _place(target)
        if slot is None:
            skipped.append(
                {"asset_id": aid, "natural_id": nid or None, "name": label, "reason": "找不到可放置的位置"}
            )
            continue

        x, y = slot
        node_id = layout.new_device_id()
        style = _device_style_for(asset, style_names)
        new_cells.append(
            _device_cell_xml(node_id, label, style, x, y, layout.node_w, layout.node_h, layout.standard)
        )

        # 3a) 可选：从某个既有节点连一条线过来
        if link_from_node_id:
            known = {d["id"] for d in layout.devices} | set(node_of_monitor)
            if link_from_node_id in known:
                new_cells.append(
                    _edge_cell_xml(
                        layout.new_edge_id(),
                        _link_style(style_names),
                        link_from_node_id,
                        node_id,
                        layout.standard,
                    )
                )
            else:
                warnings.append(f"连线起点节点 {link_from_node_id} 不存在，已忽略")

        # 3b) 建立 device_monitors 绑定 —— 事件靠它点亮节点
        m = DeviceMonitor(
            tenant_id=tenant_id,
            topology_id=topology_id,
            node_id=node_id,
            node_label=label,
            natural_id=nid or None,
            ip=ip or None,
            channel="fortisiem",
            enabled=True,
        )
        db.add(m)
        node_of_monitor[node_id] = m
        monitors_created += 1
        if nid:
            bound_nids.add(nid.lower())
        if ip:
            bound_ips.add(ip)

        added += 1
        nodes_out.append(
            {
                "node_id": node_id,
                "label": label,
                "natural_id": nid or None,
                "ip": ip or None,
                "asset_id": aid,
                "zone": target.title or target.id,
                "zone_key": target.key or None,
                "x": x,
                "y": y,
                "w": layout.node_w,
                "h": layout.node_h,
                "style": style,
                "reused": False,
            }
        )
        layout.devices.append(
            {"id": node_id, "label": label, "x": x, "y": y, "w": layout.node_w, "h": layout.node_h}
        )

    # ── 写回 XML ────────────────────────────────────────────────────────────
    # 顺序很重要：先插 cell（新建的区域框这时才在 XML 里），再改区域尺寸。
    new_xml = _insert_cells(xml, new_cells)
    for zid, zw, zh in zone_resizes:
        new_xml = _resize_zone(new_xml, zid, zw, zh)

    # ── 自检：新 XML 必须能被解析器读回来，否则前端会渲染坏 ─────────────────
    if new_xml != xml:
        check = parse_topology(new_xml)
        if check.get("error"):
            raise TopologyImportError(f"生成的拓扑无法解析：{check['error']}")
        parsed_labels = {n.get("label") for n in check.get("nodes") or []}
        missing = [
            n["label"] for n in nodes_out if not n.get("reused") and n["label"] not in parsed_labels
        ]
        if missing:
            raise TopologyImportError(f"生成的节点无法解析：{'、'.join(missing)}")

    topo.xml = new_xml

    # ── node_bindings 同步 ──────────────────────────────────────────────────
    # 方向：node_id → {natural_id, label, ip}。
    #   依据：node_bindings 只被 `len()` 当作「节点数」用（Topology.to_dict 的
    #   node_count），所以它必须**每个节点一条**；而 node_id 是唯一能一节点一
    #   key 的标识（natural_id 不保证存在，也不保证一台设备只画一个节点）。
    #   value 里带上 natural_id，按 natural_id 查仍然扫得出来。
    bindings: dict[str, Any] = dict(topo.node_bindings or {})
    for n in nodes_out:
        bindings[n["node_id"]] = {
            "natural_id": n.get("natural_id"),
            "label": n.get("label"),
            "ip": n.get("ip"),
        }
    topo.node_bindings = bindings

    db.commit()

    return {
        "added": added,
        "nodes": nodes_out,
        "skipped": skipped,
        "bound_existing": bound_existing,
        "monitors": monitors_created,
        "warnings": warnings,
    }


def _max_suffix(ids: set[str], pattern: str) -> int:
    """取一组 id 里匹配 pattern 的最大数字后缀（没有就是 0）。"""
    best = 0
    for cid in ids:
        m = re.match(pattern, cid or "")
        if m:
            best = max(best, int(m.group(1)))
    return best


def _find_existing_node(devices: list[dict[str, Any]], nid: str, label: str, ip: str) -> dict[str, Any] | None:
    """在图里找已经存在的同设备节点：先比 natural_id，再比名称，最后比 IP。"""
    nid_l = (nid or "").strip().lower()
    label_l = (label or "").strip().lower()
    ip_l = (ip or "").strip().lower()

    for key in (nid_l, label_l, ip_l):
        if not key:
            continue
        for d in devices:
            if (d.get("label") or "").strip().lower() == key:
                return d
    return None


# ── 可导入资产清单 ──────────────────────────────────────────────────────────
def list_importable_assets(db: Session, tenant_id: str, topology_id: int) -> dict[str, Any]:
    """列出该租户里「还没有绑到本拓扑」的资产。

    顺带标出两件事，方便前端提示：
      · ``already_in_graph``  —— 图里已经有同名的节点（导入会复用它，不新画）
      · ``bound_elsewhere``   —— 已经绑到别的拓扑图上了
    """
    topo = db.get(Topology, topology_id)
    if topo is None or topo.tenant_id != tenant_id:
        raise TopologyImportError("拓扑图不存在")

    graph = parse_topology(topo.xml or "")
    device_labels = {(d.get("label") or "").strip().lower() for d in graph.get("nodes") or []}

    all_monitors = db.scalars(
        select(DeviceMonitor).where(DeviceMonitor.tenant_id == tenant_id)
    ).all()
    bound_here = {
        (m.natural_id or "").strip().lower()
        for m in all_monitors
        if m.topology_id == topology_id and (m.natural_id or "").strip()
    }
    bound_ips_here = {
        (m.ip or "").strip()
        for m in all_monitors
        if m.topology_id == topology_id and (m.ip or "").strip()
    }
    bound_elsewhere = {
        (m.natural_id or "").strip().lower()
        for m in all_monitors
        if m.topology_id != topology_id and (m.natural_id or "").strip()
    }

    items: list[dict[str, Any]] = []
    for a in db.scalars(
        select(Asset).where(Asset.tenant_id == tenant_id).order_by(Asset.name)
    ).all():
        nid = (a.natural_id or "").strip()
        ip = (a.ip or "").strip()
        if (nid and nid.lower() in bound_here) or (ip and ip in bound_ips_here):
            continue
        label = (a.name or "").strip() or nid
        items.append(
            {
                "id": a.id,
                "natural_id": nid or None,
                "name": a.name,
                "type": a.type,
                "zone": a.zone or None,
                "ip": ip or None,
                "vendor": a.vendor,
                "model": a.model,
                "status": a.status,
                "source": a.source,
                "already_in_graph": bool(label and label.lower() in device_labels),
                "bound_elsewhere": bool(nid and nid.lower() in bound_elsewhere),
            }
        )

    return {"items": items, "total": len(items)}
