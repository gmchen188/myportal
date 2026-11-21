"""
myPortal 侧的对接服务 —— 实现"用户只登录一次"。

核心思路
--------
oceansite 没有 SSO 模块，也不能改。那么"免密"的唯一实现方式是：

    **myPortal 后端替用户去 oceansite 问"他是谁"**

浏览器带着 oceansite 的会话 Cookie 请求 myPortal 的 /sso/exchange；
myPortal 后端拿着同一个 Cookie 去问 oceansite 的身份端点；
拿到身份后，myPortal 建立**自己的**会话（JWT + refresh cookie），
之后所有请求都不再碰 oceansite。

为什么必须由后端去做
--------------------
浏览器把 Cookie 交给 myPortal 意味着 myPortal 拥有 oceansite 的会话凭据。
所以：
  · Cookie 只在服务端转发，绝不回显给前端、绝不写进日志
  · 转发范围只限 identity 这一个端点，不做通用反向代理
  · 身份端点的响应由 myPortal 解析，原始载荷不直接返回给浏览器

身份 → 租户的映射
-----------------
上游只说"我是谁"，不说"我能看哪个租户"。
租户由 myPortal 自己的映射表决定（external_id → tenant_id + role）。
这与 myPortal 既有的多租户原则一致：**作用域来自凭据，不来自参数。**

运行：python sso_service.py    （默认 127.0.0.1:9102）
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from fastapi import Cookie, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

# ── 配置 ────────────────────────────────────────────────────────────────────
OCEAN_BASE = os.getenv("OCEAN_BASE_URL", "http://127.0.0.1:9101").rstrip("/")
OCEAN_COOKIE = os.getenv("OCEAN_COOKIE", "OCSESSION")
OCEAN_WHOAMI = os.getenv("OCEAN_WHOAMI_PATH", "/api/session/whoami")
OCEAN_TIMEOUT = float(os.getenv("OCEAN_TIMEOUT", "5.0"))
# 部署形态：same-origin（myPortal 与 oceansite 同源，Cookie 自动携带）
#           或 cross-origin（前端带 Cookie，myPortal 后端转发）
MYPORTAL_ORIGIN = os.getenv("MYPORTAL_ORIGIN", "http://127.0.0.1:9102")
# RFC 7518 §3.2: HS256 的密钥至少 256 位（32 字节）。短密钥不是"弱一点"，
# 是可以直接被暴力还原的 —— 所以这里在**启动时**就拒绝，而不是运行时警告。
_MIN_SECRET_BYTES = 32


def _load_secret(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default or "")
    if not value:
        raise RuntimeError(
            f"{name} 未配置。生产环境必须通过环境变量注入至少 {_MIN_SECRET_BYTES} 字节的随机密钥。"
        )
    if len(value.encode("utf-8")) < _MIN_SECRET_BYTES:
        raise RuntimeError(
            f"{name} 长度 {len(value.encode('utf-8'))} 字节，低于 HS256 要求的 {_MIN_SECRET_BYTES} 字节。"
        )
    return value


# 开发默认值本身也要够长 —— 一个"仅供开发"的短密钥会在测试通过后被带进生产。
_DEV_JWT_SECRET = "dev-only-insecure-jwt-secret-change-me-in-production-0123456789"
# 但**绝不能让它在生产生效**：一个所有人相同的硬编码密钥等于没有认证。
# 生产模式下没配 JWT_SECRET 就直接拒绝启动，而不是退回默认值。
_APP_ENV = os.getenv("MP_ENV", "dev").strip().lower()
JWT_SECRET = _load_secret("JWT_SECRET", None if _APP_ENV in ("prod", "production") else _DEV_JWT_SECRET)
JWT_ALG = "HS256"
ACCESS_TTL = int(os.getenv("ACCESS_TTL_MIN", "15"))
REFRESH_TTL = int(os.getenv("REFRESH_TTL_DAYS", "7"))

# 身份映射表：oceansite 的 external_id → myPortal 租户与角色。
# 生产环境应落在门户自己的数据库里，由「租户管理」页面维护。
IDENTITY_MAP: dict[str, dict[str, str]] = {
    "OC-U-1001": {"tenant_slug": "dongfang", "role": "tenant_admin", "locale": "zh-CN"},
    "OC-U-1002": {"tenant_slug": "dongfang", "role": "viewer", "locale": "zh-CN"},
}

# 演示租户
TENANTS: dict[str, dict[str, Any]] = {
    "dongfang": {
        "id": "t-dongfang",
        "name": "东方海运 / COSCO Shipping",
        "locale": "zh-CN",
        "fortisiem_org": "DONGFANG",
        "ships": 4,
        "assets": 142,
        "eps": 24.6,
    },
    "asi": {
        "id": "t-asi",
        "name": "AquaSync Innovation",
        "locale": "zh-CN",
        "fortisiem_org": "Super",
        "ships": 12,
        "assets": 428,
        "eps": 78.3,
    },
}

app = FastAPI(title="myPortal SSO service")

# refresh token 存哈希（与 fortiportal 既有实现一致）：库被 dump 也不等于会话可用
REFRESH_STORE: dict[str, dict[str, Any]] = {}
AUDIT: list[dict[str, Any]] = []


def _now() -> float:
    return time.time()


def _b64u(raw: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def issue_access_token(*, user_id: str, email: str, role: str, tenant_id: str, locale: str) -> str:
    now = _now()
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "tid": tenant_id,
        "locale": locale,
        "iat": int(now),
        "exp": int(now + ACCESS_TTL * 60),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def new_refresh_token() -> str:
    import hashlib
    import secrets

    raw = secrets.token_urlsafe(48)
    REFRESH_STORE[hashlib.sha256(raw.encode()).hexdigest()] = {
        "user_id": "", "tenant_id": "", "role": "", "email": "", "locale": "",
        "family": raw[:12], "rotated": False, "expires": _now() + REFRESH_TTL * 86400,
    }
    return raw


def hash_refresh(raw: str) -> str:
    import hashlib

    return hashlib.sha256(raw.encode()).hexdigest()


def set_refresh_cookie(response: Response, raw: str) -> None:
    response.set_cookie(
        "mp_refresh",
        raw,
        max_age=REFRESH_TTL * 86400,
        httponly=True,
        samesite="lax",
        secure=False,  # 生产必须 True
        path="/",
    )


def record_audit(action: str, **fields: Any) -> None:
    """审计只追加。凭据本身不入审计 —— 记的是谁在什么时候以什么身份访问了什么。"""
    AUDIT.append({"ts": _now(), "action": action, **fields})


# ── 与 oceansite 对话 ───────────────────────────────────────────────────────
async def fetch_ocean_identity(session_cookie: str) -> dict[str, Any]:
    """用浏览器带来的 oceansite 会话 Cookie 问 oceansite「我是谁」。

    这是整个方案对 oceansite 的**唯一**要求，而且它多半已经存在。
    """
    url = f"{OCEAN_BASE}{OCEAN_WHOAMI}"
    try:
        async with httpx.AsyncClient(timeout=OCEAN_TIMEOUT, trust_env=False) as client:
            resp = await client.get(url, cookies={OCEAN_COOKIE: session_cookie})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"oceansite 不可达: {exc}") from exc

    if resp.status_code == 401:
        raise HTTPException(status_code=401, detail="oceansite 会话已失效")
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"oceansite 身份端点返回 {resp.status_code}")

    try:
        payload = resp.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="oceansite 身份端点返回的不是 JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="oceansite 身份端点返回的不是对象")
    return payload


def resolve_tenant(external_id: str, ocean_role: str) -> tuple[dict[str, Any], str, str, str]:
    """外部身份 → (租户, 角色, locale, 外部角色)。

    映射表里没有的人 —— 默认拒绝。
    这不是"没配好"，这是安全默认值：一个 oceansite 新增的账号
    不应该自动获得某个租户的数据。
    """
    mapping = IDENTITY_MAP.get(external_id)
    if mapping is None:
        raise HTTPException(
            status_code=403,
            detail=f"身份 {external_id} 未在 myPortal 中建立映射，拒绝接入",
        )
    tenant = TENANTS.get(mapping["tenant_slug"])
    if tenant is None:
        raise HTTPException(status_code=403, detail="映射指向的租户不存在")
    return tenant, mapping["role"], mapping["locale"], ocean_role


# ── 对外接口 ────────────────────────────────────────────────────────────────
@app.get("/")
async def landing(request: Request, OCSESSION: str | None = Cookie(default=None)):
    """myPortal 落地页 —— 用户点「网络安全模块」后到这里。

    页面自己做一次换票：拿 oceansite 的会话 Cookie 调 /api/sso/exchange，
    成功就直接进入门户，失败才显示「请先登录 oceansite」。

    这是**同源部署**下的形态（myPortal 与 oceansite 同域，Cookie 自动携带）。
    跨源部署时，前端需要把 Cookie 通过 X-Ocean-Session 头转发，
    或者由网关做同源挂载 —— 见 README.md 的部署形态对照。
    """
    has_ocean = bool(OCSESSION)
    html = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>myPortal · 正在接入</title>
<style>
 body{margin:0;min-height:100vh;display:grid;place-items:center;background:#F8FAFC;
      font-family:"Microsoft YaHei","Segoe UI",sans-serif;color:#1E3A8A}
 .box{background:#fff;border:1px solid #DBEAFE;border-radius:14px;padding:34px 36px;
      width:440px;box-shadow:0 8px 28px rgba(15,23,42,.08);text-align:center}
 .logo{width:52px;height:52px;border-radius:13px;background:#1E40AF;color:#fff;display:grid;
       place-items:center;font-weight:800;font-size:19px;margin:0 auto 16px}
 h1{font-size:19px;margin:0 0 6px} p{color:#64748B;font-size:13px;margin:0 0 20px;line-height:1.7}
 .spin{width:30px;height:30px;border:3px solid #DBEAFE;border-top-color:#1E40AF;border-radius:50%;
       margin:0 auto 18px;animation:sp .8s linear infinite}
 @keyframes sp{to{transform:rotate(360deg)}}
 .ok{background:#F0FDF4;border:1px solid #BBF7D0;color:#15803D;padding:12px;border-radius:9px;
     font-size:13px;margin-bottom:14px;text-align:left}
 .ok b{display:block;font-size:14px;margin-bottom:5px}
 .err{background:#FEF2F2;border:1px solid #FECACA;color:#B91C1C;padding:14px;border-radius:9px;
      font-size:13px;text-align:left;line-height:1.7}
 .btn{display:inline-block;background:#1E40AF;color:#fff;padding:11px 22px;border-radius:8px;
      text-decoration:none;font-size:13.5px;font-weight:700}
 .muted{font-size:11.5px;color:#94A3B8;margin-top:16px;line-height:1.7}
</style></head><body>
<div class="box">
  <div class="logo">myP</div>
  <div id="stage"><div class="spin"></div><h1>正在接入 myPortal</h1>
    <p>正在用 oceansite 的登录身份建立会话，无需再次输入账号密码。</p></div>
  <div id="result"></div>
</div>
<script>
(async function(){
  const stage = document.getElementById('stage'), result = document.getElementById('result');
  try{
    // 同源部署：浏览器自动带 OCSESSION。跨源部署时由网关挂载或前端转发 X-Ocean-Session 头。
    const r = await fetch('/api/sso/exchange', {method:'POST', credentials:'include'});
    const d = await r.json();
    if(r.ok && d.authenticated){
      stage.style.display='none';
      result.innerHTML = '<div class="ok"><b>已免密接入 ✓</b>' +
        '身份：' + (d.user.display_name||d.user.external_id||'') +
        '<br>租户：' + (d.tenant.name||'') +
        '<br>角色：' + (d.user.role||'') + '</div>' +
        '<a class="btn" href="#dashboard">进入安全态势总览 →</a>' +
        '<p class="muted">会话已由 myPortal 独立签发，此后不再依赖 oceansite。</p>';
      // 真实实现里改成 location.replace('/dashboard')，并把 token 放进内存
      window.__MP_TOKEN = d.access_token;
      window.__MP_TENANT = d.tenant;
      document.getElementById('result').querySelector('a').onclick=(e)=>{
        e.preventDefault(); location.hash='dashboard';
      };
    } else {
      stage.style.display='none';
      result.innerHTML = '<div class="err"><b>需要先登录 oceansite</b>' +
        (d.detail||'会话未建立') +
        '<br><br>本系统不提供独立的账号密码入口 —— 请回到 oceansite 登录后再进入网络安全模块。</div>';
    }
  }catch(e){
    stage.style.display='none';
    result.innerHTML = '<div class="err"><b>接入失败</b>' + e + '</div>';
  }
})();
</script></body></html>"""
    return HTMLResponse(html)


