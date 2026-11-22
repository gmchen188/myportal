import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Link } from "react-router-dom"

import { api, type Fleet, type Vessel, type VesselOverview } from "@/api/client"
import { SeverityBadge, severityLabel } from "@/components/severity"

/**
 * 总览 —— **船队视图**与**单船视图**两级。
 *
 * ## 为什么分两级
 *
 * 一支船队底下有若干艘船，每艘船有自己的设备与事件。
 * 只给一个扁平的总览，船队的人看不到「哪艘船出事了」；
 * 只给单船，船队的人看不到「整支船队怎么样」。
 *
 *     船队视图   每支船队一张卡：几艘船、多少设备、事件按严重度怎么分布
 *     单船视图   某一艘船：它的设备、监控通道、拓扑、事件
 *
 * ## 数据全部来自后台
 *
 * 没有硬编码的数字，也没有「演示数据」徽章 —— 演示版在 demo/ 目录，
 * 正式的数字带徽章标注来源。
 *
 * ## 未归船的设备不能消失
 *
 * 导入进来的设备往往还不知道装在哪艘船上。后台把它们放在「未归船」一档，
 * 这里照样显示 —— **不能因为没归船就看不见**。
 */

/** 严重度的展示顺序 —— 重的在前 */
const SEVERITIES = ["critical", "high", "medium", "low", "informational"] as const

/** 堆叠条各段配色，与徽章一致 */
const STACK_COLOR: Record<string, string> = {
    critical: "#dc2626",
    high: "#ec4899",
    medium: "#f59e0b",
    low: "#64748b",
    informational: "#94a3b8",
}

/** 严重度分布的堆叠条 + pill 矩阵 */
function SeverityBreakdown({ counts }: { counts: Record<string, number> }) {
    const total = SEVERITIES.reduce((n, s) => n + (counts[s] ?? 0), 0)
    if (total === 0) {
        return <div className="subtle" style={{ fontSize: 12 }}>无事件</div>
    }
    return (
        <div>
            {/* 堆叠条 —— 一眼看出重的占多少 */}
            <div
                style={{
                    display: "flex",
                    height: 8,
                    borderRadius: 4,
                    overflow: "hidden",
                    background: "#e2e8f0",
                    marginBottom: 8,
                }}
            >
                {SEVERITIES.map((s) => {
                    const n = counts[s] ?? 0
                    if (n === 0) return null
                    return (
                        <div
                            key={s}
                            title={`${severityLabel(s)} ${n}`}
                            style={{ width: `${(n / total) * 100}%`, background: STACK_COLOR[s] }}
                        />
                    )
                })}
            </div>
            {/* pill 矩阵 —— 具体几条 */}
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {SEVERITIES.filter((s) => (counts[s] ?? 0) > 0).map((s) => (
                    <span
                        key={s}
                        className="bdg neutral"
                        style={{ borderLeft: `3px solid ${STACK_COLOR[s]}`, paddingRight: 7 }}
                    >
                        {severityLabel(s)} <b style={{ marginLeft: 3 }}>{counts[s]}</b>
                    </span>
                ))}
            </div>
        </div>
    )
}

