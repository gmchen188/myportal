"""管理后台 API —— 用户、租户、接入源、审计。

## 权限模型

| 操作 | analyst / viewer | tenant_admin | super_admin |
|---|---|---|---|
| 看用户/接入源/审计 | ✅ | ✅ | ✅ |
| 建用户、改角色 | ❌ | ✅ 本租户 | ✅ 全部租户 |
| 停用租户 | ❌ | ❌ | ✅ |
| 管接入源 | ❌ | ✅ 本租户 | ✅ 全部租户 |

**tenant_admin 只能管自己租户的数据** —— 这是多租户的第一道防线，
和 `Principal.tenant_id` 的作用域一致。跨租户只有 super_admin。

## 每个写操作都写审计

增删改一律 `audit.record`。不写审计的管理后台等于没有 accountability。

## 密码永远不返回

`User.to_dict()` 不含 `password_hash`。这里再加一道 —— 即便有人
改了那个方法，也不会漏出去。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import Principal, principal_from_request_strict, require_admin
from ..db import AuditLog, IntakeSource, Tenant, User, get_session
from ..services import audit
from ..services.passwords import hash_password, password_problems

router = APIRouter(prefix="/api/admin", tags=["admin"])

# 接入源类型
INTAKE_KINDS = ("fortisiem", "syslog", "webhook", "agent")
# 角色
ROLES = ("tenant_admin", "analyst", "viewer")


def _require_write(p: Principal) -> Principal:
    """要改配置的权限。"""
    if not p.can_write:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需要管理员权限")
    return p


def _ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()[:64]
    return request.client.host if request.client else None


# ── 用户 ────────────────────────────────────────────────────────────────────
class UserIn(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=200)
    display_name: str | None = Field(default=None, max_length=200)
    role: str = Field(default="viewer", max_length=32)
    email: str | None = Field(default=None, max_length=200)
    tenant_id: str | None = Field(default=None, max_length=64)


class UserPatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    role: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None
    password: str | None = Field(default=None, max_length=200)


def _check_role(role: str) -> str:
    if role not in ROLES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"角色必须是：{'、'.join(ROLES)}")
    return role


def _check_tenant_scope(p: Principal, tenant_id: str) -> None:
    """tenant_admin 只能动自己租户；super_admin 随便。"""
    if p.is_super_admin:
        return
    if tenant_id != p.tenant_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "只能管理本租户的用户")


@router.get("/users")
def list_users(
    p: Principal = Depends(principal_from_request_strict),
    db: Session = Depends(get_session),
    tenant_id: str | None = Query(default=None),
):
    """用户列表。

    tenant_admin 只能看到自己租户的用户 —— **即使传了别的
    tenant_id 也拦得住**。
    """
    if not p.can_write:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需要管理员权限")
    q = db.query(User)
    if not p.is_super_admin:
        q = q.filter(User.tenant_id == p.tenant_id)
    elif tenant_id:
        q = q.filter(User.tenant_id == tenant_id)
    return [u.to_dict() for u in q.order_by(User.id).all()]


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserIn,
    request: Request,
    p: Principal = Depends(principal_from_request_strict),
    db: Session = Depends(get_session),
):
    """建用户。"""
    _require_write(p)
    role = _check_role(body.role)

    target_tenant = body.tenant_id or p.tenant_id
    _check_tenant_scope(p, target_tenant)

    tenant = db.get(Tenant, target_tenant)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "租户不存在")

    uname = body.username.strip()
    dup = db.query(User).filter(User.tenant_id == target_tenant, User.username == uname).first()
    if dup is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"租户 {tenant.slug} 下已有用户名 {uname}")

    problems = password_problems(body.password)
    if problems:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "；".join(problems))

    user = User(
        tenant_id=target_tenant,
        username=uname,
        password_hash=hash_password(body.password),
        display_name=body.display_name or uname,
        role=role,
        email=body.email,
    )
    db.add(user)
    db.commit()
    audit.record(
        db,
        tenant_id=target_tenant,
        action="user.create",
        user_id=p.db_user_id,
        username=p.user_id,
        target_type="user",
        target_id=str(user.id),
        detail={"username": uname, "role": role},
        ip=_ip(request),
    )
    return user.to_dict()


@router.patch("/users/{user_id}")
def patch_user(
    user_id: int,
    body: UserPatch,
    request: Request,
    p: Principal = Depends(principal_from_request_strict),
    db: Session = Depends(get_session),
):
    """改用户（角色、停用、改密码）。"""
    _require_write(p)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    _check_tenant_scope(p, user.tenant_id)

    changes: dict[str, Any] = {}

    if body.role is not None:
        role = _check_role(body.role)
        # **不许把自己降权或停用** —— 否则管理员可能把自己锁在门外，
        # 只能去数据库改。
        if user.id == p.db_user_id and role != user.role:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能修改自己的角色")
        changes["role"] = {"from": user.role, "to": role}
        user.role = role

    if body.display_name is not None:
        changes["display_name"] = {"from": user.display_name, "to": body.display_name}
        user.display_name = body.display_name

    if body.email is not None:
        changes["email"] = {"from": user.email, "to": body.email}
        user.email = body.email

    if body.is_active is not None:
        if user.id == p.db_user_id and not body.is_active:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能停用自己的账号")
        changes["is_active"] = {"from": user.is_active, "to": body.is_active}
        user.is_active = body.is_active

    if body.password:
        problems = password_problems(body.password)
        if problems:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "；".join(problems))
        user.password_hash = hash_password(body.password)
        changes["password"] = {"reset": True}

    db.commit()
    audit.record(
        db,
        tenant_id=user.tenant_id,
        action="user.update",
        user_id=p.db_user_id,
        username=p.user_id,
        target_type="user",
        target_id=str(user.id),
        detail={"username": user.username, "changes": changes},
        ip=_ip(request),
    )
    return user.to_dict()


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    request: Request,
    p: Principal = Depends(principal_from_request_strict),
    db: Session = Depends(get_session),
):
    """删用户。

    **不物理删除** —— 审计日志里记了谁做了什么，物理删了那些记录就
    失去了上下文。改成停用（is_active=False）。
    """
    _require_write(p)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    _check_tenant_scope(p, user.tenant_id)
    if user.id == p.db_user_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能删自己的账号")

    user.is_active = False
    db.commit()
    audit.record(
        db,
        tenant_id=user.tenant_id,
        action="user.deactivate",
        user_id=p.db_user_id,
        username=p.user_id,
        target_type="user",
        target_id=str(user.id),
        detail={"username": user.username},
        ip=_ip(request),
    )
    return user.to_dict()


# ── 租户 ────────────────────────────────────────────────────────────────────
class TenantIn(BaseModel):
    slug: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    fortisiem_org: str | None = Field(default=None, max_length=120)
    locale: str = Field(default="zh-CN", max_length=16)
    description: str | None = None


class TenantPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    fortisiem_org: str | None = Field(default=None, max_length=120)
    locale: str | None = Field(default=None, max_length=16)
    description: str | None = None
    is_active: bool | None = None


@router.get("/tenants")
def list_tenants(
    p: Principal = Depends(principal_from_request_strict),
    db: Session = Depends(get_session),
):
    """租户列表。

    super_admin 看全部；其他人只看自己租户。
    """
    q = db.query(Tenant)
    if not p.is_super_admin:
        q = q.filter(Tenant.id == p.tenant_id)
    return [t.to_dict() for t in q.order_by(Tenant.slug).all()]


@router.post("/tenants", status_code=status.HTTP_201_CREATED)
def create_tenant(
    body: TenantIn,
    request: Request,
    p: Principal = Depends(principal_from_request_strict),
    db: Session = Depends(get_session),
):
    """建租户 —— **只有 super_admin 能做**。"""
    _require_write(p)
    if not p.is_super_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "只有超级管理员能建租户")

    slug = body.slug.strip()
    if db.query(Tenant).filter(Tenant.slug == slug).first() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"租户 {slug} 已存在")

    tenant = Tenant(
        id=f"t-{slug}",
        slug=slug,
        name=body.name,
        locale=body.locale,
        fortisiem_org=body.fortisiem_org,
        description=body.description,
    )
    db.add(tenant)
    db.commit()
    audit.record(
        db,
        tenant_id=tenant.id,
        action="tenant.create",
        user_id=p.db_user_id,
        username=p.user_id,
        target_type="tenant",
        target_id=tenant.id,
        detail={"slug": slug, "name": body.name},
        ip=_ip(request),
    )
    return tenant.to_dict()


@router.patch("/tenants/{tenant_id}")
def patch_tenant(
    tenant_id: str,
    body: TenantPatch,
    request: Request,
    p: Principal = Depends(principal_from_request_strict),
    db: Session = Depends(get_session),
):
    """改租户。

    停用租户只有 super_admin 能做 —— tenant_admin 停自己租户等于
    把客户踢下线，这个决定不该由租户管理员自己做。
    """
    _require_write(p)
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "租户不存在")
    if not p.is_super_admin and tenant.id != p.tenant_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "只能管理本租户")
    if body.is_active is not None and not p.is_super_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "只有超级管理员能启停租户")

    changes: dict[str, Any] = {}
    for field in ("name", "fortisiem_org", "locale", "description", "is_active"):
        new = getattr(body, field)
        if new is None:
            continue
        old = getattr(tenant, field)
        if old == new:
            continue
        changes[field] = {"from": old, "to": new}
        setattr(tenant, field, new)

    db.commit()
    audit.record(
        db,
        tenant_id=tenant.id,
        action="tenant.update",
        user_id=p.db_user_id,
        username=p.user_id,
        target_type="tenant",
        target_id=tenant.id,
        detail={"changes": changes},
        ip=_ip(request),
    )
    return tenant.to_dict()


# ── 接入源 ──────────────────────────────────────────────────────────────────
class IntakeIn(BaseModel):
    kind: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    config: dict[str, Any] | None = None
    enabled: bool = True
    tenant_id: str | None = Field(default=None, max_length=64)


class IntakePatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    config: dict[str, Any] | None = None
    enabled: bool | None = None


def _check_kind(kind: str) -> str:
    if kind not in INTAKE_KINDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"接入类型必须是：{'、'.join(INTAKE_KINDS)}")
    return kind


@router.get("/intake-sources")
def list_intake_sources(
    p: Principal = Depends(principal_from_request_strict),
    db: Session = Depends(get_session),
):
    """接入源列表。"""
    q = db.query(IntakeSource)
    if not p.is_super_admin:
        q = q.filter(IntakeSource.tenant_id == p.tenant_id)
    return [s.to_dict() for s in q.order_by(IntakeSource.kind, IntakeSource.id).all()]


@router.post("/intake-sources", status_code=status.HTTP_201_CREATED)
def create_intake_source(
    body: IntakeIn,
    request: Request,
    p: Principal = Depends(principal_from_request_strict),
    db: Session = Depends(get_session),
):
    """登记一个接入源。"""
    _require_write(p)
    kind = _check_kind(body.kind)
    target_tenant = body.tenant_id or p.tenant_id
    if not p.is_super_admin and target_tenant != p.tenant_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "只能管理本租户的接入源")

    src = IntakeSource(
        tenant_id=target_tenant,
        kind=kind,
        name=body.name,
        description=body.description,
        config=body.config or {},
        enabled=body.enabled,
        created_by=p.user_id,
    )
    db.add(src)
    db.commit()
    audit.record(
        db,
        tenant_id=target_tenant,
        action="intake.create",
        user_id=p.db_user_id,
        username=p.user_id,
        target_type="intake_source",
        target_id=str(src.id),
        detail={"kind": kind, "name": body.name},
        ip=_ip(request),
    )
    return src.to_dict()


@router.patch("/intake-sources/{source_id}")
def patch_intake_source(
    source_id: int,
    body: IntakePatch,
    request: Request,
    p: Principal = Depends(principal_from_request_strict),
    db: Session = Depends(get_session),
):
    """改接入源（启停、改配置）。"""
    _require_write(p)
    src = db.get(IntakeSource, source_id)
    if src is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "接入源不存在")
    if not p.is_super_admin and src.tenant_id != p.tenant_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "只能管理本租户的接入源")

    changes: dict[str, Any] = {}
    for field in ("name", "description", "enabled"):
        new = getattr(body, field)
        if new is None:
            continue
        old = getattr(src, field)
        if old == new:
            continue
        changes[field] = {"from": old, "to": new}
        setattr(src, field, new)
    if body.config is not None:
        changes["config"] = {"updated": True}
        src.config = body.config

    db.commit()
    audit.record(
        db,
        tenant_id=src.tenant_id,
        action="intake.update",
        user_id=p.db_user_id,
        username=p.user_id,
        target_type="intake_source",
        target_id=str(src.id),
        detail={"changes": changes},
        ip=_ip(request),
    )
    return src.to_dict()


@router.delete("/intake-sources/{source_id}")
def delete_intake_source(
    source_id: int,
    request: Request,
    p: Principal = Depends(principal_from_request_strict),
    db: Session = Depends(get_session),
):
    """删接入源。"""
    _require_write(p)
    src = db.get(IntakeSource, source_id)
    if src is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "接入源不存在")
    if not p.is_super_admin and src.tenant_id != p.tenant_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "只能管理本租户的接入源")

    snapshot = src.to_dict()
    db.delete(src)
    db.commit()
    audit.record(
        db,
        tenant_id=snapshot["tenant_id"],
        action="intake.delete",
        user_id=p.db_user_id,
        username=p.user_id,
        target_type="intake_source",
        target_id=str(source_id),
        detail={"kind": snapshot["kind"], "name": snapshot["name"]},
        ip=_ip(request),
    )
    return {"ok": True, "deleted": snapshot}


@router.post("/intake-sources/{source_id}/touch")
def touch_intake_source(
    source_id: int,
    p: Principal = Depends(principal_from_request_strict),
    db: Session = Depends(get_session),
):
    """标记「这个通道刚刚收到东西了」。

    **由事件接入端点调用** —— 有了 last_seen_at，运维就能一眼看出
    哪个通道哑了。不用翻日志。
    """
    src = db.get(IntakeSource, source_id)
    if src is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "接入源不存在")
    from datetime import datetime, timezone

    src.last_seen_at = datetime.now(timezone.utc)
    src.events_received = (src.events_received or 0) + 1
    db.commit()
    return src.to_dict()


# ── 审计 ────────────────────────────────────────────────────────────────────
@router.get("/audit")
def list_audit(
    p: Principal = Depends(principal_from_request_strict),
    db: Session = Depends(get_session),
    action: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    """审计日志。"""
    if not p.can_write:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需要管理员权限")
    q = db.query(AuditLog)
    if not p.is_super_admin:
        q = q.filter(AuditLog.tenant_id == p.tenant_id)
    if action:
        q = q.filter(AuditLog.action == action)
    rows = q.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit).all()
    return [r.to_dict() for r in rows]


@router.get("/overview")
def admin_overview(
    p: Principal = Depends(principal_from_request_strict),
    db: Session = Depends(get_session),
):
    """后台总览 —— 数字直接回答「现在什么状态」。

    比让运维自己数几个表有用。
    """
    from sqlalchemy import func

    from ..db import Asset, Incident, Topology

    def count(model, *filters):
        q = db.query(func.count(model.id))
        for f in filters:
            q = q.filter(f)
        return q.scalar() or 0

    scope = [] if p.is_super_admin else [Tenant.id == p.tenant_id]
    tenants = db.query(Tenant).filter(*scope).all()
    tids = [t.id for t in tenants]

    users = count(User, User.tenant_id.in_(tids), User.is_active.is_(True)) if tids else 0
    assets = count(Asset, Asset.tenant_id.in_(tids)) if tids else 0
    incidents = count(Incident, Incident.tenant_id.in_(tids)) if tids else 0
    topologies = count(Topology, Topology.tenant_id.in_(tids)) if tids else 0
    sources = count(IntakeSource, IntakeSource.tenant_id.in_(tids)) if tids else 0
    active_sources = count(IntakeSource, IntakeSource.tenant_id.in_(tids), IntakeSource.enabled.is_(True)) if tids else 0

    # 「哑了」的通道 —— 启用了但从来没收到过东西
    from datetime import datetime, timedelta, timezone

    stale_cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    stale = 0
    if tids:
        stale = (
            db.query(IntakeSource)
            .filter(
                IntakeSource.tenant_id.in_(tids),
                IntakeSource.enabled.is_(True),
                IntakeSource.last_seen_at.is_(None),
            )
            .count()
        )
    return {
        "tenants": len(tenants),
        "active_tenants": sum(1 for t in tenants if t.is_active),
        "users": users,
        "assets": assets,
        "incidents": incidents,
        "topologies": topologies,
        "intake_sources": sources,
        "intake_active": active_sources,
        "intake_never_seen": stale,
        "audit_entries": count(AuditLog, AuditLog.tenant_id.in_(tids)) if tids else 0,
    }
