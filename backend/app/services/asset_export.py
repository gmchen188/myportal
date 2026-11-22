"""
资产清单导出 —— CSV / Excel。

## 为什么字段可选

资产有 13 个字段，但不同的交付场景要的列不一样：

- 船级社检验清单 → 只要「资产名称 / 类型 / 区域 / 编号 / CBS 等级」
- 交给船东的设备台账 → 要「名称 / IP / 型号 / 序列号 / 责任人」
- 跟 CMDB 对账 → 要「编号 / 名称 / IP / 厂商 / 型号 / 序列号」

一次导出全字段，交付方还得自己删列 —— 那不如让他选。

## CSV 的 BOM

**必须带 UTF-8 BOM**（`utf-8-sig`）。不带的话 Excel 打开中文全是乱码，
因为 Excel 默认按本地 ANSI 编码读 CSV。这不是可选项。

## Excel 的格式

- 首行表头加粗 + 冻结（`freeze_panes = "A2"`）
- 列宽按内容估算（中文按 2 个字符宽度算，否则列会挤成一团）
- 自动筛选（用户导出的表往往还要再筛一次）
"""

from __future__ import annotations

import csv
import io
from typing import Any

from .asset_import import ASSET_FIELDS

# 导出字段定义 —— key 对应 Asset 的属性名，label 是表头中文
EXPORT_FIELDS: list[dict[str, str]] = [
    {"key": "natural_id", "label": "资产编号"},
    {"key": "name", "label": "资产名称"},
    {"key": "type", "label": "类型"},
    {"key": "zone", "label": "安全区域"},
    {"key": "ip", "label": "IP 地址"},
    {"key": "vendor", "label": "厂商"},
    {"key": "model", "label": "型号"},
    {"key": "serial", "label": "序列号"},
    {"key": "owner", "label": "责任人"},
    {"key": "cbs_class", "label": "CBS 等级"},
    {"key": "status", "label": "状态"},
    {"key": "notes", "label": "备注"},
    {"key": "source", "label": "来源"},
    {"key": "created_at", "label": "创建时间"},
]

EXPORT_FIELD_KEYS = {f["key"] for f in EXPORT_FIELDS}


def resolve_fields(keys: list[str] | None) -> list[dict[str, str]]:
    """把请求的字段列表解析成导出字段定义。

    没指定 → 全字段。指定了但有无效字段 → 只取有效的（忽略无效的，
    不报错 —— 前端传了脏数据不该让整个导出失败）。
    """
    if not keys:
        return EXPORT_FIELDS
    wanted = [k.strip() for k in keys if k and k.strip() in EXPORT_FIELD_KEYS]
    if not wanted:
        return EXPORT_FIELDS
    order = {f["key"]: i for i, f in enumerate(EXPORT_FIELDS)}
    return sorted(
        (f for f in EXPORT_FIELDS if f["key"] in wanted),
        key=lambda f: order[f["key"]],
    )


def _cell(asset: dict[str, Any], key: str) -> str:
    v = asset.get(key)
    if v is None:
        return ""
    return str(v)


def to_csv(assets: list[dict[str, Any]], fields: list[dict[str, str]]) -> bytes:
    """导成 CSV 字节。

    **带 UTF-8 BOM** —— 不带的话 Excel 打开中文全是乱码。
    """
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow([f["label"] for f in fields])
    for a in assets:
        writer.writerow([_cell(a, f["key"]) for f in fields])
    # utf-8-sig 会写 BOM；excel 用 lineterminator=\r\n（Windows 版 Excel 认）
    return buf.getvalue().encode("utf-8-sig")


def _display_width(s: str) -> int:
    """文本显示宽度 —— 中日韩字符算 2 列。

    不这么算的话，中文表头「资产名称」（4 个字）会比英文 "IP" 宽一倍，
    Excel 的列宽按字符数算，中文列会被挤到换行。
    """
    w = 0
    for ch in s:
        w += 2 if ord(ch) > 0x2E80 else 1
    return w


def to_xlsx(assets: list[dict[str, Any]], fields: list[dict[str, str]]) -> bytes:
    """导成 xlsx 字节。"""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "资产清单"

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="1E3A5F")
    header_align = Alignment(horizontal="center", vertical="center")

    ws.append([f["label"] for f in fields])
    for i in range(1, len(fields) + 1):
        c = ws.cell(row=1, column=i)
        c.font = header_font
        c.fill = header_fill
        c.alignment = header_align

    for a in assets:
        ws.append([_cell(a, f["key"]) for f in fields])

    # 冻结首行 + 自动筛选
    ws.freeze_panes = "A2"
    if assets:
        ws.auto_filter.ref = (
            f"A1:{get_column_letter(len(fields))}{len(assets) + 1}"
        )

    # 列宽 —— 按表头与内容的最大显示宽度估算，留一点余量
    for i, f in enumerate(fields, start=1):
        longest = _display_width(f["label"])
        for a in assets[:200]:  # 只看前 200 行，够用了
            longest = max(longest, _display_width(_cell(a, f["key"])))
        ws.column_dimensions[get_column_letter(i)].width = min(max(longest + 2, 8), 45)

    # 行高（表头行）
    ws.row_dimensions[1].height = 22

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_assets(
    assets: list[dict[str, Any]],
    fmt: str = "csv",
    keys: list[str] | None = None,
) -> tuple[bytes, str, str]:
    """导出入口。返回 (内容, media_type, 文件名扩展名)。

    `fmt` 只认 `csv` 与 `xlsx` —— 不认的按 csv 处理，不报错。
    前端下拉只有两个选项，但 API 可能被直接调用。
    """
    fields = resolve_fields(keys)
    if fmt == "xlsx":
        return to_xlsx(assets, fields), (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ), "xlsx"
    return to_csv(assets, fields), "text/csv; charset=utf-8", "csv"
