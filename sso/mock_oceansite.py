"""
oceansite 模拟器 —— 用于验证 myPortal 的免密对接方案。

它模拟一个**没有 SSO 模块**的老系统所具备的能力：
  · 表单登录（用户名 + 密码）
  · 会话 Cookie
  · 一个"当前用户是谁"的查询端点

真实 oceansite 不需要改造任何一行代码 —— 只需要它已经有的那个
"带着会话 Cookie 问它我是谁"的接口。如果它连这个都没有，
退化的兜底见 README.md 的「方案 B」。

运行：python mock_oceansite.py   （默认 127.0.0.1:9101）
"""

from __future__ import annotations

import os
import secrets
import time
from typing import Any

from fastapi import Cookie, FastAPI, Form, HTTPException, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

SESSION_COOKIE = os.getenv("OCEAN_COOKIE", "OCSESSION")
SESSION_TTL = int(os.getenv("OCEAN_SESSION_TTL", "3600"))

# 演示账号 —— 真实环境由 oceansite 自己校验
USERS: dict[str, dict[str, Any]] = {
    "captain": {
        "user_id": "OC-U-1001",
        "username": "captain",
        "password": "Ocean@2026",
        "email": "captain@dongfang.example",
        "display_name": "陈船长",
        "org_code": "DONGFANG",
        "org_name": "东方海运",
        "role": "shipowner_admin",
    },
    "viewer": {
        "user_id": "OC-U-1002",
        "username": "viewer",
        "password": "Ocean@2026",
        "email": "viewer@dongfang.example",
        "display_name": "王安全员",
        "org_code": "DONGFANG",
        "org_name": "东方海运",
        "role": "shipowner_viewer",
    },
    "outsider": {
        "user_id": "OC-U-9001",
        "username": "outsider",
        "password": "Ocean@2026",
        "email": "outsider@other.example",
        "display_name": "外部人员",
        "org_code": "UNKNOWNORG",
        "org_name": "未知船东",
        "role": "guest",
    },
}

# 进程内会话表：sid -> (username, expires_at)
SESSIONS: dict[str, tuple[str, float]] = {}

app = FastAPI(title="mock-oceansite")


def _now() -> float:
    return time.time()


def _session_user(sid: str | None) -> dict[str, Any] | None:
    if not sid:
        return None
    item = SESSIONS.get(sid)
    if not item:
        return None
    username, exp = item
    if exp <= _now():
        SESSIONS.pop(sid, None)
        return None
    return USERS.get(username)


