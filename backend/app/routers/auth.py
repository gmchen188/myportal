"""认证端点 —— 登录、登出、我是谁。

## 为什么这个文件存在

之前 `auth.py` 里有个 `issue_access_token` 函数，**但没有任何地方
调用它**：没有登录端点、没有用户表、没有登录页。

结果是：多租户认证是「有锁没钥匙」——
- 开发模式靠 `X-Dev-Tenant` 头免登录
- 生产模式（`MP_ENV=prod`）要求 Bearer 令牌
- **但没有任何办法拿到令牌**

生产模式一开，整个系统锁死。这个文件补上钥匙。

## 登录为什么要慢

bcrypt 故意慢（默认约 100ms）。这是**特性不是缺陷** —— 登录接口
被暴力破解时，慢哈希让攻击者的吞吐量降到每秒几次。

代价是正常登录也多 100ms。可接受。

## 失败计数与锁定

连续失败会锁账号一段时间。**但错误信息不能泄露账号是否存在** ——
「用户不存在」和「密码错误」必须返回同样的提示，否则可以用来
枚举账号。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import (
    Principal,
    decode_access_token,
    issue_access_token,
    principal_from_request,
    principal_from_request_strict,
)
from ..db import AuditLog, Tenant, User, get_session
from ..services import audit
from ..services.passwords import hash_password, password_problems, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

# 连续失败多少次锁账号
MAX_FAILED = 5
# 锁多久
LOCK_MINUTES = 15


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=200)
    # 租户 slug。用户名在租户内唯一（复合唯一约束），
    # 所以登录必须知道是哪个租户。
    tenant: str = Field(default="asi", max_length=64)


class ChangePasswordIn(BaseModel):
    old_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


def _client_ip(request: Request) -> str | None:
    """取客户端 IP。

    `X-Forwarded-For` 会被伪造，所以只在**信任反代**时用它；
    否则用真实连接地址。审计日志里的 IP 要能当证据用。
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return request.client.host if request.client else None


def _generic_failure() -> HTTPException:
    """**账号不存在与密码错误返回同样的提示** —— 不泄露账号是否存在。"""
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码不正确")


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_session)):
    """登录。

    成功返回访问令牌；失败一律 401 + 同样的提示。
    """
    ip = _client_ip(request)
    tenant = db.query(Tenant).filter(Tenant.slug == body.tenant.strip()).first()
    if tenant is None:
        # 租户都不存在 —— 也要走一次哈希，否则「租户不存在」会明显
        # 比「密码错误」快，攻击者能据此枚举租户
        hash_password(body.password)
        raise _generic_failure()

    if not tenant.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "租户已停用")

    user = db.query(User).filter(User.tenant_id == tenant.id, User.username == body.username.strip()).first()
    if user is None:
        hash_password(body.password)
        raise _generic_failure()

    now = datetime.now(timezone.utc)
    # **SQLite 读回来的 datetime 是 naive 的**（它没有时区类型），
    # 直接跟 aware 的 now 比较会抛
    # `TypeError: can't compare offset-naive and offset-aware datetimes`。
    # 所以比较前先补上 UTC 时区。
    locked_until = user.locked_until
    if locked_until is not None and locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=timezone.utc)
    if locked_until and locked_until > now:
        remaining = int((locked_until - now).total_seconds() // 60) + 1
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"账号已锁定，请 {remaining} 分钟后再试",
        )

    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "账号已停用")

    if not verify_password(body.password, user.password_hash):
        user.failed_attempts = (user.failed_attempts or 0) + 1
        if user.failed_attempts >= MAX_FAILED:
            # 存 naive 的 UTC —— SQLite 没有时区类型，存 aware 的话
            # 读回来还是 naive，两边不一致又要踩比较的坑
            user.locked_until = (now + timedelta(minutes=LOCK_MINUTES)).replace(tzinfo=None)
            user.failed_attempts = 0
        db.commit()
        audit.record(
            db,
            tenant_id=tenant.id,
            action="auth.login_failed",
            user_id=user.id,
            username=user.username,
            detail={"attempts": user.failed_attempts},
            ip=ip,
        )
        raise _generic_failure()

    # 登录成功
    user.failed_attempts = 0
    user.locked_until = None
    user.last_login_at = now.replace(tzinfo=None)
    db.commit()

    token = issue_access_token(
        user_id=user.username,
        tenant_slug=tenant.slug,
        role=user.role,
        locale=tenant.locale,
        db_user_id=user.id,
    )
    audit.record(
        db,
        tenant_id=tenant.id,
        action="auth.login",
        user_id=user.id,
        username=user.username,
        ip=ip,
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 15 * 60,
        "user": user.to_dict(),
        "tenant": tenant.to_dict(),
    }


