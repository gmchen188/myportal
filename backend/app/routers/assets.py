"""
资产清单 API。

三条输入路径：

    POST /api/assets/import/file      上传 csv/xlsx/xls → 映射建议 + 校验 + 预览
    POST /api/assets/import/topology   从拓扑图节点生成初步资产行（待补充）
    POST /api/assets                   手工新建一行（可带模板字段集）

    POST /api/assets/commit            把预览里选中的行落库（幂等：按去重键跳过）

预览与落库分成两步，是为了让用户能在入库前改映射、补字段、跳过重复行。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import Principal, principal_from_request
from ..db import Asset, get_session
from ..services import asset_import as ai

router = APIRouter(prefix="/api/assets", tags=["assets"])


class AssetIn(BaseModel):
    name: str
    type: str
    zone: str = ""
    natural_id: str | None = None
    ip: str | None = None
    vendor: str | None = None
    model: str | None = None
    serial: str | None = None
    owner: str | None = None
    cbs_class: str | None = None
    status: str = "在用"
    notes: str | None = None


class AssetPatch(BaseModel):
    name: str | None = None
    type: str | None = None
    zone: str | None = None
    natural_id: str | None = None
    ip: str | None = None
    vendor: str | None = None
    model: str | None = None
    serial: str | None = None
    owner: str | None = None
    cbs_class: str | None = None
    status: str | None = None
    notes: str | None = None
    needs_review: bool | None = None


class CommitIn(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list)
    mapping: list[dict[str, Any]] = Field(default_factory=list)
    headers: list[str] = Field(default_factory=list)
    source: str = "import"


@router.get("")
def list_assets(
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
    q: str | None = Query(default=None),
    zone: str | None = Query(default=None),
    needs_review: bool | None = Query(default=None),
    limit: int = Query(default=200, le=1000),
    offset: int = Query(default=0, ge=0),
):
    stmt = select(Asset).where(Asset.tenant_id == p.tenant_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            Asset.name.ilike(like) | Asset.natural_id.ilike(like)
            | Asset.ip.ilike(like) | Asset.serial.ilike(like)
        )
    if zone:
        stmt = stmt.where(Asset.zone == zone)
    if needs_review is not None:
        stmt = stmt.where(Asset.needs_review == needs_review)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = stmt.order_by(Asset.name).offset(offset).limit(limit)
    items = [a.to_dict() for a in db.scalars(stmt).all()]
    return {"items": items, "total": total, "offset": offset, "limit": limit}


@router.post("")
def create_asset(
    body: AssetIn,
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
):
    """手工新建一行。"""
    if not body.name.strip():
        raise HTTPException(400, "资产名称不能为空")
    a = Asset(
        tenant_id=p.tenant_id,
        name=body.name.strip(),
        type=body.type.strip(),
        zone=body.zone.strip(),
        natural_id=(body.natural_id or "").strip() or None,
        ip=(body.ip or "").strip() or None,
        vendor=(body.vendor or "").strip() or None,
        model=(body.model or "").strip() or None,
        serial=(body.serial or "").strip() or None,
        owner=(body.owner or "").strip() or None,
        cbs_class=(body.cbs_class or "").strip() or None,
        status=body.status,
        notes=body.notes,
        source="manual",
    )
    db.add(a)
    db.commit()
    return a.to_dict()


@router.patch("/{asset_id}")
def patch_asset(
    asset_id: int,
    body: AssetPatch,
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
):
    a = db.get(Asset, asset_id)
    if not a or a.tenant_id != p.tenant_id:
        # 别的租户的记录答 404 而不是 403 —— 403 确认了资源存在
        raise HTTPException(404, "资产不存在")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(a, k, v)
    db.commit()
    return a.to_dict()


@router.delete("/{asset_id}")
def delete_asset(
    asset_id: int,
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
):
    a = db.get(Asset, asset_id)
    if not a or a.tenant_id != p.tenant_id:
        raise HTTPException(404, "资产不存在")
    db.delete(a)
    db.commit()
    return {"deleted": asset_id}


@router.get("/schema")
def asset_schema(p: Principal = Depends(principal_from_request)):
    """字段定义 —— 前端渲染导入表单与手工录入表单都用它，不用前端再写一份。"""
    return {
        "fields": [
            {
                "key": f["key"],
                "label": f["label"],
                "required": f["required"],
                "synonyms": f["syn"],
            }
            for f in ai.ASSET_FIELDS
        ],
        "zones": sorted(ai.ALLOWED_ZONES),
    }


@router.post("/import/file")
async def import_file(
    file: UploadFile = File(...),
    mapping: str | None = Form(default=None),
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
):
    """上传 csv/xlsx → 解析 → 映射建议 → 校验 → 预览。

    这一步**不写库**。返回的行带 status，前端让用户补全/挑选后再提交。
    """
    data = await file.read()
    if not data:
        raise HTTPException(400, "文件为空")

    try:
        headers, body = ai.parse_file(file.filename or "", data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # 解析器层面的意外
        raise HTTPException(400, f"文件解析失败：{e}")

    if not headers:
        raise HTTPException(400, "没能从文件里读出表头")

    mp = None
    if mapping:
        import json

        try:
            mp = json.loads(mapping)
        except json.JSONDecodeError:
            raise HTTPException(400, "mapping 不是合法 JSON")

    existing = {
        (n or "").lower()
        for (n,) in db.execute(
            select(Asset.name).where(Asset.tenant_id == p.tenant_id)
        ).all()
    }
    result = ai.validate_rows(headers, body, mp, existing)
    result["filename"] = file.filename
    return result


@router.post("/import/topology")
def import_from_topology(
    body: dict[str, Any],
    p: Principal = Depends(principal_from_request),
):
    """从拓扑图节点生成初步资产行。

    这些行**几乎总是缺必填字段**（拓扑图不画类型和区域），全部标成
    `needs_fill` —— 用户补全后才能保存。拓扑图给的是"有哪些设备"，
    不是"这些设备是什么"。
    """
    nodes = body.get("nodes") or []
    if not isinstance(nodes, list):
        raise HTTPException(400, "nodes 必须是数组")
    rows = ai.assets_from_topology_nodes(nodes)
    return {
        "rows": [r.to_dict() for r in rows],
        "stats": {
            "total": len(rows),
            "ready": sum(1 for r in rows if r.status == "ready"),
            "skip": 0,
            "needs_fill": sum(1 for r in rows if r.status == "needs_fill"),
        },
        "issues": [
            {"level": "warn", "message": "拓扑图识别出的设备缺少类型/区域，请补充后保存", "row": None, "field": None}
        ],
    }


@router.post("/commit")
def commit_rows(
    body: CommitIn,
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
):
    """把预览里选中的行落库。

    幂等：按去重键（natural_id → 名称 → 序列号）跳过已存在的。
    **已有资产不覆盖** —— 重复行跳过并列出，不静默合并。合并错一条资产，
    后面所有统计都会跟着错。
    """
    existing_keys: set[str] = set()
    for row in db.execute(
        select(Asset.natural_id, Asset.name, Asset.serial).where(Asset.tenant_id == p.tenant_id)
    ).all():
        for v in row:
            if v and (v or "").strip():
                existing_keys.add(v.strip().lower())

    created: list[dict] = []
    skipped: list[dict] = []
    failed: list[dict] = []
    # 数据库有 (tenant_id, natural_id) 复合唯一约束 —— 应用层的去重键必须
    # 和它对齐，否则"已存在"的行会撞数据库约束而不是被跳过。
    seen_natural_ids: set[str] = {k for k in existing_keys if k}

    for i, raw in enumerate(body.rows):
        vals = dict(raw.get("values") or {})
        # status == skip 的行不导入
        if raw.get("status") == "skip":
            skipped.append({"row": raw.get("row_no"), "reason": raw.get("reason") or "被跳过"})
            continue

        name = (vals.get("name") or "").strip()
        typ = (vals.get("type") or "").strip()
        if not name or not typ:
            failed.append({"row": raw.get("row_no"), "reason": "缺少名称或类型"})
            continue

        natural_id = (vals.get("natural_id") or "").strip()
        key = ai.dedupe_key(vals)
        if key and key in existing_keys:
            skipped.append({"row": raw.get("row_no"), "reason": "与已有资产重复"})
            continue
        # 复合唯一约束 (tenant_id, natural_id) 的应用层检查 ——
        # natural_id 相同就是同一条资产，与 name/serial 的去重键无关。
        if natural_id and natural_id.lower() in seen_natural_ids:
            skipped.append({"row": raw.get("row_no"), "reason": f"资产编号 {natural_id} 已存在"})
            continue

        a = Asset(
            tenant_id=p.tenant_id,
            name=name,
            type=typ,
            zone=(vals.get("zone") or "").strip(),
            natural_id=natural_id or None,
            ip=(vals.get("ip") or "").strip() or None,
            vendor=(vals.get("vendor") or "").strip() or None,
            model=(vals.get("model") or "").strip() or None,
            serial=(vals.get("serial") or "").strip() or None,
            owner=(vals.get("owner") or "").strip() or None,
            cbs_class=(vals.get("cbs_class") or "").strip() or None,
            status=(vals.get("status") or "在用").strip(),
            notes=vals.get("notes"),
            source=vals.get("source") or body.source,
            needs_review=raw.get("status") == "needs_fill",
        )
        db.add(a)
        if key:
            existing_keys.add(key)
        if natural_id:
            seen_natural_ids.add(natural_id.lower())
        created.append({"row": raw.get("row_no"), "name": name})

    db.commit()
    return {
        "created": len(created),
        "skipped": len(skipped),
        "failed": len(failed),
        "created_items": created,
        "skipped_items": skipped,
        "failed_items": failed,
    }
