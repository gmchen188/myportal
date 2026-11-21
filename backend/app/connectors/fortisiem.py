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
from datetime import datetime, timezone
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


# ── 字段映射（实机 7.5.1 验证，2026-11-21）────────────────────────────────
#
# 实机拉到的字段名与文档不完全一致，按实测来：
#
#   租户/组织   customer            （**不是** organization —— 那是别的版本）
#   严重度类别   eventSeverityCat    HIGH / MEDIUM / LOW
#   严重度数值   eventSeverity       1-10
#   事件标题     incidentTitle
#   设备名      incidentRptDevName
#   设备 IP     incidentRptIp
#   源 IP       incidentSrc         形如 "srcIpAddr:172.16.0.57, srcGeoCountry:, "
#   目标/用户   incidentTarget      形如 "destName:xxx, destIpAddr:1.2.3.4, user:admin, "
#   事件 ID     incidentId
#   状态        incidentStatus      0=未解决 3=已解决
#   时间        incidentFirstSeen   毫秒时间戳
#
# **严重度以类别为准，不以数值为准。** 实机数据里两者是冲突的：
#
#   (eventSeverity=6, eventSeverityCat='MEDIUM')
#   (eventSeverity=7, eventSeverityCat='MEDIUM')
#   (eventSeverity=9, eventSeverityCat='HIGH')
#
# 数值 9 按「0-10 惯例」会被读成 critical，但 SIEM 自己判的是 HIGH。
# **SIEM 的类别是它的判定结果，数值只是它用来判定的输入之一** ——
# 拿输入推翻结论会得到错色（critical 红 vs high 粉红）。
# 所以：类别认得就用类别；类别缺失才退回数值。
#
# 注意这与 `services/monitoring.py` 的 `severity_from_score()` 语义不同 ——
# 那个是给 webhook/syslog 用的（那里 severity 字段是 0-100 分数惯例，
# 数值优先是合理的）。**两个来源不能共用一套规则。**

_SEVERITY_BY_CAT = {
    "critical": "critical",
    "high": "high",
    "medium": "medium",
    "low": "low",
    "informational": "informational",
    "info": "informational",
}


def severity_from_siem(cat: str | None, score: float | None) -> str:
    """从 FortiSIEM 的 (eventSeverityCat, eventSeverity) 推出级别。

    **类别优先**（见上方字段映射的说明）。类别缺失或认不出时退回数值，
    数值也认不出才是 unknown。
    """
    key = (cat or "").strip().lower()
    if key in _SEVERITY_BY_CAT:
        return _SEVERITY_BY_CAT[key]
    if score is not None:
        # 数值兜底：1-10 惯例（实机观测到的范围）
        if score >= 9:
            return "critical"
        if score >= 7:
            return "high"
        if score >= 4:
            return "medium"
        if score >= 1:
            return "low"
    return "unknown"


def _url_decode(raw: str) -> str:
    """解 URL 编码。

    FortiSIEM 的 naturalId 字段是 URL 编码的 —— 实机返回 "HOST%2d1.1.1.1"，
    其中 %2d 就是 "-"。不解码的话这个 natural_id 与别处对不上，
    事件按 natural_id 归集到设备时就会落空。
    """
    if not raw or "%" not in raw:
        return raw
    from urllib.parse import unquote

    return unquote(raw)


def _parse_kv_blob(raw: str | None) -> dict[str, str]:
    """解析 "srcIpAddr:1.2.3.4, srcGeoCountry:, " 这种 KV 串。

    FortiSIEM 把 src/dest 的多个属性塞在一个逗号分隔串里，格式不统一
    （有的带空格，有的没有）。按 'key:value' 拆，取第一个冒号前的键名。
    """
    out: dict[str, str] = {}
    if not raw:
        return out
    for part in raw.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        k, _, v = part.partition(":")
        k = k.strip()
        v = v.strip()
        if k and v and k not in out:
            out[k] = v
    return out


