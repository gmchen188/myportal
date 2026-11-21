"""
票据编解码 —— 一次性票据（launch ticket）的签发与校验。

参考实现。oceansite 侧如果是 PHP / Java / .NET，请按本文件的规则重写一份，
或者反过来：**只有 oceansite 能签发、只有 myPortal 能校验**。

为什么单独抽一个文件：
票据是两条系统之间唯一的信任凭据，规则必须只有一份、两边一致。
任何一边"顺手改一下"都会让票据变成可伪造的东西。

规则
----
1. 载荷是 JSON，键固定，UTF-8，无空格。
2. 签名是 HMAC-SHA256，密钥按 issuer 分别持有。
3. 签名覆盖的是 base64url(payload) 的原始字节，不覆盖 base64 字符串本身
   —— 避免"同载荷不同编码"这类歧义。
4. 载荷里必须有 jti（一次性标识）与 exp（绝对过期时间戳）。
5. 载荷断言的是 **身份**，不是 **授权**。
   票据里说"我是谁"，不说"我能看哪个租户"。
   租户由 myPortal 自己的映射表决定 —— 见 bridge.provision_or_map()。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

# 票据有效期上限（秒）。签发方不得签发更长的 —— 校验侧也会硬性拒绝。
MAX_TTL_SECONDS = 60

REQUIRED_CLAIMS = ("iss", "sub", "iat", "exp", "jti")


def _b64u(raw: bytes) -> str:
    """base64url 且去掉填充 —— 放进 URL / query 不会被转义器再改一遍。"""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64u_decode(value: str) -> bytes:
    pad = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + pad)


# HMAC-SHA256 的密钥至少 256 位（32 字节）。短密钥可被离线暴力还原，
# 票据即等同明文 —— 所以签名与校验两侧都要拒绝短密钥。
MIN_SECRET_BYTES = 32


def _require_strong_secret(secret: str) -> None:
    if not secret:
        raise TicketError("签名密钥为空")
    if len(secret.encode("utf-8")) < MIN_SECRET_BYTES:
        raise TicketError(
            f"签名密钥长度 {len(secret.encode('utf-8'))} 字节，低于 HMAC-SHA256 要求的 "
            f"{MIN_SECRET_BYTES} 字节"
        )


def sign(payload: dict[str, Any], secret: str) -> str:
    """签发票据。payload 里必须已经带上 iat / exp / jti。"""
    _require_strong_secret(secret)
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    raw = body.encode("utf-8")
    mac = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).digest()
    return f"{_b64u(raw)}.{_b64u(mac)}"


def verify(ticket: str, secret: str, *, now: float | None = None) -> dict[str, Any]:
    """校验票据。失败一律抛 TicketError，不返回 None —— 调用方不该有机会忽略失败。"""
    _require_strong_secret(secret)
    if not ticket or "." not in ticket:
        raise TicketError("票据格式不正确")
    body_b64, mac_b64 = ticket.split(".", 1)
    try:
        raw = _b64u_decode(body_b64)
        mac = _b64u_decode(mac_b64)
    except Exception as exc:  # noqa: BLE001
        raise TicketError("票据编码损坏") from exc

    expected = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).digest()
    # 常数时间比较：早返回的长度会让攻击者逐字节试探
    if not hmac.compare_digest(mac, expected):
        raise TicketError("票据签名不匹配")

    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise TicketError("票据载荷不是合法 JSON") from exc
    if not isinstance(payload, dict):
        raise TicketError("票据载荷不是对象")

    for claim in REQUIRED_CLAIMS:
        if claim not in payload:
            raise TicketError(f"票据缺少必需声明 {claim}")

    ts = now if now is not None else time.time()
    try:
        iat = float(payload["iat"])
        exp = float(payload["exp"])
    except (TypeError, ValueError) as exc:
        raise TicketError("票据时间声明不是数字") from exc

    if exp <= ts:
        raise TicketError("票据已过期")
    if iat > ts + 60:
        raise TicketError("票据签发时间在未来")
    if exp - iat > MAX_TTL_SECONDS:
        raise TicketError(f"票据有效期超过 {MAX_TTL_SECONDS} 秒上限")

    return payload


class TicketError(Exception):
    """票据无效。所有原因都归到这里 —— 不要把细节透给终端用户。"""


def build_payload(
    *,
    issuer: str,
    subject: str,
    display_name: str = "",
    email: str = "",
    customer_code: str = "",
    ttl_seconds: int = 30,
    now: float | None = None,
) -> dict[str, Any]:
    """构造载荷。签发方用这个函数，别手搓字典。"""
    if ttl_seconds <= 0 or ttl_seconds > MAX_TTL_SECONDS:
        raise ValueError(f"ttl_seconds 必须在 1..{MAX_TTL_SECONDS} 之间")
    ts = now if now is not None else time.time()
    import secrets as _secrets

    return {
        "iss": issuer,
        "sub": subject,
        "name": display_name,
        "email": email,
        "cust": customer_code,
        "iat": int(ts),
        "exp": int(ts + ttl_seconds),
        "jti": _secrets.token_urlsafe(16),
    }
