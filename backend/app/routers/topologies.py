"""
拓扑图 API。

    GET    /api/topologies              列表
    POST   /api/topologies              保存一张（draw.io XML）
    GET    /api/topologies/{id}         取一张（含 XML）
    GET    /api/topologies/{id}/graph   取投影后的节点/连线/区域
    DELETE /api/topologies/{id}

    GET    /api/topologies/{id}/importable-assets  可导入的资产清单
    POST   /api/topologies/{id}/import-assets      把资产导入成节点

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
from ..services.image_to_topology import ImageToTopologyError, generate_from_image
from ..services.topology_import import (
    TopologyImportError,
    import_assets_as_nodes,
    list_importable_assets,
)
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


class TopologyFromImageIn(BaseModel):
    """一张架构图 → 一张拓扑图。"""

    name: str
    """新拓扑图的名字"""

    image_base64: str
    """图片的 base64（不带 data: 前缀）"""

    mime: str = "image/png"
    prompt: str | None = None
    """额外的提示（默认用内置的那条）"""

    bind_assets: bool = True
    """画完要不要顺手把资产清单里的设备绑上去 —— 绑了监控面板才有颜色"""


@router.post("/from-image")
def create_topology_from_image(
    body: TopologyFromImageIn,
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
):
    """**用一张架构图生成拓扑图**，并顺手绑好资产。

    ## 为什么要有这个

    监控面板是**拓扑图 + 设备绑定**的组合：图上有形状，绑定把形状和资产清单里
    的真实设备对上，事件才能点亮节点。没有图，就只有一张空白的画布。

    「图从哪来」以前只有一条路：跳去 networktopology 手工画。用户要的是
    **在监控面板这一页，丢一张架构图进去就有监控面板**。

    ## 这条链路的四步

        图片 →(networktopology 的 AI)→ draw.io XML
             →(存拓扑)→ Topology.xml
             →(绑资产)→ device_monitors
             →(监控面板)→ 有颜色的图

    ## 绑资产为什么在这步做

    因为**图上的设备名要和资产清单里的对得上**才有意义。AI 从截图里读到的
    名字（FW-EDGE-01、CBS-NAV-01 ...）正是资产清单里的 natural_id ——
    绑定一建好，FortiSIEM 拉回来的事件就落到对应节点上。

    不绑也不会失败，只是图是灰的（unknown）。
    """
    if not body.name.strip():
        raise HTTPException(400, "拓扑图名称不能为空")
    try:
        result = generate_from_image(
            body.image_base64,
            mime=body.mime or "image/png",
            prompt=body.prompt or "",
        )
    except ImageToTopologyError as e:
        # 502 —— 上游（画图服务）的问题，不是本接口的入参问题
        raise HTTPException(502, str(e)) from e

    t = Topology(
        tenant_id=p.tenant_id,
        name=body.name.strip(),
        xml=result.xml,
        origin="image",
        description=result.message[:500] or None,
    )
    db.add(t)
    db.commit()

    bound = 0
    bind_error: str | None = None
    if body.bind_assets:
        try:
            # 可导入的资产 = 本租户里还没绑到这张图的
            importable = list_importable_assets(
                db, tenant_id=p.tenant_id, topology_id=t.id
            )
            asset_ids = [int(a["id"]) for a in (importable.get("items") or [])]
            if asset_ids:
                summary = import_assets_as_nodes(
                    db,
                    tenant_id=p.tenant_id,
                    topology_id=t.id,
                    asset_ids=asset_ids,
                )
                # bound_existing = 绑到了图里已有的同名节点（AI 读出来的名字）
                # added            = 新画出来的节点
                bound = int(summary.get("bound_existing", 0) or 0) + int(
                    summary.get("added", 0) or 0
                )
        except TopologyImportError as e:
            # 图已经存下来了 —— 绑定失败不该把整张图丢掉
            bind_error = str(e)
        except Exception as e:  # noqa: BLE001 —— 绑定是锦上添花，不该毁掉结果
            bind_error = f"绑定设备时出错：{e}"

    out = t.to_dict(include_xml=True)
    out["bound_assets"] = bound
    out["bind_error"] = bind_error
    out["ai_message"] = result.message[:500]
    return out


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


# ── 资产 → 拓扑节点 ────────────────────────────────────────────────────────
class ImportAssetsIn(BaseModel):
    asset_ids: list[int] = []
    zone: str | None = None          # 强制放到某个区域；不给就用资产自己的 zone
    link_from_node_id: str | None = None   # 从哪个既有节点连一条线过来


@router.get("/{topology_id}/importable-assets")
def get_importable_assets(
    topology_id: int,
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
):
    """该租户里、还没绑到这张拓扑图上的资产。

    排除的是**已经绑到本拓扑**的（按 natural_id / IP 判重）—— 已绑到别的拓扑
    的仍然列出来，标 ``bound_elsewhere``，让用户知道这台设备已经在别处接了监控。
    """
    t = db.get(Topology, topology_id)
    if not t or t.tenant_id != p.tenant_id:
        raise HTTPException(404, "拓扑图不存在")
    try:
        return list_importable_assets(db, p.tenant_id, topology_id)
    except TopologyImportError as e:
        raise HTTPException(404, str(e))


@router.post("/{topology_id}/import-assets")
def post_import_assets(
    topology_id: int,
    body: ImportAssetsIn,
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
):
    """把资产清单里的设备导入成拓扑节点，并建立 device_monitors 绑定。

    幂等：同一个资产重复导入不会产生第二个节点 —— 已绑定的跳过，图里已有同名
    节点的复用那个节点。
    """
    t = db.get(Topology, topology_id)
    if not t or t.tenant_id != p.tenant_id:
        raise HTTPException(404, "拓扑图不存在")
    try:
        result = import_assets_as_nodes(
            db,
            p.tenant_id,
            topology_id,
            body.asset_ids,
            zone=body.zone,
            link_from_node_id=body.link_from_node_id,
        )
    except TopologyImportError as e:
        raise HTTPException(400, str(e))

    result["topology"] = t.to_dict()
    return result