/** 一支船队的卡片 */
function FleetCard({
    fleet,
    onOpen,
    onOpenFleet,
}: {
    fleet: Fleet
    onOpen: (v: Vessel) => void
    onOpenFleet: () => void
}) {
    return (
        <div className="card" style={{ padding: 14 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
                {/* **点船队名回到船队视图** —— 看全部船队，而不是只盯这一支。
                    卡片上的四个数字是这一支船队的，点了名字才知道全貌。 */}
                <h3
                    onClick={onOpenFleet}
                    title="查看所有船队"
                    style={{ margin: 0, fontSize: 15, cursor: "pointer" }}
                >
                    {fleet.name}
                </h3>
                {fleet.code && <span className="bdg neutral mono">{fleet.code}</span>}
            </div>

            {/* 四个大数字 */}
            <div style={{ display: "flex", gap: 14, margin: "10px 0 12px" }}>
                <div style={{ flex: 1 }}>
                    <div className="subtle" style={{ fontSize: 11 }}>船</div>
                    <div style={{ fontSize: 22, fontWeight: 700, lineHeight: 1.1 }}>{fleet.vessel_count}</div>
                </div>
                <div style={{ flex: 1 }}>
                    <div className="subtle" style={{ fontSize: 11 }}>资产</div>
                    <div style={{ fontSize: 22, fontWeight: 700, lineHeight: 1.1 }}>{fleet.asset_count}</div>
                </div>
                <div style={{ flex: 1 }}>
                    <div className="subtle" style={{ fontSize: 11 }}>已接监控</div>
                    <div style={{ fontSize: 22, fontWeight: 700, lineHeight: 1.1 }}>{fleet.monitor_count}</div>
                </div>
                <div style={{ flex: 1 }}>
                    <div className="subtle" style={{ fontSize: 11 }}>事件</div>
                    <div style={{ fontSize: 22, fontWeight: 700, lineHeight: 1.1 }}>{fleet.event_count}</div>
                </div>
            </div>

            <SeverityBreakdown counts={fleet.events_by_severity} />

            {/* 船列表 —— 点进单船视图 */}
            {fleet.vessels.length > 0 && (
                <div style={{ marginTop: 12, borderTop: "1px solid var(--line)", paddingTop: 10 }}>
                    {fleet.vessels.map((v) => (
                        <button
                            key={v.id ?? "none"}
                            onClick={() => onOpen(v)}
                            disabled={v.id === null}
                            style={{
                                display: "flex",
                                width: "100%",
                                alignItems: "center",
                                gap: 8,
                                padding: "5px 0",
                                background: "none",
                                border: "none",
                                cursor: v.id === null ? "default" : "pointer",
                                textAlign: "left",
                                color: "inherit",
                            }}
                        >
                            <span style={{ fontSize: 13 }}>{v.name}</span>
                            {v.code && <span className="subtle mono" style={{ fontSize: 11 }}>{v.code}</span>}
                            <span className="subtle" style={{ marginLeft: "auto", fontSize: 11 }}>
                                {v.asset_count} 资产 · {v.monitor_count} 监控
                            </span>
                            {v.id !== null && <span className="subtle" style={{ fontSize: 12 }}>›</span>}
                        </button>
                    ))}
                </div>
            )}
        </div>
    )
}

/**
 * 下拉里的一个选项 —— 船 + 它的船队名。
 *
 * 不同船队可能有同名船，光看船名分不清是哪一艘，所以选项里带上船队。
 */
type VesselOption = Vessel & { fleet_name?: string | null }

/** 单船视图 */
function VesselView({
    data,
    loading,
    onBack,
    vessels,
    vesselId,
    onSelect,
}: {
    data: VesselOverview | undefined
    loading: boolean
    onBack: () => void
    /** **所有船舶** —— 下拉里要能选到任意一艘 */
    vessels: VesselOption[]
    vesselId: number | null
    onSelect: (id: number) => void
}) {
    /*
     * **头部（返回 + 船舶下拉）必须始终渲染。**
     *
     * 原来 loading 分支直接 `return <加载中…>` —— 于是切进单船视图后，
     * 在数据到达之前**「← 船队视图」按钮和下拉都不存在**，用户可能点不回去。
     * （测试当场抓到的：找不到「← 船队视图」。）
     */
    const header = (
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12, flexWrap: "wrap" }}>
            <button className="link" style={{ background: "none", border: "none", cursor: "pointer", padding: 0 }} onClick={onBack}>
                ← 船队视图
            </button>
            {data && (
                <>
                    <h3 style={{ margin: 0, fontSize: 16 }}>{data.vessel.name}</h3>
                    {data.vessel.code && <span className="bdg neutral mono">{data.vessel.code}</span>}
                    {data.vessel.fleet_name && <span className="subtle">{data.vessel.fleet_name}</span>}
                </>
            )}

            {/* **船舶下拉** —— 选了哪艘船，下面就显示哪艘。
                选项带上船队名：不同船队可能有同名船，光看船名分不清。 */}
            <select
                className="select"
                style={{ width: 220, marginLeft: "auto" }}
                value={vesselId ?? ""}
                onChange={(e) => onSelect(Number(e.target.value))}
                title="选择要查看的船舶"
            >
                {vessels.length === 0 && <option value="">没有船</option>}
                {vessels.map((x) => (
                    <option key={x.id ?? "none"} value={x.id ?? ""}>
                        {x.fleet_name ? `${x.fleet_name} · ${x.name}` : x.name}
                    </option>
                ))}
            </select>
        </div>
    )

    if (loading || !data) {
        return (
            <>
                {header}
                <div className="card"><div className="subtle">加载中…</div></div>
            </>
        )
    }
    const byZone = data.assets.reduce<Record<string, typeof data.assets>>((acc, a) => {
        const z = a.zone || "未分区域"
        if (!acc[z]) acc[z] = []
        acc[z].push(a)
        return acc
    }, {})

    return (
        <>
            {header}

            <div className="grid g-4" style={{ marginBottom: 14 }}>
                <div className="card" style={{ padding: "12px 14px" }}>
                    <div className="subtle">资产</div>
                    <div style={{ fontSize: 22, fontWeight: 700 }}>{data.assets.length}</div>
                </div>
                <div className="card" style={{ padding: "12px 14px" }}>
                    <div className="subtle">已接监控</div>
                    <div style={{ fontSize: 22, fontWeight: 700 }}>{data.monitored.length}</div>
                </div>
                <div className="card" style={{ padding: "12px 14px" }}>
                    <div className="subtle">拓扑图</div>
                    <div style={{ fontSize: 22, fontWeight: 700 }}>{data.topologies.length}</div>
                </div>
                <div className="card" style={{ padding: "12px 14px" }}>
                    <div className="subtle">事件</div>
                    <div style={{ fontSize: 22, fontWeight: 700 }}>{data.events.length}</div>
                </div>
            </div>

            <div className="grid g-2" style={{ marginBottom: 14 }}>
                <div className="card">
                    <div className="card-h"><h3>事件严重度</h3></div>
                    <div style={{ padding: 14 }}>
                        <SeverityBreakdown counts={data.events_by_severity} />
                    </div>
                </div>
                <div className="card">
                    <div className="card-h"><h3>拓扑图</h3></div>
                    <div style={{ padding: 14 }}>
                        {data.topologies.length === 0 && <span className="subtle">这艘船还没有拓扑图</span>}
                        {data.topologies.map((t) => (
                            <div key={t.id} style={{ display: "flex", gap: 8, padding: "4px 0" }}>
                                <Link to="/topologies" className="link">{t.name}</Link>
                                <span className="subtle" style={{ marginLeft: "auto", fontSize: 11 }}>
                                    {t.node_count} 节点
                                </span>
                            </div>
                        ))}
                    </div>
                </div>
            </div>

            <div className="card">
                <div className="card-h">
                    <h3>设备</h3>
                    <span className="subtle" style={{ fontSize: 11 }}>按安全区域分组</span>
                </div>
                <div className="tbl-wrap">
                    <table>
                        <thead>
                            <tr><th>区域</th><th>名称</th><th>类型</th><th>IP</th><th>状态</th><th>监控</th></tr>
                        </thead>
                        <tbody>
                            {Object.entries(byZone).map(([zone, rows]) =>
                                rows.map((a, i) => (
                                    <tr key={a.id}>
                                        {i === 0 && (
                                            <td rowSpan={rows.length} className="mono" style={{ verticalAlign: "top" }}>
                                                {zone}
                                            </td>
                                        )}
                                        <td className="mono">{a.name}</td>
                                        <td className="muted">{a.type}</td>
                                        <td className="mono muted">{a.ip ?? "—"}</td>
                                        <td><span className="bdg neutral">{a.status ?? "—"}</span></td>
                                        <td>
                                            {data.monitored.some((m) => m.natural_id === a.natural_id) ? (
                                                <span className="bdg ok">已接</span>
                                            ) : (
                                                <span className="bdg neutral">未接</span>
                                            )}
                                        </td>
                                    </tr>
                                )),
                            )}
                            {data.assets.length === 0 && (
                                <tr><td colSpan={6} className="muted" style={{ textAlign: "center", padding: 22 }}>
                                    这艘船还没有资产
                                </td></tr>
                            )}
                        </tbody>
                    </table>
                </div>
            </div>
        </>
    )
}

