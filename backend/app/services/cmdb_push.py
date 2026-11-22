"""
把 myPortal 资产清单里的资产，推送到 FortiSIEM 的 CMDB。

## 为什么是「手动推送」而不是「保存即写」

CMDB 是 FortiSIEM **自己发现**的设备表（现有设备的 `discoverMethod` 全是 `LOG`），
myPortal 的资产清单是人工维护的**权威清单**。两者角色不同：

- 资产清单包含**全部**船载设备，包括那些根本没接监控的（`unknown` 状态）
- 全量灌进 CMDB 会让 SIEM 的设备视图凭空多出几十台没日志的设备，
  关联规则和覆盖率报表全歪

再者：写操作**没有事务、没有回滚**。myPortal 删一条资产，不知道该不该去 SIEM 删；
改一个设备名，可能断掉按 `natural_id` 匹配的事件关联。

所以：**保存资产 = 只写 myPortal 的库**；推送是**用户明确意图的一次性动作**。

## 幂等

按 `(tenant_id, natural_id)` 判重。已推送过的资产默认不再推 —— 重复推会产生
CMDB 里的重复设备，而 CMDB 没有「按 natural_id upsert」的语义。

`siem_pushed_at` / `siem_push_status` / `siem_task_id` 记在资产上，
列表里能直接看出「未推送 / 已推送 / 推送失败」，用户自己决定要不要重来。

## 失败不阻断

推送失败**不影响资产保存**。两条独立的流水线 —— 资产是资产，CMDB 同步是同步。
一个 SIEM 挂了不能让人存不了资产。

## 认证

CMDB 写端点要 **Basic Auth**（FortiSIEM 账号口令），而读端点现在用的是
**OAuth client_credentials**。两者权限等级不同 —— 实测 7.5.1：

    OAuth token  scope=appserver/user   → 读 200，写 403
    Basic Auth  admin 账号              → 全部 403（权限不足）

**403 有两种含义，要分清**：
- `User is not authorized to access this resource.` → 权限不足
- `Account locked due to consecutive login failures.` → **账号被锁**（口令试错太多次）

后者跟权限无关，等锁定期过就行，代码里要能区分开 —— 否则会误导成「权限不够」。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from xml.sax.saxutils import escape

# 资产字段 → CMDB 字段的映射。
#
# **来源是实机探测**（FortiSIEM 7.5.1，`POST /phoenix/rest/pub/device` 的 JSON），
# 不是照着想象填的：
#
#   deviceTag   ← 船舶安全区域 —— 顶层自由字段
#   purdueLevel ← CBS 等级（IEC 62443 Purdue Level）—— 顶层自由字段
#   contact     ← 责任人
#   importance  ← 状态
#
# `zone` 和 `cbs_class` 在 CMDB 里有**正经的顶层落点**，
# 不需要塞进 description，也不需要走自定义属性接口。
CMDB_FIELD_MAP: dict[str, str] = {
    "name": "name",
    "ip": "accessIp",
    "vendor": "deviceType.vendor",
    "model": "deviceType.model",
    "serial": "hwSerialNum",
    "zone": "deviceTag",
    "cbs_class": "purdueLevel",
    "owner": "contact",
    "status": "importance",
    "notes": "description",
}

# 不推的字段 —— natural_id 是 myPortal 自己的去重键，type 是内部分类
SKIP_FIELDS = {"natural_id", "type"}

# CBS 等级 → Purdue Level 的取值候选。
# CBS（船级社等级）与 IEC 62443 Purdue Level 不是同一套标准，
# 但工程上常被并排使用 —— **这里不做自动转换**，直接透传原文，
# 避免把「船级社等级」错当成「Purdue Level」造成合规误读。
# 转换规则要业务方给，不能由代码猜。
Purdue_LEVELS = {
    "SL1", "SL2", "SL3", "SL4",
    "L1", "L2", "L3", "L4",
    "TL1", "TL2", "TL3", "TL4",
}


@dataclass
class MappedAsset:
    """一件资产映射到 CMDB 字段后的结果。"""

    asset_id: int
    name: str
    natural_id: str | None
    fields: dict[str, Any] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)   # 没映射上的资产字段
    missing: list[str] = field(default_factory=list)   # CMDB 必填但值为空

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "name": self.name,
            "natural_id": self.natural_id,
            "fields": self.fields,
            "skipped": self.skipped,
            "missing": self.missing,
        }


def map_asset(asset: Any) -> MappedAsset:
    """把一件资产映射成 CMDB 字段。**纯函数** —— 不碰网络，可离线测。"""
    out = MappedAsset(
        asset_id=getattr(asset, "id", 0) or 0,
        name=getattr(asset, "name", "") or "",
        natural_id=getattr(asset, "natural_id", None),
    )
    for attr, cmdb_field in CMDB_FIELD_MAP.items():
        value = getattr(asset, attr, None)
        if value in (None, ""):
            continue
        out.fields[cmdb_field] = value

    for attr in ("natural_id", "type"):
        value = getattr(asset, attr, None)
        if value not in (None, ""):
            out.skipped.append(attr)

    # CMDB 里必须有 name；IP 对监控有用但对「先登记」不是硬性
    if not out.fields.get("name"):
        out.missing.append("name")
    return out


def _xml_device(mapped: MappedAsset) -> str:
    """一件设备转成 CMDB XML。

    FortiSIEM 的 `device/discovery/add` 收 XML（符合 `device.xsd`），
    结构是 `<Devices><Device>...</Device></Devices>`。
    """
    f = mapped.fields
    parts: list[str] = []

    name = f.get("name")
    if name:
        parts.append(f"<name>{escape(str(name))}</name>")
    access_ip = f.get("accessIp")
    if access_ip:
        parts.append(f"<accessIp>{escape(str(access_ip))}</accessIp>")
    tag = f.get("deviceTag")
    if tag:
        parts.append(f"<deviceTag>{escape(str(tag))}</deviceTag>")
    purdue = f.get("purdueLevel")
    if purdue:
        parts.append(f"<purdueLevel>{escape(str(purdue))}</purdueLevel>")
    desc = f.get("description")
    if desc:
        parts.append(f"<description>{escape(str(desc))}</description>")
    contact = f.get("contact")
    if contact:
        parts.append(f"<contact>{escape(str(contact))}</contact>")
    importance = f.get("importance")
    if importance:
        parts.append(f"<importance>{escape(str(importance))}</importance>")
    serial = f.get("hwSerialNum")
    if serial:
        parts.append(f"<hwSerialNum>{escape(str(serial))}</hwSerialNum>")

    vendor = f.get("deviceType.vendor")
    model = f.get("deviceType.model")
    if vendor or model:
        device_type = ""
        if vendor:
            device_type += f"<vendor>{escape(str(vendor))}</vendor>"
        if model:
            device_type += f"<model>{escape(str(model))}</model>"
        parts.append(f"<deviceType>{device_type}</deviceType>")

    return "<Device>" + "".join(parts) + "</Device>"


def build_add_xml(mapped_assets: list[MappedAsset]) -> str:
    """生成加设备的 XML 报文。

    **一个报文可以带多台设备** —— 官方端点是异步的，一次提交一批，
    返回一个 taskId，再查状态。比逐台提交快得多，也少一半的往返。
    """
    devices = "".join(_xml_device(m) for m in mapped_assets)
    return (
        '<?xml version="1.0" encoding="UTF-8" ?>'
        f"<Devices>{devices}</Devices>"
    )


# ── 错误分类 ──────────────────────────────────────────────────────────
# 403 有两种完全不同的原因，混为一谈会把「等 15 分钟」说成「去申请权限」。

LOCKED_RE = re.compile(r"account\s+locked", re.IGNORECASE)
UNAUTHORIZED_RE = re.compile(r"not\s+authorized", re.IGNORECASE)


class SiemWriteError(RuntimeError):
    """SIEM 写操作失败。`kind` 决定前端怎么提示。"""

    def __init__(self, message: str, *, kind: str = "unknown", status: int | None = None):
        super().__init__(message)
        self.kind = kind          # locked / unauthorized / bad_request / network / unknown
        self.status = status


def classify_write_error(status: int, body: str) -> SiemWriteError:
    """把 HTTP 状态 + 响应体翻译成用户能据以行动的错��。"""
    text = re.sub(r"<[^>]+>", " ", body or "")
    text = re.sub(r"\s+", " ", text).strip()

    if status == 403:
        if LOCKED_RE.search(text):
            return SiemWriteError(
                "FortiSIEM 账号已锁定（连续登录失败次数过多），等锁定期过后再试。",
                kind="locked",
                status=status,
            )
        if UNAUTHORIZED_RE.search(text):
            return SiemWriteError(
                "FortiSIEM 拒绝了写入：当前账号没有 CMDB 写权限。",
                kind="unauthorized",
                status=status,
            )
        return SiemWriteError(text or "HTTP 403", kind="unauthorized", status=status)

    if status == 401:
        return SiemWriteError(
            "FortiSIEM 认证失败：账号或口令不对。",
            kind="unauthorized",
            status=status,
        )
    if status in (400, 422):
        return SiemWriteError(
            f"FortiSIEM 认为报文不合法：{text[:200] or f'HTTP {status}'}",
            kind="bad_request",
            status=status,
        )
    if status in (502, 503, 504):
        return SiemWriteError(
            f"FortiSIEM 暂时不可达（HTTP {status}）。",
            kind="network",
            status=status,
        )
    return SiemWriteError(text or f"HTTP {status}", kind="unknown", status=status)
