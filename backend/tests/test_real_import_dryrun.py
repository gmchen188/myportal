"""
真实数据验证：在**数据库副本**上跑一次真实的导入，看结果对不对。

不改 backend/data/myportal.db —— 先把库复制到临时目录再跑。

跑：
    cd backend && "C:/Python314/python.exe" -m pytest tests/test_real_import_dryrun.py -q -s
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db import Asset, Base, DeviceMonitor, Topology  # noqa: E402
from app.services.topology_import import import_assets_as_nodes, list_importable_assets  # noqa: E402
from app.services.topology_parse import parse_topology  # noqa: E402

REAL_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "myportal.db")


@pytest.fixture(scope="module")
def real_db():
    """生产库的一份副本。真实库全程只读。

    **必须连 -wal / -shm 一起复制** —— SQLite 的 WAL 里存着最近写入的数据，
    只复制主库文件会看到一份「少了最近几笔」的数据（实测：少了 HOST-1.1.1.1
    这条资产）。这不只是测试环境的问题 —— 任何备份 SQLite 都要注意。
    """
    if not os.path.exists(REAL_DB):
        pytest.skip("生产库不存在，跳过真实数据验证")
    tmpdir = tempfile.mkdtemp(prefix="myportal-real-")
    dst = os.path.join(tmpdir, "myportal-copy.db")
    for suffix in ("", "-wal", "-shm"):
        src = REAL_DB + suffix
        if os.path.exists(src):
            shutil.copy2(src, dst + suffix)
    engine = create_engine(f"sqlite:///{dst}", future=True, connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    try:
        yield Session
    finally:
        engine.dispose()
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_real_topology_import_dryrun(real_db, capsys):
    db = real_db()
    try:
        topo = db.scalars(select(Topology).where(Topology.id == 1)).first()
        assert topo is not None, "生产库里没有拓扑图 id=1"

        before = parse_topology(topo.xml or "")
        print("\n=== 导入前 ===")
        print(f"节点数: {len(before['nodes'])}  区域数: {len(before['zones'])}  连线数: {len(before['links'])}")
        print("节点标签:", sorted(n["label"] for n in before["nodes"]))
        print("区域:", [(z.get("title"), z.get("x"), z.get("y"), z.get("w"), z.get("h")) for z in before["zones"]])

        siem_assets = db.scalars(
            select(Asset).where(Asset.source == "fortisiem", Asset.tenant_id == topo.tenant_id)
        ).all()
        print("\n=== FortiSIEM 真实设备 ===")
        for a in siem_assets:
            print(f"  id={a.id} {a.natural_id} ip={a.ip} zone={a.zone!r} type={a.type}")

        # 可导入清单
        imp = list_importable_assets(db, topo.tenant_id, topo.id)
        print("\n=== 可导入资产 ===")
        for i in imp["items"]:
            print(f"  id={i['id']} {i['name']:32s} zone={str(i['zone']):8s} "
                  f"in_graph={i['already_in_graph']} elsewhere={i['bound_elsewhere']}")

        # 导入那 3 台真实 SIEM 设备
        ids = [a.id for a in siem_assets]
        print(f"\n=== 导入 asset_ids={ids} ===")
        res = import_assets_as_nodes(db, topo.tenant_id, topo.id, ids)
        print(f"added={res['added']} bound_existing={res['bound_existing']} monitors={res['monitors']}")
        print("warnings:", res["warnings"])
        for n in res["nodes"]:
            print(f"  node={n['node_id']:6s} label={n['label']:32s} zone={n['zone']!r} "
                  f"style={n['style']} pos=({n['x']},{n['y']})")
        for s in res["skipped"]:
            print(f"  SKIPPED {s}")

        # 结果校验
        after = parse_topology(topo.xml or "")
        print("\n=== 导入后 ===")
        print(f"节点数: {len(after['nodes'])}  区域数: {len(after['zones'])}  连线数: {len(after['links'])}")
        print("parse_error:", after["error"])
        for n in after["nodes"]:
            print(f"  {n['id']:6s} {n['label']:32s} zone={n['zone']!r} zone_key={n['zone_key']!r} "
                  f"style={n['style_names']} pos=({n['x']},{n['y']})")

        assert after["error"] is None
        assert len(after["nodes"]) == len(before["nodes"]) + len(ids)
        # 原有节点一个不少
        old_labels = {n["label"] for n in before["nodes"]}
        new_labels = {n["label"] for n in after["nodes"]}
        assert old_labels <= new_labels
        # 新节点都在某个区域里
        for n in after["nodes"]:
            if n["label"] in {a.natural_id for a in siem_assets}:
                assert n["zone"], f"{n['label']} 没有落到任何区域"
        # 绑定建好了
        mons = db.scalars(
            select(DeviceMonitor).where(DeviceMonitor.topology_id == topo.id)
        ).all()
        print("\n=== device_monitors ===")
        for m in mons:
            print(f"  {m.node_id:6s} {str(m.natural_id):32s} ip={m.ip} channel={m.channel}")

        # 幂等：再导一次
        res2 = import_assets_as_nodes(db, topo.tenant_id, topo.id, ids)
        print(f"\n=== 重复导入 ===\nadded={res2['added']} skipped={res2['skipped']}")
        assert res2["added"] == 0
        after2 = parse_topology(topo.xml or "")
        assert len(after2["nodes"]) == len(after["nodes"]), "重复导入产生了新节点！"

        print("\n=== 生成的 XML 片段（尾部） ===")
        tail = (topo.xml or "").splitlines()[-8:]
        for line in tail:
            print("  " + line)

        print("\n=== node_bindings ===")
        for k, v in (topo.node_bindings or {}).items():
            print(f"  {k}: {v}")
    finally:
        db.rollback()
        db.close()
