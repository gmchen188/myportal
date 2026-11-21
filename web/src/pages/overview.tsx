import { useQuery } from "@tanstack/react-query"
import { Link } from "react-router-dom"

import { api } from "@/api/client"
import { SeverityBadge } from "@/components/severity"

/**
 * 总览。
 *
 * 数字全部来自后台 —— 没有硬编码。这里没有"演示数据"徽章：
 * 演示版在 demo/ 目录，��式的数字带徽章标注来源。
 */
export function OverviewPage() {
    const assets = useQuery({ queryKey: ["assets"], queryFn: () => api.assets.list({ limit: 1 }) })
    const topologies = useQuery({ queryKey: ["topologies"], queryFn: () => api.topologies.list() })
    const events = useQuery({ queryKey: ["events"], queryFn: () => api.monitor.events({ limit: 500 }) })
    const health = useQuery({ queryKey: ["health"], queryFn: () => api.health() })

    const items = events.data?.items ?? []
    const bySeverity = items.reduce<Record<string, number>>((acc, e) => {
        acc[e.severity] = (acc[e.severity] ?? 0) + 1
        return acc
    }, {})

    const siem = health.data?.siem

    return (
        <div>
            <h2 style={{ margin: "0 0 14px", fontSize: 16 }}>总览</h2>

            <div className="grid g-4" style={{ marginBottom: 14 }}>
                <div className="card" style={{ padding: "12px 14px" }}>
                    <div className="subtle">资产</div>
                    <div style={{ fontSize: 22, fontWeight: 700 }}>{assets.data?.total ?? "—"}</div>
                    <Link to="/assets" className="link" style={{ fontSize: 12 }}>查看清单 →</Link>
                </div>
                <div className="card" style={{ padding: "12px 14px" }}>
                    <div className="subtle">拓扑图</div>
                    <div style={{ fontSize: 22, fontWeight: 700 }}>{topologies.data?.items.length ?? "—"}</div>
                    <Link to="/topologies" className="link" style={{ fontSize: 12 }}>查看拓扑 →</Link>
                </div>
                <div className="card" style={{ padding: "12px 14px" }}>
                    <div className="subtle">事件总数</div>
                    <div style={{ fontSize: 22, fontWeight: 700 }}>{events.data?.count ?? "—"}</div>
                    <Link to="/events" className="link" style={{ fontSize: 12 }}>查看事件 →</Link>
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

            <div className="grid g-2">
                <div className="card">
                    <div className="card-h"><h3>活跃事件严重度</h3></div>
                    <div style={{ padding: 14, display: "flex", gap: 10, flexWrap: "wrap" }}>
                        {(["critical", "high", "medium", "low", "informational"] as const).map((s) => (
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
        </div>
    )
}
