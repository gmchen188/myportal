/**
 * FortiSIEM 连接面板。
 *
 * 回答两个问题：
 *   1. **连上了吗？卡在哪一段？** —— 四段诊断逐段显示，不是一句「未连接」。
 *   2. **同步过来了吗？** —— 「同步到资产清单」按钮把 SIEM 的事件与设备
 *      拉进 myPortal，并把后台返回的条数摆出来。
 *
 * ## 为什么设备单独列一张表
 *
 * 资产清单里只到 Fortinet 设备 —— 其他设备走 syslog / webhook。
 * SIEM 的 CMDB 是**已纳管设备**的权威清单：没出现在这张表里的设备，
 * 就不在 SIEM 的管理范围内，这是要查的（漏纳管 ≠ 安全）。
 */

import { Download, RefreshCw } from "lucide-react"
import { useState } from "react"

import { SiemStageList } from "@/components/siem-diagnostics"
import { useSiemStatus, useSiemSync } from "@/hooks/use-siem"

/** 时间窗口的选项。分钟数。 */
const WINDOWS = [
    { minutes: 60, label: "最近 1 小时" },
    { minutes: 1440, label: "最近 24 小时" },
    { minutes: 10080, label: "最近 7 天" },
    { minutes: 43200, label: "最近 30 天" },
]

