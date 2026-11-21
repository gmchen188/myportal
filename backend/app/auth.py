"""
认证与租户作用域。

原则：**作用域来自凭据，不来自请求参数。** 一个租户的 token 只能读它自己
的资产，参数里写别人的 tenant_id 也不行。

开发环境下允许用 `X-Dev-Tenant` 头直接指定租户（免去登录步骤），
但**生产环境必须关掉** —— 否则任何人都能读任意租户。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import Header, HTTPException, Request, status

APP_ENV = os.getenv("MP_ENV", "dev").strip().lower()
IS_PROD = APP_ENV in ("prod", "production")

JWT_SECRET = os.getenv("JWT_SECRET", "dev-only-insecure-jwt-secret-change-me-in-production-0123456789")
JWT_ALG = "HS256"
ACCESS_TTL_MIN = int(os.getenv("ACCESS_TTL_MIN", "15"))

# 开发模式的租户别名 —— 生产环境这个表不该存在
DEV_TENANTS: dict[str, dict[str, Any]] = {
    "dongfang": {"id": "t-dongfang", "name": "东方海运 / COSCO Shipping", "fortisiem_org": "DONGFANG"},
    "asi": {"id": "t-asi", "name": "AquaSync Innovation", "fortisiem_org": "Super"},
}


@dataclass
class Principal:
    """已认证的调用者。"""

    user_id: str
    tenant_id: str
    tenant_slug: str
    role: str
    locale: str
    fortisiem_org: str | None = None
    # 真实用户表的 id —— 审计日志要记它。dev 模式下是 None。
    db_user_id: int | None = None
    display_name: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role in ("tenant_admin", "super_admin")

    @property
    def is_super_admin(self) -> bool:
        """跨租户权限 —— 只有 super_admin 能管别的租户。"""
        return self.role == "super_admin"

    @property
    def can_write(self) -> bool:
        """能不能改配置。viewer / analyst 是只读的。"""
        return self.role in ("tenant_admin", "super_admin")


def issue_access_token(
    *,
    user_id: str,
    tenant_slug: str,
    role: str,
    locale: str,
    db_user_id: int | None = None,
) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "tid": tenant_slug,
        "role": role,
        "locale": locale,
        "iat": now,
        "exp": now + ACCESS_TTL_MIN * 60,
    }
    if db_user_id is not None:
        payload["uid"] = db_user_id
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "令牌已过期")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "令牌无效")


def principal_from_request(
    request: Request,
    authorization: str | None = Header(default=None),
    x_dev_tenant: str | None = Header(default=None, alias="X-Dev-Tenant"),
) -> Principal:
    """解析调用者。

    顺序：Bearer token → 开发模式的租户头。生产环境没有 token 一律 401。
    """
    if authorization and authorization.lower().startswith("bearer "):
        raw = authorization.split(" ", 1)[1].strip()
        claims = decode_access_token(raw)
        slug = claims.get("tid") or ""
        uid = claims.get("uid")

        # **租户优先从数据库读**，而不是从内存常量 ——
        # 后台改了租户名 / 停了租户，要立刻生效，不能等进程重启。
        # 常量只在租户行不存在时兜底（开发环境的首次启动）。
        tenant_row = _lookup_tenant(slug)
        if tenant_row is not None:
            if not tenant_row.is_active:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "租户已停用")
            tenant = {
                "id": tenant_row.id,
                "name": tenant_row.name,
                "fortisiem_org": tenant_row.fortisiem_org,
            }
        else:
            tenant = DEV_TENANTS.get(slug, {})

        return Principal(
            user_id=claims.get("sub", "unknown"),
            tenant_id=tenant.get("id", f"t-{slug}"),
            tenant_slug=slug,
            role=claims.get("role", "viewer"),
            locale=claims.get("locale", "zh-CN"),
            fortisiem_org=tenant.get("fortisiem_org"),
            db_user_id=uid if isinstance(uid, int) else None,
        )

    # 开发模式：允许用头直接指定租户，省掉登录步骤
    if not IS_PROD:
        slug = (x_dev_tenant or "asi").strip()
        if slug not in DEV_TENANTS:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"未知租户 {slug}；可用：{', '.join(DEV_TENANTS)}",
            )
        t = DEV_TENANTS[slug]
        return Principal(
            user_id="dev-user",
            tenant_id=t["id"],
            tenant_slug=slug,
            role="tenant_admin",
            locale="zh-CN",
            fortisiem_org=t.get("fortisiem_org"),
        )

    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "需要 Bearer 令牌")


def _lookup_tenant(slug: str):
    """按 slug 查租户行；查不到返回 None。

    单独一个函数是为了**避免循环导入**：db.py 的 seed_tenants 会
    import 本模块的 DEV_TENANTS。
    """
    from .db import SessionLocal, Tenant

    try:
        with SessionLocal() as db:
            return db.query(Tenant).filter(Tenant.slug == slug).first()
    except Exception:
        # 库还没建好（首次启动、迁移中）—— 用常量兜底
        return None


def principal_from_request_strict(
    request: Request,
    authorization: str | None = Header(default=None),
    x_dev_tenant: str | None = Header(default=None, alias="X-Dev-Tenant"),
) -> Principal:
    """**后台管理端点专用** —— 任何模式都必须有令牌。

    ## 为什么要有严格版

    开发模式（`X-Dev-Tenant` 免登录）是为了本地开发方便，让业务页面
    不用登录就能调。但**管理端点不能这样**：

        开发模式下 POST /api/admin/users 不带任何凭据 → 200

    等于任何能访问到后台端口的人都能建用户、改角色、停租户。
    「开发模式」不是「认证关闭」—— 它只是省掉登录步骤，
    **不该顺带把权限也关了**。

    所以：业务读接口用宽松版，管理端点用严格版。
    严格版在生产模式下与宽松版行为一致（都要求 Bearer）。
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "需要 Bearer 令牌")
    return principal_from_request(request, authorization, x_dev_tenant)


def require_admin(p: Principal) -> Principal:
    if not p.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需要租户管理员权限")
    return p
