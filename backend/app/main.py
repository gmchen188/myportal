"""
myPortal 后端入口。

    python -m app.main           （从 backend/ 目录）
    uvicorn app.main:app --port 9102

开发环境下用 `X-Dev-Tenant: asi` 头免登录访问（见 auth.py）。

**这个服务是「真实后台」的第一版**：资产、拓扑、事件、监控面板全部有
持久化（SQLite），不再靠前端硬编码数组。
"""

from __future__ import annotations

import os
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# 让 `python -m app.main` 从 backend/ 目录跑时能 import 到 app 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.connectors.fortisiem import get_client  # noqa: E402
from app.db import init_db  # noqa: E402
from app.routers import assets, monitoring, topologies  # noqa: E402

app = FastAPI(
    title="myPortal backend",
    version="0.1.0",
    description="船舶网络安全运营门户 —— 资产清单 / 网络拓扑 / 安全监控",
)

# 开发期前端在 6010（Next rewrite 过来的同源）或 6012 静态服务上。
# 生产环境应该走同源部署（同源就根本不需要 CORS）。
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "MP_ALLOWED_ORIGINS",
        "http://127.0.0.1:6010,http://127.0.0.1:6012,http://localhost:6010,http://localhost:6012",
    ).split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(assets.router)
app.include_router(topologies.router)
app.include_router(monitoring.router)


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/health")
def health():
    """健康检查。顺带报出 SIEM 连通性 —— 连接器不可达不该让整个后台挂掉。"""
    siem = get_client().status()
    return {
        "status": "ok",
        "siem": {
            "configured": siem.configured,
            "connected": siem.connected,
            "org": siem.org,
            "error": siem.error,
        },
    }


@app.get("/api/siem/status")
def siem_status():
    """FortiSIEM 连接状态与设备列表。"""
    c = get_client()
    st = c.status()
    out = {
        "configured": st.configured,
        "connected": st.connected,
        "org": st.org,
        "error": st.error,
        "devices": [],
    }
    if st.connected:
        try:
            out["devices"] = c.devices()
        except Exception as e:
            out["error"] = str(e)[:300]
    return out


@app.exception_handler(500)
def _internal_error(_request, exc):  # pragma: no cover
    return JSONResponse(status_code=500, content={"error": "内部错误", "detail": str(exc)[:300]})


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("MP_PORT", "9102"))
    uvicorn.run(app, host=os.getenv("MP_HOST", "127.0.0.1"), port=port)
