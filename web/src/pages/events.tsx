import { useQuery } from "@tanstack/react-query"
import { useState } from "react"

import { api, type Severity } from "@/api/client"
import { SeverityBadge } from "@/components/severity"

const SOURCE_LABEL: Record<string, string> = {
    fortisiem: "FortiSIEM",
    syslog: "Syslog / SNMP",
    webhook: "Webhook",
    manual: "人工登记",
}

/**
 * 安全事件。
 *
 * 事件的来源渠道都在这里 —— 这正是「非 Fortinet 设备如何接安全事件」的
 * 落地界面：交换机发 syslog、扫描器推 webhook，都进同一张表。
 */
export function EventsPage() {
    const [severity, setSeverity] = useState<string>("")
    const [source, setSource] = useState<string>("")
    const events = useQuery({
        queryKey: ["events", severity, source],
        queryFn: () => api.monitor.events({ severity: severity || undefined, source: source || undefined, limit: 300 }),
    })

    return (
        <div>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14 }}>
                <div>
                    <h2 style={{ margin: 0, fontSize: 16 }}>安全事件</h2>
                    <p className="subtle" style={{ margin: "3px 0 0" }}>
                        共 {events.data?.count ?? 0} 条 · 所有渠道归集到同一张表
                    </p>
                </div>
                <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
                    <select className="select" style={{ width: 130 }} value={severity} onChange={(e) => setSeverity(e.target.value)}>
                        <option value="">全部级别</option>
                        {(["critical", "high", "medium", "low", "informational"] as Severity[]).map((s) => (
                            <option key={s} value={s}>{s}</option>
                        ))}
                    </select>
                    <select className="select" style={{ width: 150 }} value={source} onChange={(e) => setSource(e.target.value)}>
                        <option value="">全部来源</option>
                        {Object.entries(SOURCE_LABEL).map(([k, v]) => (
                            <option key={k} value={k}>{v}</option>
                        ))}
                    </select>
                </div>
            </div>

            <div className="card">
                <div className="tbl-wrap">
                    <table>
                        <thead>
                            <tr><th>严重度</th><th>设备</th><th>标题</th><th>来源</th><th>时间</th></tr>
                        </thead>
                        <tbody>
                            {(events.data?.items ?? []).map((e) => (
                                <tr key={e.id}>
                                    <td><SeverityBadge severity={e.severity} /></td>
                                    <td className="mono muted">
                                        {e.device_name ?? e.device_natural_id ?? e.device_ip ?? "—"}
                                    </td>
                                    <td>{e.title}</td>
                                    <td><span className="bdg info">{SOURCE_LABEL[e.source] ?? e.source}</span></td>
                                    <td className="mono muted">
                                        {e.occurred_at?.slice(0, 16).replace("T", " ") ?? "—"}
                                    </td>
                                </tr>
                            ))}
                            {!events.data?.items.length && (
                                <tr><td colSpan={5} className="muted" style={{ textAlign: "center", padding: 26 }}>
                                    没有符合条件的事件
                                </td></tr>
                            )}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    )
}
