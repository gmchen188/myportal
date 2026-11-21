"""密码哈希。

**绝不明文存密码** —— 这是底线。数据库被拖库时，明文密码等于把
所有用户的账号一起送出去。

## 为什么用 bcrypt

- 专门为密码设计（慢、故意耗资源），暴力破解成本高
- 自带盐 —— 同一个密码每个用户的哈希都不同
- 标准库之外但极稳定，Python 3.14 上照常工作

## bcrypt 的 72 字节限制

bcrypt **只取前 72 字节**做哈希，更长的部分静默丢弃 —— 这意味着
`"A"*100` 和 `"A"*72` 的哈希是一样的。**必须自己处理**，
不能装作不知道。

做法：先算 SHA-256，把结果交给 bcrypt。这样
- 没有 72 字节截断问题
- 长密码的不同部分不会被丢掉
- SHA-256 不可逆，不会降低 bcrypt 的强度（它只做一次）

## 什么时候不用 bcrypt

`verify_password` 用**恒定时间比较** —— 直接 `==` 比较会在比较到
第一个不同字符时返回，攻击者能靠响应时间差一个字节一个字节地猜。
`hmac.compare_digest` 不管内容是否相同，耗时都一样。
"""

from __future__ import annotations

import base64
import os
import hashlib
import hmac

import bcrypt

# bcrypt 的计算强度。默认 12 —— 约 100ms 一次，
# 让暴力破解的吞吐量降到每秒几次。
#
# **测试环境可以调低**，否则 CI 光跑哈希就要两分多钟。
# 生产环境不要设这个变量 —— 调低强度等于削弱防护。
_ROUNDS = int(os.getenv("MP_BCRYPT_ROUNDS", "12"))


def _prepare(password: str) -> bytes:
    """把任意长度的密码变成 bcrypt 能安全接受的输入。

    先 SHA-256 摘要再交给 bcrypt —— 消除 72 字节截断问题，
    且 SHA-256 不可逆，不会削弱 bcrypt。

    再 base64 一遍 —— 让输入字节分布均匀（bcrypt 的 EKS 扩展对
    特定字节分布有可测的弱点），同时保证是 ASCII。
    """
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest)


def hash_password(password: str) -> str:
    """算密码哈希，返回可直接存库的字符串。"""
    if not password:
        raise ValueError("密码不能为空")
    return bcrypt.hashpw(_prepare(password), bcrypt.gensalt(rounds=_ROUNDS)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """校验密码。

    **恒定时间比较** —— 用 `hmac.compare_digest`，不用 `==`。
    哈希格式不对（数据库被改坏、或者传进来的是明文）也要返回
    False 而不是抛异常 —— 校验失败就是校验失败。
    """
    if not password or not password_hash:
        return False
    try:
        computed = bcrypt.hashpw(_prepare(password), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        # 哈希串不是合法 bcrypt 格式
        return False
    return hmac.compare_digest(computed, password_hash.encode("ascii"))


def password_problems(password: str) -> list[str]:
    """检查密码强度，返回问题清单（空列表 = 通过）。

    **不返回密码本身**，也不记录它 —— 强度检查不该把明文再过一遍手。
    """
    problems: list[str] = []
    if not password:
        return ["密码不能为空"]
    if len(password) < 10:
        problems.append("密码至少 10 位")
    if len(password) > 200:
        problems.append("密码过长（最多 200 位）")
    kinds = 0
    if any(c.islower() for c in password):
        kinds += 1
    if any(c.isupper() for c in password):
        kinds += 1
    if any(c.isdigit() for c in password):
        kinds += 1
    if any(not c.isalnum() for c in password):
        kinds += 1
    if kinds < 3:
        problems.append("密码要包含大写、小写、数字、符号中的至少 3 类")
    return problems
