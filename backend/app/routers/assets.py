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

from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import Principal, principal_from_request, principal_from_request_strict, require_admin
from ..connectors.fortisiem import get_client as get_siem_client
from ..db import Asset, AssetDraft, AssetTemplate, DeviceMonitor, Vessel, get_session
from ..services import asset_export as ax
from ..services import asset_import as ai
from ..services import asset_templates as at
from ..services import audit as audit_log
from ..services.cmdb_push import (
    SiemWriteError,
    build_add_xml,
    map_asset,
)

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
    # 改归属 —— 资产归到哪艘船
    vessel_id: int | None = None


class CommitIn(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list)
    mapping: list[dict[str, Any]] = Field(default_factory=list)
    headers: list[str] = Field(default_factory=list)
    source: str = "import"


def _filtered_assets(
    db: Session,
    tenant_id: str,
    q: str | None = None,
    zone: str | None = None,
    needs_review: bool | None = None,
    vessel_id: int | None = None,
    fleet_id: int | None = None,
):
    """按筛选条件取资产 —— 列表与导出**共用**。

    抽出來是为了保证「列表里看到的」与「导出的」是同一批。
    筛选逻辑写两遍的话，改了一处忘了另一处，用户导出的表跟他看到的
    对不上 —— 这种问题很难被发现，因为导出的文件看起来是正常的。
    """
    stmt = select(Asset).where(Asset.tenant_id == tenant_id)
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
    # 按船 / 船队筛 —— 资产清单「先按船队-单船分类」的那一层。
    #
    # **船队筛选走子查询**，不 join —— join 会把一条资产在多艘船下
    # 重复列出来（资产只属于一艘船，但 fleet 的 join 路径不同）。
    if vessel_id is not None:
        stmt = stmt.where(Asset.vessel_id == vessel_id)
    if fleet_id is not None:
        stmt = stmt.where(
            Asset.vessel_id.in_(
                select(Vessel.id).where(
                    Vessel.tenant_id == tenant_id, Vessel.fleet_id == fleet_id
                )
            )
        )
    return stmt.order_by(Asset.name)


@router.get("")
def list_assets(
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
    q: str | None = Query(default=None),
    zone: str | None = Query(default=None),
    needs_review: bool | None = Query(default=None),
    vessel_id: int | None = Query(default=None),
    fleet_id: int | None = Query(default=None),
    limit: int = Query(default=200, le=1000),
    offset: int = Query(default=0, ge=0),
):
    stmt = _filtered_assets(db, p.tenant_id, q, zone, needs_review, vessel_id, fleet_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = stmt.offset(offset).limit(limit)
    items = [a.to_dict() for a in db.scalars(stmt).all()]
    return {"items": items, "total": total, "offset": offset, "limit": limit}


@router.get("/export")
def export_assets(
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
    q: str | None = Query(default=None),
    zone: str | None = Query(default=None),
    needs_review: bool | None = Query(default=None),
    fmt: str = Query(default="csv"),
    fields: str | None = Query(default=None),
    vessel_id: int | None = Query(default=None),
    fleet_id: int | None = Query(default=None),
):
    """导出资产清单为 CSV / Excel。

    导出的是**当前筛选后的**那一批 —— 与列表看到的完全一致
    （共用 `_filtered_assets`）。

    `fields` 是逗号分隔的字段 key 列表；不给就是全字段。

    **导出是「读」动作，不改任何数据。**
    """
    keys = [k for k in (fields or "").split(",") if k.strip()] or None
    stmt = _filtered_assets(db, p.tenant_id, q, zone, needs_review, vessel_id, fleet_id)
    assets = [a.to_dict() for a in db.scalars(stmt).all()]

    content, media_type, ext = ax.export_assets(assets, fmt=fmt, keys=keys)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"资产清单-{stamp}.{ext}"
    # RFC 5987 编码 —— 文件名含中文，必须编码，否则浏览器存下来是乱码
    quoted = quote(filename)
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": (
                f"attachment; filename=assets-{stamp}.{ext}; filename*=UTF-8''{quoted}"
            ),
            "X-Total-Count": str(len(assets)),
        },
    )


