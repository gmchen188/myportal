"""
myPortal 后端 —— 数据层。

用 SQLAlchemy 2.x + SQLite。选 SQLite 是因为这是笔记本开发环境：零部署、
单文件库、可以直接删库重来。接口层全部走 SQLAlchemy ORM，将来换 PostgreSQL
只改 `create_engine` 的 URL 与 `DATABASE_URL` 环境变量，模型与查询不动。

三张核心表对应产品的三个域：

    assets      资产清单      —— 一行一件设备（船舶/网络设备）
    topologies  网络拓扑图    —— 一行一张 draw.io XML 拓扑
    incidents   安全事件      —— 从 SIEM 同步过来的事件，按设备归集

外加一张 `device_monitors` 把「拓扑里的节点」与「接监控的设备」关联起来 ——
这是监控面板能按设备变色的关键：拓扑图只画形状，监控状态来自 CMDB 设备。
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker

# ── 配置 ────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

DATABASE_URL = os.getenv("MP_DATABASE_URL", f"sqlite:///{os.path.join(DATA_DIR, 'myportal.db')}")

# SQLite 默认不开外键约束，且单线程写入在高并发下会 "database is locked"。
# WAL + busy_timeout 是让 FastAPI 的同步 session 在多请求下不打架的最小配置。
engine = create_engine(
    DATABASE_URL,
    future=True,
    connect_args={"check_same_thread": False, "timeout": 30},
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - 连接钩子
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=30000")
    cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── 租户 ────────────────────────────────────────────────────────────────────
class Tenant(Base):
    """租户。作用域来自凭据，不来自请求参数 —— 这是多租户的第一道防线。

    资产/拓扑/事件都外键指向这里。**没有租户行就不能挂资产** —— 这不是
    缺陷，是有意的：孤儿资产会让租户过滤失效。
    """

    __tablename__ = "tenants"

    id = Column(String(64), primary_key=True)
    slug = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    locale = Column(String(16), nullable=False, default="zh-CN")
    fortisiem_org = Column(String(120), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    assets = relationship("Asset", back_populates="tenant", cascade="all, delete-orphan")
    topologies = relationship("Topology", back_populates="tenant", cascade="all, delete-orphan")


# ── 资产清单 ────────────────────────────────────────────────────────────────
class Asset(Base):
    """一件资产。

    `natural_id` 是去重键（与 myPortal 既有规则一致）：先 natural_id，
    再名称，再序列号。**已有资产不会被覆盖** —— 导入时重复行跳过并列出。

    `zone` 是安全区域（Zone 0..3），拓扑图与资产清单靠它对齐。
    """

    __tablename__ = "assets"
    __table_args__ = (UniqueConstraint("tenant_id", "natural_id", name="uq_asset_tenant_natural"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)

    natural_id = Column(String(128), nullable=True, index=True)
    name = Column(String(200), nullable=False, index=True)
    type = Column(String(64), nullable=False)
    zone = Column(String(64), nullable=True)
    ip = Column(String(64), nullable=True, index=True)
    vendor = Column(String(64), nullable=True)
    model = Column(String(128), nullable=True)
    serial = Column(String(128), nullable=True)
    owner = Column(String(120), nullable=True)
    cbs_class = Column(String(64), nullable=True)
    status = Column(String(32), nullable=True, default="在用")

    # 来源：cmdb / ur_ledger / import / topology_image
    source = Column(String(32), nullable=False, default="import")
    # 该行是否由「拓扑图生成」而来 —— 这类行缺必填字段，等用户补
    needs_review = Column(Boolean, nullable=False, default=False)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    tenant = relationship("Tenant", back_populates="assets")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "natural_id": self.natural_id,
            "name": self.name,
            "type": self.type,
            "zone": self.zone,
            "ip": self.ip,
            "vendor": self.vendor,
            "model": self.model,
            "serial": self.serial,
            "owner": self.owner,
            "cbs_class": self.cbs_class,
            "status": self.status,
            "source": self.source,
            "needs_review": self.needs_review,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ── 拓扑图 ──────────────────────────────────────────────────────────────────
class Topology(Base):
    """一张网络拓扑图。

    `xml` 存 draw.io 的 mxfile XML（整份，不解析）。解析发生在读的时候 ——
    存一份原文，读的时候投影成「节点 + 连线」供监控面板用，这样 draw.io
    的格式演进不需要迁移数据。
    """

    __tablename__ = "topologies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)

    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    xml = Column(Text, nullable=False, default="")
    # 拓扑图里每个节点对应哪件资产（natural_id → 节点标签）
    node_bindings = Column(JSON, nullable=False, default=dict)
    # 图片导入时的原始来源说明
    origin = Column(String(32), nullable=False, default="manual")
    source_image = Column(String(400), nullable=True)

    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    tenant = relationship("Tenant", back_populates="topologies")

    def node_count(self) -> int:
        """这张图上**真正的设备节点数**。

        **不能用 len(node_bindings)** —— 那是「有多少节点绑了监控通道」，
        不是「图上有多少节点」。一张 11 个节点、只绑了 4 台设备的图，
        绑定数是 4，节点数是 11。拓扑列表那一列说的是「节点」。

        绑定数与节点数本来就不该相等：
          · 节点没绑设备   → 绑定数 < 节点数（绝大多数节点是这样）
          · 同一台设备画了  → 绑定数可能 > 节点数
            多个节点

        XML 解析放在函数里惰性导入 —— db.py 是数据层，不该在模块顶层
        依赖 services（services 又依赖 db，顶层互相 import 会成环）。
        """
        try:
            from .services.topology_parse import parse_topology

            g = parse_topology(self.xml or "")
            if not g.get("error"):
                return len(g.get("nodes") or [])
        except Exception:  # pragma: no cover - 解析器出问题不该让列表页 500
            pass
        return len(self.node_bindings or {})

    def to_dict(self, include_xml: bool = False) -> dict[str, Any]:
        d = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "node_bindings": self.node_bindings or {},
            "origin": self.origin,
            "source_image": self.source_image,
            "node_count": self.node_count(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_xml:
            d["xml"] = self.xml
        return d


# ── 安全事件 ────────────────────────────────────────────────────────────────
class Incident(Base):
    """一条安全事件。

    `device_natural_id` / `device_ip` 是归集到设备的依据 —— 监控面板按它
    决定哪个节点变色。FortiSIEM 那边对应 `host_ip_addr` / `host_name`。

    `source` 区分事件来源：fortisiem 是从 SIEM 同步的，其余（syslog /
    snmp_trap / webhook / manual）是**其他网络设备**的通道 —— 详见
    docs/BACKEND.md 的「非 Fortinet 设备如何接入」。
    """

    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)

    external_id = Column(String(200), nullable=True, index=True)
    title = Column(String(400), nullable=False)
    # critical / high / medium / low / informational
    severity = Column(String(32), nullable=False, default="medium", index=True)
    score = Column(Float, nullable=True)

    source = Column(String(32), nullable=False, default="fortisiem", index=True)
    device_natural_id = Column(String(128), nullable=True, index=True)
    device_ip = Column(String(64), nullable=True, index=True)
    device_name = Column(String(200), nullable=True)

    src_ip = Column(String(64), nullable=True)
    dest_ip = Column(String(64), nullable=True)
    user = Column(String(120), nullable=True)
    raw = Column(JSON, nullable=True)

    occurred_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "external_id": self.external_id,
            "title": self.title,
            "severity": self.severity,
            "score": self.score,
            "source": self.source,
            "device_natural_id": self.device_natural_id,
            "device_ip": self.device_ip,
            "device_name": self.device_name,
            "src_ip": self.src_ip,
            "dest_ip": self.dest_ip,
            "user": self.user,
            "occurred_at": self.occurred_at.isoformat() if self.occurred_at else None,
        }


class DeviceMonitor(Base):
    """把「拓扑里的节点」与「接监控的设备」关联起来。

    没有这张表，监控面板就不知道 draw.io 图里的那个方块对应哪台设备 ——
    拓扑图存的是形状和标签，设备在 CMDB 里，两边靠这张表对齐。
    """

    __tablename__ = "device_monitors"
    __table_args__ = (UniqueConstraint("topology_id", "node_id", name="uq_monitor_topology_node"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    topology_id = Column(Integer, ForeignKey("topologies.id", ondelete="CASCADE"), nullable=False, index=True)

    node_id = Column(String(120), nullable=False)
    node_label = Column(String(200), nullable=True)
    natural_id = Column(String(128), nullable=True, index=True)
    ip = Column(String(64), nullable=True, index=True)
    # 该节点接哪个通道：fortisiem / syslog / snmp / webhook
    channel = Column(String(32), nullable=False, default="fortisiem")
    enabled = Column(Boolean, nullable=False, default=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "node_id": self.node_id,
            "node_label": self.node_label,
            "natural_id": self.natural_id,
            "ip": self.ip,
            "channel": self.channel,
            "enabled": self.enabled,
        }


def init_db() -> None:
    """建表 + 播种开发租户。

    生产环境该用 alembic，但这个项目还没有迁移历史。
    """
    Base.metadata.create_all(engine)
    seed_tenants()


def seed_tenants() -> None:
    """把开发租户写进 tenants 表。

    auth.py 里的 DEV_TENANTS 只是内存常量 —— 资产要外键挂到 tenants 行上，
    没有这行，写资产就会撞 FOREIGN KEY constraint failed。

    **只播种不覆盖**：已存在的租户行保持原样（可能已被后台改过名字）。
    """
    from .auth import DEV_TENANTS

    with SessionLocal() as db:
        for slug, t in DEV_TENANTS.items():
            exists = db.get(Tenant, t["id"])
            if exists:
                continue
            db.add(
                Tenant(
                    id=t["id"],
                    slug=slug,
                    name=t["name"],
                    locale="zh-CN",
                    fortisiem_org=t.get("fortisiem_org"),
                )
            )
        db.commit()


def get_session():
    """FastAPI 依赖：每个请求一个 session，用完关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
