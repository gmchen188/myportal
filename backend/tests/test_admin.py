"""管理后台的测试 —— 登录、权限、用户/租户/接入源/审计。

## 为什么这组测试重要

后台是**唯一能改生产数据的入口**。权限写错一个符号，
就是「A 租户的人能删 B 租户的资产」。所以每个越权路径都要测。

## 库隔离

照 `test_topology_import.py` 的姿势：`dependency_overrides` 换掉
`get_session`，**不用 `with TestClient(app)`** —— 那会跑 lifespan
→ init_db() → 在真实库上建表。真实库一个字节都不动。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import AuditLog, Base, IntakeSource, Tenant, User, get_session
from app.main import app
from app.services.passwords import hash_password

ASI = "t-asi"
DONGFANG = "t-dongfang"
STRONG = "Str0ng!Passw0rd"


@pytest.fixture()
def env(tmp_path):
    """临时库 + 三个用户（super_admin / tenant_admin / analyst）。"""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'admin.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    db = Session()
    db.add(Tenant(id=ASI, slug="asi", name="AquaSync Innovation", locale="zh-CN", fortisiem_org="Super"))
    db.add(Tenant(id=DONGFANG, slug="dongfang", name="东方海运", locale="zh-CN", fortisiem_org="DONGFANG"))
    db.add(
        User(
            id=1,
            tenant_id=ASI,
            username="root",
            password_hash=hash_password(STRONG),
            display_name="超管",
            role="super_admin",
        )
    )
    db.add(
        User(
            id=2,
            tenant_id=ASI,
            username="admin1",
            password_hash=hash_password(STRONG),
            display_name="租户管理员",
            role="tenant_admin",
        )
    )
    db.add(
        User(
            id=3,
            tenant_id=ASI,
            username="viewer1",
            password_hash=hash_password(STRONG),
            display_name="只读的人",
            role="viewer",
        )
    )
    db.commit()
    db.close()

    def override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = override
    client = TestClient(app)
    yield client, Session
    app.dependency_overrides.clear()


def _login(client, username, password=STRONG, tenant="asi"):
    r = client.post("/api/auth/login", json={"username": username, "password": password, "tenant": tenant})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


# ── 登录 ────────────────────────────────────────────────────────────────────
class TestLogin:
    def test_登录成功返回令牌与用户(self, env):
        client, _ = env
        r = client.post("/api/auth/login", json={"username": "admin1", "password": STRONG, "tenant": "asi"})
        assert r.status_code == 200
        body = r.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"]
        assert body["user"]["username"] == "admin1"
        assert body["tenant"]["slug"] == "asi"

    def test_密码哈希不能出现在响应里(self, env):
        client, _ = env
        r = client.post("/api/auth/login", json={"username": "admin1", "password": STRONG, "tenant": "asi"})
        assert "password_hash" not in r.text

    def test_账号不存在与密码错提示必须一致(self, env):
        """**不能泄露账号是否存在** —— 否则可以用来枚举账号。"""
        client, _ = env
        a = client.post("/api/auth/login", json={"username": "admin1", "password": "wrong", "tenant": "asi"})
        b = client.post("/api/auth/login", json={"username": "nobody", "password": "wrong", "tenant": "asi"})
        assert a.status_code == b.status_code == 401
        assert a.json()["detail"] == b.json()["detail"]

    def test_租户不存在也是同样的提示(self, env):
        client, _ = env
        r = client.post("/api/auth/login", json={"username": "x", "password": "y", "tenant": "nosuch"})
        assert r.status_code == 401
        assert r.json()["detail"] == "用户名或密码不正确"

    def test_连续失败会锁账号(self, env):
        client, _ = env
        for _ in range(5):
            client.post("/api/auth/login", json={"username": "admin1", "password": "wrong", "tenant": "asi"})
        r = client.post("/api/auth/login", json={"username": "admin1", "password": STRONG, "tenant": "asi"})
        assert r.status_code == 429
        assert "锁定" in r.json()["detail"]

    def test_登录成功会清零失败计数(self, env):
        client, _ = env
        client.post("/api/auth/login", json={"username": "admin1", "password": "wrong", "tenant": "asi"})
        _login(client, "admin1")
        client.post("/api/auth/login", json={"username": "admin1", "password": "wrong", "tenant": "asi"})
        # 第二次失败不该把计数叠加到锁定 —— 成功登录要清零
        r = client.post("/api/auth/login", json={"username": "admin1", "password": STRONG, "tenant": "asi"})
        assert r.status_code == 200


# ── 认证闸门 ────────────────────────────────────────────────────────────────
class TestAuthGate:
    def test_后台端点无令牌一律401(self, env):
        client, _ = env
        for path in [
            "/api/admin/users",
            "/api/admin/tenants",
            "/api/admin/intake-sources",
            "/api/admin/audit",
            "/api/admin/overview",
            "/api/auth/me",
        ]:
            assert client.get(path).status_code == 401, path

    def test_假令牌也401(self, env):
        client, _ = env
        r = client.get("/api/admin/users", headers={"Authorization": "Bearer not.a.token"})
        assert r.status_code == 401


# ── 权限 ────────────────────────────────────────────────────────────────────
class TestPermissions:
    def test_viewer不能改配置(self, env):
        client, _ = env
        h = _login(client, "viewer1")
        r = client.post("/api/admin/users", headers=h, json={"username": "x", "password": STRONG})
        assert r.status_code == 403

    def test_viewer能读(self, env):
        client, _ = env
        h = _login(client, "viewer1")
        assert client.get("/api/admin/overview", headers=h).status_code == 200

    def test_tenant_admin只看得到本租户用户(self, env):
        client, Session = env
        s = Session()
        s.add(User(tenant_id=DONGFANG, username="other", password_hash=hash_password(STRONG), role="viewer"))
        s.commit()
        s.close()

        h = _login(client, "admin1")
        users = client.get("/api/admin/users", headers=h).json()
        assert all(u["tenant_id"] == ASI for u in users), "tenant_admin 不该看到别的租户的用户"

    def test_tenant_admin不能建别租户的用户(self, env):
        client, _ = env
        h = _login(client, "admin1")
        r = client.post(
            "/api/admin/users",
            headers=h,
            json={"username": "x", "password": STRONG, "tenant_id": DONGFANG},
        )
        assert r.status_code == 403

    def test_tenant_admin不能建租户(self, env):
        client, _ = env
        h = _login(client, "admin1")
        r = client.post("/api/admin/tenants", headers=h, json={"slug": "new", "name": "新租户"})
        assert r.status_code == 403

    def test_tenant_admin不能停用租户(self, env):
        client, _ = env
        h = _login(client, "admin1")
        r = client.patch("/api/admin/tenants/t-asi", headers=h, json={"is_active": False})
        assert r.status_code == 403

    def test_super_admin能建租户(self, env):
        client, _ = env
        h = _login(client, "root")
        r = client.post("/api/admin/tenants", headers=h, json={"slug": "newco", "name": "新公司"})
        assert r.status_code == 201
        assert r.json()["slug"] == "newco"

    def test_不能改自己的角色(self, env):
        """把自己降权就把自己锁在门外了 —— 必须禁止。"""
        client, _ = env
        h = _login(client, "admin1")
        me = client.get("/api/auth/me", headers=h).json()
        r = client.patch(f"/api/admin/users/{me['user']['id']}", headers=h, json={"role": "viewer"})
        assert r.status_code == 400

    def test_不能停用自己(self, env):
        client, _ = env
        h = _login(client, "admin1")
        me = client.get("/api/auth/me", headers=h).json()
        r = client.patch(f"/api/admin/users/{me['user']['id']}", headers=h, json={"is_active": False})
        assert r.status_code == 400


# ── 用户管理 ────────────────────────────────────────────────────────────────
class TestUserManagement:
    def test_建用户(self, env):
        client, _ = env
        h = _login(client, "admin1")
        r = client.post(
            "/api/admin/users",
            headers=h,
            json={"username": "analyst1", "password": "Analyst!2026ab", "role": "analyst", "display_name": "分析员"},
        )
        assert r.status_code == 201
        assert r.json()["role"] == "analyst"
        assert "password_hash" not in r.json()

    def test_弱密码被拒且提示具体(self, env):
        client, _ = env
        h = _login(client, "admin1")
        r = client.post("/api/admin/users", headers=h, json={"username": "weak", "password": "123"})
        assert r.status_code == 400
        assert "位" in r.json()["detail"]

    def test_非法角色被拒(self, env):
        client, _ = env
        h = _login(client, "admin1")
        r = client.post("/api/admin/users", headers=h, json={"username": "x", "password": STRONG, "role": "root"})
        assert r.status_code == 400
        assert "角色" in r.json()["detail"]

    def test_同租户内用户名重复被拒(self, env):
        client, _ = env
        h = _login(client, "admin1")
        r = client.post("/api/admin/users", headers=h, json={"username": "admin1", "password": STRONG})
        assert r.status_code == 409

    def test_不同租户可以有同名用户(self, env):
        """用户名在**租户内**唯一 —— 不同租户同名是允许的。"""
        client, _ = env
        h = _login(client, "root")
        r = client.post(
            "/api/admin/users",
            headers=h,
            json={"username": "admin1", "password": STRONG, "tenant_id": DONGFANG},
        )
        assert r.status_code == 201

    def test_删用户是停用不是物理删(self, env):
        """物理删了，审计日志里的上下文就没了。"""
        client, Session = env
        h = _login(client, "admin1")
        r = client.delete("/api/admin/users/3", headers=h)
        assert r.status_code == 200
        assert r.json()["is_active"] is False
        s = Session()
        assert s.get(User, 3) is not None, "用户不该被物理删除"
        s.close()

    def test_不能删自己(self, env):
        client, _ = env
        h = _login(client, "admin1")
        me = client.get("/api/auth/me", headers=h).json()
        r = client.delete(f"/api/admin/users/{me['user']['id']}", headers=h)
        assert r.status_code == 400


# ── 接入源 ──────────────────────────────────────────────────────────────────
class TestIntakeSources:
    def test_建接入源(self, env):
        client, _ = env
        h = _login(client, "admin1")
        r = client.post(
            "/api/admin/intake-sources",
            headers=h,
            json={"kind": "syslog", "name": "岸基 syslog", "config": {"port": 514}},
        )
        assert r.status_code == 201
        assert r.json()["kind"] == "syslog"
        assert r.json()["config"]["port"] == 514

    def test_非法接入类型被拒(self, env):
        client, _ = env
        h = _login(client, "admin1")
        r = client.post("/api/admin/intake-sources", headers=h, json={"kind": "bogus", "name": "x"})
        assert r.status_code == 400
        assert "接入类型" in r.json()["detail"]

    def test_能改能删(self, env):
        client, _ = env
        h = _login(client, "admin1")
        created = client.post(
            "/api/admin/intake-sources", headers=h, json={"kind": "webhook", "name": "第三方推送"}
        ).json()
        sid = created["id"]
        r = client.patch(f"/api/admin/intake-sources/{sid}", headers=h, json={"enabled": False})
        assert r.status_code == 200
        assert r.json()["enabled"] is False
        assert client.delete(f"/api/admin/intake-sources/{sid}", headers=h).status_code == 200

    def test_touch更新last_seen(self, env):
        """通道「还活着吗」的判据 —— last_seen_at。"""
        client, _ = env
        h = _login(client, "admin1")
        created = client.post(
            "/api/admin/intake-sources", headers=h, json={"kind": "syslog", "name": "s"}
        ).json()
        assert created["last_seen_at"] is None
        r = client.post(f"/api/admin/intake-sources/{created['id']}/touch", headers=h)
        assert r.status_code == 200
        assert r.json()["last_seen_at"] is not None
        assert r.json()["events_received"] == 1


# ── 审计 ────────────────────────────────────────────────────────────────────
class TestAudit:
    def test_管理动作都要写审计(self, env):
        client, _ = env
        h = _login(client, "admin1")
        client.post("/api/admin/users", headers=h, json={"username": "auditee", "password": STRONG})
        logs = client.get("/api/admin/audit", headers=h).json()
        actions = [entry["action"] for entry in logs]
        assert "user.create" in actions

    def test_审计要记下是谁干的(self, env):
        client, _ = env
        h = _login(client, "admin1")
        client.post("/api/admin/users", headers=h, json={"username": "auditee", "password": STRONG})
        logs = client.get("/api/admin/audit", headers=h).json()
        entry = next(e for e in logs if e["action"] == "user.create")
        assert entry["username"] == "admin1"
        assert entry["target_type"] == "user"
        assert entry["detail"]["username"] == "auditee"

    def test_登录失败也要审计(self, env):
        client, _ = env
        h = _login(client, "admin1")
        client.post("/api/auth/login", json={"username": "admin1", "password": "wrong", "tenant": "asi"})
        logs = client.get("/api/admin/audit", headers=h).json()
        assert any(e["action"] == "auth.login_failed" for e in logs)

    def test_审计能按动作过滤(self, env):
        client, _ = env
        h = _login(client, "admin1")
        client.post("/api/admin/users", headers=h, json={"username": "auditee", "password": STRONG})
        logs = client.get("/api/admin/audit?action=user.create", headers=h).json()
        assert logs
        assert all(e["action"] == "user.create" for e in logs)

    def test_审计只对本租户可见(self, env):
        client, Session = env
        s = Session()
        s.add(AuditLog(tenant_id=DONGFANG, action="other.tenant", username="x"))
        s.commit()
        s.close()
        h = _login(client, "admin1")
        logs = client.get("/api/admin/audit", headers=h).json()
        assert all(e["tenant_id"] == ASI for e in logs)


# ── 总览 ────────────────────────────────────────────────────────────────────
class TestOverview:
    def test_总览给数字(self, env):
        client, _ = env
        h = _login(client, "admin1")
        body = client.get("/api/admin/overview", headers=h).json()
        for key in ("tenants", "users", "assets", "incidents", "intake_sources", "audit_entries"):
            assert key in body, key

    def test_总览统计本租户范围(self, env):
        client, Session = env
        s = Session()
        s.add(User(tenant_id=DONGFANG, username="other", password_hash=hash_password(STRONG), role="viewer"))
        s.commit()
        s.close()
        h = _login(client, "admin1")
        body = client.get("/api/admin/overview", headers=h).json()
        assert body["tenants"] == 1, "tenant_admin 只该看到自己一个租户"
        assert body["users"] == 3, "本租户 3 个用户"