# ── 资产模板 ────────────────────────────────────────────────────────────────


@router.get("/templates")
def list_templates(
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
):
    """模板列表。"""
    stmt = (
        select(AssetTemplate)
        .where(AssetTemplate.tenant_id == p.tenant_id)
        .order_by(AssetTemplate.updated_at.desc())
    )
    items = [t.to_dict() for t in db.scalars(stmt).all()]
    return {"items": items, "total": len(items)}


@router.post("/templates")
async def upload_template(
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
):
    """上传模板文件（csv/xlsx/xls）→ 解析 → 存为模板。

    **不写 assets 表。** 模板是骨架，不是数据 —— 它描述「这个清单该有哪些
    列、预置哪些行」，用户据此创建草稿后再填内容。
    """
    data = await file.read()
    try:
        parsed = at.parse_template_file(file.filename or "", data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"模板解析失败：{e}")

    tpl = AssetTemplate(
        tenant_id=p.tenant_id,
        name=(name or "").strip() or (file.filename or "未命名模板"),
        source_filename=file.filename,
        headers=parsed["headers"],
        mapping=parsed["mapping"],
        template_rows=parsed["template_rows"],
        zone_hints=parsed["zone_hints"],
        row_count=parsed["row_count"],
        created_by=getattr(p, "username", None),
    )
    db.add(tpl)
    db.commit()
    return tpl.to_dict()


@router.get("/templates/{template_id}")
def get_template(
    template_id: int,
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
):
    tpl = db.get(AssetTemplate, template_id)
    if not tpl or tpl.tenant_id != p.tenant_id:
        raise HTTPException(404, "模板不存在")
    return tpl.to_dict()


@router.delete("/templates/{template_id}")
def delete_template(
    template_id: int,
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
):
    """删模板。草稿不受影响（`template_id` 是 SET NULL）。"""
    tpl = db.get(AssetTemplate, template_id)
    if not tpl or tpl.tenant_id != p.tenant_id:
        raise HTTPException(404, "模板不存在")
    db.delete(tpl)
    db.commit()
    return {"deleted": template_id}


# ── 草稿清单 ────────────────────────────────────────────────────────────────


@router.get("/drafts")
def list_drafts(
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
    status: str | None = Query(default=None),
):
    stmt = select(AssetDraft).where(AssetDraft.tenant_id == p.tenant_id)
    if status:
        stmt = stmt.where(AssetDraft.status == status)
    stmt = stmt.order_by(AssetDraft.updated_at.desc())
    items = [d.to_dict() for d in db.scalars(stmt).all()]
    return {"items": items, "total": len(items)}


@router.post("/drafts")
def create_draft(
    body: dict[str, Any],
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
):
    """基于模板创建草稿清单。

    模板的预置行会被复制成草稿行 —— **包括名称为空但有结构信息的骨架行**。
    骨架行正是模板的价值所在：照着填自己船的设备。
    """
    template_id = body.get("template_id")
    name = (body.get("name") or "").strip()

    tpl: AssetTemplate | None = None
    if template_id is not None:
        tpl = db.get(AssetTemplate, int(template_id))
        if not tpl or tpl.tenant_id != p.tenant_id:
            raise HTTPException(404, "模板不存在")

    headers: list[str] = list(tpl.headers) if tpl else []
    template_rows: list[list[str]] = list(tpl.template_rows) if tpl else []
    mapping: dict[str, str] = dict(tpl.mapping) if tpl else {}
    if not name:
        name = (tpl.name if tpl else "") + " 草稿"

    existing_names = {
        (n or "").lower()
        for (n,) in db.execute(
            select(Asset.name).where(Asset.tenant_id == p.tenant_id)
        ).all()
    }

    built = at.build_draft_rows(headers, template_rows, mapping, existing_names)

    draft = AssetDraft(
        tenant_id=p.tenant_id,
        template_id=tpl.id if tpl else None,
        name=name,
        rows=built["rows"],
        status="draft",
        version=1,
        created_by=getattr(p, "username", None),
    )
    db.add(draft)
    db.commit()
    return {
        "draft": draft.to_dict(),
        "stats": built["stats"],
        "issues": built["issues"],
    }


