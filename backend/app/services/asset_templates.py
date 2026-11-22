"""
资产模板与草稿清单的业务逻辑。

**为什么要模板**（而不是直接把上传的文件导进 assets）：

模板往往不是可入库的数据，而是**分类骨架** —— 比如某船的设备清单模板：

    | 设备类别 | 设备名称 | 类型   | 数量 | 责任部门 |
    |---------|---------|--------|------|---------|
    | 主交换机 |         | 交换机 | 2    |         |
    | 雷达    |         | 雷达   | 4    |         |

用户要的是「照这个骨架填自己船的设备」。

所以流程是三段，**中间那段是必须的**：

    上传模板  →  生成草稿清单  →  填完落库
                   ↑
            可反复编辑、可保存、明天接着填

直接 upload→commit 没有这个中间态：用户填到一半关掉页面，前功尽弃；
而且模板里的空骨架行会被当成「缺必填字段」的错误，用户根本没法用。

## 行结构与 import/file 同构

草稿的行和 `import/file` 预览的行**完全同构**：

    {"values": {...}, "row_no": N, "status": "ready"/"needs_fill"/"skip",
     "issues": [{"level","message","row","field"}]}

这样落库能直接复用 `assets.commit_rows` 的逻辑，不必写第二套 ——
两套逻辑迟早会漂移。
"""

from __future__ import annotations

from typing import Any

from . import asset_import as ai



def _is_binary_text(s: str) -> bool:
    """判断一段文本是不是二进制/乱码。

    判据：存在控制字符（除 \t \n \r）就算二进制。
    正常的表头不会有这些字符。
    """
    if not s:
        return False
    return any(ord(c) < 32 and c not in "\t\n\r" for c in s)



def _scores_from_headers(headers: list[str], mapping: dict[str, str] | None) -> dict[str, float]:
    """算每列的映射分数。

    直接用 `ai.suggest_mapping` 的结果 —— 但要按**当前 mapping** 重算：
    用户可能手工改过映射（「类型」列改成不映射了），分数要跟着变。
    """
    mapping = mapping or {}
    out: dict[str, float] = {}
    for m in ai.suggest_mapping(headers):
        h = m["header"]
        # 用户手工指定了字段 → 用规则算的分数，但只在该列仍是该字段时采信
        if mapping.get(h) == m["field"]:
            out[h] = float(m.get("score") or 0.0)
        elif h not in mapping:
            out[h] = 0.0
    return out


def parse_template_file(filename: str, data: bytes) -> dict[str, Any]:
    """解析上传的模板文件 → 表头 + 预置行 + 映射建议 + 区域候选。

    与 `ai.parse_file` 用同一个解析器 —— 模板和普通资产表在文件格式上
    没有区别，区别只在于**用途**：模板是骨架，普通表是数据。
    """
    if not data:
        raise ValueError("文件为空")
    headers, body = ai.parse_file(filename, data)
    if not headers:
        raise ValueError("没能从文件里读出表头")

    # 表头必须是**可读的文本**。
    #
    # 解析器对二进制文件不会报错 —— 它会把乱码当成一个超长的单列表头，
    # 静默产出一个「看起来能导入、其实全是垃圾」的模板。
    # 上传个 .exe 或者损坏的 xlsx 就会这样。必须在这里挡住。
    for h in headers:
        if _is_binary_text(h):
            raise ValueError("文件看起来不是表格（表头是乱码）—— 请确认是 CSV 或 Excel")

    # 全空的行丢掉（Excel 里常有格式残留的空行）
    cleaned: list[list[str]] = []
    for row in body:
        if any((c or "").strip() for c in row):
            cleaned.append(row)

    mapping = ai.suggest_mapping(headers)

    # 区域候选：模板里出现过的、能归一成 Zone N 的值
    zone_hints: list[str] = []
    for m in mapping:
        if m["field"] != "zone":
            continue
        idx = headers.index(m["header"]) if m["header"] in headers else -1
        if idx < 0:
            continue
        for row in cleaned:
            if idx < len(row):
                z = ai.normalize_zone(row[idx])
                if z and z not in zone_hints:
                    zone_hints.append(z)

    # 映射压成 {表头: 字段key}，前端改映射时直接用
    mapping_map = {m["header"]: m["field"] for m in mapping if m["field"]}

    return {
        "headers": headers,
        "template_rows": cleaned,
        "mapping": mapping_map,
        "mapping_suggestions": mapping,
        "zone_hints": zone_hints,
        "row_count": len(cleaned),
    }


