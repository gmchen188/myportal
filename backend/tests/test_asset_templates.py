"""
资产模板、草稿清单与导出的测试。

## 为什么这组测试重要

**模板 → 草稿 → 落库**是三段式，中间那段（草稿）是这个功能的核心价值：
用户照着模板填自己船的设备，填一半能存下来明天接着填。

几个容易做错、且错了之后用户才会发现的地方：

1. **模板里的空骨架行不能丢。** 模板的价值就在于那些「设备类别」行 ——
   名称待填、类型已知。丢了骨架，用户拿到的只是一张空表。
2. **去重逻辑必须与一次性导入共用。** 两套逻辑迟早漂移 —— 一套认为重复
   该跳过，另一套认为该更新，用户看到的结果自相矛盾。
3. **导出必须与列表筛选一致。** 用户导出的是「他筛选出来的」，不是全量。
4. **CSV 必须带 UTF-8 BOM。** 不带 Excel 打开中文全是乱码 —— 而这种
   问题在服务端测不出来，只能靠断言 BOM 字节。

跑：
    cd backend && "C:/Python314/python.exe" -m pytest tests/test_asset_templates.py -q
"""

from __future__ import annotations

import io
import os
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import Asset, AssetDraft, AssetTemplate, Base, Tenant, get_session  # noqa: E402
from app.main import app  # noqa: E402

ASI = "t-asi"
DONGFANG = "t-dongfang"


# ── 夹具 ────────────────────────────────────────────────────────────────────


@pytest.fixture()
def env(tmp_path):
    """临时库 + 两个租户。

    照 `test_admin.py` 的姿势：`dependency_overrides` 换掉 `get_session`，
    **不用 `with TestClient(app)`** —— 那会跑 lifespan → init_db() →
    在真实库上建表。真实库一个字节都不动。
    """
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tpl.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    db = Session()
    db.add(Tenant(id=ASI, slug="asi", name="AquaSync Innovation", locale="zh-CN"))
    db.add(Tenant(id=DONGFANG, slug="dongfang", name="东方海运", locale="zh-CN"))
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


def _hdr(tenant="asi"):
    """开发模式的租户头 —— 业务读接口允许免登录。

    注意：`/api/auth/me` 与管理端点任何模式都要令牌，资产接口不是管理
    端点，所以这里用租户头就够。
    """
    return {"X-Dev-Tenant": tenant}


# 一份典型的模板：分类骨架 + 一行完整数据
TEMPLATE_CSV = (
    "设备类别,设备名称,类型,安全区域,数量,责任人\n"
    "主交换机,,交换机,Zone 1,2,\n"
    "雷达,,雷达,Zone 2,4,\n"
    "服务器主机,SRV-01,服务器,Zone 1,1,张三\n"
)


def _upload_template(client, content=TEMPLATE_CSV, filename="船型模板.csv", tenant="asi"):
    return client.post(
        "/api/assets/templates",
        files={"file": (filename, content.encode("utf-8"), "text/csv")},
        headers=_hdr(tenant),
    )


# ── 模板上传与解析 ──────────────────────────────────────────────────────────


class TestTemplateUpload:
    def test_上传模板返回表头与预置行(self, env):
        client, _ = env
        r = _upload_template(client)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["headers"] == ["设备类别", "设备名称", "类型", "安全区域", "数量", "责任人"]
        assert d["row_count"] == 3
        # 表头不能被当成数据行
        assert d["template_rows"][0][0] == "主交换机"

    def test_模板自动映射列到资产字段(self, env):
        client, _ = env
        d = _upload_template(client).json()
        m = d["mapping"]
        assert m["设备名称"] == "name"
        assert m["类型"] == "type"
        assert m["安全区域"] == "zone"
        # 「设备类别」也是 type 的同义词 → 会映射到 type。
        # 这本身没问题（类别就是类型），但**两列映射到同一字段时必须取
        # 分数最高的列**，否则类型会变成 "主交换机" 而不是 "交换机"。
        assert m["设备类别"] == "type"

    def test_模板区域候选归一成_Zone_N(self, env):
        client, _ = env
        d = _upload_template(client).json()
        assert "Zone 1" in d["zone_hints"]
        assert "Zone 2" in d["zone_hints"]

    def test_空文件被拒(self, env):
        client, _ = env
        r = client.post(
            "/api/assets/templates",
            files={"file": ("empty.csv", b"", "text/csv")},
            headers=_hdr(),
        )
        assert r.status_code == 400

    def test_没有表头的文件被拒(self, env):
        client, _ = env
        r = client.post(
            "/api/assets/templates",
            files={"file": ("x.csv", b"\x00\x01binary", "application/octet-stream")},
            headers=_hdr(),
        )
        assert r.status_code == 400

    def test_模板不写_assets_表(self, env):
        """模板是骨架，不是数据 —— 上传模板不该产生资产。"""
        client, Session = env
        _upload_template(client)
        db = Session()
        assert db.query(Asset).count() == 0
        assert db.query(AssetTemplate).count() == 1
        db.close()

    def test_租户隔离_看不到别人的模板(self, env):
        client, _ = env
        tpl_id = _upload_template(client).json()["id"]
        r = client.get(f"/api/assets/templates/{tpl_id}", headers=_hdr("dongfang"))
        assert r.status_code == 404


