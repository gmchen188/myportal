"""
FortiSIEM 设备 → 拓扑节点的**自动绑定**测试。

被测的函数（backend/app/services/monitoring.py）：

    match_device_to_nodes(device, nodes) -> list[dict]

## 为什么要这个函数

拓扑图上的节点只有标签（FW-EDGE-01 / CBS-NAV-01），SIEM 里的设备只有
natural_id 和 IP。两边对不上 → 真实事件落不到任何节点上 → 监控面板永远是
灰的。自动匹配让「从 SIEM 同步进来的设备」直接接进已有的拓扑图，不需要
人工维护 device_monitors 绑定表。

实测的两侧现状（互不相交）：

    拓扑 11 个节点   FW-EDGE-01 / CBS-NAV-01 / OT-DMZ-01 / CBS-PROP-01 …
    device_monitors  4 条绑定，如 (node_id=d1, natural_id=FW-EDGE-01, ip=172.16.10.1)
    SIEM 真实设备    DC01.goad.lab(172.16.0.30) / fortisiem751.binqsoft.com(172.16.20.48)
                     / HOST-1.1.1.1(1.1.1.1)

## 匹配语义（与 compute_device_states 一致）

    1. natural_id == 节点 label   （大小写不敏感）
    2. device.name == 节点 label
    3. device.ip == 节点 ip

**三个键不互斥 —— 命中即全收。** 依据是同文件里 `compute_device_states`
的既有做法：它把 natural_id / IP / 名称三个键依次试，每一把都把自己命中
的事件全部收进 `matched`（用 `seen` 按对象去重），**不是命中第一个键就
停**。所以一台设备同时能对上两个不同节点时，两个节点都要返回 ——
这里保持同一套语义，不搞「优先级短路」。这样也符合直觉：设备名对上了
一个节点、IP 又对上了另一个节点，那它俩都可能是。

三条硬规则：

    1. **空值不参与匹配** —— device.ip 为 None/空串时，绝不能匹配到
       「没有 ip 的节点」。那会把一台设备绑到几十个节点上。
    2. **大小写不敏感** —— SIEM 的 naturalId 可能有大小写差异。
    3. **natural_id 先 URL 解码** —— FortiSIEM 返回的 naturalId 是 URL
       编码的（"HOST%2d1.1.1.1"，%2d 就是 "-"），不解码对不上标签。

## 第 11 条的语义决定

「natural_id 和 ip 同时能匹配到**不同**节点」→ **两个都返回**。

依据：`compute_device_states`（monitoring.py:263-276）的三键依次试、
命中即全收、只用 `seen` 做去重 —— 没有「第一个键命中就 break」的短路。
`match_device_to_nodes` 是同一份匹配语义在「设备↔节点」方向上的对应物，
所以同样全收。同一节点被多把键命中时只返回一次（按 node id 去重）。

纯函数测试，不碰网络、不碰数据库。

跑：
    cd backend && "C:/Python314/python.exe" -m pytest tests -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.monitoring import match_device_to_nodes  # noqa: E402


# ── 夹具 ────────────────────────────────────────────────────────────────────
#
# 节点形状取自拓扑解析（app/services/topology_parse.py 的 parse_topology）：
# 每个设备节点有 id / label，ip 来自 device_monitors 绑定（可能没有）。
def node(nid: str, label: str, ip: str | None = None) -> dict:
    n: dict = {"id": nid, "label": label}
    if ip is not None:
        n["ip"] = ip
    return n


# 实机拓扑的 11 个节点（节选）+ 4 条绑定里的一条
REAL_NODES = [
    node("d1", "FW-EDGE-01", "172.16.10.1"),
    node("d2", "CBS-NAV-01", "172.16.10.2"),
    node("d3", "OT-DMZ-01", "172.16.30.1"),
    node("d4", "CBS-PROP-01", "172.16.40.1"),
]


def ids(matched: list[dict]) -> list[str]:
    return [n["id"] for n in matched]


# ── 规则 1：natural_id == 节点 label ────────────────────────────────────────
class TestNaturalIdMatch:
    def test_exact_natural_id_matches_label(self):
        """natural_id 与节点 label 完全相同 → 匹配。"""
        matched = match_device_to_nodes(
            {"natural_id": "FW-EDGE-01", "name": "firewall", "ip": "10.0.0.9"},
            REAL_NODES,
        )
        assert ids(matched) == ["d1"]

    def test_case_insensitive(self):
        """大小写不同也匹配 —— SIEM 的 naturalId 大小写不可靠。

        实机返回过 "DC01.goad.lab" 这种带大小写的 FQDN，也可能有全小写。
        """
        matched = match_device_to_nodes(
            {"natural_id": "dc01.goad.lab", "name": "dc01", "ip": "172.16.0.30"},
            [node("d9", "DC01.goad.lab")],
        )
        assert ids(matched) == ["d9"]

    def test_label_with_surrounding_whitespace_still_matches(self):
        """节点 label 带首尾空格 → 去掉空格再比。

        拓扑节点的 label 是从 draw.io 的 value 属性里清洗来的，人手写图时
        常带空格。比较前统一 strip。
        """
        matched = match_device_to_nodes(
            {"natural_id": "FW-EDGE-01", "name": "fw", "ip": None},
            [node("d1", "  FW-EDGE-01  ")],
        )
        assert ids(matched) == ["d1"]

    def test_device_fields_are_trimmed_too(self):
        """设备侧的空格同样去掉 —— 两边都 strip 才对称。"""
        matched = match_device_to_nodes(
            {"natural_id": "  FW-EDGE-01  ", "name": "fw", "ip": None},
            [node("d1", "FW-EDGE-01")],
        )
        assert ids(matched) == ["d1"]

    def test_url_encoded_natural_id_is_decoded(self):
        """natural_id 是 URL 编码的 → 先解码再比。

        FortiSIEM 的 naturalId 字段实机返回 "HOST%2d1.1.1.1"，%2d 就是 "-"。
        不解码的话这个自然 ID 与标签对不上，绑定直接落空。
        """
        matched = match_device_to_nodes(
            {"natural_id": "HOST%2d1.1.1.1", "name": "host", "ip": "1.1.1.1"},
            [node("d5", "HOST-1.1.1.1")],
        )
        assert ids(matched) == ["d5"]

    def test_url_decoded_natural_id_matches_label_with_ip_also_set(self):
        """解码后与 label 相同就算命中 —— 不管这台设备还有 IP。"""
        matched = match_device_to_nodes(
            {"natural_id": "HOST%2d1.1.1.1", "name": "host", "ip": "9.9.9.9"},
            [node("d5", "HOST-1.1.1.1", "1.1.1.1")],
        )
        assert ids(matched) == ["d5"]


# ── 规则 2：device.name == 节点 label ──────────────────────────────────────
class TestNameMatch:
    def test_name_matches_when_natural_id_does_not(self):
        """natural_id 对不上、name 对得上 → 照样匹配。

        SIEM 里 natural_id 和 name 经常不是一回事（natural_id 可能是
        FQDN，name 是设备号）。规则 2 就是兜这一手。
        """
        matched = match_device_to_nodes(
            {"natural_id": "some-other-id", "name": "FW-EDGE-01", "ip": None},
            REAL_NODES,
        )
        assert ids(matched) == ["d1"]

    def test_name_match_is_case_insensitive(self):
        matched = match_device_to_nodes(
            {"natural_id": "x", "name": "fw-edge-01", "ip": None},
            REAL_NODES,
        )
        assert ids(matched) == ["d1"]


# ── 规则 3：device.ip == 节点 ip ───────────────────────────────────────────
class TestIpMatch:
    def test_ip_matches_node_ip(self):
        """IP 相同 → 匹配（自然 ID 和名字都不对得上也没关系）。"""
        matched = match_device_to_nodes(
            {"natural_id": "DC01.goad.lab", "name": "dc01", "ip": "172.16.10.1"},
            REAL_NODES,
        )
        assert ids(matched) == ["d1"]

    def test_ip_match_ignores_case_and_padding(self):
        """IP 比较同样去空格；大小写不敏感对 IP 也无害（十六进制段）。"""
        matched = match_device_to_nodes(
            {"natural_id": "x", "name": "y", "ip": " 172.16.10.1 "},
            REAL_NODES,
        )
        assert ids(matched) == ["d1"]

    def test_access_ip_is_accepted_as_alias(self):
        """SIEM 连接器返回的 IP 字段叫 access_ip，不是 ip。

        `FortiSiemClient.devices()` 归一出来的字典键是
        name / natural_id / access_ip / sn / org / vendor / model / version ——
        **没有 ip**。所以真实 SIEM 设备要靠 access_ip 才能落到节点上。
        """
        matched = match_device_to_nodes(
            {"natural_id": "fortisiem751.binqsoft.com", "name": "siem", "access_ip": "172.16.20.48"},
            [node("d7", "SIEM-CORE-01", "172.16.20.48")],
        )
        assert ids(matched) == ["d7"]


# ── 规则 4：都不匹配 ────────────────────────────────────────────────────────
class TestNoMatch:
    def test_completely_unrelated_device_returns_empty(self):
        """三个键都对不上 → 空列表（不是 None，不是抛异常）。"""
        matched = match_device_to_nodes(
            {"natural_id": "DC01.goad.lab", "name": "dc01", "ip": "172.16.0.30"},
            REAL_NODES,
        )
        assert matched == []

    def test_empty_nodes_list_returns_empty(self):
        assert match_device_to_nodes({"natural_id": "FW-EDGE-01"}, []) == []

    def test_device_with_no_usable_fields_returns_empty(self):
        """设备字典全空 → 不匹配任何节点。"""
        matched = match_device_to_nodes({"natural_id": None, "name": None, "ip": None}, REAL_NODES)
        assert matched == []


# ── 硬规则 1：空值不参与匹配 ───────────────────────────────────────────────
class TestEmptyValuesDoNotMatch:
    """**最重要的一条** —— 空值不能互相匹配。

    device.ip 是 None，节点也没有 ip —— 这不是「相等」，这是「都没说」。
    把它当成相等，一台设备会绑到所有没填 IP 的节点上（实机 11 个节点里
    一大半没填 ip），监控面板会亮一片假颜色。
    """

    def test_none_ip_does_not_match_node_without_ip(self):
        matched = match_device_to_nodes(
            {"natural_id": "DC01.goad.lab", "name": "dc01", "ip": None},
            [node("d1", "FW-EDGE-01")],  # 节点没有 ip 字段
        )
        assert matched == []

    def test_none_ip_does_not_match_node_with_empty_ip(self):
        """节点的 ip 是空串也算「没有 ip」。"""
        matched = match_device_to_nodes(
            {"natural_id": "DC01.goad.lab", "name": "dc01", "ip": None},
            [node("d1", "FW-EDGE-01", "")],
        )
        assert matched == []

    def test_empty_string_ip_does_not_match_node_without_ip(self):
        """device.ip 为 "" 与 None 同义 —— 都不参与匹配。"""
        matched = match_device_to_nodes(
            {"natural_id": "DC01.goad.lab", "name": "dc01", "ip": ""},
            [node("d1", "FW-EDGE-01")],
        )
        assert matched == []

    def test_empty_string_ip_does_not_match_node_with_empty_ip(self):
        matched = match_device_to_nodes(
            {"natural_id": "DC01.goad.lab", "name": "dc01", "ip": ""},
            [node("d1", "FW-EDGE-01", "")],
        )
        assert matched == []

    def test_none_ip_does_not_match_other_nodes_with_real_ips(self):
        """空 IP 不能顺带匹配到那些有真 IP 的节点。"""
        matched = match_device_to_nodes(
            {"natural_id": "DC01.goad.lab", "name": "dc01", "ip": None},
            REAL_NODES,
        )
        assert matched == []

    def test_empty_natural_id_and_name_do_not_match_empty_label(self):
        """空 natural_id / 空 name 不能匹配到空 label 的节点。"""
        matched = match_device_to_nodes(
            {"natural_id": "", "name": "", "ip": None},
            [node("d1", "")],
        )
        assert matched == []


# ── 多节点命中 ──────────────────────────────────────────────────────────────
class TestMultipleMatches:
    def test_duplicate_labels_all_returned_in_input_order(self):
        """多个节点 label 相同 → 全部返回，保持输入顺序。

        拓扑图里画两个同名节点不常见但合法（同名不同区的两台设备）。
        漏掉一个 = 少亮一个节点。
        """
        nodes = [
            node("d1", "FW-EDGE-01"),
            node("d2", "OT-DMZ-01"),
            node("d3", "FW-EDGE-01"),
        ]
        matched = match_device_to_nodes({"natural_id": "FW-EDGE-01"}, nodes)
        assert ids(matched) == ["d1", "d3"]

    def test_same_node_hit_by_two_keys_returned_once(self):
        """同一个节点被 natural_id 和 ip 同时命中 → 只返回一次。

        「命中即全收」不等于「同一个节点返回两遍」——去重按 node id。
        """
        nodes = [node("d1", "FW-EDGE-01", "172.16.10.1")]
        matched = match_device_to_nodes(
            {"natural_id": "FW-EDGE-01", "name": "FW-EDGE-01", "ip": "172.16.10.1"},
            nodes,
        )
        assert ids(matched) == ["d1"]

    def test_natural_id_and_ip_matching_different_nodes_returns_both(self):
        """**语义决定**：natural_id 和 ip 匹配到不同节点 → 两个都返回。

        依据：同文件的 `compute_device_states` 是「三键依次试、命中即全收」，
        每个键把自己命中的都收进 matched，用 seen 去重，**没有**「第一个键
        命中就 break」的短路。match_device_to_nodes 是同一套语义在
        「设备↔节点」方向上的对应物 —— 所以这里也是全收。

        只返回一个会漏节点：设备名对上一个节点、IP 又对上一个节点，
        那是两个真实的节点，都该亮。
        """
        nodes = [
            node("d1", "FW-EDGE-01"),          # natural_id 命中
            node("d2", "CBS-NAV-01", "1.1.1.1"),  # ip 命中
        ]
        matched = match_device_to_nodes(
            {"natural_id": "FW-EDGE-01", "name": "fw", "ip": "1.1.1.1"},
            nodes,
        )
        assert ids(matched) == ["d1", "d2"]

    def test_returned_entries_are_the_original_node_dicts(self):
        """返回的是原节点字典本身 —— 调用方要拿 node_id 去写绑定。"""
        nodes = [node("d1", "FW-EDGE-01", "172.16.10.1")]
        matched = match_device_to_nodes({"natural_id": "FW-EDGE-01"}, nodes)
        assert len(matched) == 1
        assert matched[0] is nodes[0]
        assert matched[0]["id"] == "d1"


# ── 节点 label 的别名 ──────────────────────────────────────────────────────
class TestNodeLabelAlias:
    def test_node_label_key_is_accepted(self):
        """device_monitors.to_dict() 里字段名是 node_label —— 也要认。"""
        matched = match_device_to_nodes(
            {"natural_id": "FW-EDGE-01", "name": "fw", "ip": None},
            [{"id": "d1", "node_label": "FW-EDGE-01"}],
        )
        assert ids(matched) == ["d1"]
