"""
FortiSIEM 同步：把 SIEM 的事件与设备拉进 myPortal。

    GET  /api/siem/status      连接状态（分阶段诊断）
    GET  /api/siem/incidents   只读预览 SIEM 事件（不落库）
    POST /api/siem/sync        同步事件 + 设备到当前租户

## 为什么要有这一层

FortiSIEM 是 Fortinet 设备的**权威事件源** —— 但它只认 Fortinet 设备。
其他设备（交换机、工控系统）走 syslog / webhook / SNMP Trap 直接进 myPortal。

两类事件最终都落在同一张 `incidents` 表，`source` 字段区分来源：

    fortisiem   从 SIEM 同步的
    syslog      设备主动发的
    webhook     第三方平台推的
    manual      人工登记的

这样监控面板只需要问「这个设备有哪些活跃事件」，不关心事件从哪来。

## 幂等

按 `external_id`（SIEM 的 incidentId）去重 —— 同一事件同步多次不会重复入库。
**不覆盖已存在的行**：SIEM 里改了标题/级别，我方保留先到的那条，
但把 SIEM 的最新状态记在 `raw` 里供排查。要覆盖得显式调 `overwrite=true`。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import Principal, principal_from_request
from ..connectors.fortisiem import get_client
from ..services.monitoring import match_device_to_nodes
from ..services.topology_parse import parse_topology
from ..db import Asset, DeviceMonitor, Incident, Topology, get_session

router = APIRouter(prefix="/api/siem", tags=["siem"])


def _tenant_org(p: Principal) -> str:
    """当前租户在 SIEM 里的组织名。

    租户表存了 `fortisiem_org`（t-asi → Super，t-dongfang → DONGFANG）。
    没有映射就不该乱拉 —— 直接报错，而不是把别的组织的事件抓过来。
    """
    if not p.fortisiem_org:
        raise HTTPException(
            400,
            f"租户 {p.tenant_slug} 没有配置 FortiSIEM 组织映射（fortisiem_org）",
        )
    return p.fortisiem_org


@router.get("/status")
def siem_status(refresh: bool = Query(False, description="强制重测，绕过探测缓存")):
    """FortiSIEM 连接状态与设备列表。

    带上**分阶段诊断**（tcp / tls / auth / api）：运维看到的是"卡在哪一段"，
    不是一句"连接失败"。

    `refresh=true` 绕过探测缓存 —— 用户点了「重新检测」就该真测一次，
    不能给他 10 秒前的旧结果。
    """
    c = get_client()
    st = c.status(use_cache=not refresh)
    out: dict[str, Any] = {
        "configured": st.configured,
        "connected": st.connected,
        "org": st.org,
        "error": st.error,
        "stage": st.stage,
        "probes": st.probes or {},
        "devices": [],
        # 「连接失败」与「设备清单拉取失败」是两回事，分开报
        "devices_error": None,
    }
    if st.connected:
        try:
            # **refresh=true 时绕过设备缓存** —— 用户点了「重新检测」
            # 就该真拉一次，不能给他 10 秒前的旧列表。
            out["devices"] = c.devices(use_cache=not refresh)
        except Exception as e:
            # **不能写进 out["error"]** —— 那个字段的语义是「连接失败」。
            # 连接明明是通的（四段全绿），只是设备清单这一步拉取失败。
            # 混在一起前端会同时显示「四段全通」和红色的「连接失败」，
            # 自相矛盾，还会让运维去查根本没问题的那一段。
            out["devices_error"] = str(e)[:300]
    return out


@router.get("/incidents")
def preview_siem_incidents(
    p: Principal = Depends(principal_from_request),
    minutes: int = Query(1440, ge=1, le=60 * 24 * 30),
    limit: int = Query(50, ge=1, le=500),
):
    """**只读预览** SIEM 里的事件，不落库。

    用来回答「SIEM 里现在有什么」—— 调试归集时先看这里，
    确认归一后的字段对不对，再决定要不要同步。
    """
    org = _tenant_org(p)
    c = get_client()
    try:
        evs = c.incidents(org=org, limit=limit, minutes=minutes)
    except Exception as e:
        # 带上 stage 与 probes —— 运维要靠它知道卡在哪一段，
        # 只剩一句「拉取事件失败」等于让人自己猜。
        st = c.status()
        raise HTTPException(
            502,
            {
                "error": "拉取事件失败",
                "detail": str(e)[:300],
                "stage": st.stage,
                "probes": st.probes or {},
            },
        ) from e
    # 预览不返回 raw（体积大且含内部字段）
    return [{k: v for k, v in e.items() if k != "raw"} for e in evs]


@router.post("/sync")
def sync_from_siem(
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
    minutes: int = Query(1440, ge=1, le=60 * 24 * 30, description="回溯分钟数"),
    limit: int = Query(200, ge=1, le=1000),
    devices: bool = Query(True, description="是否同时同步设备到资产清单"),
    overwrite: bool = Query(False, description="是否覆盖已存在的事件"),
):
    """把 SIEM 的事件同步到 myPortal。

    返回本次同步的新增数、跳过数、更新数。SIEM 不可达时返回 502 并带
    分阶段诊断 —— **不静默失败**：调用方要能区分「SIEM 没有事件」和
    「SIEM 连不上」。
    """
    org = _tenant_org(p)
    c = get_client()

    st = c.status()
    if not st.connected:
        raise HTTPException(
            502,
            {
                "error": "FortiSIEM 不可达",
                "stage": st.stage,
                "detail": st.error,
                "probes": st.probes or {},
            },
        )

    # -- 事件 ------------------------------------------------------------
    try:
        raw_events = c.incidents(org=org, limit=limit, minutes=minutes)
    except Exception as e:
        # 带上 stage 与 probes —— 运维要靠它知道卡在哪一段，
        # 只剩一句「拉取事件失败」等于让人自己猜。
        st = c.status()
        raise HTTPException(
            502,
            {
                "error": "拉取事件失败",
                "detail": str(e)[:300],
                "stage": st.stage,
                "probes": st.probes or {},
            },
        ) from e

    created = skipped = updated = 0
    seen_ids: set[str] = set()
    for ev in raw_events:
        ext = ev.get("external_id") or ""
        if not ext:
            continue
        if ext in seen_ids:
            # 同一批次里重复了（SIEM 偶尔会返回重复行）
            skipped += 1
            continue
        seen_ids.add(ext)

        existing = db.scalars(
            select(Incident).where(
                Incident.tenant_id == p.tenant_id,
                Incident.external_id == ext,
            )
        ).first()

        if existing is not None:
            if overwrite:
                existing.title = ev.get("title") or existing.title
                existing.severity = ev.get("severity") or existing.severity
                existing.raw = ev.get("raw")
                updated += 1
            else:
                skipped += 1
            continue

        db.add(
            Incident(
                tenant_id=p.tenant_id,
                external_id=ext,
                title=ev.get("title") or f"FortiSIEM 事件 {ext}",
                severity=ev.get("severity") or "medium",
                score=ev.get("score"),
                source="fortisiem",
                device_natural_id=ev.get("device_name") or None,
                device_ip=ev.get("device_ip") or None,
                device_name=ev.get("device_name") or None,
                src_ip=ev.get("src_ip"),
                dest_ip=ev.get("dest_ip"),
                user=ev.get("user"),
                raw=ev.get("raw"),
                occurred_at=ev.get("occurred_at") or datetime.now(timezone.utc),
            )
        )
        created += 1

    db.commit()

    # -- 设备 → 资产清单 -------------------------------------------------
    dev_stats: dict[str, Any] = {"total": 0, "created": 0, "updated": 0, "skipped": 0}
    if devices:
        try:
            siem_devs = c.devices()
        except Exception as e:
            # 设备拉不到不影响事件 —— 事件已经入库了
            dev_stats["error"] = str(e)[:200]
            siem_devs = []
        for d in siem_devs:
            dev_stats["total"] += 1
            nid = (d.get("natural_id") or "").strip()
            if not nid:
                dev_stats["skipped"] += 1
                continue
            a = db.scalars(
                select(Asset).where(
                    Asset.tenant_id == p.tenant_id,
                    Asset.natural_id == nid,
                )
            ).first()
            vendor = (d.get("vendor") or "Fortinet")[:64]
            if a is None:
                db.add(
                    Asset(
                        tenant_id=p.tenant_id,
                        natural_id=nid,
                        name=(d.get("name") or nid)[:200],
                        type=vendor,
                        vendor=vendor,
                        model=(d.get("model") or "")[:128],
                        ip=(d.get("access_ip") or "")[:64],
                        serial=(d.get("sn") or "")[:128],
                        zone="",
                        source="fortisiem",
                        status="在用",
                    )
                )
                dev_stats["created"] += 1
            else:
                # 只补空字段，不覆盖用户填的
                changed = False
                if not a.ip and d.get("access_ip"):
                    a.ip = d["access_ip"][:64]
                    changed = True
                if not a.model and d.get("model"):
                    a.model = d["model"][:128]
                    changed = True
                if not a.serial and d.get("sn"):
                    a.serial = d["sn"][:128]
                    changed = True
                dev_stats["updated" if changed else "skipped"] += 1

        # ── 自动绑定：SIEM 设备 → 拓扑节点 ─────────────────────────────
        # 拓扑图里的方块只有标签，SIEM 里的设备只有 natural_id/IP。
        # 不自动绑，真实事件就落不到节点上，面板永远是灰的。
        dev_stats["bound"] = 0
        try:
            bound = _auto_bind_devices(db, p, siem_devs)
            dev_stats["bound"] = bound
        except Exception as e:
            dev_stats["bind_error"] = str(e)[:200]

        db.commit()

    return {
        "org": org,
        "window_minutes": minutes,
        "events": {
            "fetched": len(raw_events),
            "created": created,
            "updated": updated,
            "skipped": skipped,
        },
        "devices": dev_stats,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }

def _auto_bind_devices(
    db: Session,
    p: Principal,
    devices: list[dict[str, Any]],
) -> int:
    """把 SIEM 设备自动绑到拓扑节点上，返回新建的绑定数。

    **只建新绑定，不覆盖已有的** —— 人工调过的绑定（改过 natural_id
    指向别的设备）不能被自动匹配推翻。已有绑定按 (topology, node_id)
    唯一，自动匹配到已绑的节点就跳过。

    匹配不上的设备就不同步 —— 拓扑图里没有对应方块，硬塞一个节点
    是没有意义的。
    """
    # 找出该租户的所有拓扑图与节点
    tops = db.scalars(
        select(Topology).where(Topology.tenant_id == p.tenant_id)
    ).all()
    if not tops:
        return 0

    created = 0
    for t in tops:
        graph = parse_topology(t.xml or "")
        nodes = graph.get("nodes") or []
        if not nodes:
            continue

        # 已有绑定的节点 —— 不动
        existing = db.scalars(
            select(DeviceMonitor).where(
                DeviceMonitor.tenant_id == p.tenant_id,
                DeviceMonitor.topology_id == t.id,
            )
        ).all()
        bound_nodes = {m.node_id for m in existing}

        for d in devices:
            hits = match_device_to_nodes(d, nodes)
            for n in hits:
                node_id = str(n.get("id") or "")
                if not node_id or node_id in bound_nodes:
                    continue
                db.add(
                    DeviceMonitor(
                        tenant_id=p.tenant_id,
                        topology_id=t.id,
                        node_id=node_id,
                        node_label=(n.get("label") or "")[:200],
                        natural_id=(d.get("natural_id") or "")[:128],
                        ip=(d.get("access_ip") or "")[:64],
                        channel="fortisiem",
                        enabled=True,
                    )
                )
                bound_nodes.add(node_id)
                created += 1
    return created
