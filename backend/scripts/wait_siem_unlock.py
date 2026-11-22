#!/usr/bin/env python
"""轮询 FortiSIEM admin 账号的锁定状态，解锁后做**一次**正确凭据验证。

为什么需要这个脚本
------------------
探测 Basic Auth 时如果连续试错，FortiSIEM 会在 5 次失败后锁定账号
（Hardening Guide: "A GUI user is locked out if the user fails 5 consecutive logins"）。
锁定期间所有 Basic 请求都返回：

    HTTP 403 - Account locked due to consecutive login failures.

**这个 403 不是权限问题** —— 跟 "User is not authorized" 是两回事。

## 实测补充（2026-11-22，本机 172.16.20.48）

- **锁定期实测超过 44 分钟**（文档默认 15 分钟）—— 这台机器的锁定期被改过。
  所以默认探测间隔是 **300 秒**：高频探测有「自己给自己续锁」的风险
  （万一锁定期间也计数）。
- **锁定是账号级的**：GUI 登录（`/phoenix/rest/h5/sec/login`）**也**返回
  `Account locked due to consecutive login failures.`，与 Basic Auth 共享状态。
  GUI 与 API 是两套认证路径，但锁定状态是同一个账号级的。
- 锁定事件会被 **SIEM 自己记成 incident**：
  `eventType=PH_RULE_ACCOUNT_LOCKOUT_SYSTEM`、`incidentTagName=Brute Force Logon`、
  `incidentTarget=user:admin`。用它可以确认锁定起点时间戳：

      POST /phoenix/rest/pub/incident  (Bearer token, OAuth)
      → data[].incidentFirstSeen = 锁定发生的毫秒时间戳

- 管理端点（用户/角色/解锁）**全在 404** —— OAuth 与 Basic 都够不到，
  解锁只能等锁定期自动过期。

用法：
    cd backend
    python scripts/wait_siem_unlock.py [--max-minutes 120] [--interval 300]
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

import httpx


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    env_path = Path(__file__).resolve().parents[1] / ".env"
    for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def probe(env: dict[str, str]) -> tuple[str, str]:
    """返回 (状态, 说明)。状态 ∈ locked / ok / wrong。

    ## 用**正确口令**探测 —— 这是安全的

    FortiSIEM 的锁定判定在**口令比对之前**：

    - 账号锁定中 → 任何口令都返回 403 locked，**不比对口令、不累积失败**
    - 账号已解锁 → 口令对则 200，口令错则 401（**累积 1 次失败**）

    所以拿正确口令探测：锁定时反复探都无害；解锁后要么成功、
    要么只累积一次失败（离再锁还差 4 次）。

    ## 为什么不用「不存在的用户名」探

    **测不出来** —— 不存在的用户名跟 admin 的锁定状态无关，
    它永远返回 401，看起来像「已解锁」，实际 admin 还锁着。
    我第一版就是这么写的，结果脚本报告「已解锁」，
    但用 admin 试还是 locked —— **两套探测逻辑互相矛盾**。

    唯一可靠的办法就是**拿 admin 自己的凭据去探**。
    """
    base = env["FORTISIEM_BASE_URL"].rstrip("/")
    user = env.get("FORTISIEM_BASIC_USER", "admin")
    password = env["FORTISIEM_BASIC_PASSWORD"]
    org = env.get("FORTISIEM_ORG", "Super")

    with httpx.Client(verify=False, timeout=20, trust_env=False) as client:
        r = client.post(
            f"{base}/phoenix/rest/pub/device",
            auth=(f"{org}/{user}", password),
            content=b"",
        )
        text = re.sub(r"<[^>]+>", " ", r.text or "")
        text = re.sub(r"\s+", " ", text).strip()
        if "locked" in text.lower():
            return "locked", "账号锁定中（不比对口令，不累积失败）"
        if r.status_code == 200:
            try:
                n = len(r.json().get("data", []))
            except Exception:
                n = -1
            return "ok", f"已解锁且认证通过，设备数={n}"
        if r.status_code == 401:
            return "wrong", f"已解锁但认证被拒（401）：{text[:110]}"
        return str(r.status_code), text[:140]


def verify(env: dict[str, str]) -> tuple[str, str]:
    """**用一次**正确凭据验证 —— 解锁后才调。

    返回 (状态, 说明)。状态 ∈ ok / wrong / locked。
    """
    base = env["FORTISIEM_BASE_URL"].rstrip("/")
    user = env.get("FORTISIEM_BASIC_USER", "admin")
    password = env["FORTISIEM_BASIC_PASSWORD"]
    org = env.get("FORTISIEM_ORG", "Super")

    with httpx.Client(verify=False, timeout=20, trust_env=False) as client:
        r = client.post(
            f"{base}/phoenix/rest/pub/device",
            auth=(f"{org}/{user}", password),
            content=b"",
        )
        text = re.sub(r"<[^>]+>", " ", r.text or "")
        text = re.sub(r"\s+", " ", text).strip()
        if r.status_code == 200:
            try:
                n = len(r.json().get("data", []))
            except Exception:
                n = -1
            return "ok", f"认证通过，设备数={n}"
        if "locked" in text.lower():
            return "locked", "仍锁定（锁定期间不比对口令，不累积失败）"
        return "wrong", f"HTTP {r.status_code}: {text[:140]}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-minutes", type=int, default=120)
    # **默认 300 秒（5 分钟）** —— 锁定实测已超 44 分钟（这台机器的锁定期被改过，
    # 文档默认是 15 分钟）。高频探测有「自己给自己续锁」的风险：
    # 万一锁定期间也计数，高频就是自续锁。
    ap.add_argument("--interval", type=int, default=300)
    args = ap.parse_args()

    env = load_env()
    deadline = time.time() + args.max_minutes * 60
    started = time.time()

    print(f"轮询 FortiSIEM 账号锁定状态（最多 {args.max_minutes} 分钟）", flush=True)
    print("探测用 admin 自己的凭据 —— 锁定时任何口令都不累积失败", flush=True)

    while time.time() < deadline:
        state, detail = probe(env)
        elapsed = int(time.time() - started)
        print(f"  [{elapsed:>4}s] {state:14} {detail}", flush=True)
        if state == "ok":
            print("\n✓ 已解锁且认证通过。下一步可以验证 CMDB 写端点。")
            return 0
        if state == "wrong":
            # **立刻停** —— 再探 4 次就又锁 15 分钟
            print(
                "\n✗ 账号已解锁但认证被拒 —— 口令不对。",
                "\n  **已停止探测**：再试 4 次就会重新锁上。",
                "\n  请确认口令后手动改 backend/.env 的 FORTISIEM_BASIC_PASSWORD。",
                file=sys.stderr,
            )
            return 1
        time.sleep(args.interval)

    print(f"\n✗ {args.max_minutes} 分钟内未解锁", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
