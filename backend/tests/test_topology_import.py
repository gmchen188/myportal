"""
「资产 → 拓扑节点」导入的测试。

被测的东西：

    backend/app/services/topology_import.py
        import_assets_as_nodes(db, tenant_id, topology_id, asset_ids, ...)
        list_importable_assets(db, tenant_id, topology_id)

    backend/app/routers/topologies.py
        GET  /api/topologies/{id}/importable-assets
        POST /api/topologies/{id}/import-assets

## 为什么这组测试要这么写

**核心不变量：导入后的 XML 必须能被 parse_topology 原样读回来。**
拓扑图渲染是「读 XML → 投影成节点/区域」这一步的事。生成的 XML 要是解析器读
不出来（节点丢了、区域丢了），前端就画出一张空图 —— 那比导入失败更糟，因为它
**看起来成功了**。所以每条用例都在导入后重新 parse 一遍，断言 label 和 zone 都对。

**区域归属靠坐标包含判定，不靠 parent 属性。**
parse_topology 是「设备中心点落在区域矩形内 → 归到该区域」判定的。所以新节点
必须用**绝对坐标**写，且中心点要落在目标区域里 —— 照 draw.io 的习惯写相对坐标
加 parent，节点就掉到区域外去了。

**幂等是硬要求。** 同一个资产导入两次不能画出两个方块 —— 一个节点被两条绑定指
着，监控面板会按两台设备算颜色。

跑：
    cd backend && "C:/Python314/python.exe" -m pytest tests -q
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db import Asset, Base, DeviceMonitor, Tenant, Topology, get_session  # noqa: E402
from app.main import app  # noqa: E402
from app.services.topology_import import TopologyImportError, import_assets_as_nodes  # noqa: E402
from app.services.topology_parse import parse_topology  # noqa: E402

# ── 测试用的拓扑图 XML ──────────────────────────────────────────────────────
# 裸片段（display_diagram 工具的真实产物形态：没有根元素、几何写在属性上、
# 用样式表引用）。这正是生产里那张「船队网络拓扑 V1」的形态。
BARE_XML = """
<mxStyle name="zoneBox" value="rounded=1;arcSize=12;fillColor=#ffffff;strokeColor=#d5e2f5;strokeWidth=2;"/>
<mxStyle name="zoneTitle" value="text;html=1;align=left;fontSize=20;fontStyle=1;fontColor=#1a3d8f;"/>
<mxStyle name="zoneSub" value="text;html=1;align=left;fontSize=15;fontColor=#444444;"/>
<mxStyle name="dev" value="rounded=1;arcSize=18;fillColor=#e8eef9;strokeColor=#d5e2f5;fontSize=15;"/>
<mxStyle name="devGw" value="rounded=1;arcSize=18;fillColor=#fdf3dc;strokeColor=#f5d78e;fontSize=15;"/>
<mxStyle name="devDmz" value="rounded=1;arcSize=18;fillColor=#fdeaea;strokeColor=#f4b8b8;fontSize=15;"/>
<mxStyle name="linkGreen" value="edgeStyle=orthogonalEdgeStyle;strokeColor=#1a7a1a;strokeWidth=3;"/>
<mxCell id="z1" value="" style="zoneBox;" x="100" y="50" w="555" h="340"/>
<mxCell id="z1t" value="Zone 1 · 船舶核心控制区" style="zoneTitle;" x="125" y="72" w="300" h="30"/>
<mxCell id="z1s" value="推进 / 操舵 / 电力" style="zoneSub;" x="125" y="104" w="250" h="24"/>
<mxCell id="d1" value="FW-EDGE-01" style="dev;" x="140" y="158" w="190" h="60"/>
<mxCell id="d2" value="REMOTE-GW" style="devGw;" x="390" y="158" w="190" h="60"/>
<mxCell id="e1" style="linkGreen;" source="d1" target="d2"/>
""".strip()

ASI = "t-asi"
DONGFANG = "t-dongfang"


# ── 夹具 ────────────────────────────────────────────────────────────────────
@pytest.fixture()
def env(tmp_path):
    """一套干净的临时 SQLite + 覆盖了 get_session 的 TestClient。

    **不用 app.db 自己的 engine** —— 那指向 backend/data/myportal.db（生产开发
    库）。测试往里写数据会把真实拓扑图搞乱。所以另开一个临时库，用
    dependency_overrides 把会话换掉。

    故意**不用** `with TestClient(app)`：那会跑 startup 事件 → init_db() →
    在真实库上建表。直接构造 TestClient 不触发 lifespan，真实库一个字节都不动。
    """
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    db = Session()
    db.add(Tenant(id=ASI, slug="asi", name="AquaSync Innovation", locale="zh-CN"))
    db.add(Tenant(id=DONGFANG, slug="dongfang", name="东方海运", locale="zh-CN"))
    db.add(
        Topology(
            id=1,
            tenant_id=ASI,
            name="船队网络拓扑 V1",
            xml=BARE_XML,
            origin="manual",
            node_bindings={},
        )
    )
    db.add(
        Topology(
            id=2,
            tenant_id=DONGFANG,
            name="东方海运拓扑",
            xml=BARE_XML,
            origin="manual",
            node_bindings={},
        )
    )
    db.add(
        Topology(
            id=3,
            tenant_id=ASI,
            name="船队网络拓扑 V2",
            xml=BARE_XML,
            origin="manual",
            node_bindings={},
        )
    )
    # 资产：两个已经在图里的（节点 d1/d2 同名）+ 三个图里没有的真实设备
    db.add(Asset(id=1, tenant_id=ASI, natural_id="FW-EDGE-01", name="FW-EDGE-01",
                 type="防火墙", zone="Zone 1", ip=None))
    db.add(Asset(id=2, tenant_id=ASI, natural_id="DC01.goad.lab", name="DC01.goad.lab",
                 type="Microsoft", zone="", ip="172.16.0.30", source="fortisiem"))
    db.add(Asset(id=3, tenant_id=ASI, natural_id="fortisiem751.binqsoft.com",
                 name="fortisiem751.binqsoft.com", type="Fortinet", zone="",
                 ip="172.16.20.48", source="fortisiem"))
    db.add(Asset(id=4, tenant_id=ASI, natural_id="HOST-1.1.1.1", name="HOST-1.1.1.1",
                 type="Volcengine", zone="Zone 9", ip="1.1.1.1", source="fortisiem"))
    db.add(Asset(id=5, tenant_id=DONGFANG, natural_id="OTHER-TENANT-1", name="别的租户的设备",
                 type="交换机", zone="Zone 1", ip="10.9.9.9"))
    db.commit()
    db.close()

    def _override_session():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = _override_session
    client = TestClient(app)
    client.session_factory = Session  # 测试里直接开 session 用
    try:
        yield client
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _db(client):
    s = client.session_factory()
    try:
        yield s
    finally:
        s.close()


def _graph(client, topo_id=1):
    r = client.get(f"/api/topologies/{topo_id}/graph")
    assert r.status_code == 200, r.text
    return r.json()


def _labels(graph):
    return {n["label"] for n in graph["nodes"]}


# ── 1. 导入后节点数增加 ────────────────────────────────────────────────────
class TestImportAddsNodes:
    def test_node_count_increases(self, env):
        before = len(_graph(env)["nodes"])
        r = env.post("/api/topologies/1/import-assets", json={"asset_ids": [2]})
        assert r.status_code == 200, r.text
        after = len(_graph(env)["nodes"])
        assert after == before + 1, (before, after)

    def test_result_reports_added_and_node_payload(self, env):
        r = env.post("/api/topologies/1/import-assets", json={"asset_ids": [2]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["added"] == 1
        assert len(body["nodes"]) == 1
        n = body["nodes"][0]
        assert n["label"] == "DC01.goad.lab"
        assert n["natural_id"] == "DC01.goad.lab"
        assert n["ip"] == "172.16.0.30"
        assert n["node_id"] not in ("d1", "d2")   # 不是既有节点

    def test_multiple_assets_imported_at_once(self, env):
        r = env.post("/api/topologies/1/import-assets", json={"asset_ids": [2, 3]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["added"] == 2
        labels = _labels(_graph(env))
        assert {"DC01.goad.lab", "fortisiem751.binqsoft.com"} <= labels


# ── 2. device_monitors 绑定 ────────────────────────────────────────────────
class TestDeviceMonitorBinding:
    def test_binding_created(self, env):
        r = env.post("/api/topologies/1/import-assets", json={"asset_ids": [2]})
        node_id = r.json()["nodes"][0]["node_id"]

        mons = env.get("/api/topologies/1/monitors").json()["items"]
        m = next(x for x in mons if x["node_id"] == node_id)
        assert m["natural_id"] == "DC01.goad.lab"
        assert m["ip"] == "172.16.0.30"
        assert m["channel"] == "fortisiem"
        assert m["enabled"] is True
        assert m["node_label"] == "DC01.goad.lab"

    def test_binding_row_exists_in_db(self, env):
        env.post("/api/topologies/1/import-assets", json={"asset_ids": [3]})
        s = env.session_factory()
        try:
            rows = s.query(DeviceMonitor).filter(DeviceMonitor.topology_id == 1).all()
            assert len(rows) == 1
            assert rows[0].natural_id == "fortisiem751.binqsoft.com"
            assert rows[0].tenant_id == ASI
        finally:
            s.close()

    def test_node_bindings_also_synced(self, env):
        """node_bindings 与 device_monitors 保持一致（两套绑定机制不打架）。"""
        r = env.post("/api/topologies/1/import-assets", json={"asset_ids": [2]})
        node_id = r.json()["nodes"][0]["node_id"]
        topo = env.get("/api/topologies/1").json()
        assert node_id in topo["node_bindings"]
        assert topo["node_bindings"][node_id]["natural_id"] == "DC01.goad.lab"


# ── 3. 幂等 ─────────────────────────────────────────────────────────────────
class TestIdempotency:
    def test_same_asset_twice_adds_one_node(self, env):
        env.post("/api/topologies/1/import-assets", json={"asset_ids": [2]})
        before = len(_graph(env)["nodes"])
        r = env.post("/api/topologies/1/import-assets", json={"asset_ids": [2]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["added"] == 0
        assert len(_graph(env)["nodes"]) == before

    def test_second_import_is_reported_as_skipped(self, env):
        env.post("/api/topologies/1/import-assets", json={"asset_ids": [2]})
        r = env.post("/api/topologies/1/import-assets", json={"asset_ids": [2]})
        body = r.json()
        assert body["skipped"], body
        assert body["skipped"][0]["reason"] == "已绑定到本拓扑"
        assert body["skipped"][0]["natural_id"] == "DC01.goad.lab"

    def test_duplicate_ids_in_one_request_imported_once(self, env):
        r = env.post("/api/topologies/1/import-assets", json={"asset_ids": [2, 2, 2]})
        body = r.json()
        assert body["added"] == 1
        assert len(_graph(env)["nodes"]) == 3

    def test_no_duplicate_binding_rows(self, env):
        env.post("/api/topologies/1/import-assets", json={"asset_ids": [2]})
        env.post("/api/topologies/1/import-assets", json={"asset_ids": [2]})
        s = env.session_factory()
        try:
            rows = s.query(DeviceMonitor).filter(DeviceMonitor.topology_id == 1).all()
            assert len(rows) == 1
        finally:
            s.close()

    def test_existing_same_label_node_is_reused_not_duplicated(self, env):
        """资产名与图里既有节点同名 → 复用那个节点补绑定，不画第二个方块。

        资产清单里那 11 台从拓扑图反推出来的设备本来就在图上，只是没绑到真实
        设备上。再画一个同名方块是纯粹的噪声。
        """
        r = env.post("/api/topologies/1/import-assets", json={"asset_ids": [1]})
        body = r.json()
        assert body["added"] == 0
        assert body["bound_existing"] == 1
        assert body["nodes"][0]["node_id"] == "d1"
        assert body["nodes"][0]["reused"] is True
        assert len(_graph(env)["nodes"]) == 2      # 节点数没变

        mons = env.get("/api/topologies/1/monitors").json()["items"]
        m = next(x for x in mons if x["node_id"] == "d1")
        assert m["natural_id"] == "FW-EDGE-01"


# ── 4. 导入的节点能被 parse_topology 正确解析 ───────────────────────────────
class TestParseRoundTrip:
    def test_new_xml_parses_without_error(self, env):
        env.post("/api/topologies/1/import-assets", json={"asset_ids": [2, 3, 4]})
        topo = env.get("/api/topologies/1").json()
        g = parse_topology(topo["xml"])
        assert g["error"] is None, g["error"]

    def test_label_is_asset_name(self, env):
        env.post("/api/topologies/1/import-assets", json={"asset_ids": [2]})
        topo = env.get("/api/topologies/1").json()
        g = parse_topology(topo["xml"])
        assert "DC01.goad.lab" in {n["label"] for n in g["nodes"]}

    def test_node_falls_into_expected_zone(self, env):
        """资产 zone = Zone 1 → 节点归到 Zone 1（中心点落在区域矩形内）。"""
        # 资产 4 的 zone 是 Zone 9（图里没有），先把它的 zone 改成 Zone 1
        s = env.session_factory()
        try:
            a = s.get(Asset, 4)
            a.zone = "Zone 1"
            s.commit()
        finally:
            s.close()

        env.post("/api/topologies/1/import-assets", json={"asset_ids": [4]})
        topo = env.get("/api/topologies/1").json()
        g = parse_topology(topo["xml"])
        n = next(x for x in g["nodes"] if x["label"] == "HOST-1.1.1.1")
        assert n["zone"] == "Zone 1 · 船舶核心控制区"
        assert n["zone_key"] == "Zone1"

    def test_zone_forced_by_request_parameter(self, env):
        """显式指定 zone → 节点落到那个区域（哪怕资产自己写的 zone 不同）。"""
        s = env.session_factory()
        try:
            a = s.get(Asset, 4)
            a.zone = "Zone 9"
            s.commit()
        finally:
            s.close()

        r = env.post("/api/topologies/1/import-assets", json={"asset_ids": [4], "zone": "Zone 1"})
        assert r.status_code == 200, r.text
        topo = env.get("/api/topologies/1").json()
        g = parse_topology(topo["xml"])
        n = next(x for x in g["nodes"] if x["label"] == "HOST-1.1.1.1")
        assert n["zone_key"] == "Zone1"

    def test_existing_nodes_are_preserved(self, env):
        env.post("/api/topologies/1/import-assets", json={"asset_ids": [2]})
        topo = env.get("/api/topologies/1").json()
        g = parse_topology(topo["xml"])
        labels = {n["label"] for n in g["nodes"]}
        assert {"FW-EDGE-01", "REMOTE-GW", "DC01.goad.lab"} <= labels

    def test_links_are_preserved(self, env):
        env.post("/api/topologies/1/import-assets", json={"asset_ids": [2]})
        topo = env.get("/api/topologies/1").json()
        g = parse_topology(topo["xml"])
        assert len(g["links"]) == 1
        assert (g["links"][0]["source"], g["links"][0]["target"]) == ("d1", "d2")

    def test_style_name_is_reused_not_invented(self, env):
        """新节点引用样式表里已有的样式名 —— 不新造名字。"""
        env.post("/api/topologies/1/import-assets", json={"asset_ids": [2]})
        topo = env.get("/api/topologies/1").json()
        g = parse_topology(topo["xml"])
        n = next(x for x in g["nodes"] if x["label"] == "DC01.goad.lab")
        assert n["style_names"], n
        assert set(n["style_names"]) <= {"dev", "devGw", "devDmz"}

    def test_style_reference_matches_file_convention(self, env):
        """样式引用写成 ``style="dev;"`` —— 与既有节点同一种写法。

        同一份 XML 里样式写法一半带分号一半不带，用户在 draw.io 里打开再保存
        时会看到两种写法，像是哪里坏了。
        """
        env.post("/api/topologies/1/import-assets", json={"asset_ids": [2]})
        topo = env.get("/api/topologies/1").json()
        new_cells = [
            line for line in (topo["xml"] or "").splitlines()
            if "DC01.goad.lab" in line
        ]
        assert new_cells, "找不到新节点那一行"
        assert 'style="dev;"' in new_cells[0], new_cells[0]

    def test_graph_endpoint_reflects_import(self, env):
        env.post("/api/topologies/1/import-assets", json={"asset_ids": [2]})
        g = _graph(env)
        assert "DC01.goad.lab" in _labels(g)

    def test_node_count_is_real_node_count_not_binding_count(self, env):
        """列表里的「节点数」是节点数，不是绑定数。

        原来 node_count = len(node_bindings)：一张 11 个节点、4 条绑定的图会
        显示 4。那是绑定数 —— 拓扑列表那一列说的是「节点」。
        """
        topo = env.get("/api/topologies/1").json()
        assert topo["node_count"] == 2          # 图上就 2 个节点，绑定是 0 条

        env.post("/api/topologies/1/import-assets", json={"asset_ids": [2]})
        topo = env.get("/api/topologies/1").json()
        assert topo["node_count"] == 3          # 3 个节点（不是 1 条绑定）
        assert len(topo["node_bindings"]) == 1  # 绑定确实只有 1 条

    def test_monitor_panel_sees_the_new_node(self, env):
        """导入的节点要出现在监控面板里，且能对上真实事件。"""
        env.post("/api/topologies/1/import-assets", json={"asset_ids": [2]})
        panel = env.get("/api/monitor/topologies/1/panel").json()
        n = next(x for x in panel["nodes"] if x["label"] == "DC01.goad.lab")
        assert n["natural_id"] == "DC01.goad.lab"
        assert n["ip"] == "172.16.0.30"


# ── 5. 排除已绑定的资产 ────────────────────────────────────────────────────
class TestImportableAssets:
    def test_lists_tenant_assets(self, env):
        r = env.get("/api/topologies/1/importable-assets")
        assert r.status_code == 200, r.text
        body = r.json()
        ids = {i["id"] for i in body["items"]}
        assert {1, 2, 3, 4} <= ids

    def test_excludes_assets_already_bound_to_this_topology(self, env):
        env.post("/api/topologies/1/import-assets", json={"asset_ids": [2]})
        body = env.get("/api/topologies/1/importable-assets").json()
        ids = {i["id"] for i in body["items"]}
        assert 2 not in ids
        assert 3 in ids          # 没绑的还在

    def test_excludes_by_ip_too(self, env):
        """IP 相同也算已绑定 —— natural_id 改了但设备还是那台。"""
        s = env.session_factory()
        try:
            env.post("/api/topologies/1/import-assets", json={"asset_ids": [2]})
            a = s.get(Asset, 2)
            a.natural_id = "DC01-RENAMED"
            s.commit()
        finally:
            s.close()
        body = env.get("/api/topologies/1/importable-assets").json()
        assert 2 not in {i["id"] for i in body["items"]}

    def test_asset_bound_elsewhere_is_still_listed(self, env):
        """绑到**别的**拓扑的资产仍然列出来（用户可能想在本拓扑也画一个）。"""
        s = env.session_factory()
        try:
            # 绑到 asi 的**另一张**拓扑（id=3），不是本拓扑（id=1）
            s.add(DeviceMonitor(tenant_id=ASI, topology_id=3, node_id="d1",
                                natural_id="FW-EDGE-01", channel="fortisiem"))
            s.commit()
        finally:
            s.close()
        body = env.get("/api/topologies/1/importable-assets").json()
        item = next(i for i in body["items"] if i["id"] == 1)
        assert item["bound_elsewhere"] is True

    def test_marks_asset_already_present_in_graph(self, env):
        body = env.get("/api/topologies/1/importable-assets").json()
        item = next(i for i in body["items"] if i["id"] == 1)
        assert item["already_in_graph"] is True     # FW-EDGE-01 就在图上

    def test_other_tenants_assets_not_listed(self, env):
        body = env.get("/api/topologies/1/importable-assets").json()
        names = {i["name"] for i in body["items"]}
        assert "别的租户的设备" not in names


# ── 6. 租户隔离 ─────────────────────────────────────────────────────────────
class TestTenantIsolation:
    def test_cannot_import_into_other_tenants_topology(self, env):
        """asi 租户不能往 dongfang 的拓扑里导入 —— 404，不是 403。"""
        r = env.post("/api/topologies/2/import-assets", json={"asset_ids": [2]})
        assert r.status_code == 404, r.text

    def test_other_tenants_topology_untouched(self, env):
        """asi 尝试导入 dongfang 的拓扑 → 404，且 dongfang 的拓扑一个字节没变。"""
        before = env.get("/api/topologies/2", headers={"X-Dev-Tenant": "dongfang"}).json()["xml"]
        env.post("/api/topologies/2/import-assets", json={"asset_ids": [2]})
        after = env.get("/api/topologies/2", headers={"X-Dev-Tenant": "dongfang"}).json()["xml"]
        assert after == before

    def test_cannot_list_other_tenants_importable_assets(self, env):
        r = env.get("/api/topologies/2/importable-assets", headers={"X-Dev-Tenant": "dongfang"})
        assert r.status_code == 200, r.text
        body = r.json()
        names = {i["name"] for i in body["items"]}
        assert "DC01.goad.lab" not in names      # asi 的资产
        assert "别的租户的设备" in names          # dongfang 自己的

    def test_service_layer_raises_for_other_tenant(self, env):
        """服务层自己也拦一道 —— 不能只靠路由层。"""
        s = env.session_factory()
        try:
            with pytest.raises(TopologyImportError):
                import_assets_as_nodes(s, ASI, 2, [5])   # asi 想去动 dongfang 的拓扑
        finally:
            s.close()

    def test_cannot_import_other_tenants_asset(self, env):
        """资产也按租户过滤 —— 拿 dongfang 的资产 id 到 asi 的拓扑里导入。"""
        r = env.post("/api/topologies/1/import-assets", json={"asset_ids": [5]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["added"] == 0
        assert body["skipped"][0]["reason"] == "资产不存在"


# ── 7. 边界情况 ─────────────────────────────────────────────────────────────
class TestEdgeCases:
    def test_empty_asset_list_is_noop(self, env):
        before = env.get("/api/topologies/1").json()["xml"]
        r = env.post("/api/topologies/1/import-assets", json={"asset_ids": []})
        assert r.status_code == 200
        assert r.json()["added"] == 0
        assert env.get("/api/topologies/1").json()["xml"] == before

    def test_unknown_zone_is_rejected(self, env):
        r = env.post("/api/topologies/1/import-assets", json={"asset_ids": [2], "zone": "Zone 42"})
        assert r.status_code == 400, r.text

    def test_asset_without_matching_zone_goes_to_import_zone(self, env):
        """资产的 zone 在图里不存在 → 放进自动建的「导入设备」区，不丢节点。"""
        r = env.post("/api/topologies/1/import-assets", json={"asset_ids": [4]})
        assert r.status_code == 200, r.text
        topo = env.get("/api/topologies/1").json()
        g = parse_topology(topo["xml"])
        n = next(x for x in g["nodes"] if x["label"] == "HOST-1.1.1.1")
        assert n["zone"] is not None          # 仍然落在某个区域里
        assert "导入设备" in n["zone"]
        assert r.json()["warnings"]

    def test_broken_topology_xml_is_rejected(self, env):
        s = env.session_factory()
        try:
            t = s.get(Topology, 1)
            t.xml = "<mxCell id='x' <<<"
            s.commit()
            with pytest.raises(TopologyImportError):
                import_assets_as_nodes(s, ASI, 1, [2])
        finally:
            s.close()

    def test_topology_without_zones_still_imports(self, env):
        """没有区域的图也能导入 —— 节点落在自动建的区域里。"""
        s = env.session_factory()
        try:
            t = s.get(Topology, 1)
            t.xml = (
                '<mxStyle name="dev" value="rounded=1;"/>'
                '<mxCell id="d1" value="FW-EDGE-01" style="dev;" x="10" y="10" w="190" h="60"/>'
            )
            s.commit()
        finally:
            s.close()
        r = env.post("/api/topologies/1/import-assets", json={"asset_ids": [2]})
        assert r.status_code == 200, r.text
        assert r.json()["added"] == 1

        topo = env.get("/api/topologies/1").json()
        g = parse_topology(topo["xml"])
        assert g["error"] is None
        assert "DC01.goad.lab" in {n["label"] for n in g["nodes"]}

    def test_link_from_node_creates_an_edge(self, env):
        r = env.post("/api/topologies/1/import-assets",
                     json={"asset_ids": [2], "link_from_node_id": "d1"})
        assert r.status_code == 200, r.text
        topo = env.get("/api/topologies/1").json()
        g = parse_topology(topo["xml"])
        new_id = r.json()["nodes"][0]["node_id"]
        assert any(l["source"] == "d1" and l["target"] == new_id for l in g["links"])