@router.get("/drafts/{draft_id}")
def get_draft(
    draft_id: int,
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
):
    d = db.get(AssetDraft, draft_id)
    if not d or d.tenant_id != p.tenant_id:
        raise HTTPException(404, "草稿不存在")
    return d.to_dict()


@router.put("/drafts/{draft_id}")
def save_draft(
    draft_id: int,
    body: dict[str, Any],
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
):
    """保存草稿。

    每次保存 **版本 +1** —— 想知道「改了多少轮」或回滚时用。
    保存时**重新校验**：用户改了字段，「可导入/待补充」标记必须跟着变，
    否则用户看到「待补充」但其实填完了会困惑。
    """
    d = db.get(AssetDraft, draft_id)
    if not d or d.tenant_id != p.tenant_id:
        raise HTTPException(404, "草稿不存在")

    rows = body.get("rows")
    if not isinstance(rows, list):
        raise HTTPException(400, "rows 必须是数组")

    if body.get("name"):
        d.name = str(body["name"]).strip() or d.name

    existing_names = {
        (n or "").lower()
        for (n,) in db.execute(
            select(Asset.name).where(Asset.tenant_id == p.tenant_id)
        ).all()
    }
    checked = at.revalidate_rows(rows, existing_names)
    d.rows = checked["rows"]
    d.version = (d.version or 1) + 1
    db.commit()
    return {"draft": d.to_dict(), "stats": checked["stats"], "issues": checked["issues"]}


@router.post("/drafts/{draft_id}/rows")
def append_draft_row(
    draft_id: int,
    body: dict[str, Any],
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
):
    """往草稿里加一行（用户在 UI 点「加一行」）。"""
    d = db.get(AssetDraft, draft_id)
    if not d or d.tenant_id != p.tenant_id:
        raise HTTPException(404, "草稿不存在")
    rows = list(d.rows or [])
    at.add_blank_row(rows, [f["key"] for f in ai.ASSET_FIELDS])
    d.rows = rows
    d.version = (d.version or 1) + 1
    db.commit()
    return {"draft": d.to_dict()}


@router.post("/drafts/{draft_id}/commit")
def commit_draft(
    draft_id: int,
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
):
    """把草稿落库到 assets。

    走**同一套**去重与校验逻辑（`_commit_rows`）—— 与一次性导入共用，
    两套逻辑迟早会漂移。

    落库后草稿状态改为 committed，并保留结果摘要 —— 还能回看当时导了什么。
    """
    d = db.get(AssetDraft, draft_id)
    if not d or d.tenant_id != p.tenant_id:
        raise HTTPException(404, "草稿不存在")

    rows = list(d.rows or [])
    # 重新校验一次 —— 落库前确认状态是最新的
    existing_names = {
        (n or "").lower()
        for (n,) in db.execute(
            select(Asset.name).where(Asset.tenant_id == p.tenant_id)
        ).all()
    }
    checked = at.revalidate_rows(rows, existing_names)
    d.rows = checked["rows"]

    result = _commit_rows(checked["rows"], p.tenant_id, db, source="template_draft")
    db.commit()

    d.status = "committed"
    d.commit_result = {
        "created": result["created"],
        "skipped": result["skipped"],
        "failed": result["failed"],
        "at": None,
    }
    db.commit()
    return {"draft": d.to_dict(), "result": result, "stats": checked["stats"]}


