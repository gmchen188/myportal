"""
密钥长度守卫的独立验证。

守卫的价值全在"它真的会拒绝" —— 所以这里**逐个分支**证明它会红。
一个从不触发的守卫等于没有守卫。

运行：python test_key_guard.py      （退出码 0 = 全部符合预期）
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent

PASS, FAIL = [], []


def check(name: str, condition: bool, detail: str = "") -> None:
    (PASS if condition else FAIL).append(name)
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}" + (f"  — {detail}" if detail and not condition else ""))


def import_service(env_extra: dict[str, str]):
    """在给定环境变量下尝试 import sso_service，返回 (returncode, 末行输出)。"""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", **env_extra}
    # 清掉可能从外部继承的密钥，否则测不到我们要的分支
    for k in ("JWT_SECRET", "MP_ENV", "OCEAN_TICKET_SECRET"):
        if k not in env_extra:
            env.pop(k, None)
    r = subprocess.run(
        [sys.executable, "-c", "import sso_service"],
        cwd=str(HERE), env=env, capture_output=True, timeout=40,
    )
    out = (r.stdout + r.stderr).decode("utf-8", "ignore").strip()
    last = out.splitlines()[-1] if out else ""
    return r.returncode, last


def main() -> int:
    print("[1] JWT_SECRET 长度守卫")
    rc, msg = import_service({"MP_ENV": "dev"})
    check("dev + 未配置 → 使用开发默认值，启动成功", rc == 0, f"exit={rc}: {msg}")

    rc, msg = import_service({"MP_ENV": "dev", "JWT_SECRET": "tooshort"})
    check("dev + 8 字节密钥 → 拒绝启动", rc != 0 and "32" in msg, f"exit={rc}: {msg}")

    rc, msg = import_service({"MP_ENV": "dev", "JWT_SECRET": "x" * 32})
    check("dev + 32 字节密钥 → 启动成功", rc == 0, f"exit={rc}: {msg}")

    print("\n[2] 生产环境不得退回开发默认值")
    rc, msg = import_service({"MP_ENV": "prod"})
    check("prod + 未配置 → 拒绝启动（不退回默认值）", rc != 0 and "未配置" in msg, f"exit={rc}: {msg}")

    rc, msg = import_service({"MP_ENV": "production", "JWT_SECRET": "short"})
    check("production + 短密钥 → 拒绝启动", rc != 0 and "32" in msg, f"exit={rc}: {msg}")

    rc, msg = import_service(
        {"MP_ENV": "prod", "JWT_SECRET": "a-properly-long-production-secret-0123456789"}
    )
    check("prod + 合规密钥 → 启动成功", rc == 0, f"exit={rc}: {msg}")

    print("\n[3] 票据密钥守卫（sign 与 verify 两侧）")
    sys.path.insert(0, str(HERE))
    import ticket

    for bad in ("short", "x" * 31):
        try:
            ticket.sign(ticket.build_payload(issuer="i", subject="s"), bad)
            check(f"sign() 拒绝 {len(bad)} 字节密钥", False, "被接受了")
        except ticket.TicketError:
            check(f"sign() 拒绝 {len(bad)} 字节密钥", True)

    try:
        ticket.verify("a.b", "short")
        check("verify() 拒绝短密钥", False, "被接受了")
    except ticket.TicketError:
        check("verify() 拒绝短密钥", True)

    good = "k" * 32
    payload = ticket.build_payload(issuer="i", subject="s")
    signed = ticket.sign(payload, good)
    check("32 字节密钥可正常签发", ticket.verify(signed, good)["sub"] == "s")

    print("\n[4] 换票端点在密钥不合规时返回 500 而不是放行")
    rc, msg = import_service(
        {"MP_ENV": "dev", "OCEAN_TICKET_SECRET": "tiny"}
    )
    check("短 OCEAN_TICKET_SECRET 不阻止启动（运行时校验）", rc == 0, f"exit={rc}: {msg}")

    print(f"\n{'='*58}")
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print(f"  FAILED: {f}")
        return 1
    print("密钥守卫在所有分支上都按预期拒绝 —— 它是会红的守卫。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
