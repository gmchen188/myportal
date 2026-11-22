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
    # 停用的租户：登录被拒、后台看不到它的数据，但**历史数据不删**。
    # 安全事件要留痕 —— 不能因为客户不续费就把记录抹了。
    is_active = Column(Boolean, nullable=False, default=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    assets = relationship("Asset", back_populates="tenant", cascade="all, delete-orphan")
    topologies = relationship("Topology", back_populates="tenant", cascade="all, delete-orphan")
    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "slug": self.slug,
            "name": self.name,
            "locale": self.locale,
            "fortisiem_org": self.fortisiem_org,
            "is_active": self.is_active,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


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

    # 这件资产属于哪艘船 —— 船队视图与单船视图的分组依据。
    #
    # **可空**：还没归船的资产也要能存在（导入进来的设备往往还不知道
    # 装在哪艘船上）。空着的资产在总览里归到「未归船」，
    # 在资产清单里单列一组 —— **不能因为没归船就看不见**。
    vessel_id = Column(Integer, ForeignKey("vessels.id", ondelete="SET NULL"), nullable=True, index=True)

    # 来源：cmdb / ur_ledger / import / topology_image
    source = Column(String(32), nullable=False, default="import")
    # 该行是否由「拓扑图生成」而来 —— 这类行缺必填字段，等用户补
    needs_review = Column(Boolean, nullable=False, default=False)
    notes = Column(Text, nullable=True)

    # ── FortiSIEM CMDB 推送状态 ──────────────────────────────────
    #
    # **推送是手动动作，不是保存资产时的副作用**（理由见 services/cmdb_push.py）。
    # 这三列让列表能直接显示「未推送 / 已推送 / 推送失败」，
    # 用户自己决定要不要重来 —— 避免重复推产生 CMDB 里的重复设备。
    #
    # siem_push_status: None(未推送) / pending(排队中) / ok(已推送) / failed(失败)
    siem_pushed_at = Column(DateTime(timezone=True), nullable=True)
    siem_push_status = Column(String(32), nullable=True)
    siem_task_id = Column(String(128), nullable=True)

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
            # 归属到哪艘船 —— 资产清单按船队-单船分类的依据
            "vessel_id": self.vessel_id,
            # CMDB 推送状态 —— 前端用它显示「未推送/推送中/已推送/推送失败」。
            #
            # **漏掉这三个字段的后果是静默的**：前端 `siem_push_status !== "ok"`
            # 永远成立，于是**已推送的资产也显示成「未推送」** —— 用户会再推一次，
            # CMDB 里就多了一台重复设备。
            "siem_push_status": self.siem_push_status,
            "siem_pushed_at": self.siem_pushed_at.isoformat() if self.siem_pushed_at else None,
            "siem_task_id": self.siem_task_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ── 资产模板与草稿清单 ──────────────────────────────────────────────────────


class AssetTemplate(Base):
    """资产清单的**模板** —— 用户上传的 Excel/CSV 文件解析结果。

    模板定义「这个清单该有哪些列、预置哪些行」。用户据此创建一份
    **草稿清单**，在草稿里填内容，最后落库到 `assets`。

    为什么不直接把上传的文件导进 assets：

    - 模板往往是**分类骨架**（如某船的设备清单模板：主机、交换机、
      传感器各若干行，名称待填），不是可入库的数据。
    - 用户需要「先看结构、再填内容、填一半能存下来明天接着填」。
      直接 commit 就没有这个中间态。
    """

    __tablename__ = "asset_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)

    name = Column(String(200), nullable=False)
    source_filename = Column(String(300), nullable=True)

    # 表头 —— 原始列名，保留用户的叫法
    headers = Column(JSON, nullable=False, default=list)
    # 列 → 资产字段的映射建议（key 是表头，value 是 ASSET_FIELDS 的 key）
    mapping = Column(JSON, nullable=False, default=dict)
    # 模板里的预置行（原始表格数据，未映射）
    template_rows = Column(JSON, nullable=False, default=list)
    # 模板里出现过的安全区域 —— 生成草稿时用作下拉候选
    zone_hints = Column(JSON, nullable=False, default=list)
    # 模板行数（不含表头）
    row_count = Column(Integer, nullable=False, default=0)

    created_by = Column(String(120), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    tenant = relationship("Tenant")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "source_filename": self.source_filename,
            "headers": self.headers or [],
            "mapping": self.mapping or {},
            "template_rows": self.template_rows or [],
            "zone_hints": self.zone_hints or [],
            "row_count": self.row_count,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class AssetDraft(Base):
    """基于模板创建的**资产清单草稿** —— 可反复编辑、保存、提交。

    `rows` 存的是与 `import/file` 预览**同构**的行结构
    （`{values, row_no, status, issues}`），所以落库能直接复用
    现有的 commit 逻辑，不必写第二套。

    `status`:
      draft      —— 还在编辑
      committed  —— 已经落库到 assets（保留，作为快照可回看）
    """

    __tablename__ = "asset_drafts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    template_id = Column(Integer, ForeignKey("asset_templates.id", ondelete="SET NULL"), nullable=True, index=True)

    name = Column(String(200), nullable=False)
    # 草稿行 —— 同构于 ImportRow
    rows = Column(JSON, nullable=False, default=list)
    status = Column(String(32), nullable=False, default="draft", index=True)

    # 每次保存版本 +1 —— 想知道「改了多少轮」或回滚时用
    version = Column(Integer, nullable=False, default=1)
    # 上次落库的结果摘要（新增/跳过/失败）
    commit_result = Column(JSON, nullable=True)

    created_by = Column(String(120), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    tenant = relationship("Tenant")
    template = relationship("AssetTemplate")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "template_id": self.template_id,
            "name": self.name,
            "rows": self.rows or [],
            "status": self.status,
            "version": self.version,
            "commit_result": self.commit_result,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ── 拓扑图 ──────────────────────────────────────────────────────────────────
class Fleet(Base):
    """一支船队 —— 船的上层分组。

    总览分**两级**：船队视图看整支船队的设备与事件，单船视图看某一艘船。
    船队这一层是**业务视角**，与**租户**不同 —— 租户管的是安全隔离
    （谁能看到什么），船队管的是**归属**（这堆设备属于哪支船队哪艘船）。

    所以两者不是一回事：一支船队不会跨租户，一艘船也不会跨租户。
    """

    __tablename__ = "fleets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)

    name = Column(String(200), nullable=False, index=True)
    # 船队代号 / 呼号 —— 现场常按代号叫船队
    code = Column(String(64), nullable=True, index=True)
    description = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    tenant = relationship("Tenant")


class Vessel(Base):
    """一艘船 —— 资产的直接归属。

    **资产挂在船上**，而不是直接挂在船队上 —— 因为船队视图是聚合出来的，
    有了船才能按船聚合。事件与监控设备**不需要**这一列：它们通过
    `natural_id → assets → vessel` 归属到船。
    """

    __tablename__ = "vessels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    # 船队 —— 可以为空（还没归队的船）
    #
    # **必须是 Integer**：fleet_id 指向 fleets.id（整数主键）。
    # 写成 String(64) 时 SQLite 会把值存成文本 '2'，于是
    # `vessel.fleet_id == fleet.id` 永远不成立 —— 船队视图会显示「0 艘船」。
    fleet_id = Column(Integer, ForeignKey("fleets.id", ondelete="SET NULL"), nullable=True, index=True)

    name = Column(String(200), nullable=False, index=True)
    # 船代号 / 呼号 / IMO 编号
    code = Column(String(64), nullable=True, index=True)
    imo = Column(String(32), nullable=True)
    description = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    tenant = relationship("Tenant")
    fleet = relationship("Fleet")


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
    # 这张图属于哪支船队 —— 一支船队一张总图。
    # 船队视图从它取「这支船队有几张图、多少节点」。
    fleet_id = Column(Integer, ForeignKey("fleets.id", ondelete="SET NULL"), nullable=True, index=True)
    xml = Column(Text, nullable=False, default="")
    # 拓扑图里每个节点对应哪件资产。
    #
    # **方向是 node_id → {natural_id, label, ip}**，不是 natural_id → 节点标签。
    # 依据：node_id 是唯一能「一节点一 key」的标识 —— natural_id 不保证存在
    # （SIEM 同步进来的设备可能没有），也不保证一台设备只画一个节点。
    # 要按 natural_id 查，扫 value 即可。
    # 写入方见 services/topology_import.py。
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


# ── 用户 ────────────────────────────────────────────────────────────────────
class User(Base):
    """一个能登录的人。

    **为什么要有这张表** —— 之前 auth.py 里只有 `issue_access_token`
    这个函数，**却没有任何地方能拿到令牌**：没有登录端点、没有用户表。
    多租户认证是「有锁没钥匙」，生产模式一开谁都登不进去。

    角色：
        tenant_admin  —— 本租户管理员，能管本租户的用户与接入源
        analyst       —— 能看数据、不能改配置
        viewer        —— 只读
        super_admin   —— 能管所有租户

    `password_hash` 用 bcrypt —— **绝不明文存密码**。
    """

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "username", name="uq_user_tenant_username"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)

    username = Column(String(120), nullable=False, index=True)
    password_hash = Column(String(200), nullable=False)
    display_name = Column(String(200), nullable=True)
    role = Column(String(32), nullable=False, default="viewer")
    email = Column(String(200), nullable=True)

    is_active = Column(Boolean, nullable=False, default=True)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    # 连续登录失败次数 —— 用来锁暴力破解
    failed_attempts = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    tenant = relationship("Tenant", back_populates="users")

    def to_dict(self) -> dict[str, Any]:
        """**不含 password_hash** —— 任何对外输出都不能带它。"""
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "username": self.username,
            "display_name": self.display_name,
            "role": self.role,
            "email": self.email,
            "is_active": self.is_active,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
            "failed_attempts": self.failed_attempts,
            "locked_until": self.locked_until.isoformat() if self.locked_until else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ── 接入源 ──────────────────────────────────────────────────────────────────
class IntakeSource(Base):
    """一个事件来源。

    **这是「真正有用的后台」最核心的一张表** —— 之前 syslog / webhook
    的接收端点都在代码里，但**没有任何地方能配置它们**：
    运维不知道有哪些接入源、哪个开着、上次收到东西是什么时候。

    `kind` 对应通道：
        fortisiem  —— 从 SIEM 同步
        syslog     —— UDP/TCP syslog 收进来
        webhook    —— 第三方系统推
        agent      —— 部署在设备侧的采集器

    `config` 存通道自己的配置（JSON）：syslog 收哪个端口、webhook 的
    密钥、agent 的地址。**不存明文凭据** —— 密钥类的字段由调用方自己
    处理，这里只记录非敏感的连接参数。
    """

    __tablename__ = "intake_sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)

    kind = Column(String(32), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    config = Column(JSON, nullable=True)

    enabled = Column(Boolean, nullable=False, default=True)
    # 上次收到事件的时间 —— 「这个通道还活着吗」的判据
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    # 累计收到多少条 —— 一眼看出哪个通道在贡献数据
    events_received = Column(Integer, nullable=False, default=0)

    created_by = Column(String(120), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "kind": self.kind,
            "name": self.name,
            "description": self.description,
            "config": self.config or {},
            "enabled": self.enabled,
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
            "events_received": self.events_received,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ── 审计日志 ────────────────────────────────────────────────────────────────
class AuditLog(Base):
    """谁在什么时候做了什么。

    **安全运营门户没有审计日志等于没有 accountability** ——
    出事了查不到人。写日志的粒度刻意定在「管理动作」上
    （建用户、停租户、改接入源、删资产），而不是每次查询 ——
    全量记查询会把库撑爆，而且没人会去看。

    `detail` 存动作的上下文（JSON）：改了哪个字段、改前是什么。
    """

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)

    user_id = Column(Integer, nullable=True)
    username = Column(String(120), nullable=True)
    action = Column(String(64), nullable=False, index=True)
    target_type = Column(String(64), nullable=True)
    target_id = Column(String(120), nullable=True)
    detail = Column(JSON, nullable=True)

    ip = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "username": self.username,
            "action": self.action,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "detail": self.detail or {},
            "ip": self.ip,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


def _ensure_columns() -> None:
    """给**已存在**的表补上新增的列。

    ## 为什么需要这个

    `Base.metadata.create_all(engine)` 只会建**还不存在的表**，
    **不会给已有的表加列** —— SQLite 不支持 `ALTER TABLE ... ADD
    COLUMN` 之外的列变更，但 ADD COLUMN 是支持的，所以这里手工补。

    漏了这一步的后果很隐蔽：老库上 `tenants.is_active` 这一列
    不存在，ORM 查 `Tenant` 时报 `no such column`，
    **而且只在用旧库启动时才复现** —— CI 每次都是空库，测不出来。

    做的是「查列 → 缺了就 ADD」—— 幂等，重复跑没问题。
    """
    import sqlalchemy as sa

    # 表名 → [(列名, DDL 类型)]
    wanted: dict[str, list[tuple[str, str]]] = {
        "tenants": [
            ("is_active", "BOOLEAN NOT NULL DEFAULT 1"),
            ("description", "TEXT"),
        ],
        # CMDB 推送状态 —— 老库要补这三列，否则 ORM 查 Asset 报 no such column
        "assets": [
            ("siem_pushed_at", "DATETIME"),
            ("siem_push_status", "VARCHAR(32)"),
            ("siem_task_id", "VARCHAR(128)"),
            # 船队/单船视图的分组依据 —— 老库的资产全为空（未归船）
            ("vessel_id", "INTEGER"),
        ],
        "topologies": [
            ("fleet_id", "INTEGER"),
        ],
    }
    with engine.begin() as conn:
        inspector = sa.inspect(conn)
        existing_tables = set(inspector.get_table_names())
        for table, cols in wanted.items():
            if table not in existing_tables:
                continue
            have = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl in cols:
                if name in have:
                    continue
                conn.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def _rebuild_vessels_if_misbuilt() -> None:
    """`vessels.fleet_id` 的类型不对就重建这张表。

    ## 为什么需要

    早期版本把 `fleet_id` 声明成了 `String(64)`，于是 SQLite 把它建成
    VARCHAR 列，存进去的值是**文本** `'2'` 而不是整数 `2`。
    症状很隐蔽：数据库里看着有船队有船，但
    `vessel.fleet_id == fleet.id` 永远不成立 —— **船队视图显示「0 艘船、
    0 资产」**，而 totals 又是另一个数。

    **SQLite 不能改列类型**（`ALTER TABLE ... ALTER COLUMN` 不存在），
    只能重建表。

    ## 为什么重建是安全的

    表里只有**播种**产生的数据（船队与船），没有用户录入的业务数据 ——
    用户录入的是**资产**，在另一张表上。

    重建后 `assets.vessel_id` 会指向不存在的 id，所以先清空，
    让随后的播种重新挂一遍。
    """
    import sqlalchemy as sa

    with engine.begin() as conn:
        inspector = sa.inspect(conn)
        if "vessels" not in set(inspector.get_table_names()):
            return
        cols = {c["name"]: c for c in inspector.get_columns("vessels")}
        fk = cols.get("fleet_id")
        if fk is None:
            return
        # 已经是整数列 → 不用动
        #
        # `type` 是 SQLAlchemy 的**类型对象**（VARCHAR 类），不是字符串 ——
        # 直接 `.upper()` 会 AttributeError。用 str() 取它的名字。
        if str(fk["type"]).upper() in ("INTEGER", "INT"):
            return
        conn.execute(sa.text("DROP TABLE vessels"))
        conn.execute(sa.text("UPDATE assets SET vessel_id = NULL"))
    Base.metadata.create_all(engine)


def init_db() -> None:
    """建表 + 补列 + 播种开发租户与初始管理员。

    生产环境该用 alembic，但这个项目还没有迁移历史。
    """
    Base.metadata.create_all(engine)
    _ensure_columns()
    _rebuild_vessels_if_misbuilt()
    seed_tenants()
    seed_admin_user()
    seed_fleets_and_vessels()


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


def seed_admin_user() -> None:
    """建初始管理员账号。

    **没有这个账号，生产模式登录页打开就是死的** ——
    没人能登录，就没人能建用户，就永远登不进去。

    密码从环境变量 `MP_ADMIN_PASSWORD` 来，**不写死在代码里**。
    没设这个变量就**不建** —— 不能给个默认密码 'admin/admin'，
    那等于开后门。
    """
    import os

    from .services.passwords import hash_password

    password = os.getenv("MP_ADMIN_PASSWORD", "").strip()
    if not password:
        return

    username = os.getenv("MP_ADMIN_USERNAME", "admin").strip()
    tenant_slug = os.getenv("MP_ADMIN_TENANT", "asi").strip()

    with SessionLocal() as db:
        exists = db.query(User).filter(User.username == username).first()
        if exists:
            return
        tenant = db.query(Tenant).filter(Tenant.slug == tenant_slug).first()
        if tenant is None:
            return
        db.add(
            User(
                tenant_id=tenant.id,
                username=username,
                password_hash=hash_password(password),
                display_name="初始管理员",
                role="super_admin",
            )
        )
        db.commit()


def seed_fleets_and_vessels() -> None:
    """给每个租户备好一支船队与一艘船，并把现有数据挂上去。

    ## 为什么要有这一步

    总览分**船队视图**与**单船视图**两级，资产清单也按船队-单船分组 ——
    但这些数据是**后加的维度**，库里原本没有船这一层。

    没有兜底的话：船队列表是空的 → 总览的船队视图一片空白 →
    用户以为功能坏了。而资产还在（14 件），只是没有船可挂。

    ## 挂哪个

    - **拓扑** → 船队：按拓扑名派生。现有的「船队网络拓扑 V1」正好
      就是一支船队。
    - **资产** → 船：每支船队一艘「未命名船舶」，所有没归船的资产归它。

    ## 只播种不覆盖

    已存在的船队/船保持原样（用户可能已经改过名字、已经分配过资产）。
    反复跑不会把用户的数据冲掉。
    """
    with SessionLocal() as db:
        tenants = db.query(Tenant).all()
        for tenant in tenants:
            fleets = (
                db.query(Fleet)
                .filter(Fleet.tenant_id == tenant.id)
                .order_by(Fleet.id)
                .all()
            )
            if not fleets:
                # 用现有拓扑的名字当船队名 —— 「船队网络拓扑 V1」就是它
                topo = (
                    db.query(Topology)
                    .filter(Topology.tenant_id == tenant.id)
                    .order_by(Topology.id)
                    .first()
                )
                name = topo.name if topo else "默认船队"
                fleet = Fleet(tenant_id=tenant.id, name=name)
                db.add(fleet)
                db.flush()
                fleets = [fleet]

            for fleet in fleets:
                vessels = (
                    db.query(Vessel)
                    .filter(Vessel.tenant_id == tenant.id, Vessel.fleet_id == fleet.id)
                    .all()
                )
                if not vessels:
                    vessel = Vessel(
                        tenant_id=tenant.id,
                        fleet_id=fleet.id,
                        name="未命名船舶",
                        description="导入的设备先归在这里，确认所属船舶后再改。",
                    )
                    db.add(vessel)
                    db.flush()
                    vessels = [vessel]

                # 拓扑挂到船队（第一支）
                if fleet is fleets[0]:
                    for topo in (
                        db.query(Topology)
                        .filter(Topology.tenant_id == tenant.id, Topology.fleet_id.is_(None))
                        .all()
                    ):
                        topo.fleet_id = fleet.id

                # 没归船的资产挂到第一艘船
                first = vessels[0]
                for asset in (
                    db.query(Asset)
                    .filter(Asset.tenant_id == tenant.id, Asset.vessel_id.is_(None))
                    .all()
                ):
                    asset.vessel_id = first.id
        db.commit()


def get_session():
    """FastAPI 依赖：每个请求一个 session，用完关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
