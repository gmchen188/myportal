"""CMDB 推送 —— 字段映射、XML 生成、错误分类。

这些是**纯函数**，不碰网络，所以能离线测。

**为什么映射要单独测**：映射错了不会报错，会静默地把 `zone` 写进
`description` 之类的字段 —— 船舶场景下这等于把合规属性写错地方，
比报个错更糟。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.cmdb_push import (
    CMDB_FIELD_MAP,
    MappedAsset,
    SiemWriteError,
    build_add_xml,
    classify_write_error,
    map_asset,
)


@dataclass
class FakeAsset:
    """最小 Asset 替身 —— 只给映射用到的字段。"""

    id: int = 1
    natural_id: str | None = "FW-EDGE-01"
    name: str = "边缘防火墙"
    type: str = "防火墙"
    zone: str | None = "Zone 2"
    ip: str | None = "10.0.0.1"
    vendor: str | None = "Fortinet"
    model: str | None = "FortiGate 100F"
    serial: str | None = "FG100FTK2001"
    owner: str | None = "张三"
    cbs_class: str | None = "SL2"
    status: str | None = "在用"
    notes: str | None = "驾驶台网关"


class TestMapAsset:
    def test_maps_to_top_level_cmdb_fields(self):
        """zone 和 cbs_class 要落到顶层自由字段（deviceTag / purdueLevel）。

        这不是设计偏好 —— 是实机探测出来的：
        `POST /phoenix/rest/pub/device` 的 JSON 顶层就有 `deviceTag` 和
        `purdueLevel`。塞进 description 不会报错，但等于把船舶安全区域
        和 IEC 62443 分级写成了备注 —— 合规上等于没写。
        """
        m = map_asset(FakeAsset())
        assert m.fields["deviceTag"] == "Zone 2"
        assert m.fields["purdueLevel"] == "SL2"
        assert m.fields["contact"] == "张三"
        assert m.fields["name"] == "边缘防火墙"
        assert m.fields["accessIp"] == "10.0.0.1"

    def test_maps_device_type_subfields(self):
        m = map_asset(FakeAsset())
        assert m.fields["deviceType.vendor"] == "Fortinet"
        assert m.fields["deviceType.model"] == "FortiGate 100F"
        assert m.fields["hwSerialNum"] == "FG100FTK2001"
        assert m.fields["importance"] == "在用"
        assert m.fields["description"] == "驾驶台网关"

    def test_skips_internal_fields(self):
        """natural_id 是 myPortal 的去重键，type 是内部分类 —— 都不推。"""
        m = map_asset(FakeAsset())
        assert "natural_id" in m.skipped
        assert "type" in m.skipped
        assert not any("natural_id" in k for k in m.fields)

    def test_empty_values_are_not_mapped(self):
        """空值不推 —— 推空串会把 CMDB 的字段覆盖成空。"""
        a = FakeAsset(zone=None, ip=None, cbs_class=None, serial=None, owner=None)
        m = map_asset(a)
        assert "deviceTag" not in m.fields
        assert "accessIp" not in m.fields
        assert "purdueLevel" not in m.fields

    def test_missing_name_is_flagged(self):
        m = map_asset(FakeAsset(name=""))
        assert "name" in m.missing


class TestBuildXml:
    def test_produces_devices_root(self):
        xml = build_add_xml([map_asset(FakeAsset())])
        assert xml.startswith('<?xml version="1.0" encoding="UTF-8" ?>')
        assert "<Devices>" in xml and "</Devices>" in xml
        assert "<Device>" in xml

    def test_contains_mapped_fields(self):
        xml = build_add_xml([map_asset(FakeAsset())])
        assert "<name>边缘防火墙</name>" in xml
        assert "<accessIp>10.0.0.1</accessIp>" in xml
        assert "<deviceTag>Zone 2</deviceTag>" in xml
        assert "<purdueLevel>SL2</purdueLevel>" in xml
        assert "<contact>张三</contact>" in xml
        assert "<vendor>Fortinet</vendor>" in xml

    def test_batches_multiple_devices(self):
        """一次报文带多台 —— 官方端点是异步的，一次提交一批更省往返。"""
        xml = build_add_xml([
            map_asset(FakeAsset(id=1, name="交换机A")),
            map_asset(FakeAsset(id=2, name="交换机B")),
        ])
        assert xml.count("<Device>") == 2
        assert "<name>交换机A</name>" in xml
        assert "<name>交换机B</name>" in xml

    def test_escapes_xml_special_chars(self):
        """**XML 转义不能漏** —— 资产名里出现 `&` 或 `<` 会让整个报文解析失败，
        而且报错信息往往不指向真正的字段。"""
        xml = build_add_xml([map_asset(FakeAsset(name="A&B<C>D", notes='"引号" & 符号'))])
        assert "&amp;" in xml
        assert "&lt;" in xml
        assert "&gt;" in xml
        # 不能有裸的未转义 &
        assert "<name>A&B" not in xml

    def test_omits_empty_fields(self):
        xml = build_add_xml([map_asset(FakeAsset(zone=None, owner=None, ip=None))])
        assert "<deviceTag>" not in xml
        assert "<contact>" not in xml
        assert "<accessIp>" not in xml


class TestClassifyWriteError:
    def test_locked_is_distinct_from_unauthorized(self):
        """**这两种 403 语义完全不同，混为一谈会误导人。**

        - locked：等锁定期过就行，跟权限无关
        - unauthorized：要去申请权限

        我就是被这个坑过 —— 穷举用户名试错把账号试锁了，
        一开始看到 403 以为是「权限不够」，差点得出错误结论。
        """
        locked = classify_write_error(
            403,
            "Error report HTTP Status 403 - Account locked due to consecutive login failures.",
        )
        assert locked.kind == "locked"

        unauth = classify_write_error(
            403, "User is not authorized to access this resource."
        )
        assert unauth.kind == "unauthorized"

    def test_401_is_unauthorized(self):
        e = classify_write_error(401, "")
        assert e.kind == "unauthorized"

    def test_400_is_bad_request(self):
        e = classify_write_error(400, "malformed xml")
        assert e.kind == "bad_request"

    def test_gateway_errors_are_network(self):
        for code in (502, 503, 504):
            assert classify_write_error(code, "").kind == "network"

    def test_message_is_actionable(self):
        """错误文案要说清下一步做什么 —— 用户看到「HTTP 403」不知道该干嘛。"""
        e = classify_write_error(
            403, "Account locked due to consecutive login failures."
        )
        assert "锁定" in str(e)
        e2 = classify_write_error(403, "User is not authorized to access this resource.")
        assert "权限" in str(e2)