export function OverviewPage() {
    const [view, setView] = useState<"fleet" | "vessel">("fleet")
    const [vesselId, setVesselId] = useState<number | null>(null)

    const assets = useQuery({ queryKey: ["assets"], queryFn: () => api.assets.list({ limit: 1 }) })
    const topologies = useQuery({ queryKey: ["topologies"], queryFn: () => api.topologies.list() })
    const events = useQuery({ queryKey: ["events"], queryFn: () => api.monitor.events({ limit: 500 }) })
    const health = useQuery({ queryKey: ["health"], queryFn: () => api.health() })
    const fleetData = useQuery({ queryKey: ["fleet-overview"], queryFn: () => api.fleets.overview() })
    const vesselData = useQuery({
        queryKey: ["vessel-overview", vesselId],
        queryFn: () => api.fleets.vesselOverview(vesselId as number),
        enabled: view === "vessel" && vesselId !== null,
    })

    const items = events.data?.items ?? []
    const bySeverity = items.reduce<Record<string, number>>((acc, e) => {
        acc[e.severity] = (acc[e.severity] ?? 0) + 1
        return acc
    }, {})
    const siem = health.data?.siem
    const totals = fleetData.data?.totals

    /** **所有船舶** —— 单船视图的下拉要用。带上船队名，避免同名船分不清。 */
    const allVessels: VesselOption[] = (fleetData.data?.fleets ?? []).flatMap((f) =>
        f.vessels.map((v) => ({ ...v, fleet_name: f.name })),
    )

    const openVessel = (v: Vessel) => {
        if (v.id === null) return
        setVesselId(v.id)
        setView("vessel")
    }

    /** 切到单船视图 —— 还没选船就选第一艘，别让页面空着 */
    const openVesselView = () => {
        if (vesselId === null) {
            const first = allVessels.find((v) => v.id !== null)
            if (first?.id !== null && first?.id !== undefined) setVesselId(first.id)
        }
        setView("vessel")
    }

    return (
        <div>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14, flexWrap: "wrap" }}>
                <h2 style={{ margin: 0, fontSize: 16 }}>总览</h2>
                {/* 视图切换 */}
                <div style={{ display: "flex", gap: 4, marginLeft: "auto" }}>
                    <button
                        className={view === "fleet" ? "bdg ok" : "bdg neutral"}
                        style={{ cursor: "pointer", border: "none" }}
                        onClick={() => setView("fleet")}
                    >
                        船队视图
                    </button>
                    <button
                        className={view === "vessel" ? "bdg ok" : "bdg neutral"}
                        style={{ cursor: view === "vessel" ? "default" : "pointer", border: "none" }}
                        onClick={openVesselView}
                        disabled={allVessels.length === 0}
                        title={allVessels.length === 0 ? "还没有船" : undefined}
                    >
                        单船视图
                    </button>
                </div>
            </div>

            {view === "fleet" ? (
                <>
                    {/* 全局四个数 */}
                    <div className="grid g-4" style={{ marginBottom: 14 }}>
                        <div className="card" style={{ padding: "12px 14px" }}>
                            <div className="subtle">船队</div>
                            <div style={{ fontSize: 22, fontWeight: 700 }}>{totals?.fleet_count ?? "—"}</div>
                            <div className="subtle" style={{ fontSize: 11 }}>
                                共 {totals?.vessel_count ?? "—"} 艘船
                            </div>
                        </div>
                        <div className="card" style={{ padding: "12px 14px" }}>
                            <div className="subtle">资产</div>
                            <div style={{ fontSize: 22, fontWeight: 700 }}>{totals?.asset_count ?? assets.data?.total ?? "—"}</div>
                            <Link to="/assets" className="link" style={{ fontSize: 12 }}>查看清单 →</Link>
                        </div>
                        <div className="card" style={{ padding: "12px 14px" }}>
                            <div className="subtle">拓扑图</div>
                            <div style={{ fontSize: 22, fontWeight: 700 }}>{topologies.data?.items.length ?? "—"}</div>
                            <Link to="/topologies" className="link" style={{ fontSize: 12 }}>查看拓扑 →</Link>
                        </div>
                        <div className="card" style={{ padding: "12px 14px" }}>
                            <div className="subtle">FortiSIEM</div>
                            <div style={{ fontSize: 22, fontWeight: 700 }}>
                                {siem?.connected ? "已连接" : siem?.configured ? "未连通" : "未配置"}
                            </div>
                            <div className="subtle" style={{ marginTop: 2 }}>
                                {siem?.error ?? "事件汇聚点正常"}
                            </div>
                            <Link to="/siem" className="link" style={{ fontSize: 12 }}>分段诊断 →</Link>
                        </div>
                    </div>

                    {/* 船队卡片 */}
                    <div className="grid g-2" style={{ marginBottom: 14 }}>
                        {(fleetData.data?.fleets ?? []).map((f) => (
                            <FleetCard
                                key={f.id ?? "none"}
                                fleet={f}
                                onOpen={openVessel}
                                onOpenFleet={() => setView("fleet")}
                            />
                        ))}
                        {fleetData.isLoading && <div className="subtle">加载中…</div>}
                        {fleetData.data && fleetData.data.fleets.length === 0 && (
                            <div className="card">
                                <div className="subtle">还没有船队。到「船队与船舶」页建一支。</div>
                                <Link to="/fleets" className="link">船队与船舶 →</Link>
                            </div>
                        )}
                    </div>
                </>
            ) : (
                <VesselView
                    data={vesselData.data}
                    loading={vesselData.isLoading}
                    onBack={() => setView("fleet")}
                    vessels={allVessels}
                    vesselId={vesselId}
                    onSelect={(id) => setVesselId(id)}
                />
            )}

            {/* 全船队的事件 —— 单船视图看的是那艘船的 */}
            {view === "fleet" && (
                <div className="grid g-2">
                    <div className="card">
                        <div className="card-h"><h3>活跃事件严重度</h3></div>
                        <div style={{ padding: 14, display: "flex", gap: 10, flexWrap: "wrap" }}>
                            {SEVERITIES.map((s) => (
                                <div key={s} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                    <SeverityBadge severity={s} />
                                    <b style={{ fontSize: 15 }}>{bySeverity[s] ?? 0}</b>
                                </div>
                            ))}
                            {items.length === 0 && <span className="subtle">暂无事件</span>}
                        </div>
                    </div>

                    <div className="card">
                        <div className="card-h"><h3>最近事件</h3></div>
                        <div className="tbl-wrap" style={{ maxHeight: 260, overflowY: "auto" }}>
                            <table>
                                <thead><tr><th>严重度</th><th>设备</th><th>标题</th><th>来源</th></tr></thead>
                                <tbody>
                                    {items.slice(0, 8).map((e) => (
                                        <tr key={e.id}>
                                            <td><SeverityBadge severity={e.severity} /></td>
                                            <td className="mono muted">{e.device_name ?? e.device_natural_id ?? "—"}</td>
                                            <td className="wrap">{e.title}</td>
                                            <td><span className="bdg neutral">{e.source}</span></td>
                                        </tr>
                                    ))}
                                    {items.length === 0 && (
                                        <tr><td colSpan={4} className="muted" style={{ textAlign: "center", padding: 22 }}>暂无事件</td></tr>
                                    )}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}