@router.delete("/drafts/{draft_id}")
def delete_draft(
    draft_id: int,
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
):
    d = db.get(AssetDraft, draft_id)
    if not d or d.tenant_id != p.tenant_id:
        raise HTTPException(404, "草稿不存在")
    db.delete(d)
    db.commit()
    return {"deleted": draft_id}


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

    # 改归属到别的船是**管理动作** —— 开发租户头不能改归属。
    # 其他字段（名字、状态、备注）是业务编辑，保持原来的宽松度。
    if body.vessel_id is not None:
        require_admin(p)
        # 0 表示「移出这条船」—— model_dump(exclude_none=True) 会把 null 丢掉，
        # 所以清空用一个显式的哨兵值，而不是 null。
        if body.vessel_id == 0:
            a.vessel_id = None
        else:
            vessel = db.get(Vessel, body.vessel_id)
            # **必须是本租户的船** —— 否则能把资产挂到别的租户的船上
            if vessel is None or vessel.tenant_id != p.tenant_id:
                raise HTTPException(404, "船不存在")
            a.vessel_id = vessel.id

    for k, v in body.model_dump(exclude_none=True).items():
        if k == "vessel_id":
            continue  # 上面单独处理（含清空）
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
    result = _commit_rows(body.rows, p.tenant_id, db, source=body.source)
    db.commit()
    return result


def _commit_rows(
    rows: list[dict[str, Any]],
    tenant_id: str,
    db: Session,
    source: str = "import",
) -> dict[str, Any]:
    """落库的核心逻辑 —— 预览提交与草稿提交共用。

    抽出来是为了让「草稿清单」和「一次性导入」走**同一套**去重与校验规则。
    两套逻辑迟早会漂移 —— 一套认为重复该跳过，另一套认为该更新，
    用户看到的结果就自相矛盾。
    """
    existing_keys: set[str] = set()
    for row in db.execute(
        select(Asset.natural_id, Asset.name, Asset.serial).where(Asset.tenant_id == tenant_id)
    ).all():
        # **键格式必须与 `ai.dedupe_key` 完全一致** —— 它返回
        # "natural_id:xxx" / "name:xxx" / "serial:xxx"（带字段名前缀）。
        #
        # 这里存裸值 "xxx" 的话，`key in existing_keys` 永远不成立 ——
        # **去重整个失效**，重复资产会被重复写入。
        #
        # 这不是理论问题：草稿重复提交会产生重复资产，测试实测到了。
        for field, v in zip(("natural_id", "name", "serial"), row):
            if v and str(v).strip():
                existing_keys.add(ai.dedupe_key({field: v}))

    created: list[dict] = []
    skipped: list[dict] = []
    failed: list[dict] = []
    # 数据库有 (tenant_id, natural_id) 复合唯一约束 —— 应用层的去重键必须
    # 和它对齐，否则"已存在"的行会撞数据库约束而不是被跳过。
    # natural_id 的复合唯一约束要用**裸值**比较（数据库存的是裸值），
    # 而去重键是带前缀的 —— 两者不能混用同一份集合。
    seen_natural_ids: set[str] = {
        v.strip().lower()
        for v in db.execute(
            select(Asset.natural_id).where(Asset.tenant_id == tenant_id)
        ).scalars().all()
        if v and v.strip()
    }

    for i, raw in enumerate(rows):
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
            tenant_id=tenant_id,
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
            source=vals.get("source") or source,
            needs_review=raw.get("status") == "needs_fill",
        )
        db.add(a)
        if key:
            existing_keys.add(key)
        if natural_id:
            seen_natural_ids.add(natural_id.lower())
        created.append({"row": raw.get("row_no"), "name": name})

    return {
        "created": len(created),
        "skipped": len(skipped),
        "failed": len(failed),
        "created_items": created,
        "skipped_items": skipped,
        "failed_items": failed,
    }


