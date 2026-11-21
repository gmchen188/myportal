"""
资产导入：把外部文件变成待确认的资产行。

三条来源路径共用同一个「解析 → 校验 → 预览 → 落库」的流水线，
区别只在最前面的解析器：

    csv / xlsx / xls   → 表格解析器，读出表头 + 行
    topology image     → 视觉解析器（调用 networktopology 的 VLM 能力），
                         从拓扑图里认出设备，产出「初步」资产行
    手工输入 / 模板     → 单行解析器

为什么统一成流水线：AI 只做**列名识别与建议**，必填/去重/值域/租户作用域
由服务端规则判定。这个边界不能模糊 —— AI 说"这列是设备名"是建议，
"这行的 zone 合法"是规则。

去重键：natural_id → 名称 → 序列号。**已有资产不覆盖**，重复行跳过并列出。
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any

# ── 资产字段定义 ────────────────────────────────────────────────────────────
# syn 是同义词表 —— 列名映射用。匹配算法与 myPortal 前端一致：
# 完全相等 0.99 / 互相包含 0.82 / 短词包含 0.74
ASSET_FIELDS: list[dict[str, Any]] = [
    {"key": "name", "label": "资产名称", "required": True,
     "syn": ["资产名称", "设备名称", "资产", "名称", "主机名", "hostname", "asset", "name", "系统名称"]},
    {"key": "natural_id", "label": "资产编号", "required": False,
     "syn": ["资产编号", "natural_id", "资产id", "编号", "id", "序号"]},
    {"key": "type", "label": "类型", "required": True,
     "syn": ["设备类型", "类型", "类别", "type", "category", "系统类型"]},
    {"key": "zone", "label": "安全区域", "required": True,
     "syn": ["安全区域", "安全域", "分区", "区域", "zone", "安全区"]},
    {"key": "ip", "label": "IP 地址", "required": False,
     "syn": ["ip地址", "ip", "管理ip", "地址", "ip addr", "ipaddress"]},
    {"key": "vendor", "label": "厂商", "required": False,
     "syn": ["制造商", "厂家", "厂商", "vendor", "品牌", "brand"]},
    {"key": "model", "label": "型号", "required": False,
     "syn": ["设备型号", "型号", "model", "规格", "产品型号"]},
    {"key": "serial", "label": "序列号", "required": False,
     "syn": ["资产序列号", "序列号", "serial", "sn", "序列编号"]},
    {"key": "owner", "label": "责任人", "required": False,
     "syn": ["负责人", "责任人", "归属人", "owner", "管理员"]},
    {"key": "cbs_class", "label": "CBS 等级", "required": False,
     "syn": ["cbs等级", "系统等级", "等级", "class", "分类", "船级"]},
    {"key": "status", "label": "状态", "required": False,
     "syn": ["状态", "status", "在用", "启用情况"]},
]

ALLOWED_ZONES = {"Zone 0", "Zone 1", "Zone 2", "Zone 3"}


@dataclass
class Issue:
    level: str  # err / warn / ok
    message: str
    row: int | None = None
    field: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"level": self.level, "message": self.message, "row": self.row, "field": self.field}


@dataclass
class ParsedRow:
    """一行待导入的资产。"""

    values: dict[str, Any] = field(default_factory=dict)
    row_no: int = 0
    issues: list[Issue] = field(default_factory=list)
    status: str = "ready"  # ready / skip / needs_fill
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "values": self.values,
            "row_no": self.row_no,
            "issues": [i.to_dict() for i in self.issues],
            "status": self.status,
            "reason": self.reason,
        }


# ── 列名映射建议 ────────────────────────────────────────────────────────────
def _norm(s: str) -> str:
    return re.sub(r"[\s\-_()（）]", "", (s or "").strip().lower())


def suggest_mapping(headers: list[str]) -> list[dict[str, Any]]:
    """给每个表头建议一个字段。AI 可以改这个建议，但建议本身是规则算的。"""
    out = []
    for h in headers:
        hl = _norm(h)
        best: str | None = None
        score = 0.0
        for f in ASSET_FIELDS:
            for syn in f["syn"]:
                sl = _norm(syn)
                sc = 0.0
                if hl == sl:
                    sc = 0.99
                elif hl and sl and (sl in hl or hl in sl):
                    sc = 0.82
                elif len(sl) >= 2 and sl in hl:
                    sc = 0.74
                if sc > score:
                    score, best = sc, f["key"]
        out.append({"header": h, "field": best, "score": round(score, 2)})
    return out


# ── 表格解析（CSV / TSV / XLSX / XLS）────────────────────────────────────────
def parse_delimited(text: str, delimiter: str | None = None) -> tuple[list[str], list[list[str]]]:
    """解析分隔符文本。分隔符未指定时自动嗅探。"""
    text = text.lstrip("﻿")
    if delimiter is None:
        delimiter = ","
        best = 0
        for cand in [",", "\t", ";", "|"]:
            # 只看前几行，避免正文里的符号干扰判断
            sample = "\n".join(text.split("\n")[:5])
            n = sample.count(cand)
            if n > best:
                best, delimiter = n, cand
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = [r for r in reader if any((c or "").strip() for c in r)]
    if not rows:
        return [], []
    return rows[0], rows[1:]


def parse_xlsx(data: bytes) -> tuple[list[str], list[list[str]]]:
    """解析 xlsx。xls（老格式）需要 xlrd，未装时给明确提示而不是静默失败。"""
    if data[:2] == b"PK":
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb[wb.sheetnames[0]]
        rows = [[("" if c is None else str(c)) for c in r] for r in ws.iter_rows(values_only=True)]
        wb.close()
    else:
        try:
            import xlrd  # noqa: PLC0415
        except ImportError:
            raise ValueError(
                "这是 .xls 老格式，需要 xlrd：pip install xlrd。"
                "建议另存为 .xlsx，或先转成 CSV。"
            )
        book = xlrd.open_workbook(file_contents=data)
        sheet = book.sheet_by_index(0)
        rows = []
        for r in range(sheet.nrows):
            rows.append([str(sheet.cell_value(r, c)) for c in range(sheet.ncols)])
        book.release_resources()

    rows = [r for r in rows if any((c or "").strip() for c in r)]
    if not rows:
        return [], []
    return rows[0], rows[1:]


def parse_file(filename: str, data: bytes) -> tuple[list[str], list[list[str]]]:
    """按扩展名分派。"""
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        return parse_xlsx(data)
    for enc in ("utf-8-sig", "utf-8", "gbk", "latin-1"):
        try:
            return parse_delimited(data.decode(enc))
        except UnicodeDecodeError:
            continue
    return parse_delimited(data.decode("utf-8", errors="replace"))


# ── 校验 ────────────────────────────────────────────────────────────────────
def validate_rows(
    headers: list[str],
    body: list[list[str]],
    mapping: list[dict[str, Any]] | None = None,
    existing_names: set[str] | None = None,
) -> dict[str, Any]:
    """校验一批行。

    `existing_names` 是该租户已有的资产名（小写）—— 用来标「与已有资产重复」。
    """
    existing_names = existing_names or set()
    mp = mapping or suggest_mapping(headers)

    issues: list[Issue] = []
    missing_cols = [f for f in ASSET_FIELDS if f["required"] and f["key"] not in [m["field"] for m in mp]]
    for f in missing_cols:
        issues.append(Issue("err", f"缺少必填列「{f['label']}」"))

    unmapped = [m["header"] for m in mp if not m["field"]]
    if unmapped:
        issues.append(Issue("warn", f"{len(unmapped)} 列未能自动匹配，将被忽略：{'、'.join(unmapped)}"))

    parsed: list[ParsedRow] = []
    seen: dict[str, int] = {}
    dup_count = 0
    missing_count = 0

    def cell(row: list[str], key: str) -> str:
        for i, m in enumerate(mp):
            if m["field"] == key and i < len(row):
                return (row[i] or "").strip()
        return ""

    for idx, row in enumerate(body):
        rn = idx + 2  # 表头占第 1 行
        pr = ParsedRow(row_no=rn)
        for f in ASSET_FIELDS:
            pr.values[f["key"]] = cell(row, f["key"])

        # 空行跳过
        if not any((v or "").strip() for v in pr.values.values()):
            continue

        for f in ASSET_FIELDS:
            if f["required"] and not (pr.values.get(f["key"]) or "").strip():
                pr.issues.append(Issue("err", f"缺少必填字段「{f['label']}」", rn, f["key"]))
                missing_count += 1

        name = (pr.values.get("name") or "").strip()
        if name:
            k = name.lower()
            if k in seen:
                pr.issues.append(Issue("warn", f"与第 {seen[k]} 行重复", rn, "name"))
                dup_count += 1
            else:
                seen[k] = rn
            if k in existing_names:
                pr.issues.append(Issue("warn", "与已有资产重复", rn, "name"))
                dup_count += 1

        zone = (pr.values.get("zone") or "").strip()
        if zone and zone not in ALLOWED_ZONES:
            pr.issues.append(Issue("warn", f"安全区域「{zone}」不在允许列表", rn, "zone"))

        if any(i.level == "err" for i in pr.issues):
            pr.status = "needs_fill"
        elif any(i.message == "与已有资产重复" or "重复" in i.message for i in pr.issues):
            pr.status = "skip"
        else:
            pr.status = "ready"

        parsed.append(pr)

    if missing_count:
        issues.append(Issue("warn", f"{missing_count} 处缺少必填字段"))
    if dup_count:
        issues.append(Issue("warn", f"{dup_count} 处与已有资产或本次导入重复"))
    if not issues:
        issues.append(Issue("ok", "未发现问题，可直接导入"))

    return {
        "headers": headers,
        "mapping": mp,
        "rows": [p.to_dict() for p in parsed],
        "issues": [i.to_dict() for i in issues],
        "stats": {
            "total": len(parsed),
            "ready": sum(1 for p in parsed if p.status == "ready"),
            "skip": sum(1 for p in parsed if p.status == "skip"),
            "needs_fill": sum(1 for p in parsed if p.status == "needs_fill"),
        },
    }


# ── 拓扑图 → 初步资产清单 ───────────────────────────────────────────────────
def normalize_zone(value: str | None) -> str:
    """把各种写法的安全区域归一成 "Zone N"。

    拓扑图投影出来的 zone_key 是紧凑格式（"Zone3"），而资产清单用的是
    "Zone 3" —— 不归一的话，拓扑图生成的资产 zone 值对不上允许列表，
    校验会误判成非法区域。

    认得：Zone3 / zone 3 / ZONE_3 / 区域3 / 3 → "Zone 3"
    认不得的（"OT-DMZ" 这种自由文本）原样返回 —— 那是用户的自定义区域。
    """
    if not value:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    m = re.match(r"^\s*zone[\s_\-]*(\d+)\s*$", s, re.I)
    if m:
        return f"Zone {m.group(1)}"
    m = re.match(r"^\s*(?:区域|分区|安全区)[\s_\-]*(\d+)\s*$", s)
    if m:
        return f"Zone {m.group(1)}"
    return s


def assets_from_topology_nodes(nodes: list[dict[str, Any]]) -> list[ParsedRow]:
    """从拓扑图的节点列表生成初步资产行。

    这些行**几乎总是缺必填字段**（拓扑图不画类型和区域），所以全部标成
    `needs_fill` —— 用户补全后才能保存。这是有意的：拓扑图给的是「有哪些
    设备」，不是「这些设备是什么」。

    识别规则按设备的命名惯例（与 myPortal 既有数据一致）：
        FW-EDGE-*  → 防火墙      REMOTE-GW → 远程网关
        CBS-*      → 船舶系统    CCTV-GW  → 摄像头网关
        OT-DMZ-*   → DMZ 边界    *-GW     → 网关
        *-SW/*-SWT → 交换机     *-RTR    → 路由器
        *-SRV     → 服务器      *-PLC    → PLC
    """
    out: list[ParsedRow] = []
    for i, n in enumerate(nodes):
        label = (n.get("label") or "").strip()
        if not label:
            continue
        pr = ParsedRow(row_no=i + 1)
        natural_id = label
        zone = normalize_zone(n.get("zone"))
        pr.values = {
            "name": label,
            "natural_id": natural_id,
            "type": infer_device_type(label),
            "zone": zone,
            "ip": n.get("ip") or "",
            "vendor": n.get("vendor") or "",
            "model": "",
            "serial": "",
            "owner": "",
            "cbs_class": "",
            "status": "在用",
        }
        pr.values["source"] = "topology_image"

        missing = [f["label"] for f in ASSET_FIELDS if f["required"] and not (pr.values.get(f["key"]) or "").strip()]
        if missing:
            pr.issues.append(Issue("err", f"待补充：{'、'.join(missing)}", i + 1, missing[0]))
            pr.status = "needs_fill"
        else:
            pr.status = "ready"
        pr.reason = "从拓扑图识别"
        out.append(pr)
    return out


def infer_device_type(label: str) -> str:
    """按命名惯例猜设备类型 —— 这是**建议**，用户可以改。"""
    u = label.upper()
    rules: list[tuple[str, str]] = [
        ("FW-EDGE", "防火墙"),
        ("FIREWALL", "防火墙"),
        ("REMOTE-GW", "远程网关"),
        ("CCTV-GW", "摄像头网关"),
        ("OT-DMZ", "DMZ"),
        ("DMZ", "DMZ"),
        ("CBS-", "船舶系统"),
        ("PLC", "PLC"),
        ("HMI", "HMI"),
        ("RTU", "RTU"),
        ("SWITCH", "交换机"),
        ("-SW", "交换机"),
        ("RTR", "路由器"),
        ("ROUTER", "路由器"),
        ("SRV", "服务器"),
        ("SERVER", "服务器"),
        ("-GW", "网关"),
    ]
    for token, t in rules:
        if token in u:
            return t
    return "网络设备"


def dedupe_key(values: dict[str, Any]) -> str:
    """去重键：natural_id → 名称 → 序列号。"""
    for k in ("natural_id", "name", "serial"):
        v = (values.get(k) or "").strip().lower()
        if v:
            return f"{k}:{v}"
    return ""
