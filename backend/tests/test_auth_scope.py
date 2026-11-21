"""认证作用域的回归测试。

## 为什么要有这个文件

`/api/siem/status` 曾**漏掉** `Depends(principal_from_request)` ——
同文件的 incidents / sync 都有，只有它没有。

后果：MP_ENV=prod 下**无任何凭据**就能拿到 200，而它返回的东西
不少：SIEM 组织名、四段探测细节、**设备清单**（名称 / 访问 IP /
SN / 型号 / 版本）。

这类漏洞靠肉眼很难发现 —— 文件里 3 个端点，2 个有认证 1 个没有，
格式上只差一行。所以必须有测试锁住。
"""

from fastapi.testclient import TestClient

from app.main import app


def test_siem_status_requires_auth_in_prod(monkeypatch):
    """生产模式下，SIEM 状态端点必须要凭据。"""
    import app.auth as auth_mod

    monkeypatch.setattr(auth_mod, "IS_PROD", True)

    client = TestClient(app)
    resp = client.get("/api/siem/status")
    assert resp.status_code == 401, resp.text

    # dev 租户头在生产模式下也不能放行
    resp2 = client.get("/api/siem/status", headers={"X-Dev-Tenant": "asi"})
    assert resp2.status_code == 401, resp2.text


def test_siem_status_allows_dev_tenant_in_dev(monkeypatch):
    """开发模式下，dev 租户头仍然可用（不然本地开发没法做）。"""
    import app.auth as auth_mod

    monkeypatch.setattr(auth_mod, "IS_PROD", False)

    client = TestClient(app)
    resp = client.get("/api/siem/status", headers={"X-Dev-Tenant": "asi"})
    # 连接器连不上时也应该是 200 —— 诊断信息本身就是给运维看的
    assert resp.status_code == 200, resp.text
    assert "stage" in resp.json()


def test_all_data_endpoints_require_auth_in_prod(monkeypatch):
    """**所有**业务端点在生产模式下都必须 401。

    防止再出现「漏加 Depends」—— 一个端点一个端点列出来。
    """
    import app.auth as auth_mod

    monkeypatch.setattr(auth_mod, "IS_PROD", True)

    client = TestClient(app)
    paths = [
        "/api/assets",
        "/api/assets/schema",
        "/api/topologies",
        "/api/events",
        "/api/siem/status",
        "/api/siem/incidents",
        "/api/monitor/topologies/1/panel",
    ]
    for path in paths:
        resp = client.get(path)
        assert resp.status_code == 401, f"{path} 在生产模式下返回了 {resp.status_code}，应当 401"