export function SiemPage() {
    const status = useSiemStatus()
    const sync = useSiemSync()
    const [minutes, setMinutes] = useState(1440)
    const [overwrite, setOverwrite] = useState(false)

    const data = status.data
    const devices = data?.devices ?? []
    const result = sync.data

    return (
        <div>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14 }}>
                <div>
                    <h2 style={{ margin: 0, fontSize: 16 }}>FortiSIEM 连接</h2>
                    <p className="subtle" style={{ margin: "3px 0 0" }}>
                        分段诊断 · 设备清单 · 同步到资产
                    </p>
                </div>
                <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
                    <select
                        className="select"
                        style={{ width: 150 }}
                        value={minutes}
                        onChange={(e) => setMinutes(Number(e.target.value))}
                        aria-label="同步时间窗口"
                    >
                        {WINDOWS.map((w) => (
                            <option key={w.minutes} value={w.minutes}>
                                {w.label}
                            </option>
                        ))}
                    </select>
                    <button
                        type="button"
                        className="btn"
                        onClick={() => void status.refetch()}
                        disabled={status.isFetching}
                    >
                        <RefreshCw size={14} />
                        {status.isFetching ? "检测中…" : "重新检测"}
                    </button>
                    <button
                        type="button"
                        className="btn primary"
                        onClick={() =>
                            sync.mutate({ minutes, devices: true, overwrite })
                        }
                        disabled={sync.isPending}
                    >
                        <Download size={14} />
                        {sync.isPending ? "同步中…" : "同步到资产清单"}
                    </button>
                </div>
            </div>

            {/*
              加载中 —— 不裸奔。

              注意 `isLoading` 不够用：TanStack Query 的 `isLoading` 是
              `isPending && isFetching`，而查询**被暂停**时 isFetching 是
              false —— 页面会既不显示加载、也不显示错误，一片空白。

              所以判据用 `isPending`（还没有数据）。「已暂停」单独说清楚：
              它不是加载慢，而是查询没在跑 —— 浏览器离线，或标签页在后台
              （TanStack Query 的重试以窗口聚焦为前提）。

              手动「重新检测」不受暂停影响：refetch 直接起一次新请求。
            */}
            {status.isPending && !data && (
                <div className="card" style={{ padding: 24, textAlign: "center" }}>
                    {status.fetchStatus === "paused" ? (
                        <>
                            <p className="muted">检测已暂停</p>
                            <p className="subtle" style={{ marginTop: 6 }}>
                                浏览器离线，或标签页在后台 —— 恢复后会自动重试，也可以点右上角「重新检测」
                            </p>
                        </>
                    ) : (
                        <p className="muted">正在检测 FortiSIEM 连接…</p>
                    )}
                </div>
            )}

            {/* 请求失败 —— 说清楚是请求失败，不是「SIEM 连不上」 */}
            {status.isError && (
                <div className="card" style={{ padding: 14, marginBottom: 14, borderColor: "var(--color-sev-critical)" }}>
                    <b style={{ color: "var(--color-sev-critical)" }}>无法获取连接状态</b>
                    <div className="subtle" style={{ marginTop: 4 }}>
                        {status.error instanceof Error ? status.error.message : String(status.error)}
                    </div>
                    <button
                        type="button"
                        className="btn"
                        style={{ marginTop: 10 }}
                        onClick={() => void status.refetch()}
                    >
                        重试
                    </button>
                </div>
            )}

            {data && (
                <>
                    {/* 汇总 */}
                    <div className="grid g-4" style={{ marginBottom: 14 }}>
                        <div className="card" style={{ padding: "12px 14px" }}>
                            <div className="subtle">连接状态</div>
                            <div style={{ fontSize: 18, fontWeight: 700, marginTop: 2 }}>
                                {data.connected ? "已连接" : data.configured ? "未连通" : "未配置"}
                            </div>
                            <div className="subtle" style={{ marginTop: 2 }}>
                                {data.stage === "ok" ? "四段全通" : data.stage ? `卡在 ${data.stage} 段` : "未探测"}
                            </div>
                        </div>
                        <div className="card" style={{ padding: "12px 14px" }}>
                            <div className="subtle">组织</div>
                            <div style={{ fontSize: 18, fontWeight: 700, marginTop: 2 }}>{data.org ?? "—"}</div>
                            <div className="subtle" style={{ marginTop: 2 }}>
                                SIEM 侧的租户边界
                            </div>
                        </div>
                        <div className="card" style={{ padding: "12px 14px" }}>
                            <div className="subtle">已纳管设备</div>
                            <div style={{ fontSize: 18, fontWeight: 700, marginTop: 2 }}>{devices.length}</div>
                            <div className="subtle" style={{ marginTop: 2 }}>
                                来自 SIEM CMDB
                            </div>
                        </div>
                        <div className="card" style={{ padding: "12px 14px" }}>
                            <div className="subtle">凭据</div>
                            <div style={{ fontSize: 18, fontWeight: 700, marginTop: 2 }}>
                                {data.configured ? "已配置" : "未配置"}
                            </div>
                            <div className="subtle" style={{ marginTop: 2 }}>
                                {data.configured ? "client id / secret 已设置" : "缺少 client id / secret"}
                            </div>
                        </div>
                    </div>

                    {/* 失败原因 —— 顶层 error 与分段诊断分开呈现 */}
                    {data.error && (
                        <div
                            className="card"
                            style={{
                                padding: 12,
                                marginBottom: 14,
                                borderColor: "var(--color-sev-critical)",
                            }}
                        >
                            <b style={{ color: "var(--color-sev-critical)" }}>连接失败</b>
                            <div style={{ marginTop: 4, fontSize: 13 }}>{data.error}</div>
                        </div>
                    )}

                    <div className="grid g-21" style={{ marginBottom: 14 }}>
                        {/* 四段诊断 */}
                        <div className="card">
                            <div className="card-h">
                                <h3>分段诊断</h3>
                                <span className="sub">TCP → TLS → 认证 → 读取设备</span>
                            </div>
                            <SiemStageList status={data} />
                        </div>

                        {/* 同步 */}
                        <div className="card">
                            <div className="card-h">
                                <h3>同步</h3>
                            </div>
                            <div style={{ padding: 14 }}>
                                <p className="subtle" style={{ margin: "0 0 10px" }}>
                                    把 SIEM 的事件与设备拉进 myPortal。按
                                    <span className="mono"> external_id </span>
                                    去重，重复同步不会重复入库。
                                </p>

                                <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, marginBottom: 10 }}>
                                    <input
                                        type="checkbox"
                                        checked={overwrite}
                                        onChange={(e) => setOverwrite(e.target.checked)}
                                    />
                                    覆盖已存在的行（默认不覆盖 —— 保留先到的那条）
                                </label>

                                <button
                                    type="button"
                                    className="btn primary"
                                    style={{ width: "100%" }}
                                    onClick={() => sync.mutate({ minutes, devices: true, overwrite })}
                                    disabled={sync.isPending}
                                >
                                    <Download size={14} />
                                    {sync.isPending ? "同步中…" : "同步到资产清单"}
                                </button>

                                {sync.isError && (
                                    <div
                                        style={{
                                            marginTop: 12,
                                            padding: 10,
                                            borderRadius: 8,
                                            border: "1px solid var(--color-sev-critical)",
                                            fontSize: 12.5,
                                            color: "var(--color-sev-critical)",
                                        }}
                                    >
                                        {sync.error instanceof Error
                                            ? sync.error.message
                                            : String(sync.error)}
                                    </div>
                                )}

                                {result && !sync.isError && (
                                    <div style={{ marginTop: 12 }}>
                                        <div className="subtle" style={{ marginBottom: 6 }}>
                                            上次同步 · 组织 {result.org} · 回溯 {result.window_minutes} 分钟
                                        </div>
                                        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
                                            <span className="bdg info">
                                                事件 拉取 {result.events.fetched ?? 0}
                                            </span>
                                            <span className="bdg ok">
                                                事件 新增 {result.events.created}
                                            </span>
                                            <span className="bdg warn">
                                                事件 更新 {result.events.updated}
                                            </span>
                                            <span className="bdg neutral">
                                                事件 跳过 {result.events.skipped}
                                            </span>
                                        </div>
                                        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                                            <span className="bdg info">
                                                设备 共 {result.devices.total ?? 0}
                                            </span>
                                            <span className="bdg ok">
                                                设备 新增 {result.devices.created}
                                            </span>
                                            <span className="bdg warn">
                                                设备 更新 {result.devices.updated}
                                            </span>
                                            <span className="bdg neutral">
                                                设备 跳过 {result.devices.skipped}
                                            </span>
                                        </div>
                                        <div className="mono muted" style={{ marginTop: 8, fontSize: 11.5 }}>
                                            {result.synced_at?.slice(0, 19).replace("T", " ")}
                                        </div>
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>

                    {/* 设备清单 */}
                    <div className="card">
                        <div className="card-h">
                            <h3>SIEM 设备清单</h3>
                            <span className="sub">共 {devices.length} 台</span>
                        </div>
                        <div className="tbl-wrap">
                            <table>
                                <thead>
                                    <tr>
                                        <th>名称</th>
                                        <th>自然标识</th>
                                        <th>访问 IP</th>
                                        <th>厂商</th>
                                        <th>型号</th>
                                        <th>版本</th>
                                        <th>组织</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {devices.map((d) => (
                                        <tr key={d.natural_id || d.name}>
                                            <td className="strong">{d.name || "—"}</td>
                                            <td className="mono muted">{d.natural_id || "—"}</td>
                                            <td className="mono muted">{d.access_ip || "—"}</td>
                                            <td>{d.vendor ?? "—"}</td>
                                            <td className="muted">{d.model ?? "—"}</td>
                                            <td className="muted">{d.version ?? "—"}</td>
                                            <td>
                                                <span className="bdg neutral">{d.org ?? "—"}</span>
                                            </td>
                                        </tr>
                                    ))}
                                    {devices.length === 0 && (
                                        <tr>
                                            <td colSpan={7} className="muted" style={{ textAlign: "center", padding: 26 }}>
                                                {data.connected ? "SIEM 里没有读到设备" : "SIEM 未连通，取不到设备清单"}
                                            </td>
                                        </tr>
                                    )}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </>
            )}
        </div>
    )
}