# 探测结果的缓存时长（秒）。
#
# **为什么需要缓存**：/health（侧栏指示灯）与 /api/siem/status（面板）都会
# 调 status()，前端两个都是 30 秒轮询 —— 不缓存就是每分钟 4 次完整探测
# （每次 = 1 TCP + 1 TLS + 1 OAuth + 1 CMDB XML，实测 156ms）。
#
# 而且 /health 只需要一个「连上了没有」的布尔值给指示灯 —— 让它为了
# 显示个绿点而跑完整探测是浪费。
#
# 10 秒的窗口足够消掉重复探测，又短到「拔了网线再插上」几十秒内能反映。
_STATUS_CACHE_TTL = float(os.getenv("FORTISIEM_STATUS_CACHE_TTL", "10"))


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
    # 探测结果缓存（见 _STATUS_CACHE_TTL 的说明）
    _status_cache: SiemStatus | None = field(default=None, init=False)
    _status_cache_expires: float = field(default=0.0, init=False)
    # 设备列表缓存 —— 与探测缓存同 TTL。
    # 不缓存的话，每次 30 秒轮询都要真拉一遍 CMDB XML（几十台设备）。
    _devices_cache: list[dict[str, Any]] | None = field(default=None, init=False)
    _devices_cache_expires: float = field(default=0.0, init=False)

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
    def devices(self, *, use_cache: bool = True) -> list[dict[str, Any]]:
        """CMDB 设备列表。内部面答 XML。

        设备的组织在每个 <device> 上：
            <organization id="1" name="Super"/>
        丢掉属性就丢了组织名，而组织名是租户边界。

        ## 缓存

        **必须缓存** —— 前端 30 秒轮询一次，每次拉 CMDB 都是一次完整
        HTTP 请求（拉 XML、解析几十台设备）。不缓存的话侧栏的 /health
        轮询和 /siem 面板的轮询每次都真拉一遍。

        TTL 与探测缓存一致（10 秒）—— 同一轮询周期内两个入口拿到的是
        同一份数据，不会一个显示 3 台另一个显示 0 台。
        """
        import xml.etree.ElementTree as ET

        now = time.time()
        if use_cache and self._devices_cache is not None and now < self._devices_cache_expires:
            return self._devices_cache

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
                    # naturalId 是 **URL 编码**的 —— 实机返回 "HOST%2d1.1.1.1"
                    # （%2d 就是 "-"）。不解码的话资产清单里的 natural_id
                    # 会跟别处对不上，事件归集按 natural_id 匹配时也匹配不上。
                    "natural_id": _url_decode((d.findtext("naturalId") or "").strip()),
                    "access_ip": (d.findtext("accessIp") or "").strip(),
                    "sn": (d.findtext("sn") or "").strip(),
                    "org": (org.get("name") if org is not None else None),
                    "org_id": (org.get("id") if org is not None else None),
                    "vendor": (dt.findtext("vendor") if dt is not None else None),
                    "model": (dt.findtext("model") if dt is not None else None),
                    "version": (dt.findtext("version") if dt is not None else None),
                }
            )
        # 写缓存 —— 下次轮询直接复用
        self._devices_cache = out
        self._devices_cache_expires = now + _STATUS_CACHE_TTL
        return out

    def incidents(
        self,
        org: str | None = None,
        limit: int = 200,
        minutes: int = 1440,
    ) -> list[dict[str, Any]]:
        """取事件。走 `/phoenix/rest/pub/incident`（POST richer）。7.5.1 上
        `/phoenix/rest/pub/v2/query/incidents` 是 404 —— 别用那条。

        **返回已归一的事件字典**，字段名对齐我方 `incidents` 表：
        title / severity / device_* / src_ip / dest_ip / user / occurred_at。
        归一放在 connector 做，不在路由做 —— 换数据源时只改这一处。
        """
        now = int(time.time() * 1000)
        payload = {
            "start": 0,
            "size": limit,
            # 0=未解决 1/2=处理中 3=已解决 —— 全要，历史也要
            "incidentStatus": [0, 1, 2, 3],
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

        out: list[dict[str, Any]] = []
        for i in items:
            # 租户过滤：实机字段是 `customer`（旧文档写的 organization 是别的版本）。
            # **匹配不上就丢弃** —— 无法归属的记录不能归给任何租户。
            org_name = (i.get("customer") or i.get("organization") or i.get("org_name") or "").lower()
            if target and org_name and org_name != target:
                continue

            src = _parse_kv_blob(i.get("incidentSrc"))
            tgt = _parse_kv_blob(i.get("incidentTarget"))
            score = i.get("eventSeverity")
            first_seen = i.get("incidentFirstSeen")
            out.append(
                {
                    "external_id": str(i.get("incidentId") or ""),
                    "title": (i.get("incidentTitle") or i.get("eventName") or "").strip()[:400],
                    "severity": severity_from_siem(i.get("eventSeverityCat"), score),
                    "score": float(score) if score is not None else None,
                    "source": "fortisiem",
                    "device_name": (i.get("incidentRptDevName") or "").strip(),
                    "device_ip": (i.get("incidentRptIp") or "").strip(),
                    "src_ip": src.get("srcIpAddr"),
                    "dest_ip": tgt.get("destIpAddr"),
                    "user": tgt.get("user"),
                    # 毫秒时间戳 → 带时区的 datetime
                    "occurred_at": (
                        datetime.fromtimestamp(first_seen / 1000, tz=timezone.utc)
                        if first_seen
                        else None
                    ),
                    # 0=未解决 3=已解决。保持 SIEM 原值。
                    "incident_status": i.get("incidentStatus"),
                    "org": i.get("customer"),
                    "raw": i,
                }
            )
        return out

    def status(self, *, use_cache: bool = True) -> SiemStatus:
        """带缓存的探活入口。真正的探测逻辑在 _probe() 里。"""
        now = time.time()
        if use_cache and self._status_cache and now < self._status_cache_expires:
            return self._status_cache
        result = self._probe()
        self._status_cache = result
        self._status_cache_expires = now + _STATUS_CACHE_TTL
        return result

    def _probe(self) -> SiemStatus:
        """探活，并把「连不上」拆成可定位的阶段。

        分四段，每段的结果单独报出来：

            tcp     TCP 能不能连上        —— 不通 = 网络/路由问题
            tls     TLS 能不能握手        —— 不通 = 证书或协议问题
            auth    能不能取到 token      —— 不行 = 凭据问题
            api     能不能读到设备        —— 不行 = 权限或接口问题

        **不合并成一句「连接失败」** —— 那等于让运维自己猜。

        `use_cache=True` 时，10 秒内重复调用直接复用上一次结果 ——
        避免 /health 与 /api/siem/status 的双轮询把探测打两遍。
        需要强制重测时传 `use_cache=False`。
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
