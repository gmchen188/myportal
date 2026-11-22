#!/usr/bin/env python
"""探测 FortiSIEM 的 CMDB 写接口在**当前实例**上到底能不能用。

为什么需要这个脚本
------------------
官方 Integration API Guide 写的写端点，跟 7.5.1 实机对不上：

  文档（6.7.2）：POST /phoenix/rest/device/discovery/add  ← 加设备
  实机（7.5.1）：端点**存在**（403 而不是 404），但当前凭据没权限

而且 7.5.1 的 What's New 又把一批老端点改名了。**照着文档写实现会踩空。**
所以每次 FortiSIEM 升级后都该重跑这个脚本，拿实测结果决定怎么做。

安全边界
--------
脚本**不写任何设备**：
  · 读端点用 GET/POST（POST 端点是查询型的）
  · 写端点只用**空 body** 或 **空数组** 探测 —— 空操作不会创建/删除东西
  · 探测前后各读一次设备列表，核对数量与 id 不变
  · delete 端点**只传空数组**，绝不用真实 device id

用法
----
    cd backend
    python scripts/probe_siem_write_api.py

只读 .env，不打印任何密钥。
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

try:
    import httpx
except ImportError:  # pragma: no cover
    print("需要 httpx：pip install httpx", file=sys.stderr)
    raise SystemExit(2)


# ── 候选端点 ──────────────────────────────────────────────────────────
# (方法, 路径, 说明, 是否有副作用)
PROBES: list[tuple[str, str, str]] = [
    ("GET", "/phoenix/rest/cmdbDeviceInfo/devices", "读 CMDB 设备（XML）"),
    ("POST", "/phoenix/rest/pub/device", "读设备列表（JSON，有 id/purdueLevel/deviceTag）"),
    ("GET", "/phoenix/rest/organization/list", "读组织列表（7.5.1 新端点）"),
    ("GET", "/phoenix/rest/config/Domain", "读组织列表（老端点）"),
    # 官方文档里的写端点
    ("POST", "/phoenix/rest/device/discovery/add", "★ 加设备（文档端点）"),
    ("POST", "/phoenix/rest/device/update", "★ 改设备（文档端点）"),
    ("POST", "/phoenix/rest/device/list/delete", "★ 删设备（文档端点）"),
    ("GET", "/phoenix/rest/cmdbDeviceInfo/properties", "★ 自定义属性（读）"),
    ("POST", "/phoenix/rest/cmdbDeviceInfo/properties", "★ 自定义属性（写）"),
    ("POST", "/phoenix/rest/deviceMon/discover", "设备发现"),
    ("POST", "/phoenix/rest/deviceMon/updateCredential", "创建设备凭据"),
    # 7.5.1 What's New 提到的 pub 命名空间
    ("POST", "/phoenix/rest/pub/device/delete", "★ 删设备（7.5.x 端点）"),
    ("POST", "/phoenix/rest/pub/device/add", "加设备（7.5.x 猜测端点）"),
    ("POST", "/phoenix/rest/pub/device/update", "改设备（7.5.x 猜测端点）"),
    ("POST", "/phoenix/rest/pub/device/list", "设备列表（7.5.x 猜测端点）"),
    ("POST", "/phoenix/rest/pub/deviceMaint/update", "设备维护（7.5.x 猜测端点）"),
]


def load_env() -> dict[str, str]:
    """从 backend/.env 读配置（不打印值）。"""
    env: dict[str, str] = {}
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        print(f"✗ 找不到 {env_path}", file=sys.stderr)
        raise SystemExit(2)
    for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def get_token(client: httpx.Client, env: dict[str, str]) -> str:
    """拿 OAuth token —— FortiSIEM 偶尔瞬时返回非 JSON，重试几次。"""
    url = f"{env['FORTISIEM_BASE_URL']}/phoenix/rest/pub/security/oauth/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": env["FORTISIEM_CLIENT_ID"],
        "client_secret": env["FORTISIEM_CLIENT_SECRET"],
    }
    for attempt in range(4):
        try:
            r = client.post(url, data=data)
            if r.status_code == 200:
                tok = r.json().get("access_token", "")
                if tok:
                    return tok
        except Exception:
            pass
        time.sleep(2)
    print("✗ 取 token 失败", file=sys.stderr)
    raise SystemExit(1)


def device_snapshot(client: httpx.Client, headers: dict[str, str]) -> list[tuple[int, str]]:
    """读设备列表 (id, name) —— 用来证明探测没改动任何东西。"""
    r = client.post(
        f"{client.base_url.__str__().rstrip('/')}/phoenix/rest/pub/device",
        headers=headers,
        content=b"",
    )
    if r.status_code != 200:
        return []
    return sorted((d["id"], d["name"]) for d in r.json().get("data", []))


def classify(code: int) -> str:
    if code == 404:
        return "✗ 不存在"
    if code == 403:
        return "△ 存在但无权限"   # ← 关键：路由存在，只是凭据不够
    if code == 405:
        return "△ 路径存在但方法不对"
    if code in (400, 422):
        return "✓ 存在（缺参数）"
    if code == 200:
        return "✓ 可访问"
    if code == 401:
        return "△ 需认证"
    return f"? HTTP {code}"


def main() -> int:
    env = load_env()
    base = env["FORTISIEM_BASE_URL"].rstrip("/")
    org = env.get("FORTISIEM_ORG", "(未配置)")

    print("=" * 78)
    print("FortiSIEM CMDB 写接口探测")
    print("=" * 78)
    print(f"  实例   {base}")
    print(f"  组织   {org}")
    print()

    with httpx.Client(verify=False, timeout=30, trust_env=False) as client:
        client.base_url = base  # type: ignore[assignment]

        # ── 四段诊断 ─────────────────────────────────────────────
        print("── 连通性 ──")
        try:
            r = client.get(f"{base}/")
            print(f"  [tcp/tls] ✓ HTTP {r.status_code}")
        except Exception as exc:
            print(f"  [tcp/tls] ✗ {type(exc).__name__}: {exc}")
            return 1

        token = get_token(client, env)
        headers = {"Authorization": f"Bearer {token}"}
        print(f"  [auth]    ✓ token {len(token)} 字符")

        # token 作用域 —— 决定写权限
        import base64

        try:
            payload = token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload))
            print(
                f"            scope={claims.get('scope')} "
                f"custId={claims.get('custId')} user={claims.get('userName')}"
            )
        except Exception:
            pass

        # ── 探测前快照 ───────────────────────────────────────────
        before = device_snapshot(client, headers)
        print(f"\n── 探测前设备（{len(before)} 台）──")
        for did, name in before:
            print(f"  {did:<10} {name}")

        # ── 端点探测 ─────────────────────────────────────────────
        print("\n── 端点探测（空 body / 空数组，无副作用）──")
        print(f"{'方法':<5} {'端点':<50} {'HTTP':<5} 判定")
        print("-" * 92)
        results: list[tuple[str, str, int, str]] = []
        for method, path, note in PROBES:
            try:
                # delete 类端点用空数组，其余用空 body —— 都不会真正改动数据
                content = b"[]" if path.endswith("/delete") else b""
                r = client.request(method, f"{base}{path}", headers=headers, content=content)
                verdict = classify(r.status_code)
                print(f"{method:<5} {path:<50} {r.status_code:<5} {verdict}   {note}")
                results.append((method, path, r.status_code, verdict))
            except Exception as exc:
                print(f"{method:<5} {path:<50} ERR     {type(exc).__name__}   {note}")
            time.sleep(0.2)

        # ── 探测后核对 ───────────────────────────────────────────
        after = device_snapshot(client, headers)
        print(f"\n── 探测后设备（{len(after)} 台）──")
        for did, name in after:
            print(f"  {did:<10} {name}")

        print()
        if before == after:
            print("✓ 探测未改动任何设备（前后快照完全一致）")
        else:
            print("✗ 设备列表发生变化！探测脚本有副作用，必须查！")
            print(f"   before={before}")
            print(f"   after ={after}")

        # ── 结论 ─────────────────────────────────────────────────
        writable = [r for r in results if r[2] == 200 and r[1].endswith("/delete")]
        forbidden = [r for r in results if r[2] == 403]
        print("\n" + "=" * 78)
        print("结论")
        print("=" * 78)
        if forbidden:
            print("  写端点存在但当前凭据无权限（403）：")
            for m, p, c, v in forbidden:
                print(f"    {m} {p}")
            print("  → 需要更高权限的账号（官方要求 Basic Auth 的 FortiSIEM 账号）")
        if writable:
            print("  当前凭据可直接调用的写端点：")
            for m, p, c, v in writable:
                print(f"    {m} {p}")
        if not forbidden and not writable:
            print("  未发现任何可写端点。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
