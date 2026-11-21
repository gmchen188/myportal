"""
syslog UDP 接收器 —— 让非 Fortinet 设备直接发事件到 myPortal。

## 为什么需要它

不是所有网络设备都能接进 FortiSIEM：

  · 工控交换机、PLC、RTU 通常只发 syslog，没有 SIEM collector 配置的余地
  · 很多 OT 网段**不允许出站**到 SOC（安全分区要求），但允许发到同区的
    采集器 —— myPortal 部署在 OT 侧就能收
  · 老设备只支持 SNMP Trap

所以 myPortal 自己起一个 UDP 监听，把收到的 syslog 落到 `incidents` 表，
与 FortiSIEM 同步来的事件**同一张表、同一套归集与配色逻辑**。

## 用法

    python -m app.services.syslog_collector --port 514 --tenant asi

设备侧把 syslog 指向这台机器：

    SW-CORE-01(config)# logging host 10.0.0.5 514
    SW-CORE-01(config)# logging trap informational
    SW-CORE-01(config)# logging facility local7

## 端口 514 需要 root

Linux/macOS 上 514 是特权端口。非特权用户用 1514，然后转发：

    iptables -A PREROUTING -p udp --dport 514 -j REDIRECT --to-port 1514

Windows 上 514 通常可以直接绑（除非被别的服务占了）。

## 租户怎么定

监听器绑一个租户（命令行参数）。生产环境应该按源 IP 段分租户 ——
多租户下不能让一台交换机的事件落到别的租户去。`--tenant-map` 可以给
「源 IP 前缀 → 租户」的映射；没匹配到的按默认租户，并记一条审计。
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import logging
import re
import socket
import sys
import threading
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from ..db import Incident, SessionLocal
from ..services.monitoring import normalize_severity

log = logging.getLogger("myportal.syslog")

# RFC3164: <PRI>TIMESTAMP HOSTNAME TAG: CONTENT
SYSLOG_RE = re.compile(
    r"^<(?P<pri>\d{1,3})>(?P<ts>\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+"
    r"(?P<host>\S+)\s+(?P<tag>[^:]*):\s*(?P<msg>.*)$",
    re.S,
)
# RFC5424: <PRI>1 TIMESTAMP HOST APP PROCID MSGID [SD] MSG
SYSLOG5424_RE = re.compile(
    r"^<(?P<pri>\d{1,3})>1\s+(?P<ts>\S+)\s+(?P<host>\S+)\s+(?P<app>\S+)\s+"
    r"(?P<procid>\S+)\s+(?P<msgid>\S+)\s*(?P<sd>-|\[.*\])\s*(?P<msg>.*)$",
    re.S,
)

IP_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")


def parse_line(text: str) -> dict[str, Any]:
    """解析一行 syslog，抽出 host / tag / msg / ip / severity。"""
    out: dict[str, Any] = {
        "host": "", "tag": "", "app": "", "msg": text.strip(), "ip": None, "severity": "medium",
    }
    m = SYSLOG5424_RE.match(text) or SYSLOG_RE.match(text)
    if m:
        g = m.groupdict()
        out["host"] = (g.get("host") or "").strip()
        out["tag"] = (g.get("tag") or g.get("app") or "").strip()
        out["msg"] = (g.get("msg") or "").strip()
        if g.get("app"):
            out["app"] = g["app"]

    ipm = IP_RE.search(out["msg"])
    if ipm:
        out["ip"] = ipm.group(1)

    low = out["msg"].lower()
    if re.search(r"\b(critical|crit|fatal|emerg\w*|panic|严重|紧急)\b", low):
        out["severity"] = "critical"
    elif re.search(r"\b(high|高危)\b", low):
        out["severity"] = "high"
    elif re.search(r"\b(low|低危)\b", low):
        out["severity"] = "low"
    elif re.search(r"\b(info\w*|notice|提示)\b", low):
        out["severity"] = "informational"
    else:
        out["severity"] = normalize_severity(out["severity"])
    return out


def store_event(parsed: dict[str, Any], tenant_id: str, source: str = "syslog") -> int | None:
    """落库。返回事件 id。"""
    with SessionLocal() as db:
        inc = Incident(
            tenant_id=tenant_id,
            title=(parsed["msg"][:200] or parsed["tag"] or "syslog"),
            severity=parsed["severity"],
            source=source,
            device_name=parsed["host"] or None,
            device_ip=parsed["ip"],
            raw=parsed,
            occurred_at=datetime.now(timezone.utc),
        )
        db.add(inc)
        db.commit()
        return inc.id


class Collector:
    """UDP syslog 接收器。"""

    def __init__(self, port: int = 1514, tenant_id: str = "t-asi",
                 bind: str = "0.0.0.0", tenant_map: dict[str, str] | None = None):
        self.port = port
        self.tenant_id = tenant_id
        self.bind = bind
        # "10.1." → "t-dongfang"，按源 IP 前缀分租户
        self.tenant_map = tenant_map or {}
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((bind, port))
        self.count = 0

    def _tenant_for(self, src_ip: str) -> str:
        if not src_ip:
            return self.tenant_id
        try:
            addr = ipaddress.ip_address(src_ip)
        except ValueError:
            return self.tenant_id
        for prefix, tid in self.tenant_map.items():
            try:
                net = ipaddress.ip_network(prefix, strict=False)
            except ValueError:
                continue
            if addr in net:
                return tid
        return self.tenant_id

    def serve_forever(self) -> None:
        log.info("syslog collector listening on %s:%d (tenant %s)", self.bind, self.port, self.tenant_id)
        while True:
            data, addr = self.sock.recvfrom(65535)
            try:
                text = data.decode("utf-8", errors="replace")
            except Exception:
                continue
            for line in text.splitlines():
                if not line.strip():
                    continue
                parsed = parse_line(line)
                # 源 IP 优先用于分租户；解析出的 IP 用于设备归集
                src_ip = addr[0]
                tid = self._tenant_for(src_ip)
                try:
                    eid = store_event(parsed, tid)
                    self.count += 1
                    log.info("[%s] %s %s → %s", tid, parsed["host"], parsed["severity"], eid)
                except Exception as e:
                    log.error("落库失败：%s", e)

    def close(self) -> None:
        self.sock.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="myPortal syslog collector")
    ap.add_argument("--port", type=int, default=1514)
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--tenant", default="t-asi", help="默认租户 id")
    ap.add_argument("--tenant-map", default="", help='JSON: {"10.1.":"t-dongfang"}')
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    tmap = json.loads(args.tenant_map) if args.tenant_map else {}
    c = Collector(port=args.port, tenant_id=args.tenant, bind=args.bind, tenant_map=tmap)
    try:
        c.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
