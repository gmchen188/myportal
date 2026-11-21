"""
FortiSIEM 连接器。

按 skill `fortinet-api-integration` 里那份**实机验证过的**契约实现：

    认证   POST /phoenix/rest/pub/security/oauth/token
           form-encoded，grant_type=client_credentials → access_token（15 分钟）
           **不是** admin GUI 密码 —— API 凭据是单独的
    内部面 严格 Accept: application/json 会 406，要发
           "application/json, text/plain, */*"
    表名   ph_incident（不是 phoenix_incident）、ph_device、ph_sys_domain
    租户   ph_incident.cust_org_id → ph_sys_domain.domain_id → name
           REST 面叫 organization，MCP 面叫 org_name —— 两个都认

**连接不可达时必须优雅降级**：这台开发机连不上 FortiSIEM（不在 172.16.0.x
网段），所以连接器不能抛异常把整个后台带崩 —— 它返回空结果 + 明确的
"未连接"标记，监控面板照常显示（设备灰色 = 不知道，不是有问题）。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

# ── 配置 ────────────────────────────────────────────────────────────────────
FS_BASE = os.getenv("FORTISIEM_BASE_URL", "https://172.16.20.48").rstrip("/")
FS_CLIENT_ID = os.getenv("FORTISIEM_CLIENT_ID", "")
FS_CLIENT_SECRET = os.getenv("FORTISIEM_CLIENT_SECRET", "")
FS_ORG = os.getenv("FORTISIEM_ORG", "Super")
FS_TIMEOUT = float(os.getenv("FORTISIEM_TIMEOUT", "15.0"))
FS_VERIFY_TLS = os.getenv("FORTISIEM_VERIFY_TLS", "false").lower() not in ("0", "false", "no")

# 内部面要这个 Accept —— 严格 JSON 会 406
_ACCEPT = "application/json, text/plain, */*"


@dataclass
class SiemStatus:
    configured: bool = False
    connected: bool = False
    org: str | None = None
    error: str | None = None
    last_sync: str | None = None
    incident_count: int = 0
    # 分阶段诊断 —— 「连不上」有太多种原因，不分阶段就只能猜
    stage: str | None = None
    # 各阶段的实测结果，供前端显示
    probes: dict[str, Any] | None = None


@dataclass
class FortiSiemClient:
    """极简客户端。用 dataclass 而不是类，因为状态只有两个：token 与 client。"""

    base_url: str = FS_BASE
    client_id: str = FS_CLIENT_ID
    client_secret: str = FS_CLIENT_SECRET
    org: str = FS_ORG
    _token: str | None = field(default=None, init=False)
    _token_expires: float = field(default=0.0, init=False)
    _client: httpx.Client | None = field(default=None, init=False)

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def _ensure_client(self) -> httpx.Client:
        if self._client is None:
            # trust_env=False —— 系统代理会把到内网设备的调用劫持掉，
            # 表现为 12 秒后的 TLS 超时（看起来像"设备不通"）
            self._client = httpx.Client(
                timeout=httpx.Timeout(FS_TIMEOUT),
                verify=FS_VERIFY_TLS,
                trust_env=False,
            )
        return self._client

    # ── 认证 ────────────────────────────────────────────────────────────────
    def token(self) -> str:
        """按需铸造 access token。

        7.5.1 用 OAuth 2.0 Client Credentials（Refresh Token grant 被替换了）。
        body 必须 form-encoded —— JSON 会 415，GET 会 405。
        **同一个 client 不能反复铸造**（appliance 会拒），所以缓存到过期前。
        """
        if self._token and time.time() < self._token_expires - 60:
            return self._token
        if not self.configured:
            raise RuntimeError("FortiSIEM 凭据未配置（FORTISIEM_CLIENT_ID / FORTISIEM_CLIENT_SECRET）")

        r = self._ensure_client().post(
            f"{self.base_url}/phoenix/rest/pub/security/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if r.status_code != 200:
            raise RuntimeError(f"取 token 失败：HTTP {r.status_code} {r.text[:200]}")
        data = r.json()
        self._token = data["access_token"]
        self._token_expires = time.time() + float(data.get("expires_in", 900))
        return self._token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token()}",
            "Accept": _ACCEPT,
        }

    # ── 读 ──────────────────────────────────────────────────────────────────
    def devices(self) -> list[dict[str, Any]]:
        """CMDB 设备列表。内部面答 XML。

        设备的组织在每个 <device> 上：
            <organization id="1" name="Super"/>
        丢掉属性就丢了组织名，而组织名是租户边界。
        """
        import xml.etree.ElementTree as ET

        r = self._ensure_client().get(
            f"{self.base_url}/phoenix/rest/cmdbDeviceInfo/devices",
            headers=self._headers(),
        )
        r.raise_for_status()
        root = ET.fromstring(r.text)
        out = []
        for d in root.iter("device"):
            org = d.find("organization")
            dt = d.find("deviceType")
            out.append(
                {
                    "name": (d.findtext("name") or "").strip(),
                    "natural_id": (d.findtext("naturalId") or "").strip(),
                    "access_ip": (d.findtext("accessIp") or "").strip(),
                    "sn": (d.findtext("sn") or "").strip(),
                    "org": (org.get("name") if org is not None else None),
                    "org_id": (org.get("id") if org is not None else None),
                    "vendor": (dt.findtext("vendor") if dt is not None else None),
                    "model": (dt.findtext("model") if dt is not None else None),
                    "version": (dt.findtext("version") if dt is not None else None),
                }
            )
        return out

    def incidents(
        self,
        org: str | None = None,
        limit: int = 200,
        minutes: int = 1440,
    ) -> list[dict[str, Any]]:
        """取事件。

        走 `/phoenix/rest/pub/incident`（POST  richer）。7.5.1 上
        `/phoenix/rest/pub/v2/query/incidents` 是 404 —— 别用那条。
        """
        now = int(time.time() * 1000)
        payload = {
            "start": 0,
            "size": limit,
            "incidentStatus": [0],
            "timeFrom": now - minutes * 60 * 1000,
            "timeTo": now,
        }
        r = self._ensure_client().post(
            f"{self.base_url}/phoenix/rest/pub/incident",
            json=payload,
            headers={**self._headers(), "Content-Type": "application/json"},
        )
        r.raise_for_status()
        data = r.json()
        items = data.get("data") or data.get("incidents") or []
        target = (org or self.org or "").lower()
        out = []
        for i in items:
            # 租户过滤：组织名匹配。**匹配不上就丢弃**，而不是放行 ——
            # 无法归属的记录不能归给任何租户。
            org_name = (i.get("organization") or i.get("org_name") or "").lower()
            if target and org_name and org_name != target:
                continue
            out.append(i)
        return out

    def status(self) -> SiemStatus:
        """探活，并把「连不上」拆成可定位的阶段。

        分四段，每段的结果单独报出来：

            tcp     TCP 能不能连上        —— 不通 = 网络/路由问题
            tls     TLS 能不能握手        —— 不通 = 证书或协议问题
            auth    能不能取到 token      —— 不行 = 凭据问题
            api     能不能读到设备        —— 不行 = 权限或接口问题

        **不合并成一句「连接失败」** —— 那等于让运维自己猜。
        """
        probes: dict[str, Any] = {}

        # ① TCP
        import socket
        import urllib.parse

        parsed = urllib.parse.urlparse(self.base_url)
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            with socket.create_connection((host, port), timeout=8):
                probes["tcp"] = {"ok": True, "detail": f"{host}:{port} 可连接"}
        except Exception as e:
            probes["tcp"] = {"ok": False, "detail": f"{host}:{port} 不可连接：{type(e).__name__}"}
            return SiemStatus(
                configured=self.configured, connected=False, org=self.org,
                error=f"网络不通：{probes['tcp']['detail']}",
                stage="tcp", probes=probes,
            )

        # ② TLS
        try:
            r = self._ensure_client().get(self.base_url, timeout=10)
            probes["tls"] = {"ok": True, "detail": f"TLS 握手成功，HTTP {r.status_code}"}
        except httpx.ConnectError as e:
            probes["tls"] = {"ok": False, "detail": f"TLS 失败：{str(e)[:120]}"}
            return SiemStatus(
                configured=self.configured, connected=False, org=self.org,
                error=probes["tls"]["detail"], stage="tls", probes=probes,
            )
        except Exception as e:
            probes["tls"] = {"ok": True, "detail": f"连接成功（{type(e).__name__}）"}

        # ③ 认证
        if not self.configured:
            probes["auth"] = {
                "ok": False,
                "detail": "未配置 FORTISIEM_CLIENT_ID / FORTISIEM_CLIENT_SECRET",
            }
            return SiemStatus(
                configured=False, connected=False, org=self.org,
                error=probes["auth"]["detail"], stage="auth", probes=probes,
            )
        try:
            self.token()
            probes["auth"] = {"ok": True, "detail": "token 获取成功"}
        except Exception as e:
            probes["auth"] = {"ok": False, "detail": str(e)[:200]}
            return SiemStatus(
                configured=True, connected=False, org=self.org,
                error=probes["auth"]["detail"], stage="auth", probes=probes,
            )

        # ④ 读设备
        try:
            devs = self.devices()
            probes["api"] = {"ok": True, "detail": f"读到 {len(devs)} 台设备"}
            return SiemStatus(
                configured=True, connected=True, org=self.org,
                incident_count=len(devs), stage="ok", probes=probes,
            )
        except Exception as e:
            probes["api"] = {"ok": False, "detail": str(e)[:200]}
            return SiemStatus(
                configured=True, connected=False, org=self.org,
                error=probes["api"]["detail"], stage="api", probes=probes,
            )


# 全局单例 —— token 要按 (base_url, client_id) 缓存，不能每次请求重铸
_client_singleton: FortiSiemClient | None = None


def get_client() -> FortiSiemClient:
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = FortiSiemClient()
    return _client_singleton
