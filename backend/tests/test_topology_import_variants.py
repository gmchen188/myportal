"""
标准 draw.io（mxfile）格式的导入路径 + 区域放不下时的扩区路径。

这两条路径真实拓扑图**现在**还没走到，但迟早会走到：
  · networktopology 画布应用保存的图可能是标准 mxfile（不是裸片段）
  · 用户在一个已经画满的区域里再导入设备 → 要么扩区，要么换区域

跑：
    cd backend && "C:/Python314/python.exe" -m pytest tests/test_topology_import_variants.py -q
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db import Asset, Base, DeviceMonitor, Topology  # noqa: E402
from app.services.topology_import import import_assets_as_nodes  # noqa: E402
from app.services.topology_parse import parse_topology  # noqa: E402

ASI = "t-asi"

# 标准 draw.io：mxfile > diagram > mxGraphModel，几何在 mxGeometry 子元素里
STANDARD_XML = (
    '<mxfile host="app.diagrams.net"><diagram id="d1" name="拓扑">'
    "<mxGraphModel dx=\"1200\" dy=\"800\" grid=\"0\" page=\"1\">"
    "<root>"
    "<mxCell id=\"0\"/>"
    "<mxCell id=\"1\" parent=\"0\"/>"
    "<mxCell id=\"z1\" value=\"\" style=\"rounded=1;fillColor=#ffffff;\" vertex=\"1\" parent=\"1\">"
    "<mxGeometry x=\"100\" y=\"50\" width=\"555\" height=\"340\" as=\"geometry\"/>"
    "</mxCell>"
    "<mxCell id=\"z1t\" value=\"Zone 1 · 船舶核心控制区\" style=\"text;html=1;fontSize=20;\" "
    "vertex=\"1\" parent=\"1\">"
    "<mxGeometry x=\"125\" y=\"72\" width=\"300\" height=\"30\" as=\"geometry\"/>"
    "</mxCell>"
    "<mxCell id=\"d1\" value=\"FW-EDGE-01\" style=\"rounded=1;\" vertex=\"1\" parent=\"1\">"
    "<mxGeometry x=\"140\" y=\"158\" width=\"190\" height=\"60\" as=\"geometry\"/>"
    "</mxCell>"
    "</root>"
    "</mxGraphModel>"
    "</diagram>"
    "</mxfile>"
)


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'v.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    s = Session()
    s.add(Topology(id=1, tenant_id=ASI, name="标准格式拓扑", xml=STANDARD_XML, node_bindings={}))
    for i in range(1, 9):
        s.add(Asset(id=i, tenant_id=ASI, natural_id=f"DEV-{i}", name=f"DEV-{i}",
                    type="交换机", zone="Zone 1", ip=f"10.0.0.{i}"))
    s.commit()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


class TestStandardMxfile:
    def test_import_into_standard_mxfile(self, db):
        res = import_assets_as_nodes(db, ASI, 1, [1])
        assert res["added"] == 1
        topo = db.get(Topology, 1)

        g = parse_topology(topo.xml)
        assert g["error"] is None, g["error"]
        n = next(x for x in g["nodes"] if x["label"] == "DEV-1")
        assert n["zone_key"] == "Zone1"
        assert n["x"] > 0 and n["y"] > 0

    def test_new_cell_went_inside_mxgraphmodel(self, db):
        import_assets_as_nodes(db, ASI, 1, [1])
        topo = db.get(Topology, 1)
        # 关键：cell 必须落在 mxGraphModel 里，落在外面 XML 就废了
        assert "</mxGraphModel>" in topo.xml
        idx_cell = topo.xml.index("DEV-1")
        idx_open = topo.xml.index("<mxGraphModel")
        idx_close = topo.xml.index("</mxGraphModel>")
        assert idx_open < idx_cell < idx_close

    def test_new_cell_went_inside_root_element(self, db):
        """cell 必须是 ``<root>`` 的子元素 —— draw.io 只认这个结构。

        插到 ``</mxGraphModel>`` 前面（也就是 ``</root>`` 后面）的话，
        parse_topology 照样读得出来（它全文 iter），但 draw.io 打开是空图。
        """
        import_assets_as_nodes(db, ASI, 1, [1])
        topo = db.get(Topology, 1)
        assert "</root>" in topo.xml
        idx_cell = topo.xml.index("DEV-1")
        assert topo.xml.index("<root>") < idx_cell < topo.xml.index("</root>"), \
            "新 cell 跑到了 <root> 外面 —— draw.io 会打开一张空图"

    def test_original_mxfile_structure_preserved(self, db):
        import_assets_as_nodes(db, ASI, 1, [1])
        topo = db.get(Topology, 1)
        assert topo.xml.startswith("<mxfile")
        assert "<mxGraphModel" in topo.xml
        assert "</mxfile>" in topo.xml
        assert 'value="FW-EDGE-01"' in topo.xml

    def test_existing_nodes_kept(self, db):
        import_assets_as_nodes(db, ASI, 1, [1])
        g = parse_topology(db.get(Topology, 1).xml)
        labels = {n["label"] for n in g["nodes"]}
        assert "FW-EDGE-01" in labels
        assert "DEV-1" in labels

    def test_binding_created(self, db):
        res = import_assets_as_nodes(db, ASI, 1, [1])
        node_id = res["nodes"][0]["node_id"]
        m = db.query(DeviceMonitor).filter(DeviceMonitor.topology_id == 1).one()
        assert m.node_id == node_id
        assert m.natural_id == "DEV-1"
        assert m.ip == "10.0.0.1"


class TestZoneFull:
    """区域画满了怎么办 —— 扩区域，不丢节点。"""

    def test_zone_is_grown_when_full(self, db):
        # 区域 555×340 放得下 2 列 × 1 行（190+55 间距，108 顶部留白）
        res = import_assets_as_nodes(db, ASI, 1, [1, 2, 3, 4, 5])
        assert res["added"] == 5
        topo = db.get(Topology, 1)
        g = parse_topology(topo.xml)
        assert g["error"] is None
        # 所有新节点都还在区域里（没有掉出去变成 zone=None）
        new_nodes = [n for n in g["nodes"] if n["label"].startswith("DEV-")]
        assert len(new_nodes) == 5
        for n in new_nodes:
            assert n["zone_key"] == "Zone1", n

    def test_no_node_lost_when_zone_grows(self, db):
        res = import_assets_as_nodes(db, ASI, 1, [1, 2, 3, 4, 5, 6, 7, 8])
        assert res["added"] == 8
        g = parse_topology(db.get(Topology, 1).xml)
        labels = {n["label"] for n in g["nodes"]}
        for i in range(1, 9):
            assert f"DEV-{i}" in labels, f"DEV-{i} 丢了"

    def test_grown_zone_actually_got_bigger(self, db):
        import_assets_as_nodes(db, ASI, 1, [1, 2, 3, 4, 5])
        g = parse_topology(db.get(Topology, 1).xml)
        zone = next(z for z in g["zones"] if z.get("title", "").startswith("Zone 1"))
        # 扩的是宽（多一列）—— 555 放不下 5 个 190 宽的节点
        assert zone["w"] > 555, zone

    def test_nodes_do_not_overlap_each_other(self, db):
        import_assets_as_nodes(db, ASI, 1, [1, 2, 3, 4, 5])
        g = parse_topology(db.get(Topology, 1).xml)
        new_nodes = [n for n in g["nodes"] if n["label"].startswith("DEV-")]
        for i, a in enumerate(new_nodes):
            for b in new_nodes[i + 1:]:
                overlap = (
                    a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"]
                    and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"]
                )
                assert not overlap, f"{a['label']} 与 {b['label']} 重叠了"


# ── 裸片段 + 真实拓扑的区域布局 ─────────────────────────────────────────────
# 生产上那张图是**裸片段**（没有根元素），四个区域并排：
#   Zone 3 (95,70)   Zone 0 (740,70)
#   Zone 1 (1395,70) Zone 2 (740,480)
# 区域旁边就是别的区域 —— 扩区不能撞上去。这是真实布局，也是最容易出错的。
BARE_REAL_LAYOUT = """
<mxStyle name="zoneBox" value="rounded=1;fillColor=#ffffff;strokeColor=#d5e2f5;"/>
<mxStyle name="zoneTitle" value="text;html=1;fontSize=20;"/>
<mxStyle name="dev" value="rounded=1;fillColor=#e8eef9;"/>
<mxCell id="z3" value="" style="zoneBox;" x="95" y="70" w="555" h="340"/>
<mxCell id="z3t" value="Zone 3 · 岸基管理区" style="zoneTitle;" x="120" y="92" w="300" h="30"/>
<mxCell id="z0" value="" style="zoneBox;" x="740" y="70" w="555" h="340"/>
<mxCell id="z0t" value="Zone 0 · 通用业务区" style="zoneTitle;" x="765" y="92" w="300" h="30"/>
<mxCell id="z2" value="" style="zoneBox;" x="740" y="480" w="555" h="340"/>
<mxCell id="z2t" value="Zone 2 · 船员生活区" style="zoneTitle;" x="765" y="502" w="300" h="30"/>
<mxCell id="d1" value="FW-EDGE-01" style="dev;" x="135" y="178" w="190" h="60"/>
""".strip()


@pytest.fixture()
def bare_db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'b.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    s = Session()
    s.add(Topology(id=1, tenant_id=ASI, name="裸片段拓扑", xml=BARE_REAL_LAYOUT, node_bindings={}))
    for i in range(1, 9):
        s.add(Asset(id=i, tenant_id=ASI, natural_id=f"DEV-{i}", name=f"DEV-{i}",
                    type="交换机", zone="Zone 3", ip=f"10.0.0.{i}"))
    s.commit()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


class TestBareFragmentZoneGrowth:
    """裸片段格式 + 真实区域布局：扩区不能撞到旁边的区域。"""

    def test_zone_growth_respects_neighbouring_zones(self, bare_db):
        res = import_assets_as_nodes(bare_db, ASI, 1, [1, 2, 3, 4, 5])
        assert res["added"] == 5, res["skipped"]
        g = parse_topology(bare_db.get(Topology, 1).xml)
        assert g["error"] is None

        zones = {z["id"]: z for z in g["zones"]}
        # 旁边的区域不能被压到
        assert zones["z0"]["x"] == 740 and zones["z0"]["w"] == 555
        assert zones["z2"]["y"] == 480 and zones["z2"]["h"] == 340

        # 新节点都在 Zone 3 里
        for n in g["nodes"]:
            if n["label"].startswith("DEV-"):
                assert n["zone_key"] == "Zone3", n

    def test_zone3_grew_downward_not_rightward(self, bare_db):
        """右边紧挨着 Zone 0 —— 只能往下扩，不能往右扩。"""
        import_assets_as_nodes(bare_db, ASI, 1, [1, 2, 3, 4, 5])
        g = parse_topology(bare_db.get(Topology, 1).xml)
        z3 = next(z for z in g["zones"] if z["id"] == "z3")
        assert z3["w"] == 555, "不该往右扩 —— 右边是 Zone 0"
        assert z3["h"] > 340, "应该往下扩"

    def test_growth_did_not_overlap_neighbouring_zone(self, bare_db):
        import_assets_as_nodes(bare_db, ASI, 1, [1, 2, 3, 4, 5, 6, 7, 8])
        g = parse_topology(bare_db.get(Topology, 1).xml)
        z3 = next(z for z in g["zones"] if z["id"] == "z3")
        z0 = next(z for z in g["zones"] if z["id"] == "z0")
        z2 = next(z for z in g["zones"] if z["id"] == "z2")
        # z3 (95,70,w,h) 与 z0 (740,70) / z2 (740,480) 不得相交
        assert z3["x"] + z3["w"] <= z0["x"], (z3, z0)
        assert z3["x"] + z3["w"] <= z2["x"], (z3, z2)

    def test_bare_fragment_stays_bare(self, bare_db):
        """裸片段不能被套上 <root> —— 那会改变这份文件的形态。"""
        import_assets_as_nodes(bare_db, ASI, 1, [1])
        xml = bare_db.get(Topology, 1).xml
        assert "<root>" not in xml
        assert "<mxfile" not in xml
        assert "DEV-1" in xml

    def test_no_node_lost(self, bare_db):
        import_assets_as_nodes(bare_db, ASI, 1, [1, 2, 3, 4, 5, 6, 7, 8])
        g = parse_topology(bare_db.get(Topology, 1).xml)
        labels = {n["label"] for n in g["nodes"]}
        for i in range(1, 9):
            assert f"DEV-{i}" in labels, f"DEV-{i} 丢了"