# ── 草稿：模板 → 草稿清单 ───────────────────────────────────────────────────


class TestDraft:
    def test_基于模板创建草稿(self, env):
        client, _ = env
        tpl_id = _upload_template(client).json()["id"]
        r = client.post(
            "/api/assets/drafts",
            json={"template_id": tpl_id, "name": "我的船资产清单"},
            headers=_hdr(),
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["draft"]["name"] == "我的船资产清单"
        assert d["draft"]["status"] == "draft"
        assert d["draft"]["version"] == 1
        assert len(d["draft"]["rows"]) == 3

    def test_骨架行保留_不能丢(self, env):
        """**核心**：模板里的空名称行必须保留。

        丢了骨架，用户拿到的只是一张空表 —— 模板就没意义了。
        """
        client, _ = env
        tpl_id = _upload_template(client).json()["id"]
        d = client.post(
            "/api/assets/drafts", json={"template_id": tpl_id}, headers=_hdr()
        ).json()
        rows = d["draft"]["rows"]
        # 三行都在
        assert len(rows) == 3
        # 「主交换机」那行：名称空、类型是交换机 → 是骨架行
        skeleton = [r for r in rows if (r["values"].get("type") or "") == "交换机"]
        assert len(skeleton) == 1, rows
        assert skeleton[0]["from_template"] is True
        assert skeleton[0]["status"] == "needs_fill"

    def test_骨架行带上了模板里的类型与区域(self, env):
        client, _ = env
        tpl_id = _upload_template(client).json()["id"]
        rows = client.post(
            "/api/assets/drafts", json={"template_id": tpl_id}, headers=_hdr()
        ).json()["draft"]["rows"]
        skel = next(r for r in rows if (r["values"].get("type") or "") == "雷达")
        assert skel["values"]["zone"] == "Zone 2"

    def test_有完整数据的行为_ready(self, env):
        client, _ = env
        tpl_id = _upload_template(client).json()["id"]
        rows = client.post(
            "/api/assets/drafts", json={"template_id": tpl_id}, headers=_hdr()
        ).json()["draft"]["rows"]
        full = next(r for r in rows if (r["values"].get("name") or "") == "SRV-01")
        assert full["status"] == "ready"

    def test_草稿不立刻写_assets(self, env):
        client, Session = env
        tpl_id = _upload_template(client).json()["id"]
        client.post("/api/assets/drafts", json={"template_id": tpl_id}, headers=_hdr())
        db = Session()
        assert db.query(Asset).count() == 0
        assert db.query(AssetDraft).count() == 1
        db.close()

    def test_加一行(self, env):
        client, _ = env
        tpl_id = _upload_template(client).json()["id"]
        did = client.post(
            "/api/assets/drafts", json={"template_id": tpl_id}, headers=_hdr()
        ).json()["draft"]["id"]
        r = client.post(f"/api/assets/drafts/{did}/rows", json={}, headers=_hdr())
        assert r.status_code == 200, r.text
        assert len(r.json()["draft"]["rows"]) == 4

    def test_租户隔离_不能读别人草稿(self, env):
        client, _ = env
        tpl_id = _upload_template(client).json()["id"]
        did = client.post(
            "/api/assets/drafts", json={"template_id": tpl_id}, headers=_hdr()
        ).json()["draft"]["id"]
        assert client.get(f"/api/assets/drafts/{did}", headers=_hdr("dongfang")).status_code == 404
        assert client.put(f"/api/assets/drafts/{did}", json={"rows": []}, headers=_hdr("dongfang")).status_code == 404
        assert client.post(f"/api/assets/drafts/{did}/commit", headers=_hdr("dongfang")).status_code == 404


# ── 草稿：编辑与保存 ────────────────────────────────────────────────────────


class TestDraftEditing:
    def _draft(self, client):
        tpl_id = _upload_template(client).json()["id"]
        return client.post(
            "/api/assets/drafts", json={"template_id": tpl_id}, headers=_hdr()
        ).json()["draft"]

    def test_保存后版本递增(self, env):
        client, _ = env
        d = self._draft(client)
        r = client.put(
            f"/api/assets/drafts/{d['id']}", json={"rows": d["rows"]}, headers=_hdr()
        )
        assert r.status_code == 200, r.text
        assert r.json()["draft"]["version"] == 2

    def test_编辑后重新校验_填完就从待补充变可导入(self, env):
        """**用户改了字段，标记必须跟着变** —— 否则用户看到「待补充」
        但其实填完了，会困惑。"""
        client, _ = env
        d = self._draft(client)
        rows = [dict(r) for r in d["rows"]]
        # 把骨架行补全
        rows[0]["values"] = {**rows[0]["values"], "name": "SW-CORE-01"}
        r = client.put(f"/api/assets/drafts/{d['id']}", json={"rows": rows}, headers=_hdr())
        assert r.status_code == 200, r.text
        stats = r.json()["stats"]
        assert stats["ready"] >= 2
        assert stats["needs_fill"] < stats["total"]

    def test_保存后可再读回_内容一致(self, env):
        client, _ = env
        d = self._draft(client)
        rows = [dict(r) for r in d["rows"]]
        rows[0]["values"] = {**rows[0]["values"], "name": "SW-CORE-01"}
        client.put(f"/api/assets/drafts/{d['id']}", json={"rows": rows}, headers=_hdr())
        again = client.get(f"/api/assets/drafts/{d['id']}", headers=_hdr()).json()
        names = [r["values"].get("name") for r in again["rows"]]
        assert "SW-CORE-01" in names

    def test_全空的行被丢弃(self, env):
        """用户清空了一整行 → 删掉比留着占位好。"""
        client, _ = env
        d = self._draft(client)
        rows = [dict(r) for r in d["rows"]]
        rows.append({"values": {k: "" for k in rows[0]["values"]}, "row_no": 99, "status": "ready"})
        r = client.put(f"/api/assets/drafts/{d['id']}", json={"rows": rows}, headers=_hdr())
        assert len(r.json()["draft"]["rows"]) == 3

    def test_重名标为待补充(self, env):
        client, _ = env
        d = self._draft(client)
        rows = [dict(r) for r in d["rows"]]
        rows[1]["values"] = {**rows[1]["values"], "name": "SRV-01"}  # 与第 3 行重名
        r = client.put(f"/api/assets/drafts/{d['id']}", json={"rows": rows}, headers=_hdr())
        assert r.json()["stats"]["needs_fill"] >= 1

    def test_改草稿名也保存(self, env):
        client, _ = env
        d = self._draft(client)
        r = client.put(
            f"/api/assets/drafts/{d['id']}",
            json={"rows": d["rows"], "name": "改成新名字"},
            headers=_hdr(),
        )
        assert r.json()["draft"]["name"] == "改成新名字"


# ── 草稿落库 ────────────────────────────────────────────────────────────────


class TestDraftCommit:
    def _draft(self, client):
        tpl_id = _upload_template(client).json()["id"]
        return client.post(
            "/api/assets/drafts", json={"template_id": tpl_id}, headers=_hdr()
        ).json()["draft"]

    def test_落库写入_assets(self, env):
        client, Session = env
        d = self._draft(client)
        rows = [dict(r) for r in d["rows"]]
        rows[0]["values"] = {**rows[0]["values"], "name": "SW-CORE-01"}
        client.put(f"/api/assets/drafts/{d['id']}", json={"rows": rows}, headers=_hdr())
        r = client.post(f"/api/assets/drafts/{d['id']}/commit", headers=_hdr())
        assert r.status_code == 200, r.text
        assert r.json()["result"]["created"] == 2  # SRV-01 + SW-CORE-01
        db = Session()
        assert db.query(Asset).count() == 2
        db.close()

    def test_落库后草稿状态变_committed(self, env):
        client, _ = env
        d = self._draft(client)
        rows = [dict(r) for r in d["rows"]]
        rows[0]["values"] = {**rows[0]["values"], "name": "SW-CORE-01"}
        client.put(f"/api/assets/drafts/{d['id']}", json={"rows": rows}, headers=_hdr())
        r = client.post(f"/api/assets/drafts/{d['id']}/commit", headers=_hdr())
        assert r.json()["draft"]["status"] == "committed"
        assert r.json()["draft"]["commit_result"]["created"] == 2

    def test_重复落库幂等_第二次全跳过(self, env):
        """**幂等**：草稿提交两次，第二次不该产生重复资产。

        去重逻辑与一次性导入共用 —— 同一套规则。
        """
        client, Session = env
        d = self._draft(client)
        rows = [dict(r) for r in d["rows"]]
        rows[0]["values"] = {**rows[0]["values"], "name": "SW-CORE-01"}
        client.put(f"/api/assets/drafts/{d['id']}", json={"rows": rows}, headers=_hdr())

        first = client.post(f"/api/assets/drafts/{d['id']}/commit", headers=_hdr()).json()
        assert first["result"]["created"] == 2

        second = client.post(f"/api/assets/drafts/{d['id']}/commit", headers=_hdr()).json()
        assert second["result"]["created"] == 0
        assert second["result"]["skipped"] == 2

        db = Session()
        assert db.query(Asset).count() == 2
        db.close()

    def test_骨架行没填名字_提交时算失败_不写库(self, env):
        """骨架行没填名字 → 提交时算「失败」，不写库。

        语义与**一次性导入一致**（既有契约）：预览阶段标 `needs_fill`，
        用户补全后才提交；提交时仍缺必填就是 failed。
        """
        client, Session = env
        d = self._draft(client)
        r = client.post(f"/api/assets/drafts/{d['id']}/commit", headers=_hdr())
        assert r.json()["result"]["failed"] == 2  # 两个骨架行
        assert r.json()["result"]["created"] == 1  # 只有 SRV-01
        db = Session()
        assert db.query(Asset).count() == 1
        db.close()

    def test_来源标记为_template_draft(self, env):
        client, Session = env
        d = self._draft(client)
        rows = [dict(r) for r in d["rows"]]
        rows[0]["values"] = {**rows[0]["values"], "name": "SW-CORE-01"}
        client.put(f"/api/assets/drafts/{d['id']}", json={"rows": rows}, headers=_hdr())
        client.post(f"/api/assets/drafts/{d['id']}/commit", headers=_hdr())
        db = Session()
        assert db.query(Asset).first().source == "template_draft"
        db.close()

    def test_草稿列表能看到(self, env):
        client, _ = env
        self._draft(client)
        r = client.get("/api/assets/drafts", headers=_hdr())
        assert r.status_code == 200
        assert r.json()["total"] == 1


# ── 导出 ────────────────────────────────────────────────────────────────────


class TestExport:
    def _seed(self, client, Session):
        db = Session()
        db.add(Asset(tenant_id=ASI, natural_id="A-01", name="主机A", type="服务器",
                     zone="Zone 1", ip="10.0.0.1", vendor="华为", model="X", serial="S1",
                     owner="张三", cbs_class="A", status="在用", source="manual"))
        db.add(Asset(tenant_id=ASI, natural_id="A-02", name="主机B", type="交换机",
                     zone="Zone 2", ip="10.0.0.2", status="在用", source="manual"))
        db.add(Asset(tenant_id=DONGFANG, natural_id="B-01", name="别人的主机", type="服务器",
                     zone="Zone 1", status="在用", source="manual"))
        db.commit()
        db.close()

    def test_导出_csv(self, env):
        client, Session = env
        self._seed(client, Session)
        r = client.get("/api/assets/export?fmt=csv", headers=_hdr())
        assert r.status_code == 200, r.text
        assert "text/csv" in r.headers["content-type"]
        assert "attachment" in r.headers["content-disposition"]
        body = r.content.decode("utf-8-sig")
        assert "资产名称" in body
        assert "主机A" in body
        assert "主机B" in body

    def test_csv_带_BOM_否则_Excel_中文乱码(self, env):
        """**必须带 UTF-8 BOM** —— 不带 Excel 按 ANSI 读，中文全是乱码。

        这种问题在服务端看不出来，只能断言 BOM 字节。
        """
        client, Session = env
        self._seed(client, Session)
        r = client.get("/api/assets/export?fmt=csv", headers=_hdr())
        assert r.content[:3] == b"\xef\xbb\xbf", r.content[:6]

    def test_导出_xlsx_可被_openpyxl_读回(self, env):
        client, Session = env
        self._seed(client, Session)
        r = client.get("/api/assets/export?fmt=xlsx", headers=_hdr())
        assert r.status_code == 200, r.text
        assert "spreadsheetml" in r.headers["content-type"]
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(r.content))
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        assert rows[0][0] == "资产编号"
        assert any("主机A" in str(c) for c in rows[1])

    def test_导出遵循筛选_与列表一致(self, env):
        """用户导出的是「他筛选出来的」—— 必须与列表看到的同一批。"""
        client, Session = env
        self._seed(client, Session)
        r = client.get("/api/assets/export?fmt=csv&zone=Zone 1", headers=_hdr())
        body = r.content.decode("utf-8-sig")
        assert "主机A" in body
        assert "主机B" not in body
        assert r.headers["X-Total-Count"] == "1"

    def test_导出支持关键字筛选(self, env):
        client, Session = env
        self._seed(client, Session)
        r = client.get("/api/assets/export?fmt=csv&q=主机B", headers=_hdr())
        body = r.content.decode("utf-8-sig")
        assert "主机B" in body
        assert "主机A" not in body

    def test_导出可选字段(self, env):
        client, Session = env
        self._seed(client, Session)
        r = client.get("/api/assets/export?fmt=csv&fields=name,ip", headers=_hdr())
        body = r.content.decode("utf-8-sig")
        head = body.split("\r\n")[0]
        assert head == "资产名称,IP 地址"
        assert "资产编号" not in head

    def test_导出不含_assets_编号_当_未指定字段(self, env):
        client, Session = env
        self._seed(client, Session)
        r = client.get("/api/assets/export?fmt=csv", headers=_hdr())
        body = r.content.decode("utf-8-sig")
        assert "资产编号" in body  # 默认全字段

    def test_无效字段被忽略_不报错(self, env):
        """前端传了脏字段不该让整个导出失败。"""
        client, Session = env
        self._seed(client, Session)
        r = client.get("/api/assets/export?fmt=csv&fields=name,不存在字段", headers=_hdr())
        assert r.status_code == 200
        body = r.content.decode("utf-8-sig")
        assert body.split("\r\n")[0] == "资产名称"

    def test_租户隔离_导不出别人的资产(self, env):
        client, Session = env
        self._seed(client, Session)
        r = client.get("/api/assets/export?fmt=csv", headers=_hdr())
        body = r.content.decode("utf-8-sig")
        assert "别人的主机" not in body
        assert r.headers["X-Total-Count"] == "2"

    def test_文件名含中文时_用_RFC5987_编码(self, env):
        client, Session = env
        self._seed(client, Session)
        r = client.get("/api/assets/export?fmt=csv", headers=_hdr())
        cd = r.headers["content-disposition"]
        assert "filename*=UTF-8''" in cd
        assert "%E8%B5%84%E4%BA%A7" in cd  # 「资产」的百分号编码

    def test_未知格式回退_csv(self, env):
        client, Session = env
        self._seed(client, Session)
        r = client.get("/api/assets/export?fmt=pdf", headers=_hdr())
        assert r.status_code == 200
        assert "text/csv" in r.headers["content-type"]


class TestMultiColumnMapping:
    """同一字段被多列映射时，取分数最高的列。"""

    def test_设备类别与类型都在时_类型取分数更高的列(self, env):
        """真实场景：模板里有「设备类别」和「类型」两列。

        按列序取第一个的话，type 会变成 "主交换机" 而不是 "交换机" ——
        资产类型全错。
        """
        client, _ = env
        tpl_id = _upload_template(client).json()["id"]
        rows = client.post(
            "/api/assets/drafts", json={"template_id": tpl_id}, headers=_hdr()
        ).json()["draft"]["rows"]
        skel = next(r for r in rows if r["values"].get("name") == "")
        # 「类型」列是完全匹配（0.99），「设备类别」是包含匹配（更低）
        assert skel["values"]["type"] == "交换机"
        assert skel["values"]["zone"] == "Zone 1"