# ── FortiSIEM CMDB 推送 ───────────────────────────────────────────────────
#
# **推送是显式的手动动作，不是保存资产时的副作用。**
# 理由写在 services/cmdb_push.py 里 —— 简单说：CMDB 只该有「接了监控的设备」，
# 而资产清单包含全部船载设备。
#
# 这三个端点用**严格认证**（`principal_from_request_strict`）——
# 推送会改 SIEM 侧的设备库，属于管理动作，不能是开发模式免令牌。


class CmdbPushIn(BaseModel):
    asset_ids: list[int] = Field(default_factory=list)
    force: bool = False  # 已推送过的资产是否也重推


def _monitored_keys(db: Session, tenant_id: str) -> tuple[set[str], set[str]]:
    """这个租户下「已接入监控」的设备键。

    返回 (natural_id 集合, ip 集合)。

    ## 为什么需要

    CMDB 里只该有**接了监控的设备**。资产清单包含全部船载设备 ——
    实测 14 件资产里只有 7 件接了监控（`device_monitors` 表）。

    如果让用户「全选就推」，会把那 7 件没接监控的也灌进 SIEM，
    设备视图和覆盖率报表全歪 —— 这正是「保存资产时自动写 CMDB」
    这个方案被否掉的原因。

    所以前端**默认只勾选已接入监控的**，用户要推其他的得自己勾。

    ## 匹配键

    与 `services/topology_import.py` 的设备绑定规则一致：
    natural_id 与 ip 两类键都试，命中即算已接入。
    """
    stmt = select(DeviceMonitor).where(
        DeviceMonitor.tenant_id == tenant_id,
        DeviceMonitor.enabled.is_(True),
    )
    nat: set[str] = set()
    ip: set[str] = set()
    for m in db.scalars(stmt).all():
        if m.natural_id:
            nat.add(m.natural_id)
        if m.ip:
            ip.add(m.ip)
    return nat, ip


def _cmdb_assets(db: Session, tenant_id: str, asset_ids: list[int]) -> list[Asset]:
    """按 id 取资产，**并按租户过滤** —— 不能让 A 租户推 B 租户的资产。"""
    if not asset_ids:
        return []
    stmt = select(Asset).where(Asset.tenant_id == tenant_id, Asset.id.in_(asset_ids))
    return list(db.scalars(stmt).all())


@router.get("/cmdb/status")
def cmdb_status(p: Principal = Depends(principal_from_request_strict)):
    """写凭据配没配、能不能写。

    **只读，不碰 SIEM** —— 让前端能提前告诉用户「没配写凭据」，
    而不是等点推送才失败。
    """
    client = get_siem_client()
    return {
        "write_configured": client.write_configured(),
        "org": client.org,
        "base_url": client.base_url,
        "read_configured": client.configured,
    }


@router.get("/cmdb/preview")
def cmdb_preview(
    p: Principal = Depends(principal_from_request_strict),
    db: Session = Depends(get_session),
    ids: str = Query(default=""),
):
    """映射预览 —— **纯本地计算，不碰 SIEM**。

    用户在点「推送」之前先看到「我的资产会变成 CMDB 的哪些字段」，
    尤其要看清 `zone → deviceTag`、`cbs_class → purdueLevel`
    这类不直观的映射。
    """
    asset_ids = [int(x) for x in ids.split(",") if x.strip().isdigit()]
    mon_nat, mon_ip = _monitored_keys(db, p.tenant_id)

    def _mark(a: Asset) -> dict[str, Any]:
        d = map_asset(a).to_dict()
        d["monitored"] = bool(
            (a.natural_id and a.natural_id in mon_nat)
            or (a.ip and a.ip in mon_ip)
        )
        return d

    # **不带 ids 时返回全部资产的监控状态**（不含映射明细）——
    # 前端要靠它算出「默认勾选哪些」，不能等用户先勾上才有数据。
    if not asset_ids:
        stmt = select(Asset).where(Asset.tenant_id == p.tenant_id).limit(500)
        all_assets = list(db.scalars(stmt).all())
        return {
            "items": [_mark(a) for a in all_assets],
            "mapped_count": 0,
            "monitored_count": sum(
                1 for a in all_assets
                if (a.natural_id and a.natural_id in mon_nat)
                or (a.ip and a.ip in mon_ip)
            ),
            "write_configured": get_siem_client().write_configured(),
        }

    assets = _cmdb_assets(db, p.tenant_id, asset_ids)
    items = [_mark(a) for a in assets]
    return {
        "items": items,
        "mapped_count": len(assets),
        "monitored_count": sum(1 for d in items if d["monitored"]),
        "write_configured": get_siem_client().write_configured(),
    }