LOGIN_HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>oceansite 登录</title>
<style>
  body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0F172A;
       font-family:"Microsoft YaHei","Segoe UI",sans-serif;color:#0F172A}
  .box{background:#fff;padding:34px 32px;border-radius:12px;width:360px;
       box-shadow:0 20px 60px rgba(0,0,0,.35)}
  h1{font-size:21px;margin:0 0 6px} p.sub{color:#64748B;font-size:13px;margin:0 0 22px}
  label{display:block;font-size:12.5px;font-weight:600;color:#475569;margin-bottom:6px}
  input{width:100%;height:42px;padding:0 12px;border:1.5px solid #DBEAFE;border-radius:8px;
        font-size:14px;margin-bottom:14px;box-sizing:border-box}
  button{width:100%;height:44px;border:none;border-radius:8px;background:#1E40AF;color:#fff;
         font-size:15px;font-weight:700;cursor:pointer}
  .err{background:#FEF2F2;border:1px solid #FECACA;color:#B91C1C;padding:9px 12px;
       border-radius:8px;font-size:12.5px;margin-bottom:16px}
  .hint{font-size:11.5px;color:#94A3B8;margin-top:16px;line-height:1.7}
  code{background:#F1F5F9;padding:1px 5px;border-radius:4px}
</style></head><body>
<div class="box">
  <h1>oceansite</h1>
  <p class="sub">船东服务平台</p>
  {err}
  <form method="post" action="/login">
    <label>用户名</label><input name="username" autofocus autocomplete="username">
    <label>密码</label><input name="password" type="password" autocomplete="current-password">
    <button type="submit">登录</button>
  </form>
  <div class="hint">
    演示账号：<code>captain</code> / <code>viewer</code> / <code>outsider</code>，
    密码均为 <code>Ocean@2026</code><br>
    本系统 <b>没有 SSO 模块</b> —— 这正是要解决的约束。
  </div>
</div></body></html>"""


@app.get("/login", response_class=HTMLResponse)
async def login_page(error: str | None = None) -> str:
    err = f'<div class="err">{error}</div>' if error else ""
    return LOGIN_HTML.replace("{err}", err)


@app.post("/login")
async def login(response: Response, username: str = Form(...), password: str = Form(...)):
    user = USERS.get(username.strip().lower())
    if not user or user["password"] != password:
        return RedirectResponse("/login?error=用户名或密码错误", status_code=303)
    sid = secrets.token_urlsafe(32)
    SESSIONS[sid] = (user["username"], _now() + SESSION_TTL)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(
        SESSION_COOKIE,
        sid,
        max_age=SESSION_TTL,
        httponly=True,
        samesite="lax",
        secure=False,  # 本地演示走 http；生产必须 True
        path="/",
    )
    return resp


@app.get("/")
async def home(response: Response, OCSESSION: str | None = Cookie(default=None)):
    user = _session_user(OCSESSION)
    if not user:
        return RedirectResponse("/login", status_code=303)

    # oceansite 的「网络安全模块」入口 —— 就是这样一个普通链接
    mp_link = os.getenv("MYPORTAL_URL", "http://127.0.0.1:9102/")
    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>oceansite · 船东服务平台</title>
<style>
 body{{margin:0;font-family:"Microsoft YaHei","Segoe UI",sans-serif;background:#F1F5F9;color:#1E3A8A}}
 header{{background:#0F172A;color:#fff;padding:16px 28px;display:flex;align-items:center;gap:14px}}
 .logo{{width:34px;height:34px;border-radius:8px;background:#1E40AF;display:grid;place-items:center;
        font-weight:800;font-size:13px}}
 header b{{font-size:16px}} header span{{color:#94A3B8;font-size:12px}}
 .who{{margin-left:auto;text-align:right;font-size:12px;color:#BFDBFE}}
 .wrap{{max-width:900px;margin:28px auto;padding:0 22px}}
 .card{{background:#fff;border:1px solid #DBEAFE;border-radius:12px;padding:22px 24px;margin-bottom:16px;
        box-shadow:0 1px 2px rgba(15,23,42,.06)}}
 h2{{font-size:16px;margin:0 0 14px}}
 .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}}
 .kv{{background:#F8FAFC;border:1px solid #DBEAFE;border-radius:9px;padding:12px 14px}}
 .kv small{{display:block;color:#64748B;font-size:11.5px;margin-bottom:4px}}
 .kv b{{font-size:14px;font-family:Consolas,monospace}}
 .mod{{display:flex;align-items:center;gap:14px;padding:16px 18px;border:1.5px solid #1E40AF;
       border-radius:10px;background:#EFF6FF;text-decoration:none;color:inherit;transition:.16s}}
 .mod:hover{{box-shadow:0 6px 18px rgba(30,64,175,.14)}}
 .mod .ic{{width:44px;height:44px;border-radius:10px;background:#1E40AF;color:#fff;display:grid;
           place-items:center;font-size:19px;font-weight:800;flex-shrink:0}}
 .mod b{{display:block;font-size:15px;color:#1E40AF}}
 .mod span{{font-size:12.5px;color:#475569}}
 .mod .go{{margin-left:auto;color:#1E40AF;font-size:13px;font-weight:600}}
 .tag{{display:inline-block;font-size:11px;padding:2px 9px;border-radius:20px;background:#FEF3C7;
       color:#A35208;border:1px solid #FDE68A;font-weight:700}}
 a.lnk{{color:#1E40AF;font-size:13px;font-weight:600;text-decoration:none}}
</style></head><body>
<header>
  <div class="logo">OC</div>
  <div><b>oceansite</b><br><span>船东服务平台</span></div>
  <div class="who">{user['display_name']}（{user['username']}）<br>
       <span style="color:#94A3B8;font-size:11px">{user['org_name']} · {user['role']}</span></div>
</header>
<div class="wrap">
  <div class="card">
    <h2>船舶与租户信息</h2>
    <div class="grid">
      <div class="kv"><small>用户标识</small><b>{user['user_id']}</b></div>
      <div class="kv"><small>所属组织</small><b>{user['org_code']}</b></div>
      <div class="kv"><small>组织名称</small><b>{user['org_name']}</b></div>
      <div class="kv"><small>角色</small><b>{user['role']}</b></div>
    </div>
  </div>
  <div class="card">
    <h2>应用模块</h2>
    <a class="mod" href="{mp_link}">
      <span class="ic">盾</span>
      <span><b>网络安全模块</b><span>船舶网络安全态势 · 事件 · UR 合规</span></span>
      <span class="go">进入 →</span>
    </a>
    <p style="font-size:12px;color:#64748B;margin:14px 0 0">
      点击后跳转 myPortal —— <b>不再要求输入第二套账号密码</b>。
      <span class="tag" style="margin-left:6px">免密对接</span>
    </p>
  </div>
  <div class="card" style="font-size:12.5px;color:#475569;line-height:1.8">
    <b style="color:#1E3A8A">会话状态</b><br>
    Cookie <code>{SESSION_COOKIE}</code> 已下发（HttpOnly · SameSite=Lax）· TTL {SESSION_TTL}s<br>
    <a class="lnk" href="/logout">退出登录</a>
  </div>
</div></body></html>"""
    return HTMLResponse(html)


@app.get("/logout")
async def logout(response: Response, OCSESSION: str | None = Cookie(default=None)):
    SESSIONS.pop(OCSESSION or "", None)
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@app.get("/api/session/whoami")
async def whoami(OCSESSION: str | None = Cookie(default=None)):
    """现成的身份查询端点 —— 整个方案只依赖这一个能力。

    如果真实 oceansite 没有 JSON 端点，但有「已登录才能访问的页面」，
    见 README.md 方案 B 的退化兜底。
    """
    user = _session_user(OCSESSION)
    if not user:
        return JSONResponse({"error": "not_authenticated"}, status_code=401)
    return JSONResponse(
        {
            "user_id": user["user_id"],
            "username": user["username"],
            "email": user["email"],
            "display_name": user["display_name"],
            "org_code": user["org_code"],
            "org_name": user["org_name"],
            "role": user["role"],
        }
    )


@app.get("/api/session/check")
async def check(OCSESSION: str | None = Cookie(default=None)):
    """最简形态：只回答"登录了没有"。连身份都不给也能用 —— 身份可从别处取。"""
    return JSONResponse({"authenticated": _session_user(OCSESSION) is not None})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("OCEAN_PORT", "9101")), log_level="warning")
