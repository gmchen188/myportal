"""
draw.io XML 的解析与投影。

存的是整份 mxfile XML（不拆开存），读的时候投影成「节点 + 连线」。
这样 draw.io 的格式演进不需要数据迁移 —— 存的是原文，读的时候才解析。

投影出的节点带 `kind`：
    zone   —— 安全区域容器（区域框，标签形如 "Zone 1 · 船舶核心控制区"）
    device —— 设备节点
    link   —— 连线

**区域与设备的关系靠坐标包含判断**：设备的中心点落在某个 zone 框内，
就属于那个区域。这与画图时的语义一致 —— 用户把设备画在哪个框里就是哪个区。
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any


def _parse_float(v: str | None) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _style_value(style: str, key: str) -> str:
    """从 draw.io 的分号分隔 style 串里取一个键。

    style 形如 `rounded=1;fillColor=#fff;strokeColor=#000;`。
    值里可能含分号（少见），所以按分号切完再找前缀匹配的那一段。
    """
    for part in (style or "").split(";"):
        if part.startswith(key + "="):
            return part[len(key) + 1:]
    return ""


def _resolve_styles(root: ET.Element) -> dict[str, str]:
    """收集 <mxStyle name= value=> 的样式表。

    display_diagram 工具产出的 XML 用样式表引用（style="dev;"）而不是内联
    属性，所以必须把表解出来才能判断一个 cell 是区域还是设备。
    """
    table: dict[str, str] = {}
    for st in root.iter("mxStyle"):
        name = st.get("name")
        value = st.get("value")
        if name and value is not None:
            table[name] = value
    return table


def _style_names(style: str) -> list[str]:
    """取出 style 里引用的**样式名**（不展开）。

    `zoneBox;` → ["zoneBox"]。这是判断「这个 cell 是什么」的关键 ——
    展开成 `rounded=1;fillColor=…` 之后名字就没了，区域框和普通方框
    长得一样，无法区分。
    """
    out = []
    for part in (style or "").split(";"):
        p = part.strip()
        if p and "=" not in p:
            out.append(p)
    return out


def _effective_style(style: str, table: dict[str, str]) -> str:
    """把样式表引用展开成实际样式串。

    `dev;` → 查表得到 dev 的 value → 拼上其余内联部分。
    """
    parts = [p for p in (style or "").split(";") if p]
    out: list[str] = []
    for p in parts:
        if p in table:
            out.extend(x for x in table[p].split(";") if x)
        else:
            out.append(p)
    return ";".join(out)


def _parse_xml_any(xml: str) -> tuple[ET.Element | None, str | None]:
    """解析三种可能的 XML 形态。

    1. 标准 draw.io：`<mxfile><diagram><mxGraphModel>…`
    2. 带根的片段：`<mxGraphModel>…`
    3. **display_diagram 工具产出的裸片段**：一串并列的 `<mxStyle>` +
       `<mxCell>`，**没有根元素**

    第 3 种是真实存在的：AI 生成拓扑时，工具返回的是裸 cell 列表，
    不是完整的 mxfile。所以解析器不能假设有根元素。

    第 3 种的处理办法：用 `<root>` 把片段包起来再解析 —— 但 XML 里可能
    有多个顶层元素，直接包会变成非法 XML。所以逐个顶层元素切出来，
    分别解析，再合并。

    返回 (根元素, 错误信息)。
    """
    text = (xml or "").strip()
    if not text:
        return None, None

    # 先试标准形态
    try:
        return ET.fromstring(text), None
    except ET.ParseError as first_err:
        pass

    # 试包一层 root
    try:
        return ET.fromstring(f"<root>{text}</root>"), None
    except ET.ParseError:
        pass

    # 逐个切顶层元素
    try:
        root = ET.Element("root")
        i = 0
        n = len(text)
        while i < n:
            if text[i] != "<":
                i += 1
                continue
            j = text.find(">", i)
            if j < 0:
                break
            tag = text[i + 1 : j].split()[0].rstrip("/>")
            # 自闭合？
            if text[j - 1] == "/":
                frag = text[i : j + 1]
                i = j + 1
            else:
                close = f"</{tag}>"
                k = text.find(close, j)
                if k < 0:
                    continue
                frag = text[i : k + len(close)]
                i = k + len(close)
            try:
                root.append(ET.fromstring(frag))
            except ET.ParseError:
                continue
        if len(root):
            return root, None
        return None, f"XML 解析失败：{first_err}"
    except Exception as e:
        return None, f"XML 解析失败：{e}"


def parse_topology(xml: str) -> dict[str, Any]:
    """把 draw.io XML 投影成节点与连线。

    解析失败不抛异常 —— 返回 error 字段让调用方决定怎么提示。
    一份坏 XML 不该让整个监控面板 500。
    """
    if not xml or not xml.strip():
        return {"nodes": [], "links": [], "zones": [], "error": None}

    root, err = _parse_xml_any(xml)
    if root is None:
        return {"nodes": [], "links": [], "zones": [], "error": err}

    table = _resolve_styles(root)

    zones: list[dict[str, Any]] = []
    zone_labels: list[dict[str, Any]] = []
    devices: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []

    cells: dict[str, dict[str, Any]] = {}

    for cell in root.iter("mxCell"):
        cid = cell.get("id")
        if not cid:
            continue
        raw_style = cell.get("style", "")
        style = _effective_style(raw_style, table)
        names = _style_names(raw_style)
        value = cell.get("value") or ""

        # 几何有两种位置：
        #   标准 draw.io   → <mxCell><mxGeometry x= y= width= height=/></mxCell>
        #   display_diagram → 直接写在 <mxCell x= y= w= h=> 属性上
        # 两种都读，否则 AI 生成的图会全部落在原点、归区全乱。
        geom = cell.find("mxGeometry")
        if geom is not None:
            x = _parse_float(geom.get("x"))
            y = _parse_float(geom.get("y"))
            w = _parse_float(geom.get("width"))
            h = _parse_float(geom.get("height"))
        else:
            x = _parse_float(cell.get("x"))
            y = _parse_float(cell.get("y"))
            w = _parse_float(cell.get("w"))
            h = _parse_float(cell.get("h"))

        # 连线：标准格式有 edge="1"，display_diagram 靠 source/target 判断
        is_edge = cell.get("edge") == "1" or bool(cell.get("source") and cell.get("target"))
        # 顶点：标准格式有 vertex="1"，display_diagram **不写这个属性** ——
        # 没有 edge 就是顶点。不能因为缺 vertex="1" 就把节点全丢掉。
        is_vertex = (not is_edge) and cell.get("vertex") in ("1", None, "")

        info = {
            "id": cid,
            "label": _clean_label(value),
            "style": style,
            "style_names": names,
            "x": x,
            "y": y,
            "w": w,
            "h": h,
            "parent": cell.get("parent"),
            "vertex": is_vertex,
            "edge": is_edge,
            "source": cell.get("source"),
            "target": cell.get("target"),
        }
        cells[cid] = info

        if is_edge:
            links.append(
                {
                    "id": cid,
                    "source": info["source"],
                    "target": info["target"],
                    "style": style,
                    "dashed": "dashed=1" in style,
                    "color": _style_value(style, "strokeColor"),
                }
            )
            continue

        if not is_vertex:
            continue

        # 分类：
        #   zoneBox  → 区域框（大容器）
        #   zoneTitle/zoneSub → 区域的标题/副标题，不是设备
        #   dev/devGw/devDmz → 设备
        #   兜底：标签像 "Zone N" 的是区域；面积大且无标签的是区域框
        if "zoneBox" in names:
            zones.append(info)
        elif any(n in names for n in ("zoneTitle", "zoneSub")):
            zone_labels.append(info)
        elif re.match(r"^Zone\s*\d", info["label"], re.I):
            zone_labels.append(info)
        elif w > 300 and h > 200 and not info["label"]:
            zones.append(info)
        else:
            devices.append(info)

    # 区域名从标题 cell 上取（区域框本身没有标签）
    for z in zones:
        z["title"] = None
        z["subtitle"] = None
    for zl in zone_labels:
        # 标题 cell 在区域框内部：找包含它的那个区域
        cx = zl["x"] + zl["w"] / 2
        cy = zl["y"] + zl["h"] / 2
        for z in zones:
            if z["x"] <= cx <= z["x"] + z["w"] and z["y"] <= cy <= z["y"] + z["h"]:
                if z["title"] is None:
                    z["title"] = zl["label"]
                else:
                    z["subtitle"] = zl["label"]
                break

    # 设备归区：中心点落在哪个 zone 框里
    for d in devices:
        cx = d["x"] + d["w"] / 2
        cy = d["y"] + d["h"] / 2
        d["zone"] = None
        for z in zones:
            if z["x"] <= cx <= z["x"] + z["w"] and z["y"] <= cy <= z["y"] + z["h"]:
                d["zone"] = z.get("title") or z["label"] or z["id"]
                break
        if d["zone"]:
            # "Zone 1 · 船舶核心控制区" → "Zone 1"
            m = re.match(r"^(Zone\s*\d+)", d["zone"], re.I)
            d["zone_key"] = m.group(1).replace(" ", "") if m else d["zone"]
        else:
            d["zone_key"] = None

    return {
        "nodes": devices,
        "zones": zones,
        "links": links,
        "error": None,
    }


def _clean_label(value: str) -> str:
    """去掉 HTML 标签，保留纯文本。"""
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", "", value)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
    )
    return text.strip()


def zone_display_name(zone_label: str) -> str:
    """把 "Zone 1 · 船舶核心控制区" 拆成 ("Zone 1", "船舶核心控制区")。"""
    if "·" in zone_label:
        key, _, name = zone_label.partition("·")
        return key.strip(), name.strip()
    return zone_label.strip(), ""
