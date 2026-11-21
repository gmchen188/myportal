"""审计日志。

## 为什么需要

安全运营门户没有审计日志等于没有 accountability —— 出事了查不到人。
「谁把某个租户停了」「谁改了接入源配置」「谁删了资产」，
这些都必须能回答。

## 记什么、不记什么

**记**：管理动作 —— 建用户、改角色、停租户、改接入源、删资产、
触发 SIEM 同步。

**不记**：每次查询。全量记查询会把库撑爆，而且没人会去看。

这个取舍是刻意的：审计日志的价值在「动作」，不在「访问」。

## 写失败不能拖垮主流程

写审计是在业务事务之外做的。**审计写失败时业务必须照常成功** ——
审计是辅助记录，不是业务的一部分。反过来（业务失败但审计写了）
也要注意：所以调用点在业务成功之后。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..db import AuditLog


def record(
    db: Session,
    *,
    tenant_id: str,
    action: str,
    user_id: int | None = None,
    username: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    detail: dict[str, Any] | None = None,
    ip: str | None = None,
) -> AuditLog | None:
    """写一条审计记录。

    **返回 None 而不是抛异常** —— 调用方不该因为审计写不进去而失败。
    但也不该完全静默：写 stderr 让人知道出了问题。
    """
    try:
        entry = AuditLog(
            tenant_id=tenant_id,
            user_id=user_id,
            username=username,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail or {},
            ip=ip,
        )
        db.add(entry)
        db.commit()
        return entry
    except Exception as exc:  # pragma: no cover - 审计不该拖垮业务
        import sys

        print(f"[audit] 写审计日志失败: {exc}", file=sys.stderr)
        try:
            db.rollback()
        except Exception:
            pass
        return None
