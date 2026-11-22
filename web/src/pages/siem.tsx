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

import { type SiemStatus, stageLabel } from "@/api/client"
import { SiemStageList } from "@/components/siem-diagnostics"
import { useSiemRefresh, useSiemStatus, useSiemSync } from "@/hooks/use-siem"

/** 时间窗口的选项。分钟数。 */
const WINDOWS = [
    { minutes: 60, label: "最近 1 小时" },
    { minutes: 1440, label: "最近 24 小时" },
    { minutes: 10080, label: "最近 7 天" },
    { minutes: 43200, label: "最近 30 天" },
]

/** 把分钟数说成人话 ——「回溯 1440 分钟」没人读得懂。 */
function windowLabel(minutes: number): string {
    const known = WINDOWS.find((w) => w.minutes === minutes)
    if (known) return known.label
    if (minutes % 1440 === 0) return `最近 ${minutes / 1440} 天`
    if (minutes % 60 === 0) return `最近 ${minutes / 60} 小时`
    return `最近 ${minutes} 分钟`
}

export function SiemPage() {
    const status = useSiemStatus()

    /**
     * 错误文本 —— 用 `.detail`（人话）不用 `.message`（带 "[502] " 前缀）。
     *
     * 同时记下状态码与是否带四段诊断，用于区分「后台挂了」与
     * 「SIEM 连不上」—— 这两者的处置方向完全不同。
     */
    const statusError = status.error as { detail?: string; message?: string; status?: number } | null
    const statusErrorStatus = statusError?.status ?? 0
    const statusErrorHasProbes = Boolean(
        (statusError as { meta?: { probes?: unknown } } | null)?.meta?.probes,
    )
    const statusErrorText =
        statusError?.detail ?? statusError?.message ?? "未知错误"
    const refresh = useSiemRefresh()

    /** 重新检测的失败原因 —— 后端返回的是 {error, stage} 结构 */
    const refreshErrorText = (() => {
        const e = refresh.error as { detail?: string; message?: string } | null
        return e?.detail ?? e?.message ?? "未知错误"
    })()
    const sync = useSiemSync()

    /**
     * 同步失败时后台带回来的四段实测结果。
     *
     * 502 的 body 里有 `probes` —— 后台特意塞进去的运维定位信息。
     * extractErrorMeta 把它提取出来了（ApiError.meta），但不渲染
     * 就等于白带。
     */
    const syncProbes = (() => {
        const e = sync.error as { meta?: { probes?: Record<string, { ok: boolean; detail?: string }> } } | null
        const p = e?.meta?.probes
        return p && Object.keys(p).length > 0 ? p : null
    })()

    /** 把 probes 拼成一个 SiemStageList 能吃的 SiemStatus */
    const syncProbeStatus = (() => {
        const e = sync.error as { meta?: { stage?: string; probes?: Record<string, { ok: boolean; detail?: string }> } } | null
        const probes = e?.meta?.probes ?? {}
        const stage = e?.meta?.stage ?? null
        return {
            configured: true,
            connected: !stage || stage === "ok",
            org: null,
            // **顶层 error 传 null** —— stageRows 对失败段是
            // `status.error ?? probe.detail`，传了顶层 error 就会把
            // 每一段自己的实测 detail 盖掉（全变成同一句 502）。
            // 这里要的就是「每段各自的实测结果」。
            error: null,
            stage: (stage ?? "ok") as SiemStatus["stage"],
            probes: {
                tcp: probes.tcp,
                tls: probes.tls,
                auth: probes.auth,
                api: probes.api,
            },
            devices: [],
        } as SiemStatus
    })()
    const [minutes, setMinutes] = useState(1440)
    const [overwrite, setOverwrite] = useState(false)

    const data = status.data
    const devices = data?.devices ?? []
    const result = sync.data

    return (
        <div>
            <div className="page-head">
                <div>
                    <h2 style={{ margin: 0, fontSize: 16 }}>FortiSIEM 连接</h2>
                    <p className="subtle" style={{ margin: "3px 0 0" }}>
                        分段诊断 · 设备清单 · 同步到资产
                    </p>
                </div>
                <div className="page-tools">
                    <select
                        className="select"
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
                    {/*
                      overwrite 复选框放在按钮旁边 ——
                      之前它只在下面的同步卡片里，而上面的主按钮看不到它，
                      按钮的行为却依赖于它。
                    */}
                    <label
                        style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 5,
                            fontSize: 12,
                            cursor: "pointer",
                        }}
                        title="只影响事件；设备行只补空字段，不覆盖你填的"
                    >
                        <input
                            type="checkbox"
                            checked={overwrite}
                            onChange={(e) => setOverwrite(e.target.checked)}
                        />
                        覆盖已有事件
                    </label>
                    <button
                        type="button"
                        className="btn"
                        onClick={() => refresh.mutate()}
                        disabled={refresh.isPending || status.isFetching}
                    >
                        <RefreshCw size={14} />
                        {refresh.isPending ? "检测中…" : "重新检测"}
                    </button>
                    {/*
                      重新检测失败必须说出来 —— 否则按钮从「检测中…」变回
                      「重新检测」，屏上还是上一次的旧诊断结果，用户会以为
                      刚测出来的就是新的。
                    */}
                    {refresh.isError && (
                        <span className="muted" style={{ color: "var(--color-sev-critical)" }}>
                            重新检测失败：{refreshErrorText}
                        </span>
                    )}
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

            {/*
              请求失败。

              **TanStack Query v5 在 error 时保留 data**（reducer 只把
              status 改成 "error"）。所以后台挂掉后的下一次轮询失败，
              屏上会同时出现「无法获取连接状态」和「四段全通」——
              自相矛盾。

              分两种说法：
                · 没有旧数据 → 「无法获取连接状态」
                · 有旧数据   → 「刷新失败，以下是上次结果」
              旧数据标清楚是上次的，不要让人当成刚测的。
            */}
            {status.isError && (
                <div className="card" style={{ padding: 14, marginBottom: 14, borderColor: "var(--color-sev-critical)" }}>
                    <b style={{ color: "var(--color-sev-critical)" }}>
                        {data ? "刷新连接状态失败" : "无法获取连接状态"}
                    </b>
                    <div className="subtle" style={{ marginTop: 4 }}>
                        {/* 用 .detail 不是 .message ——
                            message 带 "[502] " 前缀，对用户是噪音；
                            detail 才是后端给的人话。 */}
                        {statusErrorText}
                    </div>
                    {/*
                      502 有两种完全不同的原因，处置也不同 ——
                      不说清楚用户会查错方向：
                        · 后端进程死了   → 要去启动后端
                        · 后端活着但 SIEM 连不上 → 要查 SIEM 的网络/凭据
                      后端主动返回的 502 带着四段诊断（stage/probes），
                      那种情况 detail 里已经有具体原因了。
                    */}
                    {statusErrorStatus === 502 && !statusErrorHasProbes && (
                        <div className="subtle" style={{ marginTop: 6 }}>
                            提示：这个 502 更可能是**后台服务本身没在运行**，
                            而不是 FortiSIEM 不可达 —— 先确认后台已启动，再排查 SIEM 侧。
                        </div>
                    )}
                    {data && (
                        <div className="subtle" style={{ marginTop: 6 }}>
                            下面显示的是**上一次成功探测**的结果，不是当前状态。
                        </div>
                    )}
                    <button
                        type="button"
                        className="btn"
                        style={{ marginTop: 10 }}
                        onClick={() => refresh.mutate()}
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
                                {data.stage === "ok" ? "四段全通" : data.stage ? `卡在 ${stageLabel(data.stage)} 这一段` : "未探测"}
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
                    {/*
                      连接失败 —— 四段诊断里已经有逐段说明了，这里只给总因。
                      「设备清单拉取失败」是另一回事（连接是通的），单独一块，
                      否则会出现「四段全通」+ 红「连接失败」自相矛盾。
                    */}
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
                    {data.devices_error && (
                        <div
                            className="card"
                            style={{
                                padding: 12,
                                marginBottom: 14,
                                borderColor: "var(--color-sev-high)",
                            }}
                        >
                            <b style={{ color: "var(--color-sev-high)" }}>
                                设备清单拉取失败
                            </b>
                            <div style={{ marginTop: 4, fontSize: 13 }}>
                                连接本身是通的（四段诊断全绿），但取设备列表这一步失败了：
                                {data.devices_error}
                            </div>
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

                                {/*
                                  同步按钮只在上面的工具栏里有一个 ——
                                  之前这里还有一个一模一样的 primary 按钮，
                                  运维不知道该点哪个。overwrite 复选框
                                  也移到了工具栏（紧挨着按钮）。
                                */}
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
                                        {/*
                                          502 的 body 里带了四段实测结果（probes）——
                                          后台特意塞进去的运维定位信息。提取出来了
                                          就得用上，否则等于白带。
                                        */}
                                        {syncProbes && (
                                            <div
                                                style={{
                                                    marginTop: 8,
                                                    paddingTop: 8,
                                                    borderTop: "1px solid var(--border)",
                                                }}
                                            >
                                                <div style={{ fontWeight: 600, marginBottom: 4 }}>
                                                    失败时的分段实测结果
                                                </div>
                                                <SiemStageList status={syncProbeStatus} />
                                            </div>
                                        )}
                                    </div>
                                )}

                                {result && !sync.isError && (
                                    <div style={{ marginTop: 12 }}>
                                        <div className="subtle" style={{ marginBottom: 6 }}>
                                            上次同步 · 组织 {result.org} · {windowLabel(result.window_minutes)}
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
                                        {/*
                                          「拉取 0」有两种完全相反的含义：
                                            · SIEM 里确实没有事件
                                            · 事件都在时间窗之外
                                          用户看到 0 会以为前者。**必须说清楚** ——
                                          否则运维会以为同步没生效。
                                        */}
                                        {(result.events.fetched ?? 0) === 0 && (
                                            <div className="bdg warn" style={{ marginTop: 6, display: "block" }}>
                                                这个时间窗内没有事件。SIEM 里可能有更早的事件 ——
                                                换一个更长的时间窗再试。
                                            </div>
                                        )}
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
                                            {result.devices.bound !== undefined && (
                                                <span className="bdg ok">
                                                    已绑到拓扑节点 {result.devices.bound}
                                                </span>
                                            )}
                                        </div>
                                        {/*
                                          设备拉取失败必须显红 ——
                                          否则「设备 共 0」跟「SIEM 里确实没有
                                          纳管设备」长得一模一样。而这个面板
                                          存在的意义就是区分「漏纳管 ≠ 安全」。
                                        */}
                                        {result.devices.error && (
                                            <div
                                                className="bdg err"
                                                style={{ marginTop: 8, display: "block" }}
                                            >
                                                设备拉取失败：{result.devices.error}
                                                （上面的「设备 共 0」不代表 SIEM 里没有设备）
                                            </div>
                                        )}
                                        {result.devices.bind_error && (
                                            <div
                                                className="bdg warn"
                                                style={{ marginTop: 6, display: "block" }}
                                            >
                                                拓扑自动绑定失败：{result.devices.bind_error}
                                            </div>
                                        )}
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
                                    {/*
                                      key 兜底可能撞 ——
                                      natural_id 为空是真实存在的（后端会跳过
                                      没有 natural_id 的设备），两台同名设备会
                                      产生重复 React key（警告 + 渲染错位）。
                                      兜底时补上索引。
                                    */}
                                    {devices.map((d, i) => (
                                        <tr key={d.natural_id || `${d.name}#${i}`}>
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