@app.get("/api/session")
async def session_state(
    request: Request,
    mp_refresh: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
):
    """前端启动时问一次：当前会话是谁、属于哪个租户。"""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
        try:
            claims = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        except jwt.PyJWTError:
            return JSONResponse({"authenticated": False}, status_code=401)
        return JSONResponse(
            {
                "authenticated": True,
                "user": {
                    "email": claims.get("email"),
                    "role": claims.get("role"),
                    "locale": claims.get("locale"),
                },
                "tenant": {"id": claims.get("tid")},
                "source": "myportal",
            }
        )

    if mp_refresh:
        item = REFRESH_STORE.get(hash_refresh(mp_refresh))
        if item and not item["rotated"] and item["expires"] > _now():
            token = issue_access_token(
                user_id=item["user_id"],
                email=item["email"],
                role=item["role"],
                tenant_id=item["tenant_id"],
                locale=item["locale"],
            )
            return JSONResponse(
                {
                    "authenticated": True,
                    "access_token": token,
                    "user": {"email": item["email"], "role": item["role"], "locale": item["locale"]},
                    "tenant": {"id": item["tenant_id"]},
                    "source": "myportal",
                }
            )

    return JSONResponse({"authenticated": False}, status_code=401)


@app.post("/api/sso/exchange")
async def exchange(
    request: Request,
    response: Response,
    OCSESSION: str | None = Cookie(default=None),
):
    """**免密换票** —— 用户在 oceansite 已登录，这里直接建立 myPortal 会话。

    请求可以带：
      · Cookie 头里的 OCSESSION（同源部署时浏览器自动带）
      · 或 X-Ocean-Session 头（跨源部署时前端显式转发）

    两种形态都不需要用户再输入任何凭据。
    """
    ocean_cookie = OCSESSION or request.headers.get("x-ocean-session")
    if not ocean_cookie:
        raise HTTPException(
            status_code=401,
            detail="未携带 oceansite 会话，请先在 oceansite 登录",
        )

    identity = await fetch_ocean_identity(ocean_cookie)

    external_id = str(identity.get("user_id") or "").strip()
    if not external_id:
        raise HTTPException(status_code=502, detail="oceansite 未返回用户标识")

    tenant, role, locale, ocean_role = resolve_tenant(external_id, str(identity.get("role", "")))

    token = issue_access_token(
        user_id=external_id,
        email=str(identity.get("email") or ""),
        role=role,
        tenant_id=tenant["id"],
        locale=locale,
    )
    raw_refresh = new_refresh_token()
    key = hash_refresh(raw_refresh)
    REFRESH_STORE[key].update(
        {
            "user_id": external_id,
            "tenant_id": tenant["id"],
            "role": role,
            "email": str(identity.get("email") or ""),
            "locale": locale,
        }
    )
    set_refresh_cookie(response, raw_refresh)

    record_audit(
        "auth.sso_exchange",
        actor=external_id,
        tenant_id=tenant["id"],
        outcome="granted",
        source_system="oceansite",
        ocean_role=ocean_role,
    )

    return JSONResponse(
        {
            "authenticated": True,
            "access_token": token,
            "expires_in": ACCESS_TTL * 60,
            "user": {
                "external_id": external_id,
                "email": identity.get("email"),
                "display_name": identity.get("display_name"),
                "role": role,
                "locale": locale,
            },
            "tenant": {
                "id": tenant["id"],
                "name": tenant["name"],
                "fortisiem_org": tenant["fortisiem_org"],
            },
            "source": "oceansite",
        }
    )


