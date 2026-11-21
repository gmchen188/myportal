"""
监控面板 API + 事件接入。

## 监控面板

    GET /api/monitor/topologies/{id}/panel
    → 节点 + 设备状态 + 颜色 + 事件计数

## 事件接入（这是"其他网络设备如何接收安全事件"的落地）

    POST /api/events/webhook     第三方系统 POST 进来（漏洞扫描、OT 监控、UEBA）
    POST /api/events/syslog      设备发来的 syslog（文本，RFC3164 风格）
    POST /api/events             人工登记
    GET  /api/events             查询

**核心设计：myPortal 自己就是事件汇聚点。**

不是所有网络设备都要接进 FortiSIEM。分通道：

    交换机/路由器/工控设备  →  syslog 到 myPortal（UDP 514 或 HTTP）
    老旧设备（不支持 syslog）→  SNMP Trap 到 myPortal
    漏洞扫描器/UEBA/OT 监控 →  HTTP webhook 到 myPortal
    Fortinet 设备          →  从 FortiSIEM 同步（FortiSIEM 仍是权威源）

所有通道最终写进同一张 `incidents` 表，按 natural_id / IP / 名称归集到设备，
监控面板按设备算颜色。

**这样做的三个好处**：

1. **FortiSIEM 不可达时监控面板仍然工作** —— 直连 myPortal 的通道不依赖 SIEM
2. **不用为每种设备类型写 FortiSIEM parser** —— 归一在 myPortal 侧做
3. **OT 网络不需要开放到 FortiSIEM 的通路** —— 很多 OT 网段不允许出站到 SOC，
   设备直连 myPortal（部署在 OT 侧）更现实
"""

from __future__ import annotations

import re
import socket
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import Principal, principal_from_request
from ..db import DeviceMonitor, Incident, Topology, get_session
from ..services.monitoring import (
    SEVERITY_COLOR,
    compute_device_states,
    normalize_severity,
    severity_counts,
    severity_from_score,
)

router = APIRouter(prefix="/api", tags=["monitor"])


# ── 监控面板 ────────────────────────────────────────────────────────────────
@router.get("/monitor/topologies/{topology_id}/panel")
def monitor_panel(
    topology_id: int,
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
):
    """监控面板数据：节点 + 状态 + 颜色。

    这是整个监控功能的读接口。前端拿它渲染拓扑面板：
    每个节点按 severity 上色，critical 红 / high 粉红 / medium 黄 / 正常绿。
    """
    t = db.get(Topology, topology_id)
    if not t or t.tenant_id != p.tenant_id:
        raise HTTPException(404, "拓扑图不存在")

    from ..services.topology_parse import parse_topology

    graph = parse_topology(t.xml or "")

    binds = db.scalars(
        select(DeviceMonitor).where(
            DeviceMonitor.tenant_id == p.tenant_id,
            DeviceMonitor.topology_id == topology_id,
        )
    ).all()
    by_node = {m.node_id: m for m in binds}

    # 组装设备清单：拓扑节点 + 绑定信息
    devices: list[dict[str, Any]] = []
    for n in graph["nodes"]:
        b = by_node.get(n["id"])
        devices.append(
            {
                "node_id": n["id"],
                "label": n["label"],
                "zone": n.get("zone"),
                "zone_key": n.get("zone_key"),
                "x": n["x"],
                "y": n["y"],
                "w": n["w"],
                "h": n["h"],
                "natural_id": b.natural_id if b else None,
                "ip": b.ip if b else None,
                "channel": b.channel if b else "fortisiem",
                "enabled": b.enabled if b else True,
            }
        )

    # 拿该租户的活跃事件
    inc_rows = db.scalars(
        select(Incident).where(Incident.tenant_id == p.tenant_id)
    ).all()
    incidents = [
        {
            "id": i.id,
            "title": i.title,
            "severity": i.severity,
            "device_natural_id": i.device_natural_id,
            "device_ip": i.device_ip,
            "device_name": i.device_name,
            "occurred_at": i.occurred_at.isoformat() if i.occurred_at else None,
            "incident_status": 0,
            "source": i.source,
        }
        for i in inc_rows
    ]

    states = compute_device_states(devices, incidents)
    counts = severity_counts(states)

    return {
        "topology": t.to_dict(),
        "nodes": states,
        "zones": graph["zones"],
        "links": graph["links"],
        "counts": counts,
        "severity_colors": SEVERITY_COLOR,
        "total_incidents": len(incidents),
        "parse_error": graph.get("error"),
    }


# ── 事件接入 ────────────────────────────────────────────────────────────────
class EventIn(BaseModel):
    title: str
    severity: str = "medium"
    score: float | None = None
    source: str = "manual"
    device_natural_id: str | None = None
    device_ip: str | None = None
    device_name: str | None = None
    src_ip: str | None = None
    dest_ip: str | None = None
    user: str | None = None
    external_id: str | None = None
    occurred_at: datetime | None = None
    raw: dict[str, Any] | None = None


class WebhookIn(BaseModel):
    """第三方系统推来的事件。

    字段名各系统不一样（Splunk 用 `host`/`severity`，扫描器用 `target`/
    `risk`），所以接受几个别名再归一。**归一在这一处做**，不在各处重复。
    """

    title: str | None = None
    message: str | None = None
    summary: str | None = None
    severity: str | None = None
    risk: str | None = None
    level: str | None = None
    score: float | None = None
    host: str | None = None
    device: str | None = None
    device_natural_id: str | None = None
    asset_id: str | None = None
    ip: str | None = None
    dst_ip: str | None = None
    src_ip: str | None = None
    user: str | None = None
    source: str = "webhook"
    external_id: str | None = None
    occurred_at: datetime | None = None
    raw: dict[str, Any] | None = None