@router.get("/me")
def me(p: Principal = Depends(principal_from_request_strict), db: Session = Depends(get_session)):
    """当前是谁。

    前端启动时调它 —— 拿到 401 就跳登录页。

    **用严格版**：开发模式的无头请求会返回 dev 用户，那样前端永远
    跳不过去登录页 —— 「是否已登录」就判断不了。
    """
    tenant = db.get(Tenant, p.tenant_id)
    out: dict[str, object] = {
        "user_id": p.user_id,
        "tenant_id": p.tenant_id,
        "tenant_slug": p.tenant_slug,
        "role": p.role,
        "locale": p.locale,
        "is_admin": p.is_admin,
        "is_super_admin": p.is_super_admin,
        "can_write": p.can_write,
    }
    if p.db_user_id is not None:
        user = db.get(User, p.db_user_id)
        if user is not None:
            out["user"] = user.to_dict()
    if tenant is not None:
        out["tenant"] = tenant.to_dict()
    return out


@router.post("/logout")
def logout(
    request: Request,
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
):
    """登出。

    访问令牌是无状态的（JWT），**服务端没法真的作废它** ——
    所以这里只记一条审计，然后让前端丢掉令牌。

    真正要立刻踢下线，得把令牌存进黑名单（Redis 或一张表）。
    那是另一个需求，不在这一版的范围里 —— 但**必须说清楚**，
    不能让人以为登出就等于令牌失效了。
    """
    audit.record(
        db,
        tenant_id=p.tenant_id,
        action="auth.logout",
        user_id=p.db_user_id,
        username=p.user_id,
        ip=_client_ip(request),
    )
    return {"ok": True, "note": "访问令牌是无状态的，服务端不再持有；客户端应丢弃令牌"}


@router.post("/change-password")
def change_password(
    body: ChangePasswordIn,
    p: Principal = Depends(principal_from_request),
    db: Session = Depends(get_session),
):
    """改自己的密码。

    **必须验证旧密码** —— 没有这一步，任何能拿到令牌的人都能改密码，
    令牌泄露就等于账号永久失陷。
    """
    if p.db_user_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "开发模式账号没有可改的密码")

    user = db.get(User, p.db_user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")

    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "原密码不正确")

    problems = password_problems(body.new_password)
    if problems:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "；".join(problems))

    if body.new_password == body.old_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "新密码不能与原密码相同")

    user.password_hash = hash_password(body.new_password)
    db.commit()
    audit.record(
        db,
        tenant_id=p.tenant_id,
        action="auth.change_password",
        user_id=user.id,
        username=user.username,
    )
    return {"ok": True}


@router.get("/login-attempts")
def login_attempts(p: Principal = Depends(principal_from_request), db: Session = Depends(get_session)):
    """最近的登录失败记录 —— 排查「是不是有人在撞库」。"""
    if not p.can_write:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需要管理员权限")
    rows = (
        db.query(AuditLog)
        .filter(AuditLog.tenant_id == p.tenant_id, AuditLog.action == "auth.login_failed")
        .order_by(AuditLog.created_at.desc())
        .limit(50)
        .all()
    )
    return [r.to_dict() for r in rows]