def build_draft_rows(
    headers: list[str],
    template_rows: list[list[str]],
    mapping: dict[str, str] | None = None,
    existing_names: set[str] | None = None,
) -> dict[str, Any]:
    """根据模板生成草稿行。

    **保留模板里的空骨架行。** 模板的价值就在于那些「设备类别」行 ——
    名称待填、类型已知。如果把空行全丢掉，用户拿到的就只是一张空表，
    模板的意义没了。

    所以规则是：
      - 整行全空 → 丢掉（Excel 格式残留）
      - 有类型/区域等结构性信息、但名称为空 → **保留**，标 `needs_fill`
      - 名称已有 → 标 `ready`（可直接落库）
    """
    existing_names = existing_names or set()

    # 把 {表头: 字段key} 转回 validate_rows 要的 [{header, field}] 列表。
    #
    # **必须带上 score** —— 同一字段被多列映射时（"设备类别" 与 "类型"
    # 都会匹配到 type），validate_rows 靠 score 决定取哪一列。
    # score 丢了就退回按列序取第一个，类型会变成 "主交换机" 而不是
    # "交换机" —— 资产类型全错。
    scores = _scores_from_headers(headers, mapping)
    mp = [
        {"header": h, "field": (mapping or {}).get(h), "score": scores.get(h, 0.0)}
        for h in headers
    ]

    # validate_rows 会把「缺必填字段」标成 err → status=needs_fill，
    # 正好是我们要的语义（骨架行就是待填行）。
    result = ai.validate_rows(headers, template_rows, mp, existing_names)

    rows = result["rows"]

    # 补一个「骨架行」标记：名称空但有别的信息 —— 前端可以高亮这些行，
    # 让用户知道「这些行是从模板带来的、需要填名称」
    for r in rows:
        vals = r.get("values") or {}
        has_name = bool((vals.get("name") or "").strip())
        has_structure = any(
            (vals.get(k) or "").strip()
            for k in ("type", "zone", "vendor", "model", "cbs_class", "natural_id")
        )
        r["from_template"] = not has_name and has_structure

    return {
        "rows": rows,
        "stats": result["stats"],
        "issues": result["issues"],
    }


def add_blank_row(rows: list[dict[str, Any]], fields: list[str]) -> dict[str, Any]:
    """往草稿里加一个空行（用户在 UI 里点「加一行」）。

    字段集用 ASSET_FIELDS 的 key —— 前后端对同一份定义。
    """
    blank = {
        "values": {f: "" for f in fields},
        "row_no": (max((r.get("row_no") or 0) for r in rows) + 1) if rows else 1,
        "status": "needs_fill",
        "issues": [],
        "from_template": False,
    }
    rows.append(blank)
    return blank


def revalidate_rows(
    rows: list[dict[str, Any]],
    existing_names: set[str] | None = None,
) -> dict[str, Any]:
    """草稿编辑后重新算每行的状态与提示。

    用户在表格里改了字段，「可导入/待补充」标记必须跟着变 ——
    否则用户看到「待补充」但其实已经填完了，会困惑。

    重新校验而不是增量修补：草稿行数不大（几十行），全量重算更简单，
    也不会因为漏了某条规则而算错状态。
    """
    existing_names = existing_names or set()
    required = [f["key"] for f in ai.ASSET_FIELDS if f["required"]]
    out: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    seen: dict[str, int] = {}

    for idx, raw in enumerate(rows):
        vals = dict(raw.get("values") or {})
        row_no = raw.get("row_no") or (idx + 1)
        row_issues: list[dict[str, Any]] = []
        status = "ready"

        # 整行全空 → 跳过（用户清空了一整行，删掉比留着占位好）
        if not any((v or "").strip() for v in vals.values()):
            continue

        for key in required:
            if not (vals.get(key) or "").strip():
                label = next(
                    (f["label"] for f in ai.ASSET_FIELDS if f["key"] == key), key
                )
                row_issues.append(
                    {"level": "err", "message": f"缺少必填字段「{label}」", "row": row_no, "field": key}
                )
                status = "needs_fill"

        name = (vals.get("name") or "").strip()
        if name:
            k = name.lower()
            if k in seen:
                row_issues.append(
                    {"level": "warn", "message": f"与第 {seen[k]} 行重复", "row": row_no, "field": "name"}
                )
                status = "needs_fill"
            else:
                seen[k] = row_no
            if k in existing_names:
                row_issues.append(
                    {"level": "warn", "message": "与已有资产重复", "row": row_no, "field": "name"}
                )
                status = "needs_fill"

        zone = (vals.get("zone") or "").strip()
        if zone:
            z = ai.normalize_zone(zone)
            if z != zone:
                vals["zone"] = z
            if z not in ai.ALLOWED_ZONES:
                row_issues.append(
                    {"level": "warn", "message": f"安全区域「{z}」不在允许列表", "row": row_no, "field": "zone"}
                )

        row = {
            "values": vals,
            "row_no": row_no,
            "status": status,
            "issues": row_issues,
            "from_template": raw.get("from_template", False),
        }
        out.append(row)

        for iss in row_issues:
            if iss["level"] == "err":
                issues.append(iss)

    stats = {
        "total": len(out),
        "ready": sum(1 for r in out if r["status"] == "ready"),
        "skip": 0,
        "needs_fill": sum(1 for r in out if r["status"] == "needs_fill"),
    }
    return {"rows": out, "stats": stats, "issues": issues}
