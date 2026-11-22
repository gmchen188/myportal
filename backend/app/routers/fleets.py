"""
船队 / 船 API —— 总览的两级视图与资产清单的分组依据。

## 为什么是两级

    船队视图   看整支船队：几艘船、多少设备、事件分布
    单船视图   看某一艘船：它的设备、拓扑、事件

**船队这一层是业务视角，与租户不同** —— 租户管安全隔离（谁能看到什么），
船队管归属（这堆设备属于哪支船队哪艘船）。一支船队不跨租户。

## 归属怎么算

    资产        assets.vessel_id        ← 直接挂
    监控设备    device_monitors.natural_id → assets.natural_id → vessel
    事件        incidents.device_natural_id → assets.natural_id → vessel

**监控与事件不需要自己的 vessel 列** —— 事件量大（每天几万条），
多一列就多一次写；靠 natural_id 关联一次就够。

**没归船的设备不能消失**：归到「未归船」一组，在总览里单独计数。
导入进来的设备往往还不知道装在哪艘船上。

## 端点

    GET    /api/fleets                    船队树（船队 → 船 → 统计）
    GET    /api/fleets/overview           船队视图的汇总数据
    GET    /api/fleets/vessels/{id}/overview  单船视图的数据
    POST   /api/fleets                    建船队
    PATCH  /api/fleets/{id}               改船队
    DELETE /api/fleets/{id}               删船队（船变成「未归队」，资产不动）
    GET    /api/fleets/vessels            船列表
    POST   /api/fleets/vessels            建船
    PATCH  /api/fleets/vessels/{id}       改船
    DELETE /api/fleets/vessels/{id}       删船（资产变成「未归船」，不删资产）
    POST   /api/fleets/vessels/{id}/assets  批量把资产归到这艘船

## 认证

读用宽松版（业务读接口），**写用严格版** —— 改归属是管理动作，
开发租户头不能绕过。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import Principal, principal_from_request, principal_from_request_strict, require_admin
from ..db import Asset, DeviceMonitor, Fleet, Incident, Topology, Vessel, get_session
from ..services import audit as audit_log

router = APIRouter(prefix="/api/fleets", tags=["fleets"])


# ── 输入 ────────────────────────────────────────────────────────────────


class FleetIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    code: str | None = Field(default=None, max_length=64)
    description: str | None = None


class FleetPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    code: str | None = Field(default=None, max_length=64)
    description: str | None = None


class VesselIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    fleet_id: int | None = None
    code: str | None = Field(default=None, max_length=64)
    imo: str | None = Field(default=None, max_length=32)
    description: str | None = None


class VesselPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    fleet_id: int | None = None
    code: str | None = Field(default=None, max_length=64)
    imo: str | None = Field(default=None, max_length=32)
    description: str | None = None


class AssignAssets(BaseModel):
    asset_ids: list[int] = Field(default_factory=list)


# ── 统计 ────────────────────────────────────────────────────────────────


def _severity_counts(db: Session, tenant_id: str) -> dict[int, dict[str, int]]:
    """每艘船的事件数，按严重度。

    **走 join 而不是把事件全拉出来** —— 事件量最大的一天几万条，
    拉进 Python 再数会把内存吃满。

    关联是 `incidents.device_natural_id → assets.natural_id`，
    **同一 natural_id 在多个租户都可能有** —— 所以 join 条件里带上 tenant_id，
    不然会算到别的租户的资产上。
    """
    stmt = (
        select(Asset.vessel_id, Incident.severity, func.count())
        .select_from(Incident)
        .join(
            Asset,
            (Asset.natural_id == Incident.device_natural_id)
            & (Asset.tenant_id == Incident.tenant_id),
        )
        .where(Incident.tenant_id == tenant_id)
        .group_by(Asset.vessel_id, Incident.severity)
    )
    out: dict[int, dict[str, int]] = {}
    for vessel_id, severity, n in db.execute(stmt):
        out.setdefault(vessel_id or 0, {})[severity or "unknown"] = n
    return out


def _asset_counts(db: Session, tenant_id: str) -> dict[int, int]:
    stmt = (
        select(Asset.vessel_id, func.count())
        .where(Asset.tenant_id == tenant_id)
        .group_by(Asset.vessel_id)
    )
    return {(vid or 0): n for vid, n in db.execute(stmt)}


def _monitor_counts(db: Session, tenant_id: str) -> dict[int, int]:
    """每艘船接了几台监控设备。

    走 `device_monitors.natural_id → assets.natural_id`。
    **一台设备只能算一次** —— assets 的 natural_id 在租户内唯一，
    join 出来不会重复。
    """
    stmt = (
        select(Asset.vessel_id, func.count(func.distinct(DeviceMonitor.id)))
        .select_from(DeviceMonitor)
        .join(
            Asset,
            (Asset.natural_id == DeviceMonitor.natural_id)
            & (Asset.tenant_id == DeviceMonitor.tenant_id),
        )
        .where(DeviceMonitor.tenant_id == tenant_id)
        .group_by(Asset.vessel_id)
    )
    return {(vid or 0): n for vid, n in db.execute(stmt)}


def _vessel_rows(
    db: Session,
    tenant_id: str,
    asset_counts: dict[int, int],
    monitor_counts: dict[int, int],
    sev: dict[int, dict[str, int]],
) -> list[dict[str, Any]]:
    vessels = (
        db.query(Vessel)
        .filter(Vessel.tenant_id == tenant_id)
        .order_by(Vessel.fleet_id.is_(None), Vessel.fleet_id, Vessel.id)
        .all()
    )
    rows: list[dict[str, Any]] = []
    for v in vessels:
        counts = sev.get(v.id, {})
        rows.append(
            {
                "id": v.id,
                "fleet_id": v.fleet_id,
                "name": v.name,
                "code": v.code,
                "imo": v.imo,
                "description": v.description,
                "asset_count": asset_counts.get(v.id, 0),
                "monitor_count": monitor_counts.get(v.id, 0),
                "event_count": sum(counts.values()),
                "events_by_severity": counts,
            }
        )
    # 未归船的资产：不能消失，单独一行
    unassigned = asset_counts.get(0, 0)
    if unassigned:
        rows.append(
            {
                "id": None,
                "fleet_id": None,
                "name": "未归船",
                "code": None,
                "imo": None,
                "description": "还没确认属于哪艘船的设备",
                "asset_count": unassigned,
                "monitor_count": monitor_counts.get(0, 0),
                "event_count": sum(sev.get(0, {}).values()),
                "events_by_severity": sev.get(0, {}),
            }
        )
    return rows


def _fleet_rows(
    db: Session,
    tenant_id: str,
    vessel_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    fleets = (
        db.query(Fleet)
        .filter(Fleet.tenant_id == tenant_id)
        .order_by(Fleet.id)
        .all()
    )
    topo_counts = dict(
        db.execute(
            select(Topology.fleet_id, func.count())
            .where(Topology.tenant_id == tenant_id)
            .group_by(Topology.fleet_id)
        ).all()
    )
    out: list[dict[str, Any]] = []
    for f in fleets:
        vessels = [v for v in vessel_rows if v["fleet_id"] == f.id]
        out.append(
            {
                "id": f.id,
                "name": f.name,
                "code": f.code,
                "description": f.description,
                "vessel_count": len(vessels),
                "asset_count": sum(v["asset_count"] for v in vessels),
                "monitor_count": sum(v["monitor_count"] for v in vessels),
                "event_count": sum(v["event_count"] for v in vessels),
                "events_by_severity": _merge_severity(vessels),
                "topology_count": topo_counts.get(f.id, 0),
                "vessels": vessels,
            }
        )
    return out


def _unassigned_row(vessel_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """把「未归船」那一行提升成一个独立的档。

    ## 为什么需要这一步

    「未归船」的资产 `vessel_id` 是空 → 它的 `fleet_id` 也是空 → **不属于
    任何船队**。但它必须出现在船队视图里 —— 导入进来的设备常常还不知道
    装在哪艘船上，藏起来等于让它们从总览里消失。

    不提升成档的话：`totals` 算得到它（它也在 vessel_rows 里），
    但 `fleets` 里逐支船队加起来对不上 —— **合计与分项不一致**，
    看的人会以为统计错了。
    """
    for v in vessel_rows:
        if v["id"] is None:
            return {
                "id": None,
                "name": "未归船",
                "code": None,
                "description": "还没确认属于哪艘船的设备",
                "vessel_count": 0,
                "asset_count": v["asset_count"],
                "monitor_count": v["monitor_count"],
                "event_count": v["event_count"],
                "events_by_severity": v["events_by_severity"],
                "topology_count": 0,
                "vessels": [v],
            }
    return None


def _merge_severity(vessels: list[dict[str, Any]]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for v in vessels:
        for k, n in (v.get("events_by_severity") or {}).items():
            merged[k] = merged.get(k, 0) + n
    return merged


# ── 读 ──────────────────────────────────────────────────────────────────


@router.get("")
def list_fleets(
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
):
    """船队树 —— 船队 → 船 → 统计。"""
    asset_counts = _asset_counts(db, p.tenant_id)
    monitor_counts = _monitor_counts(db, p.tenant_id)
    sev = _severity_counts(db, p.tenant_id)
    vessel_rows = _vessel_rows(db, p.tenant_id, asset_counts, monitor_counts, sev)
    fleets = _fleet_rows(db, p.tenant_id, vessel_rows)
    # 未归船的设备单列一档 —— 不能因为没归船就看不见
    unassigned = _unassigned_row(vessel_rows)
    if unassigned:
        fleets.append(unassigned)
    # 未归队的船（fleet_id 为空）也算一档，用户能看见它们
    orphan = [v for v in vessel_rows if v["fleet_id"] is None and v["id"] is not None]
    if orphan:
        fleets.append(
            {
                "id": None,
                "name": "未归队",
                "code": None,
                "description": "还没归到船队的船",
                "vessel_count": len(orphan),
                "asset_count": sum(v["asset_count"] for v in orphan),
                "monitor_count": sum(v["monitor_count"] for v in orphan),
                "event_count": sum(v["event_count"] for v in orphan),
                "events_by_severity": _merge_severity(orphan),
                "topology_count": 0,
                "vessels": orphan,
            }
        )
    return {"fleets": fleets, "vessels": vessel_rows}


@router.get("/overview")
def fleet_overview(
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
):
    """船队视图的汇总 —— 每支船队一行。"""
    asset_counts = _asset_counts(db, p.tenant_id)
    monitor_counts = _monitor_counts(db, p.tenant_id)
    sev = _severity_counts(db, p.tenant_id)
    vessel_rows = _vessel_rows(db, p.tenant_id, asset_counts, monitor_counts, sev)
    fleets = _fleet_rows(db, p.tenant_id, vessel_rows)
    unassigned = _unassigned_row(vessel_rows)
    if unassigned:
        fleets.append(unassigned)
    return {
        "fleets": fleets,
        "totals": {
            "fleet_count": len([f for f in fleets if f["id"] is not None]),
            "vessel_count": len([v for v in vessel_rows if v["id"] is not None]),
            "asset_count": sum(v["asset_count"] for v in vessel_rows),
            "monitor_count": sum(v["monitor_count"] for v in vessel_rows),
            "event_count": sum(v["event_count"] for v in vessel_rows),
        },
    }


@router.get("/vessels/{vessel_id}/overview")
def vessel_overview(
    vessel_id: int,
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
):
    """单船视图 —— 这艘船的设备、拓扑、事件。"""
    vessel = db.get(Vessel, vessel_id)
    if vessel is None or vessel.tenant_id != p.tenant_id:
        raise HTTPException(status_code=404, detail="船不存在")

    assets = (
        db.query(Asset)
        .filter(Asset.tenant_id == p.tenant_id, Asset.vessel_id == vessel.id)
        .order_by(Asset.zone, Asset.name)
        .all()
    )
    # 监控设备靠 natural_id 关联
    nat_ids = [a.natural_id for a in assets if a.natural_id]
    monitors = (
        db.query(DeviceMonitor)
        .filter(
            DeviceMonitor.tenant_id == p.tenant_id,
            DeviceMonitor.natural_id.in_(nat_ids) if nat_ids else False,
        )
        .all()
    )
    incidents = (
        db.query(Incident)
        .filter(
            Incident.tenant_id == p.tenant_id,
            Incident.device_natural_id.in_(nat_ids) if nat_ids else False,
        )
        .order_by(Incident.occurred_at.desc())
        .limit(200)
        .all()
    )
    by_sev: dict[str, int] = {}
    for i in incidents:
        by_sev[i.severity or "unknown"] = by_sev.get(i.severity or "unknown", 0) + 1

    # 这艘船的拓扑：拓扑挂在船队上，同船队的都算
    fleet = db.get(Fleet, vessel.fleet_id) if vessel.fleet_id else None
    topologies = (
        db.query(Topology)
        .filter(Topology.tenant_id == p.tenant_id)
        .all()
        if fleet is None
        else db.query(Topology)
        .filter(Topology.tenant_id == p.tenant_id, Topology.fleet_id == fleet.id)
        .all()
    )

    return {
        "vessel": {
            "id": vessel.id,
            "fleet_id": vessel.fleet_id,
            "fleet_name": fleet.name if fleet else None,
            "name": vessel.name,
            "code": vessel.code,
            "imo": vessel.imo,
            "description": vessel.description,
        },
        "assets": [
            {
                "id": a.id,
                "natural_id": a.natural_id,
                "name": a.name,
                "type": a.type,
                "zone": a.zone,
                "ip": a.ip,
                "status": a.status,
                "siem_push_status": a.siem_push_status,
            }
            for a in assets
        ],
        "monitored": [
            {
                "natural_id": m.natural_id,
                "node_label": m.node_label,
                "ip": m.ip,
                "channel": m.channel,
                "enabled": m.enabled,
            }
            for m in monitors
        ],
        "topologies": [
            {"id": t.id, "name": t.name, "node_count": t.node_count()}
            for t in topologies
        ],
        "events": [
            {
                "id": i.id,
                "title": i.title,
                "severity": i.severity,
                "device_natural_id": i.device_natural_id,
                "occurred_at": i.occurred_at.isoformat() if i.occurred_at else None,
            }
            for i in incidents
        ],
        "events_by_severity": by_sev,
    }


# ── 写 ──────────────────────────────────────────────────────────────────


@router.post("")
def create_fleet(
    body: FleetIn,
    p: Principal = Depends(principal_from_request_strict),
    db: Session = Depends(get_session),
):
    require_admin(p)
    fleet = Fleet(
        tenant_id=p.tenant_id,
        name=body.name,
        code=body.code,
        description=body.description,
    )
    db.add(fleet)
    db.commit()
    audit_log.record(db, tenant_id=p.tenant_id, user_id=getattr(p, "user_id", None), username=getattr(p, "username", None), action="fleet.create", target_type="fleet", target_id=str(fleet.id),
                    detail={"name": fleet.name})
    return {"id": fleet.id, "name": fleet.name, "code": fleet.code, "description": fleet.description}


@router.patch("/{fleet_id}")
def patch_fleet(
    fleet_id: int,
    body: FleetPatch,
    p: Principal = Depends(principal_from_request_strict),
    db: Session = Depends(get_session),
):
    require_admin(p)
    fleet = db.get(Fleet, fleet_id)
    if fleet is None or fleet.tenant_id != p.tenant_id:
        raise HTTPException(status_code=404, detail="船队不存在")
    # **exclude_unset=True 才能区分「没传」和「显式传 null」** ——
    # 用 `if v is not None` 过滤的话，PATCH {"code": null} 会被整个忽略，
    # 标签就清不掉（清空标签 = 前端把空串转成 null 发过来）。
    updates = body.model_dump(exclude_unset=True)
    # 名字不能被清空 —— 空名字会让列表页出现无名船队。
    if updates.get("name") == "":
        updates.pop("name")
    for k, v in updates.items():
        setattr(fleet, k, v)
    db.commit()
    audit_log.record(db, tenant_id=p.tenant_id, user_id=getattr(p, "user_id", None), username=getattr(p, "username", None), action="fleet.update", target_type="fleet", target_id=str(fleet.id), detail={})
    return {"id": fleet.id, "name": fleet.name, "code": fleet.code, "description": fleet.description}


@router.delete("/{fleet_id}")
def delete_fleet(
    fleet_id: int,
    p: Principal = Depends(principal_from_request_strict),
    db: Session = Depends(get_session),
):
    """删船队 —— **不删船，也不删资产**。

    船变成「未归队」，资产跟着船走。删船队不是删设备。
    """
    require_admin(p)
    fleet = db.get(Fleet, fleet_id)
    if fleet is None or fleet.tenant_id != p.tenant_id:
        raise HTTPException(status_code=404, detail="船队不存在")
    for v in db.query(Vessel).filter(Vessel.fleet_id == fleet.id).all():
        v.fleet_id = None
    for t in db.query(Topology).filter(Topology.fleet_id == fleet.id).all():
        t.fleet_id = None
    db.delete(fleet)
    db.commit()
    audit_log.record(db, tenant_id=p.tenant_id, user_id=getattr(p, "user_id", None), username=getattr(p, "username", None), action="fleet.delete", target_type="fleet", target_id=str(fleet_id), detail={})
    return {"ok": True}


@router.get("/vessels")
def list_vessels(
    fleet_id: int | None = Query(default=None),
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
):
    asset_counts = _asset_counts(db, p.tenant_id)
    monitor_counts = _monitor_counts(db, p.tenant_id)
    sev = _severity_counts(db, p.tenant_id)
    rows = _vessel_rows(db, p.tenant_id, asset_counts, monitor_counts, sev)
    if fleet_id is not None:
        rows = [r for r in rows if r["fleet_id"] == fleet_id]
    return {"vessels": rows}


@router.post("/vessels")
def create_vessel(
    body: VesselIn,
    p: Principal = Depends(principal_from_request_strict),
    db: Session = Depends(get_session),
):
    require_admin(p)
    if body.fleet_id is not None:
        fleet = db.get(Fleet, body.fleet_id)
        if fleet is None or fleet.tenant_id != p.tenant_id:
            raise HTTPException(status_code=404, detail="船队不存在")
    vessel = Vessel(
        tenant_id=p.tenant_id,
        fleet_id=body.fleet_id,
        name=body.name,
        code=body.code,
        imo=body.imo,
        description=body.description,
    )
    db.add(vessel)
    db.commit()
    audit_log.record(db, tenant_id=p.tenant_id, user_id=getattr(p, "user_id", None), username=getattr(p, "username", None), action="vessel.create", target_type="vessel", target_id=str(vessel.id),
                    detail={"name": vessel.name, "fleet_id": vessel.fleet_id})
    return {"id": vessel.id, "fleet_id": vessel.fleet_id, "name": vessel.name,
            "code": vessel.code, "imo": vessel.imo, "description": vessel.description}


@router.patch("/vessels/{vessel_id}")
def patch_vessel(
    vessel_id: int,
    body: VesselPatch,
    p: Principal = Depends(principal_from_request_strict),
    db: Session = Depends(get_session),
):
    require_admin(p)
    vessel = db.get(Vessel, vessel_id)
    if vessel is None or vessel.tenant_id != p.tenant_id:
        raise HTTPException(status_code=404, detail="船不存在")
    if body.fleet_id is not None:
        fleet = db.get(Fleet, body.fleet_id)
        if fleet is None or fleet.tenant_id != p.tenant_id:
            raise HTTPException(status_code=404, detail="船队不存在")
    for k, v in body.model_dump(exclude_unset=True).items():
        # 名字不能被清空 —— 空名字会让列表页出现无名船。
        if k == "name" and v == "":
            continue
        setattr(vessel, k, v)
    db.commit()
    audit_log.record(db, tenant_id=p.tenant_id, user_id=getattr(p, "user_id", None), username=getattr(p, "username", None), action="vessel.update", target_type="vessel", target_id=str(vessel.id), detail={})
    return {"id": vessel.id, "fleet_id": vessel.fleet_id, "name": vessel.name,
            "code": vessel.code, "imo": vessel.imo, "description": vessel.description}


@router.delete("/vessels/{vessel_id}")
def delete_vessel(
    vessel_id: int,
    p: Principal = Depends(principal_from_request_strict),
    db: Session = Depends(get_session),
):
    """删船 —— **资产不删**，只是变成「未归船」。"""
    require_admin(p)
    vessel = db.get(Vessel, vessel_id)
    if vessel is None or vessel.tenant_id != p.tenant_id:
        raise HTTPException(status_code=404, detail="船不存在")
    for a in db.query(Asset).filter(Asset.vessel_id == vessel.id).all():
        a.vessel_id = None
    db.delete(vessel)
    db.commit()
    audit_log.record(db, tenant_id=p.tenant_id, user_id=getattr(p, "user_id", None), username=getattr(p, "username", None), action="vessel.delete", target_type="vessel", target_id=str(vessel_id), detail={})
    return {"ok": True}


@router.post("/vessels/{vessel_id}/assets")
def assign_assets(
    vessel_id: int,
    body: AssignAssets,
    p: Principal = Depends(principal_from_request_strict),
    db: Session = Depends(get_session),
):
    """把一批资产归到这艘船。

    **幂等** —— 同一批资产再归一次，结果一样。
    """
    require_admin(p)
    vessel = db.get(Vessel, vessel_id)
    if vessel is None or vessel.tenant_id != p.tenant_id:
        raise HTTPException(status_code=404, detail="船不存在")
    moved = 0
    for aid in body.asset_ids:
        a = db.get(Asset, aid)
        if a is None or a.tenant_id != p.tenant_id:
            continue
        if a.vessel_id != vessel.id:
            a.vessel_id = vessel.id
            moved += 1
    db.commit()
    audit_log.record(db, tenant_id=p.tenant_id, user_id=getattr(p, "user_id", None), username=getattr(p, "username", None), action="vessel.assign_assets", target_type="vessel",
                    target_id=str(vessel.id), detail={"requested": len(body.asset_ids), "moved": moved})
    return {"ok": True, "moved": moved, "requested": len(body.asset_ids)}