@router.post("/cmdb/push")
def cmdb_push(
    body: CmdbPushIn,
    p: Principal = Depends(principal_from_request_strict),
    db: Session = Depends(get_session),
):
    """把选中的资产推到 FortiSIEM CMDB。

    **幂等**：默认跳过 `siem_push_status == "ok"` 的资产
    （`force=True` 可以重推）。CMDB 没有「按 natural_id upsert」语义，
    重复推会产生重复设备。

    **失败不阻断资产保存** —— 推送失败只把该资产标成 failed，
    资产本身照旧在库里。

    **不自动同步删除** —— myPortal 删资产不动 SIEM，
    避免误删 SIEM 里正被事件关联的设备。
    """
    client = get_siem_client()
    if not client.write_configured():
        raise HTTPException(
            status_code=503,
            detail="FortiSIEM 写凭据未配置，无法推送 CMDB。",
        )

    assets = _cmdb_assets(db, p.tenant_id, body.asset_ids)
    if not assets:
        raise HTTPException(status_code=400, detail="没有可推送的资产（检查 id 或租户）。")

    # 幂等过滤
    skipped: list[dict[str, Any]] = []
    to_push: list[Asset] = []
    for a in assets:
        if a.siem_push_status == "ok" and not body.force:
            skipped.append({"id": a.id, "name": a.name, "reason": "已推送过（用 force 可重推）"})
            continue
        to_push.append(a)

    if not to_push:
        return {
            "pushed": 0,
            "skipped": skipped,
            "task_id": None,
            "message": "选中的资产都已推送过。",
        }

    mapped = [map_asset(a) for a in to_push]
    xml_body = build_add_xml(mapped)

    try:
        result = client.cmdb_add_devices(xml_body)
    except SiemWriteError as exc:
        # 记成 failed，但**不抛** —— 资产还在库里，用户可以改配置后重推
        now = datetime.now()
        for a in to_push:
            a.siem_push_status = "failed"
            a.siem_pushed_at = now
        db.commit()
        audit_log.record(
            db,
            tenant_id=p.tenant_id,
            action="cmdb_push_failed",
            user_id=getattr(p, "user_id", None),
            username=getattr(p, "username", None),
            target_type="asset",
            detail={"count": len(to_push), "error": str(exc), "kind": exc.kind},
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    task_id = result.get("task_id") or None
    now = datetime.now()
    for a in to_push:
        a.siem_push_status = "ok"
        a.siem_pushed_at = now
        a.siem_task_id = task_id
    db.commit()

    audit_log.record(
        db,
        tenant_id=p.tenant_id,
        action="cmdb_push",
        user_id=getattr(p, "user_id", None),
        username=getattr(p, "username", None),
        target_type="asset",
        detail={
            "count": len(to_push),
            "task_id": task_id,
            "asset_ids": [a.id for a in to_push],
        },
    )

    return {
        "pushed": len(to_push),
        "skipped": skipped,
        "task_id": task_id,
        "message": f"已提交 {len(to_push)} 台设备到 FortiSIEM CMDB。"
        + (f"（任务号 {task_id}）" if task_id else ""),
    }
