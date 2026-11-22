"""船队 / 船舶 —— 总览的两级视图与资产清单的分组依据。

## 为什么这组测试重要

「船队-单船」是**归属关系**，归属错了不会报错 —— 设备会静默地
出现在错误的船下面，运维照着错的归属去排查。

所以每个归属路径都要测：统计算对、删船不删资产、跨租户看不到、
批量归船幂等。

## 库隔离

照 `test_admin.py` 的姿势：`dependency_overrides` 换掉 `get_session`，
**不用 `with TestClient(app)`** —— 那会跑 lifespan → init_db() →
在真实库上建表。真实库一个字节都不动。

播种函数要单独测，它用的是全局 engine —— 用 monkeypatch 把它换到临时库。
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import (
    Asset,
    Base,
    DeviceMonitor,
    Fleet,
    Incident,
    Tenant,
    Topology,
    User,
    Vessel,
    get_session,
)
from app.main import app
from app.services.passwords import hash_password

ASI = "t-asi"
DONGFANG = "t-dongfang"
STRONG = "Str0ng!Passw0rd"


@pytest.fixture()
def env(tmp_path):
    """临时库 + 两个租户 + 三种角色。"""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'fleets.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    db = Session()
    db.add(Tenant(id=ASI, slug="asi", name="AquaSync Innovation", locale="zh-CN"))
    db.add(Tenant(id=DONGFANG, slug="dongfang", name="东方海运", locale="zh-CN"))
    for uid, role in ((1, "super_admin"), (2, "tenant_admin"), (3, "viewer")):
        db.add(
            User(
                id=uid,
                tenant_id=ASI,
                username=f"u{uid}",
                password_hash=hash_password(STRONG),
                display_name=role,
                role=role,
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


def _seed_tree(Session):
    """一支船队、两艘船、三件资产、两条监控、三条事件。"""
    db = Session()
    fleet = Fleet(tenant_id=ASI, name="东海船队", code="DF")
    db.add(fleet)
    db.flush()
    v1 = Vessel(tenant_id=ASI, fleet_id=fleet.id, name="海洋一号", code="HY1")
    v2 = Vessel(tenant_id=ASI, fleet_id=fleet.id, name="海洋二号", code="HY2")
    db.add_all([v1, v2])
    db.flush()
    db.add_all(
        [
            Asset(tenant_id=ASI, natural_id="A1", name="A1", type="防火墙", zone="Zone 1", vessel_id=v1.id),
            Asset(tenant_id=ASI, natural_id="A2", name="A2", type="网关", zone="Zone 1", vessel_id=v1.id),
            Asset(tenant_id=ASI, natural_id="A3", name="A3", type="交换机", zone="Zone 2", vessel_id=v2.id),
            # **没归船的资产** —— 它不能从清单里消失
            Asset(tenant_id=ASI, natural_id="A4", name="A4", type="摄像头", zone="Zone 3", vessel_id=None),
        ]
    )
    # device_monitors.topology_id 是 NOT NULL —— 监控设备一定挂在某张图上
    topo = Topology(tenant_id=ASI, name="船队网络拓扑", xml="<mxfile/>", fleet_id=fleet.id)
    db.add(topo)
    db.flush()
    db.add_all(
        [
            DeviceMonitor(
                tenant_id=ASI, topology_id=topo.id, node_id="d1", node_label="A1",
                natural_id="A1", channel="fortisiem", enabled=1,
            ),
            DeviceMonitor(
                tenant_id=ASI, topology_id=topo.id, node_id="d3", node_label="A3",
                natural_id="A3", channel="fortisiem", enabled=1,
            ),
        ]
    )
    db.add_all(
        [
            Incident(tenant_id=ASI, title="严重事件", severity="critical", device_natural_id="A1"),
            Incident(tenant_id=ASI, title="高危事件", severity="high", device_natural_id="A1"),
            Incident(tenant_id=ASI, title="低危事件", severity="low", device_natural_id="A3"),
        ]
    )
    db.commit()
    ids = {"fleet": fleet.id, "v1": v1.id, "v2": v2.id}
    db.close()
    return ids


# ── 船队视图 ────────────────────────────────────────────────────────────────
class TestFleetOverview:
    def test_counts_by_vessel(self, env):
        """每艘船的资产/监控/事件数要分开算，不能混在一起。"""
        client, Session = env
        ids = _seed_tree(Session)
        h = _login(client, "u1")
        r = client.get("/api/fleets/overview", headers=h)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["totals"]["asset_count"] == 4
        assert data["totals"]["monitor_count"] == 2
        assert data["totals"]["event_count"] == 3

        fleet = data["fleets"][0]
        assert fleet["name"] == "东海船队"
        assert fleet["vessel_count"] == 2
        by_name = {v["name"]: v for v in fleet["vessels"]}
        assert by_name["海洋一号"]["asset_count"] == 2
        assert by_name["海洋一号"]["monitor_count"] == 1
        assert by_name["海洋一号"]["event_count"] == 2
        assert by_name["海洋二号"]["asset_count"] == 1
        assert by_name["海洋二号"]["event_count"] == 1

    def test_severity_split_per_vessel(self, env):
        """严重度分布按船拆开 —— 船队的人要知道哪艘船更严重。"""
        client, Session = env
        _seed_tree(Session)
        h = _login(client, "u1")
        data = client.get("/api/fleets/overview", headers=h).json()
        fleet = data["fleets"][0]
        by_name = {v["name"]: v for v in fleet["vessels"]}
        assert by_name["海洋一号"]["events_by_severity"] == {"critical": 1, "high": 1}
        assert by_name["海洋二号"]["events_by_severity"] == {"low": 1}
        assert fleet["events_by_severity"] == {"critical": 1, "high": 1, "low": 1}

    def test_unassigned_assets_stay_visible(self, env):
        """**没归船的设备不能消失** —— 它单列一组。"""
        client, Session = env
        _seed_tree(Session)
        h = _login(client, "u1")
        data = client.get("/api/fleets/overview", headers=h).json()
        names = [v["name"] for f in data["fleets"] for v in f["vessels"]]
        assert "未归船" in names, names
        orphan = next(v for f in data["fleets"] for v in f["vessels"] if v["name"] == "未归船")
        assert orphan["asset_count"] == 1
        assert orphan["id"] is None

    def test_fleet_id_is_an_integer(self, env):
        """`fleet_id` 必须是整数列。

        写成 String(64) 时 SQLite 存成文本 '2'，`vessel.fleet_id == fleet.id`
        永远不成立 —— **船队视图显示 0 艘船**，而 totals 是另一个数。
        这个测试就是钉住那个坑。
        """
        client, Session = env
        ids = _seed_tree(Session)
        db = Session()
        v = db.get(Vessel, ids["v1"])
        assert isinstance(v.fleet_id, int), f"fleet_id 是 {type(v.fleet_id)} —— 文本会比不上整数主键"
        db.close()


# ── 单船视图 ────────────────────────────────────────────────────────────────
class TestVesselOverview:
    def test_lists_assets_and_monitors(self, env):
        client, Session = env
        ids = _seed_tree(Session)
        h = _login(client, "u1")
        r = client.get(f"/api/fleets/vessels/{ids['v1']}/overview", headers=h)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["vessel"]["name"] == "海洋一号"
        assert data["vessel"]["fleet_name"] == "东海船队"
        assert [a["name"] for a in data["assets"]] == ["A1", "A2"]
        assert [m["natural_id"] for m in data["monitored"]] == ["A1"]
        assert data["events_by_severity"] == {"critical": 1, "high": 1}

    def test_unknown_vessel_is_404(self, env):
        client, _ = env
        h = _login(client, "u1")
        assert client.get("/api/fleets/vessels/9999/overview", headers=h).status_code == 404


# ── 管理动作 ────────────────────────────────────────────────────────────────
class TestManage:
    def test_create_fleet_and_vessel(self, env):
        client, Session = env
        h = _login(client, "u1")
        r = client.post("/api/fleets", json={"name": "南海船队"}, headers=h)
        assert r.status_code == 200, r.text
        fleet_id = r.json()["id"]
        r = client.post(
            "/api/fleets/vessels",
            json={"name": "远洋三号", "fleet_id": fleet_id, "code": "Y3"},
            headers=h,
        )
        assert r.status_code == 200, r.text
        vid = r.json()["id"]
        db = Session()
        v = db.get(Vessel, vid)
        assert v.fleet_id == fleet_id
        db.close()

    def test_delete_vessel_keeps_assets(self, env):
        """**删船不删资产** —— 资产变成「未归船」，还在清单里。"""
        client, Session = env
        ids = _seed_tree(Session)
        h = _login(client, "u1")
        assert client.delete(f"/api/fleets/vessels/{ids['v1']}", headers=h).status_code == 200
        db = Session()
        a = db.query(Asset).filter(Asset.natural_id == "A1").first()
        assert a is not None, "资产被删了 —— 不该发生"
        assert a.vessel_id is None, "资产应该变成未归船"
        db.close()

    def test_delete_fleet_is_refused_while_it_has_vessels(self, env):
        """删船队 —— **底下还有船就不给删**（409）。

        船必须属于某一支船队，所以「删船队 → 船变孤儿」这条路堵死了。
        要删船队，先把船移到别的船队。
        """
        client, Session = env
        ids = _seed_tree(Session)
        h = _login(client, "u1")
        r = client.delete(f"/api/fleets/{ids['fleet']}", headers=h)
        assert r.status_code == 409, r.text
        assert "船" in r.json()["detail"]
        db = Session()
        v = db.get(Vessel, ids["v1"])
        assert v is not None, "船被删了 —— 不该发生"
        assert v.fleet_id == ids["fleet"], "船的归属被改了 —— 不该发生"
        db.close()

    def test_delete_fleet_works_when_it_has_no_vessels(self, env):
        """没有船的船队照删。"""
        client, Session = env
        _seed_tree(Session)
        h = _login(client, "u1")
        db = Session()
        empty = Fleet(tenant_id=ASI, name="空船队")
        db.add(empty)
        db.commit()
        fid = empty.id
        db.close()
        r = client.delete(f"/api/fleets/{fid}", headers=h)
        assert r.status_code == 200, r.text

    def test_create_vessel_requires_a_fleet(self, env):
        """**新建船必须给船队** —— 不给就是 422。

        船可以飘在船队之外的话，「船队视图」永远缺一块。
        """
        client, Session = env
        h = _login(client, "u1")
        r = client.post("/api/fleets/vessels", json={"name": "无主船"}, headers=h)
        assert r.status_code == 422, r.text
        assert "fleet_id" in r.text, r.text

    def test_vessel_can_change_its_fleet(self, env):
        """船可以改归属 —— 移船队是正常业务动作。"""
        client, Session = env
        ids = _seed_tree(Session)
        h = _login(client, "u1")
        db = Session()
        other = Fleet(tenant_id=ASI, name="接收船队")
        db.add(other)
        db.commit()
        oid = other.id
        db.close()
        r = client.patch(
            f"/api/fleets/vessels/{ids['v1']}", json={"fleet_id": oid}, headers=h
        )
        assert r.status_code == 200, r.text
        assert r.json()["fleet_id"] == oid
        # 移走一艘还剩一艘 → 还是不能删船队
        r2 = client.delete(f"/api/fleets/{ids['fleet']}", headers=h)
        assert r2.status_code == 409, r2.text
        assert "1 艘船" in r2.json()["detail"], r2.text
        # 两艘都移走 → 原船队空了，可以删
        r3 = client.patch(
            f"/api/fleets/vessels/{ids['v2']}", json={"fleet_id": oid}, headers=h
        )
        assert r3.status_code == 200, r3.text
        r4 = client.delete(f"/api/fleets/{ids['fleet']}", headers=h)
        assert r4.status_code == 200, r4.text

    def test_assign_assets_is_idempotent(self, env):
        """批量归船幂等 —— 同一批再归一次，结果一样。"""
        client, Session = env
        ids = _seed_tree(Session)
        h = _login(client, "u1")
        db = Session()
        a4 = db.query(Asset).filter(Asset.natural_id == "A4").first()
        aid = a4.id
        db.close()
        r = client.post(f"/api/fleets/vessels/{ids['v1']}/assets", json={"asset_ids": [aid]}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["moved"] == 1
        r = client.post(f"/api/fleets/vessels/{ids['v1']}/assets", json={"asset_ids": [aid]}, headers=h)
        assert r.json()["moved"] == 0, "重复归船不该再报改动"

    def test_other_tenants_fleet_is_invisible(self, env):
        """**跨租户看不到别人的船** —— 船队是业务归属，也是隔离边界。"""
        client, Session = env
        db = Session()
        db.add(Fleet(tenant_id=DONGFANG, name="别人的船队"))
        db.commit()
        db.close()
        h = _login(client, "u1")
        data = client.get("/api/fleets", headers=h).json()
        assert all(f["name"] != "别人的船队" for f in data["fleets"])


# ── 认证 ────────────────────────────────────────────────────────────────────
class TestAuthGate:
    def test_manage_endpoints_need_a_token(self, env):
        """**管理端点必须严格认证** —— 开发租户头也不能绕过。"""
        client, _ = env
        for method, path, body in [
            ("post", "/api/fleets", {"name": "X"}),
            ("patch", "/api/fleets/1", {"name": "X"}),
            ("delete", "/api/fleets/1", None),
            ("post", "/api/fleets/vessels", {"name": "X"}),
            ("patch", "/api/fleets/vessels/1", {"name": "X"}),
            ("delete", "/api/fleets/vessels/1", None),
            ("post", "/api/fleets/vessels/1/assets", {"asset_ids": [1]}),
        ]:
            r = getattr(client, method)(path, json=body) if body else getattr(client, method)(path)
            assert r.status_code == 401, f"{method} {path} → {r.status_code}"

    def test_viewer_cannot_manage(self, env):
        """只读的人不能建船队。"""
        client, _ = env
        h = _login(client, "u3")
        assert client.post("/api/fleets", json={"name": "X"}, headers=h).status_code == 403

    def test_read_endpoints_allow_viewer(self, env):
        client, _ = env
        h = _login(client, "u3")
        assert client.get("/api/fleets", headers=h).status_code == 200
        assert client.get("/api/fleets/overview", headers=h).status_code == 200


# ── 资产侧的筛选与归属 ──────────────────────────────────────────────────────
class TestAssetVessel:
    def test_filter_by_vessel(self, env):
        client, Session = env
        ids = _seed_tree(Session)
        h = _login(client, "u1")
        r = client.get(f"/api/assets?vessel_id={ids['v1']}", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["total"] == 2

    def test_filter_by_fleet(self, env):
        client, Session = env
        ids = _seed_tree(Session)
        h = _login(client, "u1")
        r = client.get(f"/api/assets?fleet_id={ids['fleet']}", headers=h)
        assert r.json()["total"] == 3, "船队下的三件（未归船的那件不算）"

    def test_asset_list_carries_vessel_and_siem_status(self, env):
        """列表要带 vessel_id 与 siem_push_status。

        **漏掉 siem_push_status 的后果是静默的**：前端
        `siem_push_status !== "ok"` 永远成立 → **已推送的资产也显示成
        「未推送」** → 用户再推一次 → CMDB 里多一台重复设备。
        """
        client, Session = env
        _seed_tree(Session)
        h = _login(client, "u1")
        item = client.get("/api/assets", headers=h).json()["items"][0]
        assert "vessel_id" in item
        assert "siem_push_status" in item
        assert "siem_pushed_at" in item

    def test_patch_asset_moves_it_to_a_vessel(self, env):
        client, Session = env
        ids = _seed_tree(Session)
        h = _login(client, "u1")
        db = Session()
        a4 = db.query(Asset).filter(Asset.natural_id == "A4").first()
        aid = a4.id
        db.close()
        r = client.patch(f"/api/assets/{aid}", json={"vessel_id": ids["v1"]}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["vessel_id"] == ids["v1"]

    def test_patch_asset_can_unassign(self, env):
        """**清空归属**用 0 表示 —— model_dump(exclude_none=True) 会把 null 丢掉。"""
        client, Session = env
        ids = _seed_tree(Session)
        h = _login(client, "u1")
        db = Session()
        a1 = db.query(Asset).filter(Asset.natural_id == "A1").first()
        aid = a1.id
        db.close()
        r = client.patch(f"/api/assets/{aid}", json={"vessel_id": 0}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["vessel_id"] is None

    def test_export_carries_vessel_and_fleet_names(self, env):
        """导出表里要有**船名与船队名**，不是 id。

        `to_dict()` 只有 `vessel_id` —— 交付方拿到一列数字没有意义。
        """
        client, Session = env
        ids = _seed_tree(Session)
        h = _login(client, "u1")
        r = client.get("/api/assets/export?fmt=csv", headers=h)
        assert r.status_code == 200, r.text
        body = r.content.decode("utf-8-sig")
        assert "所属船舶" in body
        assert "所属船队" in body
        assert "海洋一号" in body, body[:400]
        assert "东海船队" in body, body[:400]

    def test_cannot_move_asset_to_another_tenants_vessel(self, env):
        """不能把资产挂到别的租户的船上。"""
        client, Session = env
        _seed_tree(Session)
        db = Session()
        # 船必须有归属 —— 给它一支别的租户的船队
        other_fleet = Fleet(tenant_id=DONGFANG, name="别人的船队")
        db.add(other_fleet)
        db.flush()
        db.add(Vessel(tenant_id=DONGFANG, fleet_id=other_fleet.id, name="别人的船"))
        db.commit()
        db.close()
        h = _login(client, "u1")
        db = Session()
        a1 = db.query(Asset).filter(Asset.natural_id == "A1").first()
        aid = a1.id
        db.close()
        r = client.patch(f"/api/assets/{aid}", json={"vessel_id": 9999}, headers=h)
        assert r.status_code == 404


    def test_patch_fleet_can_change_and_clear_code(self, env):
        """**标签要能改，也要能清空。**

        清空标签 = 前端把空串转成 `null` 发过来（`code: str | None`）。

        **这里有个容易漏的坑**：用 `if v is not None` 过滤字段的话，
        显式传的 `null` 和「没传这个字段」就分不出来了 —— `null` 会被整个
        忽略，标签清不掉。要用 `model_dump(exclude_unset=True)`。
        """
        client, Session = env
        h = _login(client, "u1")
        r = client.post("/api/fleets", json={"name": "标签队", "code": "T-1"}, headers=h)
        assert r.status_code == 200, r.text
        fid = r.json()["id"]
        assert r.json()["code"] == "T-1"

        # 改标签
        r = client.patch(f"/api/fleets/{fid}", json={"code": "T-2"}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["code"] == "T-2"

        # 清空标签
        r = client.patch(f"/api/fleets/{fid}", json={"code": None}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["code"] is None, r.text

    def test_patch_fleet_cannot_blank_the_name(self, env):
        """名字不能被清空 —— 否则列表页会出现无名船队。"""
        client, Session = env
        h = _login(client, "u1")
        r = client.post("/api/fleets", json={"name": "有名字的队"}, headers=h)
        fid = r.json()["id"]
        r = client.patch(f"/api/fleets/{fid}", json={"name": ""}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "有名字的队"

    def test_patch_vessel_can_change_and_clear_code(self, env):
        client, Session = env
        h = _login(client, "u1")
        r = client.post("/api/fleets", json={"name": "船队X"}, headers=h)
        fid = r.json()["id"]
        r = client.post(
            "/api/fleets/vessels",
            json={"name": "船Y", "code": "V-1", "fleet_id": fid},
            headers=h,
        )
        assert r.status_code == 200, r.text
        vid = r.json()["id"]
        assert r.json()["code"] == "V-1"

        r = client.patch(f"/api/fleets/vessels/{vid}", json={"code": "V-2"}, headers=h)
        assert r.json()["code"] == "V-2"

        r = client.patch(f"/api/fleets/vessels/{vid}", json={"code": None}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["code"] is None, r.text

    def test_patch_fleet_only_touches_the_given_fields(self, env):
        """**没传的字段不能被清掉** —— 这就是 exclude_unset 的另一面。"""
        client, Session = env
        h = _login(client, "u1")
        r = client.post(
            "/api/fleets",
            json={"name": "字段队", "code": "KEEP", "description": "描述"},
            headers=h,
        )
        fid = r.json()["id"]
        # 只改名字
        r = client.patch(f"/api/fleets/{fid}", json={"name": "改名了"}, headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["name"] == "改名了"
        assert body["code"] == "KEEP", body
        assert body["description"] == "描述", body


    def test_asset_filter_rejects_a_vessel_from_another_fleet(self, env):
        """「船队 A + 船队 B 的船」要报错，**不能返回空列表**。

        空列表看起来像「设备丢了」—— 用户会去查数据、查导入记录，
        其实只是筛选条件打架。
        """
        client, Session = env
        ids = _seed_tree(Session)
        h = _login(client, "u1")
        db = Session()
        other = Fleet(tenant_id=ASI, name="另一支船队")
        db.add(other)
        db.flush()
        oid = other.id
        db.close()
        # v1 在 ids["fleet"]，用另一支船队去筛它 → 矛盾
        r = client.get(
            f"/api/assets?vessel_id={ids['v1']}&fleet_id={oid}", headers=h
        )
        assert r.status_code == 400, r.text
        assert "不属于" in r.json()["detail"]

    def test_asset_filter_by_fleet_and_its_vessel_works(self, env):
        """一致��组合正常返回。"""
        client, Session = env
        ids = _seed_tree(Session)
        h = _login(client, "u1")
        r = client.get(
            f"/api/assets?vessel_id={ids['v1']}&fleet_id={ids['fleet']}", headers=h
        )
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert items, "一致组合应该有结果"
        assert all(a["vessel_id"] == ids["v1"] for a in items)


class TestImageToTopology:
    """图片 → 拓扑图。"""

    def test_sse_parsing_picks_the_last_xml(self):
        """**取最后一个 XML** —— 模型可能画完再改一次。

        SSE 的形状是实测出来的：每行 `data: {json}`，
        XML 在 `tool-input-available` 事件的 `input.xml` 里。
        """
        from app.services.image_to_topology import _parse_sse

        sse = "\n".join([
            'data: {"type":"start"}',
            'data: {"type":"text-delta","id":"0","delta":"画好了"}',
            'data: {"type":"tool-input-available","toolCallId":"c1","toolName":"get_shape_library","input":{"library":"cisco19"}}',
            # **raw 字符串** —— JSON 里的 \" 必须保留反斜杠，
            # 普通字符串会把它吃掉一层，JSON 就成了裸引号、解析直接失败。
            r'data: {"type":"tool-input-available","toolCallId":"c2","toolName":"display_diagram","input":{"xml":"<mxCell id=\"a\"/>"}}',
            r'data: {"type":"tool-input-available","toolCallId":"c3","toolName":"display_diagram","input":{"xml":"<mxCell id=\"b\"/><mxCell id=\"c\"/>"}}',
            "data: [DONE]",
        ])
        xml, text, tools = _parse_sse(sse)
        assert xml is not None
        assert 'id="c"' in xml, xml
        assert 'id="b"' in xml
        # 后一个覆盖前一个 —— 只有一个 id="b"、没有 id="a"
        assert 'id="a"' not in xml
        assert text == "画好了"
        assert "display_diagram" in tools

    def test_sse_ignores_non_mxcell_xml(self):
        """别的工具也可能带 xml 字段 —— 只有含 mxCell 的才算图。"""
        from app.services.image_to_topology import _parse_sse

        sse = (
            r'data: {"type":"tool-input-available","toolName":"other",'
            r'"input":{"xml":"<html>not a diagram</html>"}}\n'
        )
        xml, _, _ = _parse_sse(sse)
        assert xml is None

    def test_endpoint_saves_the_topology(self, env, monkeypatch):
        """端点：存下拓扑、origin=image、返回绑定数。"""
        client, Session = env
        h = _login(client, "u1")

        def fake_generate(image_base64, mime="image/png", prompt="", timeout=0):
            from app.services.image_to_topology import TopologyFromImage
            return TopologyFromImage(
                xml='<mxStyle name="dev" value="x"/><mxCell id="d1" value="FW-EDGE-01" style="dev;" x="1" y="2" w="3" h="4"/>',
                message="画好了",
                tool_calls=["display_diagram"],
            )

        import app.routers.topologies as topo_router
        monkeypatch.setattr(topo_router, "generate_from_image", fake_generate)

        r = client.post(
            "/api/topologies/from-image",
            json={"name": "架构图", "image_base64": "aGk="},
            headers=h,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["origin"] == "image"
        assert "<mxCell" in body["xml"]
        assert body["name"] == "架构图"
        # 存下来了
        db = Session()
        t = db.query(Topology).filter(Topology.name == "架构图").first()
        assert t is not None
        db.close()

    def test_endpoint_reports_upstream_failure(self, env, monkeypatch):
        """上游挂了 → 502，并且带上人话说明。"""
        client, Session = env
        h = _login(client, "u1")

        def boom(*a, **k):
            from app.services.image_to_topology import ImageToTopologyError
            raise ImageToTopologyError("连不上画图服务（http://127.0.0.1:6002/networktopology）")

        import app.routers.topologies as topo_router
        monkeypatch.setattr(topo_router, "generate_from_image", boom)

        r = client.post(
            "/api/topologies/from-image",
            json={"name": "架构图", "image_base64": "aGk="},
            headers=h,
        )
        assert r.status_code == 502, r.text
        assert "连不上" in r.json()["detail"]

    def test_endpoint_rejects_empty_name(self, env, monkeypatch):
        client, Session = env
        h = _login(client, "u1")
        r = client.post(
            "/api/topologies/from-image",
            json={"name": "  ", "image_base64": "aGk="},
            headers=h,
        )
        assert r.status_code == 400


class TestTopologyParseNoHang:
    """**解析器不能死循环。**

    ## 这条为什么重要

    `topology_parse` 是监控面板的必经之路（`Topology.to_dict()` 每次都调
    `node_count()` → `parse_topology()`）。

    解析裸 XML 片段时有一段手写的「逐个切顶层元素」。那里曾经有个
    **找不到闭标签就 `continue` 却不推进游标**的分支 → `while` 永远转 →
    **这个请求的线程永远不释放** → 线程池被占满 → **整个后台卡死**，
    监控面板表现为「死机」。

    实测触发条件：属性值里带 `>`（AI 生成的 XML 里很常见）→
    `find(">")` 落到标签中间 → tag 解析错 → 找不到闭标签 → 进那个分支。

    ## 为什么用子进程测

    万一以后又写回一个死循环，测试会**卡住整个测试进程**而不是失败。
    放在子进程里跑 + 超时，才能真正变成「测试失败」而不是「CI 卡死」。
    """

    XML_WITH_GT_IN_ATTR = (
        '<mxCell id="a" value="x > y" style="dev;"/>'
        '<mxCell id="b" value="ok" style="dev;"/>'
    )

    # **真正触发死循环的样本**（实测：旧代码在这上面永远转下去）。
    #
    # 三个条件同时满足才会进到那个分支：
    #   1. `<root>` 包裹那步解析失败（否则走不到「逐个切顶层元素」）
    #   2. 标签**不是自闭合**（`text[j-1] != "/"`）
    #   3. 找不到对应的闭标签（`find(close, j) < 0`）
    #
    # `value="x>"` 让 `find(">")` 落在标签中间 → tag 解析成 mxCell →
    # 文档里又没有 `</mxCell>` → 走进 `k < 0` 分支 → 旧代码不推进游标 →
    # **死循环**。
    XML_THAT_HUNG = '<mxCell id="a" value="x>"><mxCell id="b" style="dev;"/>' 

    def _parse_in_subprocess(self, xml: str, timeout: int = 20) -> tuple[int, str]:
        import os
        import subprocess
        import sys
        import textwrap

        code = textwrap.dedent(
            f"""
            import sys, time
            sys.path.insert(0, r"{os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}")
            from app.services.topology_parse import parse_topology
            t0 = time.time()
            g = parse_topology({xml!r})
            print(f"{{time.time()-t0:.3f}}|{{len(g.get('nodes') or [])}}|{{g.get('error')}}")
            """
        )
        try:
            r = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return 124, "超时 —— 解析器死循环了"
        return r.returncode, (r.stdout or "").strip() + (r.stderr or "")

    def test_attribute_containing_gt_does_not_hang(self):
        code, out = self._parse_in_subprocess(self.XML_WITH_GT_IN_ATTR)
        assert code != 124, f"解析器死循环了：{out}"
        assert code == 0, out
        secs, nodes, err = out.split("|", 2)
        assert float(secs) < 5, f"解析耗时 {secs}s，太慢了"
        assert int(nodes) == 2, f"两个 cell 都该解析出来，实际 {nodes}"

    def test_normal_fragment_still_parses(self):
        code, out = self._parse_in_subprocess(
            '<mxStyle name="dev" value="rounded=1"/>'
            '<mxCell id="a" value="FW-1" style="dev;" x="1" y="2" w="3" h="4"/>'
        )
        assert code == 0, out
        secs, nodes, err = out.split("|", 2)
        assert int(nodes) == 1
        assert err == "None"

    def test_the_real_hang_sample(self):
        """**这个样本在旧代码上会死循环** —— 实测过（变异验证：改回去就卡死）。"""
        code, out = self._parse_in_subprocess(self.XML_THAT_HUNG)
        assert code != 124, f"解析器死循环了：{out}"
        assert code == 0, out

    def test_unclosed_tag_does_not_hang(self):
        """闭标签缺失（AI 截断的 XML）也不能卡死。"""
        code, out = self._parse_in_subprocess('<mxCell id="a" value="x" style="dev;"/>')
        assert code != 124, f"解析器死循环了：{out}"