@app.post("/api/sso/exchange-ticket")
async def exchange_ticket(request: Request, response: Response):
    """**票据换票** —— oceansite 侧能改造时的更标准路径。

    oceansite 在跳转到 myPortal 之前生成一个一次性票据，
    myPortal 用共享密钥校验后建立会话。票据 60 秒内有效、只能用一次。

    与 /api/sso/exchange 的区别：后者不需要 oceansite 改代码，
    前者需要 oceansite 提供一个"签发票据"的接口。
    两者可以共存 —— 上线时先上零改造的那条，有条件再切到票据。
    """
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))
    import ticket as ticket_mod

    body = await request.json()
    raw = str(body.get("ticket") or "")
    secret = os.getenv("OCEAN_TICKET_SECRET", "")
    if not secret:
        raise HTTPException(status_code=500, detail="未配置 OCEAN_TICKET_SECRET")
    if len(secret.encode("utf-8")) < _MIN_SECRET_BYTES:
        # 密钥太短时**明确拒绝**，不要降级放行 —— 否则 HMAC 的强度形同虚设
        raise HTTPException(
            status_code=500,
            detail=f"OCEAN_TICKET_SECRET 长度不足 {_MIN_SECRET_BYTES} 字节",
        )

    try:
        claims = ticket_mod.verify(raw, secret)
    except ticket_mod.TicketError as exc:
        record_audit("auth.sso_ticket_rejected", outcome="denied", reason=str(exc))
        raise HTTPException(status_code=401, detail="票据无效或已过期") from exc

    external_id = str(claims.get("sub") or "").strip()
    if not external_id:
        raise HTTPException(status_code=401, detail="票据缺少用户标识")

    tenant, role, locale, ocean_role = resolve_tenant(external_id, str(claims.get("role", "")))

    token = issue_access_token(
        user_id=external_id,
        email=str(claims.get("email") or ""),
        role=role,
        tenant_id=tenant["id"],
        locale=locale,
    )
    raw_refresh = new_refresh_token()
    REFRESH_STORE[hash_refresh(raw_refresh)].update(
        {
            "user_id": external_id,
            "tenant_id": tenant["id"],
            "role": role,
            "email": str(claims.get("email") or ""),
            "locale": locale,
        }
    )
    set_refresh_cookie(response, raw_refresh)

    record_audit(
        "auth.sso_ticket_exchange",
        actor=external_id,
        tenant_id=tenant["id"],
        outcome="granted",
        source_system="oceansite",
        jti=claims.get("jti"),
    )

    return JSONResponse(
        {
            "authenticated": True,
            "access_token": token,
            "user": {"external_id": external_id, "role": role, "locale": locale},
            "tenant": {"id": tenant["id"], "name": tenant["name"]},
            "source": "oceansite-ticket",
        }
    )


@app.get("/api/tenant/summary")
async def tenant_summary(authorization: str | None = Header(default=None)):
    """演示：拿到会话后取租户统计。真实实现走 FortiSIEM MCP + 租户作用域。"""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="缺少访问令牌")
    token = authorization.split(" ", 1)[1]
    try:
        claims = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="令牌无效") from exc

    tenant = next((t for t in TENANTS.values() if t["id"] == claims.get("tid")), None)
    if tenant is None:
        raise HTTPException(status_code=404, detail="租户不存在")
    return JSONResponse(
        {
            "tenant": tenant["name"],
            "fortisiem_org": tenant["fortisiem_org"],
            "ships": tenant["ships"],
            "assets": tenant["assets"],
            "eps": tenant["eps"],
        }
    )


@app.get("/api/audit")
async def audit_log():
    return JSONResponse({"entries": AUDIT[-50:]})


@app.get("/health")
async def health():
    return JSONResponse({"ok": True, "ocean_base": OCEAN_BASE})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("MYPORTAL_PORT", "9102")), log_level="warning")
