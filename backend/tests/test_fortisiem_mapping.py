"""
FortiSIEM 字段映射的回归测试。

被测的两个纯函数（backend/app/connectors/fortisiem.py）：

  · severity_from_siem(cat, score)  —— (eventSeverityCat, eventSeverity) → 我方级别
  · _parse_kv_blob(raw)             —— "srcIpAddr:1.2.3.4, srcGeoCountry:, " → dict

**核心语义：严重度以类别为准，不以数值为准。**
实机（FortiSIEM 7.5.1 / 172.16.20.48）数据里两者是冲突的：

    (eventSeverity=6, eventSeverityCat='MEDIUM') → medium
    (eventSeverity=7, eventSeverityCat='MEDIUM') → medium   ← 数值 7 看着像 high
    (eventSeverity=9, eventSeverityCat='HIGH')   → high     ← 数值 9 看着像 critical

SIEM 的类别是它的**判定结果**，数值只是它用来判定的输入之一。拿输入推翻结论
会得到错色（critical 红 vs high 粉红）。所以类别认得就用类别；类别缺失或
认不出才退回数值兜底（>=9 critical / >=7 high / >=4 medium / >=1 low / 都无 → unknown）。

注意这与 services/monitoring.py 的 severity_from_score() 语义不同 —— 那个给
webhook/syslog 用（severity 是 0-100 分数惯例，数值优先合理）。**两个来源不能共用
一套规则**，所以这里测的是 connector 自己的那套。

全部是纯函数 / 假客户端，不碰网络。

跑：
    cd backend && "C:/Python314/python.exe" -m pytest tests -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.connectors.fortisiem import (  # noqa: E402
    FortiSiemClient,
    _parse_kv_blob,
    severity_from_siem,
)


# ── severity_from_siem：类别优先 ───────────────────────────────────────────
class TestSeverityFromSiem:
    def test_real_machine_category_wins_over_score(self):
        """实机三个组合 —— 类别说了算，数值被忽略。

        这三条是整个函数的立身之本：数值 7 / 9 会把人（和旧代码）带偏。
        """
        assert severity_from_siem("MEDIUM", 6) == "medium"
        assert severity_from_siem("MEDIUM", 7) == "medium"   # 数值 7 但类别是 MEDIUM
        assert severity_from_siem("HIGH", 9) == "high"       # 数值 9 但类别是 HIGH

    def test_score_ignored_entirely_when_category_present(self):
        """只要类别认得，数值多大都不改变结论 —— 极端值也要压住。"""
        assert severity_from_siem("LOW", 10) == "low"
        assert severity_from_siem("MEDIUM", 9) == "medium"
        assert severity_from_siem("HIGH", 1) == "high"

    def test_missing_category_falls_back_to_score(self):
        """类别缺失（None）→ 数值兜底四档。"""
        assert severity_from_siem(None, 9) == "critical"
        assert severity_from_siem(None, 10) == "critical"
        assert severity_from_siem(None, 7) == "high"
        assert severity_from_siem(None, 4) == "medium"
        assert severity_from_siem(None, 1) == "low"

    def test_score_fallback_boundaries(self):
        """数值兜底的分档边界：>=9 / >=7 / >=4 / >=1。"""
        assert severity_from_siem(None, 9.0) == "critical"
        assert severity_from_siem(None, 8.9) == "high"
        assert severity_from_siem(None, 7.0) == "high"
        assert severity_from_siem(None, 6.9) == "medium"
        assert severity_from_siem(None, 4.0) == "medium"
        assert severity_from_siem(None, 3.9) == "low"
        assert severity_from_siem(None, 1.0) == "low"
        assert severity_from_siem(None, 0.5) == "unknown"   # 不到 1 → unknown

    def test_no_category_and_no_score_is_unknown(self):
        """两边都没有 → unknown（不是 low、不是 normal）。"""
        assert severity_from_siem(None, None) == "unknown"

    def test_empty_category_treated_as_missing(self):
        """空串 / 纯空白 = 类别缺失，不是「认不出」之外的第三种情况。"""
        assert severity_from_siem("", 8) == "high"
        assert severity_from_siem("   ", 5) == "medium"
        assert severity_from_siem("", None) == "unknown"

    def test_case_insensitive(self):
        """类别大小写不敏感（实机是大写，但不能只认大写）。"""
        assert severity_from_siem("high", 9) == "high"
        assert severity_from_siem("HIGH", 9) == "high"
        assert severity_from_siem(" High ", 9) == "high"
        assert severity_from_siem("medium", 6) == "medium"
        assert severity_from_siem("MeDiUm", 6) == "medium"
        assert severity_from_siem("low", 2) == "low"
        assert severity_from_siem("critical", 5) == "critical"

    def test_informational_aliases(self):
        """'informational' 与 'info' 都映射到我方 informational。"""
        assert severity_from_siem("informational", 1) == "informational"
        assert severity_from_siem("INFORMATIONAL", 1) == "informational"
        assert severity_from_siem("info", 1) == "informational"
        assert severity_from_siem("INFO", 1) == "informational"

    def test_unknown_category_falls_back_to_score(self):
        """不认识的类别（如 'WEIRD'）→ 退回数值，而不是崩掉或瞎猜。"""
        assert severity_from_siem("WEIRD", 9) == "critical"
        assert severity_from_siem("WEIRD", 7) == "high"
        assert severity_from_siem("WEIRD", 4) == "medium"
        assert severity_from_siem("WEIRD", 1) == "low"
        # 类别不认识、数值也没有 → unknown
        assert severity_from_siem("WEIRD", None) == "unknown"


# ── _parse_kv_blob：解析 SIEM 的逗号分隔 KV 串 ─────────────────────────────
class TestParseKvBlob:
    def test_real_machine_src_blob(self):
        """实机 incidentSrc 原样：空值的键不应出现在结果里。"""
        raw = "srcIpAddr:172.16.0.57, srcGeoCountry:, "
        assert _parse_kv_blob(raw) == {"srcIpAddr": "172.16.0.57"}
        assert "srcGeoCountry" not in _parse_kv_blob(raw)

    def test_real_machine_target_blob(self):
        """实机 incidentTarget 原样：三个键各对应正确值。"""
        raw = "destName:fortisiem751.binqsoft.com, destIpAddr:172.16.20.48, user:admin, "
        assert _parse_kv_blob(raw) == {
            "destName": "fortisiem751.binqsoft.com",
            "destIpAddr": "172.16.20.48",
            "user": "admin",
        }

    def test_none_and_empty(self):
        assert _parse_kv_blob(None) == {}
        assert _parse_kv_blob("") == {}

    def test_no_colon_is_not_a_pair(self):
        """没有冒号的片段直接丢掉，不是键值对。"""
        assert _parse_kv_blob("novalue") == {}
        assert _parse_kv_blob("novalue, other") == {}

    def test_value_may_contain_colon(self):
        """按第一个冒号切，值里的冒号要保住（URL 之类）。"""
        assert _parse_kv_blob("url:https://172.16.20.48/phoenix") == {
            "url": "https://172.16.20.48/phoenix"
        }

    def test_whitespace_around_keys_and_values_is_trimmed(self):
        assert _parse_kv_blob(" user : admin ") == {"user": "admin"}

    def test_first_occurrence_wins(self):
        """同一个键出现多次 → 取第一个（SIEM 串里靠前的通常是主值）。"""
        assert _parse_kv_blob("srcIpAddr:1.1.1.1, srcIpAddr:2.2.2.2") == {
            "srcIpAddr": "1.1.1.1"
        }


# ── 接线验证：connector 确实用的是这套规则 ─────────────────────────────────
class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    """假 httpx 客户端 —— 只回预置 payload，不发任何网络请求。

    按 URL 路由：认证端点回 token，事件端点回 payload。
    """

    def __init__(self, payload):
        self._payload = payload
        self.calls = []

    def post(self, url, json=None, headers=None, data=None, **kwargs):
        self.calls.append({"url": url, "json": json, "data": data})
        if url.endswith("/security/oauth/token"):
            return _FakeResponse({"access_token": "fake-token", "expires_in": 900})
        return _FakeResponse(self._payload)


class TestFortiSiemIncidentNormalization:
    """用假客户端跑 incidents()，确认归一化链路真的接上了这两个函数。"""

    def _client(self, monkeypatch, payload):
        client = FortiSiemClient(client_id="id", client_secret="secret", org="Super")
        fake = _FakeClient(payload)
        monkeypatch.setattr(client, "_ensure_client", lambda: fake)
        return client, fake

    def test_incident_uses_category_for_severity_and_parses_blobs(self, monkeypatch):
        payload = {
            "data": [
                {
                    "incidentId": 4711,
                    "incidentTitle": "Firewall login failed",
                    "eventSeverityCat": "HIGH",
                    "eventSeverity": 9,
                    "customer": "Super",
                    "incidentSrc": "srcIpAddr:172.16.0.57, srcGeoCountry:, ",
                    "incidentTarget": (
                        "destName:fortisiem751.binqsoft.com, "
                        "destIpAddr:172.16.20.48, user:admin, "
                    ),
                    "incidentRptDevName": "FW-EDGE-01",
                    "incidentRptIp": "172.16.20.10",
                    "incidentFirstSeen": 1763740000000,
                    "incidentStatus": 0,
                }
            ]
        }
        client, fake = self._client(monkeypatch, payload)
        out = client.incidents(org="Super")

        assert len(out) == 1
        inc = out[0]
        # 关键：数值 9 没有把类别 HIGH 翻成 critical
        assert inc["severity"] == "high"
        assert inc["score"] == 9.0
        assert inc["src_ip"] == "172.16.0.57"
        assert inc["dest_ip"] == "172.16.20.48"
        assert inc["user"] == "admin"
        assert inc["device_name"] == "FW-EDGE-01"
        assert inc["device_ip"] == "172.16.20.10"
        assert inc["external_id"] == "4711"
        assert inc["occurred_at"] is not None
        assert inc["incident_status"] == 0
        # 走的是 7.5.1 上真实存在的那个端点
        incident_calls = [c for c in fake.calls if c["url"].endswith("/phoenix/rest/pub/incident")]
        assert len(incident_calls) == 1, fake.calls
        assert incident_calls[0]["json"]["size"] == 200

    def test_incident_unknown_category_falls_back_to_score(self, monkeypatch):
        payload = {
            "data": [
                {
                    "incidentId": 1,
                    "incidentTitle": "t",
                    "eventSeverityCat": None,
                    "eventSeverity": 7,
                    "customer": "Super",
                    "incidentSrc": "",
                    "incidentTarget": None,
                }
            ]
        }
        client, _ = self._client(monkeypatch, payload)
        out = client.incidents(org="Super")
        assert out[0]["severity"] == "high"
        assert out[0]["src_ip"] is None
        assert out[0]["dest_ip"] is None
        assert out[0]["user"] is None
