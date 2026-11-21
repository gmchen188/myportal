"""
监控面板的设备状态计算。

## 颜色规则

    critical  → 红    (#dc2626)
    high      → 粉红  (#ec4899)
    medium    → 黄    (#f59e0b)
    low       → 蓝灰  (#64748b)
    normal    → 绿    (#16a34a)
    unknown   → 灰    (#94a3b8)

规则：**一个设备的颜色由它当前未解决事件里的最高级别决定**，不是最新事件
的决定。一台设备昨天有 critical、今天没有新事件 —— 它仍然是红的，直到
那条事件被关闭。取"最新事件"的颜色会让设备闪一下就变绿，那是在骗人。

`unknown` 是独立状态：**没有数据 ≠ 正常**。一台没接入监控的设备画成绿色，
运维会以为它安全 —— 这是最危险的一种错。灰色明确说"我不知道"。

## 事件从哪来

每个设备可以绑一个**通道**（channel），决定它的事件来源：

    fortisiem   从 FortiSIEM 同步（Fortinet 设备、以及已在 SIEM CMDB 里的设备）
    syslog      设备直接发 syslog 到 myPortal 的接收端口（交换机/路由器/工控设备）
    snmp_trap   SNMP Trap（老设备、不支持 syslog 的）
    webhook     第三方系统 POST 进来（漏洞扫描器、OT 监控系统、UEBA）
    manual      人工登记

**这就是"其他网络设备如何接收安全事件"的答案**：不是所有设备都要接进
FortiSIEM。myPortal 自己就是一个事件汇聚点 —— 交换机发 syslog、工控设备
经 SNMP Trap、扫描器经 webhook，都直接到 myPortal，统一归集到同一张
`incidents` 表。FortiSIEM 仍是 Fortinet 生态的权威源，myPortal 是跨厂商
的汇聚层。

这样设计还有个好处：**FortiSIEM 不可达时监控面板仍然工作**。设备直连
myPortal 的通道不依赖 SIEM。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

# 级别 → 颜色。按需求：critical 红、high 粉红、medium 黄、正常绿。
SEVERITY_COLOR: dict[str, str] = {
    "critical": "#dc2626",
    "high": "#ec4899",
    "medium": "#f59e0b",
    "low": "#64748b",
    "informational": "#64748b",
    "normal": "#16a34a",
    "unknown": "#94a3b8",
}

SEVERITY_ORDER = ["critical", "high", "medium", "low", "informational"]

# 未解决的事件算「活跃」。FortiSIEM 的 incident_status：0=active，
# 1=auto, 2=manual, 3=system cleared。已 clear 的不再计入。
ACTIVE_STATUSES = {0, 1, 2}


@dataclass
class DeviceState:
    natural_id: str | None
    ip: str | None
    label: str
    severity: str = "unknown"
    active_incidents: int = 0
    last_event_at: str | None = None
    top_title: str | None = None
    channel: str = "fortisiem"
    connected: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "natural_id": self.natural_id,
            "ip": self.ip,
            "label": self.label,
            "severity": self.severity,
            "color": SEVERITY_COLOR.get(self.severity, SEVERITY_COLOR["unknown"]),
            "active_incidents": self.active_incidents,
            "last_event_at": self.last_event_at,
            "top_title": self.top_title,
            "channel": self.channel,
            "connected": self.connected,
        }


def _severity_rank(sev: str | None) -> int:
    """级别权重。**越大越严重** —— 这样 max() 取出来的就是最严重的那条。

    SEVERITY_ORDER 是从严重到轻排的（critical 在前），所以 index() 直接用
    会得到 critical=0、low=4 —— 用 max() 反而选中最轻的。必须倒过来。
    """
    if not sev:
        return -1
    s = sev.lower()
    if s not in SEVERITY_ORDER:
        return len(SEVERITY_ORDER)
    return len(SEVERITY_ORDER) - SEVERITY_ORDER.index(s)


def normalize_severity(raw: str | None) -> str:
    """把各种来源的级别写法归一。

    FortiSIEM 的 `severity_cat` 是 HIGH/MEDIUM/LOW 三个值，**没有 CRITICAL**
    —— 临界事件在 SIEM 里是 `severity` 数值（9-10）。所以两列都要看：
    类别说"最高是什么"，数值说"有多高"。

    别的来源常见写法：critical/crit/紧急、high/高危、medium/med/中危、
    low/低危、info/informational/提示。
    """
    if not raw:
        return "unknown"
    s = str(raw).strip().lower()
    if s in ("critical", "crit", "紧急", "严重"):
        return "critical"
    if s in ("high", "高危", "高"):
        return "high"
    if s in ("medium", "med", "中危", "中"):
        return "medium"
    if s in ("low", "低危", "低"):
        return "low"
    if s in ("informational", "info", "提示", "信息"):
        return "informational"
    if s in ("normal", "ok", "正常"):
        return "normal"
    return "unknown"


def severity_from_score(score: float | None, category: str | None) -> str:
    """从 FortiSIEM 的 (severity_cat, severity) 推出级别。

    SIEM 的 `severity` 是数值，0-100 惯例，实际设备上：
    9-10 → critical，7-8 → high，4-6 → medium，1-3 → low。
    `severity_cat` 只有 HIGH/MEDIUM/LOW —— 所以 critical 只能从数值来。
    """
    cat = normalize_severity(category)
    if score is None:
        return cat
    if score >= 9:
        return "critical"
    if score >= 7:
        return "high"
    if score >= 4:
        return "medium"
    if score >= 1:
        return "low"
    return cat if cat != "unknown" else "normal"


def match_device_to_nodes(
    device: dict[str, Any],
    nodes: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """把一台设备匹配到拓扑图上的节点。

    **为什么要自动匹配**：拓扑图里的方块只有标签（FW-EDGE-01），
    SIEM 里的设备只有 natural_id 和 IP。两边对不上，事件就落不到
    节点上，监控面板永远是灰的。自动匹配让「从 SIEM 同步的设备」
    直接接进已有的拓扑图，不需要人工维护绑定表。

    匹配键与优先级（与 `compute_device_states` 的事件匹配保持一致 ——
    那边是 natural_id → IP → 名称依次试、命中就全收）：

        1. natural_id == 节点 label   优先级最高
        2. device.name == 节点 label
        3. device.ip == 节点 ip

    **三个键不互斥** —— 同一台设备可能同时命中不同节点的不同键，
    那就都返回（和 compute_device_states 一样，命中即收）。

    三条硬规则：

    1. **空值不参与匹配** —— device.ip 为 None/空串时，绝不能匹配到
       「没有 ip 的节点」。那会把一台设备绑到几十个节点上。
    2. **大小写不敏感** —— SIEM 的 naturalId 可能有大小写差异。
    3. **natural_id 先 URL 解码** —— FortiSIEM 返回的 naturalId 是
       URL 编码的（"HOST%2d1.1.1.1"），不解码对不上标签。
    """
    from urllib.parse import unquote

    def _norm(v: Any) -> str:
        return str(v or "").strip().lower()

    def _nid(v: Any) -> str:
        raw = str(v or "").strip()
        if not raw:
            return ""
        # 只在有 % 时才解 —— 避免无谓的处理
        return unquote(raw).strip().lower() if "%" in raw else raw.lower()

    dev_nid = _nid(device.get("natural_id"))
    dev_name = _norm(device.get("name"))
    dev_ip = _norm(device.get("ip") or device.get("access_ip"))

    matched: list[dict[str, Any]] = []
    seen: set[str] = set()
    for n in nodes:
        nid = str(n.get("id") or "")
        if nid in seen:
            continue
        label = _norm(n.get("label") or n.get("node_label"))
        node_ip = _norm(n.get("ip"))

        hit = False
        if dev_nid and label and dev_nid == label:
            hit = True
        if dev_name and label and dev_name == label:
            hit = True
        # IP 比较要求两边都有值 —— 空 IP 不参与
        if dev_ip and node_ip and dev_ip == node_ip:
            hit = True

        if hit:
            seen.add(nid)
            matched.append(n)

    return matched


def compute_device_states(
    devices: Iterable[dict[str, Any]],
    incidents: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """算出每个设备的监控状态。

    `devices` 是监控面板上的节点（来自拓扑图 + device_monitors 绑定）。
    `incidents` 是该租户的事件（来自数据库或 SIEM 同步结果）。

    匹配顺序：natural_id → IP → 名称。三个键都试，因为不同来源的事件
    填的字段不一样：SIEM 的事件带 host_ip_addr 和 host_name，
    syslog 解析出来的可能只有 IP。
    """
    devs = list(devices)
    incs = list(incidents)

    # 建立索引：一个键 → 事件列表
    by_nid: dict[str, list[dict]] = {}
    by_ip: dict[str, list[dict]] = {}
    by_name: dict[str, list[dict]] = {}
    for inc in incs:
        nid = (inc.get("device_natural_id") or "").strip()
        ip = (inc.get("device_ip") or "").strip()
        nm = (inc.get("device_name") or "").strip()
        if nid:
            by_nid.setdefault(nid.lower(), []).append(inc)
        if ip:
            by_ip.setdefault(ip, []).append(inc)
        if nm:
            by_name.setdefault(nm.lower(), []).append(inc)

    out: list[dict[str, Any]] = []
    for d in devs:
        nid = (d.get("natural_id") or "").strip()
        ip = (d.get("ip") or "").strip()
        label = (d.get("label") or d.get("node_label") or nid or ip or "?").strip()

        matched: list[dict] = []
        seen: set[int] = set()
        # 三个键依次试：natural_id → IP → 名称。不同来源的事件填的字段不一样 ——
        # SIEM 的事件带 host_ip_addr 和 host_name，syslog 解析出来的可能只有 IP。
        candidates: list[tuple[str, dict[str, list[dict]]]] = []
        if nid:
            candidates.append((nid.lower(), by_nid))
        if ip:
            candidates.append((ip, by_ip))
        if label:
            candidates.append((label.lower(), by_name))
        for key, idx in candidates:
            for inc in idx.get(key, []):
                iid = id(inc)
                if iid not in seen:
                    seen.add(iid)
                    matched.append(inc)

        state = DeviceState(
            natural_id=nid or None,
            ip=ip or None,
            label=label,
            channel=d.get("channel", "fortisiem"),
        )

        if not matched:
            # 没匹配到任何事件 —— 但这不等于"正常"，等于"不知道"
            state.severity = "unknown"
            out.append(state.to_dict())
            continue

        # 只看活跃（未解决）的事件
        active = [
            i for i in matched
            if i.get("incident_status") is None or int(i.get("incident_status", 0)) in ACTIVE_STATUSES
        ]
        if not active:
            # 有历史事件但都已关闭 → 回到正常
            state.severity = "normal"
            latest = max(matched, key=lambda i: (i.get("occurred_at") or "", i.get("id") or 0))
            state.last_event_at = latest.get("occurred_at")
            state.active_incidents = 0
            out.append(state.to_dict())
            continue

        top = max(active, key=lambda i: (_severity_rank(i.get("severity")), i.get("occurred_at") or ""))
        state.severity = top.get("severity") or "medium"
        state.active_incidents = len(active)
        state.top_title = top.get("title")
        latest = max(active, key=lambda i: (i.get("occurred_at") or "", i.get("id") or 0))
        state.last_event_at = latest.get("occurred_at")
        out.append(state.to_dict())

    return out


def severity_counts(states: list[dict[str, Any]]) -> dict[str, int]:
    counts = {k: 0 for k in SEVERITY_ORDER}
    counts["unknown"] = 0
    for s in states:
        sev = s.get("severity", "unknown")
        counts[sev] = counts.get(sev, 0) + 1
    return counts
