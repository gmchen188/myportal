"""
免密对接的端到端验证 —— 证明"用户只登录一次"真的成立。

不靠肉眼。每一项都是断言，改坏了就会红。

运行：python verify_sso.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

HERE = Path(__file__).parent
OCEAN = os.getenv("OCEAN_BASE_URL", "http://127.0.0.1:9101")
PORTAL = os.getenv("MYPORTAL_BASE_URL", "http://127.0.0.1:9102")

PASS, FAIL = [], []


def check(name: str, condition: bool, detail: str = "") -> None:
    (PASS if condition else FAIL).append(name)
    mark = "PASS" if condition else "FAIL"
    print(f"  [{mark}] {name}" + (f"  — {detail}" if detail and not condition else ""))


def wait_up(url: str, timeout: float = 25.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            httpx.get(url, timeout=2.0, trust_env=False).raise_for_status()
            return True
        except Exception:
            time.sleep(0.4)
    return False


def main() -> int:
    procs: list[subprocess.Popen] = []
    try:
        # ── 拉起两个服务 ──────────────────────────────────────────────────
        ticket_secret = "test-shared-secret-at-least-32-bytes-long"
        for script, port in (("mock_oceansite.py", 9101), ("sso_service.py", 9102)):
            # 票据密钥必须在子进程启动前就位 —— 运行中再设 os.environ 影响不到已启动的进程
            env = {
                **os.environ,
                "PYTHONIOENCODING": "utf-8",
                "OCEAN_TICKET_SECRET": ticket_secret,
            }
            procs.append(
                subprocess.Popen(
                    [sys.executable, str(HERE / script)],
                    cwd=str(HERE), env=env,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            )
        print("等待服务就绪 …")
        if not wait_up(f"{OCEAN}/health" if False else f"{OCEAN}/login"):
            print("oceansite 未就绪")
            return 2
        if not wait_up(f"{PORTAL}/health"):
            print("myPortal SSO 服务未就绪")
            return 2

        c = httpx.Client(timeout=10.0, follow_redirects=False, trust_env=False)

        # ── 1. 用户在 oceansite 登录 ─────────────────────────────────────
        print("\n[1] 用户在 oceansite 登录")
        r = c.post(f"{OCEAN}/login", data={"username": "captain", "password": "Ocean@2026"})
        check("oceansite 登录成功（302 跳首页）", r.status_code == 303, f"got {r.status_code}")
        ocean_cookie = r.cookies.get("OCSESSION")
        check("oceansite 下发会话 Cookie", bool(ocean_cookie), "no OCSESSION")
        home = c.get(f"{OCEAN}/")
        check("oceansite 首页可访问（会话有效）", home.status_code == 200, f"got {home.status_code}")
        check("首页含「网络安全模块」入口", "网络安全模块" in home.text)

        # ── 2. 点击「网络安全模块」跳转到 myPortal ────────────────────────
        print("\n[2] 点击「网络安全模块」进入 myPortal")
        r = c.post(f"{PORTAL}/api/sso/exchange")
        check("换票接口返回 200", r.status_code == 200, f"got {r.status_code}: {r.text[:120]}")
        if r.status_code != 200:
            print(json_dumps := r.text[:400])
            return 1
        data = r.json()
        check("返回 authenticated=true", data.get("authenticated") is True)
        check("返回 myPortal 访问令牌", bool(data.get("access_token")))
        check("身份来自 oceansite", data.get("source") == "oceansite", str(data.get("source")))
        check(
            "用户标识取自 oceansite",
            data.get("user", {}).get("external_id") == "OC-U-1001",
            str(data.get("user")),
        )
        tenant = data.get("tenant", {})
        check("解析出租户「东方海运」", "东方海运" in str(tenant.get("name")), str(tenant))
        check("租户绑定 FortiSIEM Organization", tenant.get("fortisiem_org") == "DONGFANG")
        check("角色按映射表给出（tenant_admin）", data.get("user", {}).get("role") == "tenant_admin")

        # 关键：响应里绝不能出现 oceansite 的 Cookie
        check("响应未泄露 oceansite 会话 Cookie", ocean_cookie not in r.text)

        # ── 3. 换票后 myPortal 会话独立可用 ──────────────────────────────
        print("\n[3] 换票后 myPortal 会话独立可用（不再需要 oceansite）")
        token = data["access_token"]
        s = c.get(f"{PORTAL}/api/session", headers={"Authorization": f"Bearer {token}"})
        check("会话端点返回已认证", s.status_code == 200 and s.json().get("authenticated") is True)
        check("会话端点回报租户 id", s.json().get("tenant", {}).get("id") == "t-dongfang")

        ts = c.get(f"{PORTAL}/api/tenant/summary", headers={"Authorization": f"Bearer {token}"})
        check("可用 myPortal 会话取租户统计", ts.status_code == 200, f"got {ts.status_code}")
        check(
            "统计属于映射后的租户",
            ts.status_code == 200 and ts.json().get("fortisiem_org") == "DONGFANG",
            ts.text[:120],
        )

        # ── 4. 负向用例 ──────────────────────────────────────────────────
        print("\n[4] 负向用例")

        c2 = httpx.Client(timeout=10.0, follow_redirects=False, trust_env=False)
        r = c2.post(f"{PORTAL}/api/sso/exchange")
        check("无 oceansite 会话 → 401", r.status_code == 401, f"got {r.status_code}")

        r = c2.post(
            f"{PORTAL}/api/sso/exchange",
            headers={"X-Ocean-Session": "totally-invalid-session-value"},
        )
        check("伪造/失效 Cookie → 401", r.status_code == 401, f"got {r.status_code}")

        c3 = httpx.Client(timeout=10.0, follow_redirects=False, trust_env=False)
        c3.post(f"{OCEAN}/login", data={"username": "outsider", "password": "Ocean@2026"})
        r = c3.post(f"{PORTAL}/api/sso/exchange")
        check("未映射身份 → 403（默认拒绝）", r.status_code == 403, f"got {r.status_code}")
        check("拒绝信息不泄露租户数据", "DONGFANG" not in r.text and "t-dongfang" not in r.text)

        c4 = httpx.Client(timeout=10.0, follow_redirects=False, trust_env=False)
        c4.post(f"{OCEAN}/login", data={"username": "viewer", "password": "Ocean@2026"})
        r = c4.post(f"{PORTAL}/api/sso/exchange")
        check("viewer 映射到 viewer 角色", r.status_code == 200 and r.json()["user"]["role"] == "viewer",
              r.text[:120])

        # 网关转发形态：Cookie 改由 X-Ocean-Session 头送达
        print("\n[4b] 网关转发形态（X-Ocean-Session 头）")
        c5 = httpx.Client(timeout=10.0, follow_redirects=False, trust_env=False)
        lr = c5.post(f"{OCEAN}/login", data={"username": "captain", "password": "Ocean@2026"})
        sid = lr.cookies.get("OCSESSION")
        r = httpx.post(
            f"{PORTAL}/api/sso/exchange",
            headers={"X-Ocean-Session": sid or ""},
            timeout=10.0, trust_env=False,
        )
        check("头转发形态可换票", r.status_code == 200, f"got {r.status_code}: {r.text[:120]}")
        if r.status_code == 200:
            check("头转发形态租户一致", r.json()["tenant"]["id"] == "t-dongfang")
        r = httpx.post(
            f"{PORTAL}/api/sso/exchange",
            headers={"X-Ocean-Session": "not-a-real-session"},
            timeout=10.0, trust_env=False,
        )
        check("头转发形态下伪造值 → 401", r.status_code == 401, f"got {r.status_code}")

        # 票据路径
        print("\n[5] 票据路径（oceansite 可改造时）")
        sys.path.insert(0, str(HERE))
        import ticket as ticket_mod

        secret = ticket_secret
        claims = ticket_mod.build_payload(
            issuer="oceansite", subject="OC-U-1001", display_name="陈船长",
            email="captain@dongfang.example", customer_code="DONGFANG", ttl_seconds=30,
        )
        signed = ticket_mod.sign(claims, secret)
        r = httpx.post(
            f"{PORTAL}/api/sso/exchange-ticket", json={"ticket": signed}, trust_env=False
        )
        check("有效票据可换票", r.status_code == 200, f"got {r.status_code}: {r.text[:120]}")
        if r.status_code == 200:
            check("票据身份映射到同一租户", r.json()["tenant"]["id"] == "t-dongfang")

        tampered = signed[:-4] + ("AAAA" if not signed.endswith("AAAA") else "BBBB")
        r = httpx.post(f"{PORTAL}/api/sso/exchange-ticket", json={"ticket": tampered}, trust_env=False)
        check("被篡改的票据 → 401", r.status_code == 401, f"got {r.status_code}")

        expired = ticket_mod.sign(
            ticket_mod.build_payload(
                issuer="oceansite", subject="OC-U-1001", ttl_seconds=30,
                now=time.time() - 120,
            ),
            secret,
        )
        r = httpx.post(f"{PORTAL}/api/sso/exchange-ticket", json={"ticket": expired}, trust_env=False)
        check("过期票据 → 401", r.status_code == 401, f"got {r.status_code}")

        # 短密钥必须被拒绝 —— 否则 HMAC 强度形同虚设
        try:
            ticket_mod.sign(claims, "short")
            check("短密钥被拒绝", False, "sign() 接受了短密钥")
        except ticket_mod.TicketError:
            check("短密钥被拒绝", True)

        wrong_key = ticket_mod.sign(claims, "a-different-secret-of-32-bytes-minimum!!")
        r = httpx.post(f"{PORTAL}/api/sso/exchange-ticket", json={"ticket": wrong_key}, trust_env=False)
        check("用别的密钥签的票据 → 401", r.status_code == 401, f"got {r.status_code}")

        # ── 6. 审计留痕 ──────────────────────────────────────────────────
        print("\n[6] 审计留痕")
        a = httpx.get(f"{PORTAL}/api/audit", timeout=10.0, trust_env=False).json()
        actions = [e["action"] for e in a["entries"]]
        check("记录了 sso_exchange", "auth.sso_exchange" in actions, str(actions))
        check("记录了被拒绝的票据", "auth.sso_ticket_rejected" in actions, str(actions))
        blob = str(a)
        check("审计未记录任何会话凭据", ocean_cookie not in blob and "totally-invalid" not in blob)

        # ── 7. 密钥长度守卫 ──────────────────────────────────────────────
        print("\n[7] 密钥长度守卫（启动即拒绝，不是运行时警告）")
        guard = HERE / "test_key_guard.py"
        if guard.exists():
            r = subprocess.run(
                [sys.executable, str(guard)], cwd=str(HERE),
                capture_output=True, timeout=60,
            )
            out = (r.stdout + r.stderr).decode("utf-8", "ignore")
            check("短密钥守卫测试通过", r.returncode == 0, out.strip()[-200:])
        else:
            check("短密钥守卫测试脚本存在", False, "test_key_guard.py 缺失")

        # ── 汇总 ─────────────────────────────────────────────────────────
        print(f"\n{'='*60}")
        print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
        if FAIL:
            for f in FAIL:
                print(f"  FAILED: {f}")
            return 1
        print("全部通过 —— 用户只登录一次，跳转 myPortal 不再需要输入凭据。")
        return 0
    finally:
        for p in procs:
            p.terminate()
        try:
            import time as _t

            _t.sleep(0.6)
            for p in procs:
                p.kill()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
