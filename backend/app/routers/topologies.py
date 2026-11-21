"""
拓扑图 API。

    GET    /api/topologies              列表
    POST   /api/topologies              保存一张（draw.io XML）
    GET    /api/topologies/{id}         取一张（含 XML）
    GET    /api/topologies/{id}/graph   取投影后的节点/连线/区域
    DELETE /api/topologies/{id}

存整份 XML，读的时候投影 —— 见 services/topology_parse.py 的说明。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import Principal, principal_from_request
from ..db import DeviceMonitor, Topology, get_session
from ..services.topology_parse import parse_topology

router = APIRouter(prefix="/api/topologies", tags=["topologies"])


class TopologyIn(BaseModel):
    name: str
    description: str | None = None
    xml: str = ""
    origin: str = "manual"          # manual / image / ai / template
    source_image: str | None = None
    node_bindings: dict[str, Any] = {}


@router.get("")
def list_topologies(
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
):
    stmt = (
        select(Topology)
        .where(Topology.tenant_id == p.tenant_id)
        .order_by(Topology.updated_at.desc())
    )
    return {"items": [t.to_dict() for t in db.scalars(stmt).all()]}


@router.post("")
def save_topology(
    body: TopologyIn,
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
):
    if not body.name.strip():
        raise HTTPException(400, "拓扑图名称不能为空")
    t = Topology(
        tenant_id=p.tenant_id,
        name=body.name.strip(),
        description=body.description,
        xml=body.xml,
        origin=body.origin,
        source_image=body.source_image,
        node_bindings=body.node_bindings or {},
    )
    db.add(t)
    db.commit()
    return t.to_dict(include_xml=True)


@router.get("/{topology_id}")
def get_topology(
    topology_id: int,
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
):
    t = db.get(Topology, topology_id)
    if not t or t.tenant_id != p.tenant_id:
        raise HTTPException(404, "拓扑图不存在")
    return t.to_dict(include_xml=True)


@router.delete("/{topology_id}")
def delete_topology(
    topology_id: int,
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
):
    t = db.get(Topology, topology_id)
    if not t or t.tenant_id != p.tenant_id:
        raise HTTPException(404, "拓扑图不存在")
    db.delete(t)
    db.commit()
    return {"deleted": topology_id}


@router.get("/{topology_id}/graph")
def get_graph(
    topology_id: int,
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
):
    """投影后的节点/连线/区域 —— 监控面板直接吃这个结构。"""
    t = db.get(Topology, topology_id)
    if not t or t.tenant_id != p.tenant_id:
        raise HTTPException(404, "拓扑图不存在")
    graph = parse_topology(t.xml or "")
    graph["topology"] = t.to_dict()
    return graph


@router.get("/{topology_id}/monitors")
def list_monitors(
    topology_id: int,
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
):
    """节点 ↔ 设备的绑定表。监控面板靠它知道哪个方块接哪台设备。"""
    t = db.get(Topology, topology_id)
    if not t or t.tenant_id != p.tenant_id:
        raise HTTPException(404, "拓扑图不存在")
    rows = db.scalars(
        select(DeviceMonitor).where(
            DeviceMonitor.tenant_id == p.tenant_id,
            DeviceMonitor.topology_id == topology_id,
        )
    ).all()
    return {"items": [m.to_dict() for m in rows]}


class MonitorIn(BaseModel):
    node_id: str
    node_label: str | None = None
    natural_id: str | None = None
    ip: str | None = None
    channel: str = "fortisiem"
    enabled: bool = True


@router.post("/{topology_id}/monitors")
def upsert_monitor(
    topology_id: int,
    body: MonitorIn,
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
):
    """绑定或更新一个节点的监控通道。"""
    t = db.get(Topology, topology_id)
    if not t or t.tenant_id != p.tenant_id:
        raise HTTPException(404, "拓扑图不存在")

    m = db.scalar(
        select(DeviceMonitor).where(
            DeviceMonitor.tenant_id == p.tenant_id,
            DeviceMonitor.topology_id == topology_id,
            DeviceMonitor.node_id == body.node_id,
        )
    )
    if not m:
        m = DeviceMonitor(tenant_id=p.tenant_id, topology_id=topology_id, node_id=body.node_id)
        db.add(m)
    m.node_label = body.node_label
    m.natural_id = body.natural_id
    m.ip = body.ip
    m.channel = body.channel
    m.enabled = body.enabled
    db.commit()
    return m.to_dict()