@router.post("/events")
def create_event(
    body: EventIn,
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
):
    sev = body.severity if body.severity in SEVERITY_COLOR else severity_from_score(body.score, body.severity)
    if sev == "unknown":
        sev = "medium"
    inc = Incident(
        tenant_id=p.tenant_id,
        external_id=body.external_id,
        title=body.title,
        severity=sev,
        score=body.score,
        source=body.source,
        device_natural_id=body.device_natural_id,
        device_ip=body.device_ip,
        device_name=body.device_name,
        src_ip=body.src_ip,
        dest_ip=body.dest_ip,
        user=body.user,
        raw=body.raw,
        occurred_at=body.occurred_at or datetime.now(timezone.utc),
    )
    db.add(inc)
    db.commit()
    return inc.to_dict()


@router.post("/events/webhook")
def create_event_webhook(
    body: WebhookIn,
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
):
    """第三方系统推事件进来。"""
    title = (body.title or body.summary or body.message or "").strip()
    if not title:
        raise HTTPException(400, "缺少 title/message/summary 之一")

    sev_raw = body.severity or body.risk or body.level
    sev = normalize_severity(sev_raw)
    if sev == "unknown":
        sev = severity_from_score(body.score, sev_raw)

    inc = Incident(
        tenant_id=p.tenant_id,
        external_id=body.external_id,
        title=title[:400],
        severity=sev,
        score=body.score,
        source=body.source,
        device_natural_id=body.device_natural_id or body.asset_id,
        device_ip=body.ip or body.dst_ip,
        device_name=body.device or body.host,
        src_ip=body.src_ip,
        dest_ip=body.dst_ip or body.ip,
        user=body.user,
        raw=body.raw or body.model_dump(),
        occurred_at=body.occurred_at or datetime.now(timezone.utc),
    )
    db.add(inc)
    db.commit()
    return inc.to_dict()


# RFC3164: <PRI>TIMESTAMP HOSTNAME TAG: CONTENT
_SYSLOG_RE = re.compile(
    r"^<(?P<pri>\d{1,3})>(?P<ts>\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+"
    r"(?P<host>\S+)\s+(?P<tag>[^:]+):\s*(?P<msg>.*)$",
    re.S,
)


@router.post("/events/syslog")
def create_event_syslog(
    payload: dict[str, Any],
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
):
    """接收设备发来的 syslog 文本。

    解析 RFC3164 头部拿主机名与 tag，再从正文里尽力提取 IP 与级别。
    提取不到就退到 "medium" —— **宁可标成中等，也不要静默丢弃一条事件**。

    生产部署时 UDP 514 的接收器由 `services/syslog_collector.py` 起，
    收进来后转成 HTTP 打到这里。
    """
    text = (payload.get("text") or payload.get("line") or "").strip()
    if not text:
        raise HTTPException(400, "缺少 text")

    host = (payload.get("host") or "").strip()
    tag = ""
    msg = text
    m = _SYSLOG_RE.match(text)
    if m:
        host = host or m.group("host")
        tag = m.group("tag")
        msg = m.group("msg")

    # 找正文里的第一个 IP
    ip = None
    ipm = re.search(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b", msg)
    if ipm:
        ip = ipm.group(1)

    # 级别：正文里的关键字优先
    sev = "medium"
    sl = msg.lower()
    if re.search(r"\b(critical|crit|fatal|emerg\w*|严重|紧急)\b", sl):
        sev = "critical"
    elif re.search(r"\b(high|高危|严重程度\s*[:=]?\s*high)\b", sl):
        sev = "high"
    elif re.search(r"\b(low|低危)\b", sl):
        sev = "low"
    elif re.search(r"\b(info\w*|提示)\b", sl):
        sev = "informational"

    inc = Incident(
        tenant_id=p.tenant_id,
        external_id=payload.get("external_id"),
        title=(msg[:200] or tag or "syslog"),
        severity=sev,
        source="syslog",
        device_name=host or None,
        device_ip=ip,
        raw={"tag": tag, "text": text, "collector": payload.get("collector")},
        occurred_at=datetime.now(timezone.utc),
    )
    db.add(inc)
    db.commit()
    return inc.to_dict()


@router.get("/events")
def list_events(
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
    severity: str | None = Query(default=None),
    device_natural_id: str | None = Query(default=None),
    source: str | None = Query(default=None),
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0),
):
    stmt = select(Incident).where(Incident.tenant_id == p.tenant_id)
    if severity:
        stmt = stmt.where(Incident.severity == severity)
    if device_natural_id:
        stmt = stmt.where(Incident.device_natural_id == device_natural_id)
    if source:
        stmt = stmt.where(Incident.source == source)
    stmt = stmt.order_by(Incident.occurred_at.desc()).offset(offset).limit(limit)
    items = [i.to_dict() for i in db.scalars(stmt).all()]
    return {"items": items, "count": len(items)}


# ── 图生图的模型选择器 ──────────────────────────────────────────────────────
@router.get("/models/image-capable")
def image_capable_models(p: Principal = Depends(principal_from_request)):
    """图生图可选的模型清单。

    返回**全部**模型并标出 `image_capable` —— 前端要能显示"选这个不行"
    的提示，所以不能只返回可用的那部分。
    """
    from ..services.model_picker import image_capable_models as _pick

    return _pick()


@router.get("/models/{model_id}/image-check")
def image_check(
    model_id: str,
    p: Principal = Depends(principal_from_request),
):
    """检查某模型能不能读图。

    能力不足时**明确说不行**，不要默默降级 —— 用户上传了图却得到一句
    "我看不清"，比直接报错更让人困惑。
    """
    from ..services.model_picker import can_handle_image

    ok, reason = can_handle_image(model_id)
    return {"model": model_id, "can_handle_image": ok, "reason": reason}
