"""
端到端验证：导入真实 SIEM 设备后，监控面板的节点真的会变色吗？

这是整个需求的**目的**，不是实现细节：
    真实事件（FortiSIEM 的 high/medium）→ 落到导入的节点 → 面板上点亮

用真实的 incidents 表数据 + 真实的拓扑 XML，在数据库副本上跑。

跑：
    cd backend && "C:/Python314/python.exe" -m pytest tests/test_real_import_e2e.py -q -s
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

from app.db import Asset, Base, DeviceMonitor, Incident, Topology  # noqa: E402
from app.services.monitoring import compute_device_states  # noqa: E402
from app.services.topology_import import import_assets_as_nodes  # noqa: E402
from app.services.topology_parse import parse_topology  # noqa: E402

REAL_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "myportal.db")


@pytest.fixture(scope="module")
def real_db():
    if not os.path.exists(REAL_DB):
        pytest.skip("生产库不存在")
    tmpdir = tempfile.mkdtemp(prefix="myportal-e2e-")
    dst = os.path.join(tmpdir, "copy.db")
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


def test_real_events_light_up_imported_nodes(real_db):
    db = real_db()
    try:
        topo = db.scalars(select(Topology).where(Topology.id == 1)).first()
        graph = parse_topology(topo.xml or "")

        # 导入前的面板状态
        binds = db.scalars(
            select(DeviceMonitor).where(DeviceMonitor.topology_id == topo.id)
        ).all()
        by_node = {m.node_id: m for m in binds}
        devices_before = [
            {
                "node_id": n["id"],
                "label": n["label"],
                "natural_id": by_node[n["id"]].natural_id if n["id"] in by_node else None,
                "ip": by_node[n["id"]].ip if n["id"] in by_node else None,
            }
            for n in graph["nodes"]
        ]
        incidents = [
            {
                "id": i.id,
                "title": i.title,
                "severity": i.severity,
                "device_natural_id": i.device_natural_id,
                "device_ip": i.device_ip,
                "device_name": i.device_name,
                "occurred_at": i.occurred_at,
                "incident_status": 0,
                "source": i.source,
            }
            for i in db.scalars(select(Incident).where(Incident.tenant_id == topo.tenant_id)).all()
        ]
        states_before = compute_device_states(devices_before, incidents)
        lit_before = [s for s in states_before if s["severity"] != "unknown"]
        print("\n=== 导入前 ===")
        print(f"节点 {len(devices_before)} 个，点亮 {len(lit_before)} 个")
        for s in states_before:
            print(f"  {s['label']:32s} {s['severity']:8s} {s['color']}")

        # 导入真实 SIEM 设备
        siem_assets = db.scalars(
            select(Asset).where(Asset.source == "fortisiem", Asset.tenant_id == topo.tenant_id)
        ).all()
        res = import_assets_as_nodes(db, topo.tenant_id, topo.id, [a.id for a in siem_assets])
        print(f"\n=== 导入 {len(siem_assets)} 台 SIEM 设备 → added={res['added']} ===")

        # 导入后的面板状态
        graph2 = parse_topology(topo.xml or "")
        binds2 = db.scalars(
            select(DeviceMonitor).where(DeviceMonitor.topology_id == topo.id)
        ).all()
        by_node2 = {m.node_id: m for m in binds2}
        devices_after = [
            {
                "node_id": n["id"],
                "label": n["label"],
                "natural_id": by_node2[n["id"]].natural_id if n["id"] in by_node2 else None,
                "ip": by_node2[n["id"]].ip if n["id"] in by_node2 else None,
            }
            for n in graph2["nodes"]
        ]
        states_after = compute_device_states(devices_after, incidents)
        lit_after = [s for s in states_after if s["severity"] != "unknown"]
        print("\n=== 导入后 ===")
        print(f"节点 {len(devices_after)} 个，点亮 {len(lit_after)} 个")
        for s in states_after:
            mark = "*" if s["severity"] != "unknown" else " "
            print(f" {mark} {s['label']:32s} {s['severity']:8s} {s['color']}")

        # 断言：新导入的节点真的亮了
        siem_labels = {a.natural_id for a in siem_assets}
        lit_labels = {s["label"] for s in lit_after}
        assert siem_labels & lit_labels, (
            f"SIEM 设备一个都没点亮：siem={siem_labels} lit={lit_labels}"
        )
        # 而且点亮数只增不减
        assert len(lit_after) > len(lit_before)
        print(f"\n✓ 点亮节点数 {len(lit_before)} → {len(lit_after)}")
        print(f"✓ 新点亮的: {sorted((siem_labels & lit_labels) - {s['label'] for s in lit_before})}")
    finally:
        db.rollback()
        db.close()
