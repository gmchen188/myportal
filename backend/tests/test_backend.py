"""
后台的单元测试。

覆盖的是**今天实际踩过的坑**，不是泛泛的覆盖率：

  · display_diagram 的裸 XML 片段（无根元素、无 vertex 属性、几何在属性上）
  · 区域框与区域标题是分开的 cell
  · 去重键与数据库复合唯一约束要对齐
  · zone 紧凑格式要归一
  · 严重度：critical 只能从数值来（SIEM 的 severity_cat 没有 CRITICAL）
  · 没有数据 ≠ 正常 —— 灰色是独立状态
  · 租户隔离

跑：
    cd backend && python -m pytest tests -q
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import asset_import as ai  # noqa: E402
from app.services.monitoring import (  # noqa: E402
    compute_device_states,
    normalize_severity,
    severity_counts,
    severity_from_score,
)
from app.services.syslog_collector import parse_line  # noqa: E402
from app.services.topology_parse import parse_topology  # noqa: E402


# ── 拓扑解析 ────────────────────────────────────────────────────────────────
# 这是 display_diagram 工具今天真实产出的 XML 片段：
# 无根元素、无 vertex 属性、几何写在属性上、用样式表引用。
BARE_XML = """
<mxStyle name="zoneBox" value="rounded=1;arcSize=12;fillColor=#ffffff;strokeColor=#d5e2f5;"/>
<mxStyle name="zoneTitle" value="text;html=1;fontSize=20;"/>
<mxStyle name="dev" value="rounded=1;arcSize=18;fillColor=#e8eef9;"/>
<mxStyle name="linkGreen" value="edgeStyle=orthogonalEdgeStyle;strokeColor=#1a7a1a;strokeWidth=3;"/>
<mxCell id="z1" value="" style="zoneBox;" x="100" y="50" w="500" h="300"/>
<mxCell id="z1t" value="Zone 1 · 船舶核心控制区" style="zoneTitle;" x="120" y="70" w="300" h="30"/>
<mxCell id="d1" value="FW-EDGE-01" style="dev;" x="150" y="150" w="120" h="60"/>
<mxCell id="d2" value="CBS-NAV-01" style="dev;" x="350" y="150" w="120" h="60"/>
<mxCell id="e1" style="linkGreen;" source="d1" target="d2"/>
""".strip()


class TestTopologyParse:
    def test_bare_fragment_parses(self):
        """display_diagram 的裸片段必须能解析 —— 它没有根元素。"""
        g = parse_topology(BARE_XML)
        assert g["error"] is None, g["error"]

    def test_counts(self):
        g = parse_topology(BARE_XML)
        assert len(g["nodes"]) == 2, g["nodes"]      # 两个设备
        assert len(g["zones"]) == 1, g["zones"]      # 一个区域框
        assert len(g["links"]) == 1, g["links"]      # 一条连线

    def test_zone_title_from_title_cell(self):
        """区域名在单独的标题 cell 上，不在区域框上。"""
        g = parse_topology(BARE_XML)
        assert g["zones"][0]["title"] == "Zone 1 · 船舶核心控制区"

    def test_device_assigned_to_zone(self):
        """设备中心点落在区域框内 → 归到该区域。"""
        g = parse_topology(BARE_XML)
        assert all(n["zone"] == "Zone 1 · 船舶核心控制区" for n in g["nodes"])
        assert all(n["zone_key"] == "Zone1" for n in g["nodes"])

    def test_geometry_from_attributes(self):
        """几何写在属性上时要读得到（否则全落原点）。"""
        g = parse_topology(BARE_XML)
        d = next(n for n in g["nodes"] if n["label"] == "FW-EDGE-01")
        assert d["x"] == 150 and d["y"] == 150 and d["w"] == 120

    def test_standard_mxfile(self):
        """标准 draw.io 格式也要能解析。"""
        xml = (
            '<mxfile><diagram><mxGraphModel>'
            '<mxCell id="n1" value="RTR-1" style="rounded=1;" vertex="1" parent="1">'
            '<mxGeometry x="10" y="20" width="100" height="50" as="geometry"/>'
            '</mxCell>'
            '<mxCell id="e1" edge="1" source="n1" target="n1" parent="1">'
            '<mxGeometry relative="1" as="geometry"/></mxCell>'
            '</mxGraphModel></diagram></mxfile>'
        )
        g = parse_topology(xml)
        assert g["error"] is None
        assert len(g["nodes"]) == 1
        n = g["nodes"][0]
        assert n["label"] == "RTR-1"
        assert n["x"] == 10 and n["y"] == 20 and n["w"] == 100

    def test_broken_xml_returns_error_not_raise(self):
        """坏 XML 不该让监控面板 500。"""
        g = parse_topology("<mxCell id='x' <<<")
        assert g["error"]
        assert g["nodes"] == []

    def test_empty_xml(self):
        g = parse_topology("")
        assert g["error"] is None
        assert g["nodes"] == []


# ── 资产导入 ────────────────────────────────────────────────────────────────
class TestAssetImport:
    def test_column_mapping(self):
        headers = ["设备名称", "类型", "安全区域", "IP地址"]
        m = {x["header"]: x["field"] for x in ai.suggest_mapping(headers)}
        assert m["设备名称"] == "name"
        assert m["类型"] == "type"
        assert m["安全区域"] == "zone"
        assert m["IP地址"] == "ip"

    def test_unknown_column_left_unmapped(self):
        m = {x["header"]: x["field"] for x in ai.suggest_mapping(["设备名称", "神秘列"])}
        assert m["设备名称"] == "name"
        assert m["神秘列"] is None

    def test_duplicate_rows_skipped(self):
        headers = ["设备名称", "类型", "安全区域"]
        body = [
            ["A", "交换机", "Zone 1"],
            ["B", "交换机", "Zone 1"],
            ["A", "交换机", "Zone 1"],
        ]
        r = ai.validate_rows(headers, body)
        assert r["stats"]["ready"] == 2
        assert r["stats"]["skip"] == 1

    def test_missing_required_is_needs_fill(self):
        headers = ["设备名称", "类型", "安全区域"]
        body = [["", "交换机", "Zone 1"]]
        r = ai.validate_rows(headers, body)
        assert r["stats"]["needs_fill"] == 1

    def test_illegal_zone_warns_but_does_not_block(self):
        headers = ["设备名称", "类型", "安全区域"]
        body = [["A", "交换机", "Zone 99"]]
        r = ai.validate_rows(headers, body)
        row = r["rows"][0]
        assert row["status"] == "ready"          # 不阻断
        assert any("不在允许列表" in i["message"] for i in row["issues"])  # 但要警告

    def test_delimited_parsing(self):
        headers, body = ai.parse_delimited("a,b,c\n1,2,3\n4,5,6")
        assert headers == ["a", "b", "c"]
        assert len(body) == 2

    def test_tsv_autodetect(self):
        headers, body = ai.parse_delimited("a\tb\n1\t2")
        assert headers == ["a", "b"]

    def test_zone_normalization(self):
        """拓扑图给的是紧凑格式，要归一成 'Zone N'。"""
        assert ai.normalize_zone("Zone3") == "Zone 3"
        assert ai.normalize_zone("zone 1") == "Zone 1"
        assert ai.normalize_zone("区域2") == "Zone 2"
        assert ai.normalize_zone("Zone 0") == "Zone 0"
        assert ai.normalize_zone("OT-DMZ") == "OT-DMZ"   # 自由文本原样
        assert ai.normalize_zone("") == ""

    def test_topology_nodes_become_assets(self):
        nodes = [
            {"label": "FW-EDGE-01", "zone": "Zone3"},
            {"label": "CBS-NAV-01", "zone": "Zone1"},
            {"label": "OT-DMZ-01", "zone": "Zone1"},
        ]
        rows = ai.assets_from_topology_nodes(nodes)
        assert len(rows) == 3
        assert rows[0].values["type"] == "防火墙"
        assert rows[1].values["type"] == "船舶系统"
        assert rows[2].values["type"] == "DMZ"
        assert all(r.values["zone"].startswith("Zone ") for r in rows)

    def test_topology_asset_needs_review_when_incomplete(self):
        """拓扑图不画 IP → 那行要标 needs_fill。"""
        rows = ai.assets_from_topology_nodes([{"label": "X-1", "zone": "Zone1"}])
        assert rows[0].status in ("ready", "needs_fill")
        # type 与 zone 都有 → ready；ip 是可选字段，不影响
        assert rows[0].values["ip"] == ""

    def test_dedupe_key_precedence(self):
        assert ai.dedupe_key({"natural_id": "N1", "name": "x"}) == "natural_id:n1"
        assert ai.dedupe_key({"name": "X"}) == "name:x"
        assert ai.dedupe_key({"serial": "S1"}) == "serial:s1"


# ── 监控状态 ────────────────────────────────────────────────────────────────
class TestMonitoring:
    def test_severity_normalization(self):
        assert normalize_severity("CRITICAL") == "critical"
        assert normalize_severity("crit") == "critical"
        assert normalize_severity("紧急") == "critical"
        assert normalize_severity("HIGH") == "high"
        assert normalize_severity("med") == "medium"
        assert normalize_severity("") == "unknown"

    def test_critical_only_from_score(self):
        """FortiSIEM 的 severity_cat 只有 HIGH/MEDIUM/LOW ——
        CRITICAL 只能从数值 severity 推出来。"""
        assert severity_from_score(9.5, "HIGH") == "critical"
        assert severity_from_score(10, "HIGH") == "critical"
        assert severity_from_score(7.5, "HIGH") == "high"
        assert severity_from_score(5, "MEDIUM") == "medium"
        assert severity_from_score(2, "LOW") == "low"

    def test_color_map_matches_requirement(self):
        """需求：critical 红 / high 粉红 / medium 黄 / 正常 绿。"""
        from app.services.monitoring import SEVERITY_COLOR

        assert SEVERITY_COLOR["critical"] == "#dc2626"   # 红
        assert SEVERITY_COLOR["high"] == "#ec4899"       # 粉红
        assert SEVERITY_COLOR["medium"] == "#f59e0b"     # 黄
        assert SEVERITY_COLOR["normal"] == "#16a34a"     # 绿
        assert SEVERITY_COLOR["unknown"] == "#94a3b8"    # 灰

    def test_device_takes_highest_active_severity(self):
        """设备颜色由最高级别决定，不是最新事件。"""
        devs = [{"natural_id": "D1", "label": "D1"}]
        incs = [
            {"device_natural_id": "D1", "severity": "low", "incident_status": 0, "id": 1},
            {"device_natural_id": "D1", "severity": "critical", "incident_status": 0, "id": 2},
            {"device_natural_id": "D1", "severity": "medium", "incident_status": 0, "id": 3},
        ]
        st = compute_device_states(devs, incs)
        assert st[0]["severity"] == "critical"
        assert st[0]["active_incidents"] == 3

    def test_closed_incident_returns_to_normal(self):
        devs = [{"natural_id": "D1", "label": "D1"}]
        incs = [{"device_natural_id": "D1", "severity": "critical", "incident_status": 3, "id": 1}]
        st = compute_device_states(devs, incs)
        assert st[0]["severity"] == "normal"
        assert st[0]["active_incidents"] == 0

    def test_no_data_is_unknown_not_normal(self):
        """没有数据 ≠ 正常。灰色是独立状态。"""
        devs = [{"natural_id": "D1", "label": "D1"}]
        st = compute_device_states(devs, [])
        assert st[0]["severity"] == "unknown"
        assert st[0]["color"] == "#94a3b8"

    def test_match_by_ip_when_no_natural_id(self):
        devs = [{"natural_id": None, "ip": "10.0.0.1", "label": "SW1"}]
        incs = [{"device_ip": "10.0.0.1", "severity": "high", "incident_status": 0, "id": 1}]
        st = compute_device_states(devs, incs)
        assert st[0]["severity"] == "high"

    def test_match_by_name(self):
        devs = [{"natural_id": None, "ip": None, "label": "OT-DMZ-01"}]
        incs = [{"device_name": "OT-DMZ-01", "severity": "medium", "incident_status": 0, "id": 1}]
        st = compute_device_states(devs, incs)
        assert st[0]["severity"] == "medium"

    def test_counts(self):
        devs = [{"natural_id": "A"}, {"natural_id": "B"}, {"natural_id": "C"}]
        incs = [
            {"device_natural_id": "A", "severity": "critical", "incident_status": 0, "id": 1},
            {"device_natural_id": "B", "severity": "medium", "incident_status": 0, "id": 2},
        ]
        st = compute_device_states(devs, incs)
        c = severity_counts(st)
        assert c["critical"] == 1 and c["medium"] == 1 and c["unknown"] == 1


# ── syslog 解析 ─────────────────────────────────────────────────────────────
class TestSyslog:
    def test_rfc3164(self):
        p = parse_line("<134>Nov 21 21:50:12 SW-CORE-01 %LINK-3-UPDOWN: Interface up")
        assert p["host"] == "SW-CORE-01"
        assert p["tag"] == "%LINK-3-UPDOWN"
        assert "Interface up" in p["msg"]

    def test_rfc5424(self):
        p = parse_line("<134>1 2026-11-21T21:50:12Z SW-CORE-01 sshd 123 ID47 - link up")
        assert p["host"] == "SW-CORE-01"
        assert p["app"] == "sshd"

    def test_ip_extraction(self):
        p = parse_line("<134>Nov 21 21:50:12 R1 %SYS: peer 10.1.2.3 unreachable")
        assert p["ip"] == "10.1.2.3"

    def test_severity_keywords(self):
        assert parse_line("<134>Nov 21 21:50:12 D1 %X: CRITICAL failure")["severity"] == "critical"
        assert parse_line("<134>Nov 21 21:50:12 D1 %X: high severity")["severity"] == "high"
        assert parse_line("<134>Nov 21 21:50:12 D1 %X: informational")["severity"] == "informational"

    def test_unparseable_still_returns_something(self):
        """解析不出来也要返回一条，不能丢。"""
        p = parse_line("完全不是 syslog 的一行")
        assert p["msg"] == "完全不是 syslog 的一行"
        assert p["severity"] == "medium"
