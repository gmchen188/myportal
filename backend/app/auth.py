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

    @property
    def is_admin(self) -> bool:
        return self.role in ("tenant_admin", "super_admin")


def issue_access_token(*, user_id: str, tenant_slug: str, role: str, locale: str) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "tid": tenant_slug,
        "role": role,
        "locale": locale,
        "iat": now,
        "exp": now + ACCESS_TTL_MIN * 60,
    }
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
        tenant = DEV_TENANTS.get(slug, {})
        return Principal(
            user_id=claims.get("sub", "unknown"),
            tenant_id=tenant.get("id", f"t-{slug}"),
            tenant_slug=slug,
            role=claims.get("role", "viewer"),
            locale=claims.get("locale", "zh-CN"),
            fortisiem_org=tenant.get("fortisiem_org"),
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


def require_admin(p: Principal) -> Principal:
    if not p.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需要租户管理员权限")
    return p
