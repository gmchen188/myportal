import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AlertTriangle, CheckCircle2, CloudUpload, Loader2, XCircle } from "lucide-react"
import { useState } from "react"

import { api, type Asset, type CmdbMappedAsset } from "../api/client"

/**
 * 把资产推到 FortiSIEM CMDB。
 *
 * ## 为什么是手动动作
 *
 * CMDB 是 FortiSIEM **自己发现**的设备表；资产清单是人工维护的**权威清单**。
 * 保存资产时自动写 CMDB 会把没接监控的设备也灌进去，污染 SIEM 的设备视图。
 *
 * ## 为什么要先预览
 *
 * 映射不是一对一的 —— `zone → deviceTag`、`cbs_class → purdueLevel`
 * 这类不直观。用户点「推送」之前应该看到「我的资产会变成 CMDB 的什么字段」。
 *
 * ## 失败不阻断
 *
 * 推送失败只影响推送状态，资产照旧在库里 —— 改完配置可以重推。
 */

/** CMDB 字段的中文说明 —— 预览时要说清字段去哪了。 */
const CMDB_FIELD_LABEL: Record<string, string> = {
    name: "设备名称",
    accessIp: "管理 IP",
    "deviceType.vendor": "厂商",
    "deviceType.model": "型号",
    hwSerialNum: "硬件序列号",
    deviceTag: "设备标签（船舶安全区域）",
    purdueLevel: "Purdue Level（IEC 62443 分级）",
    contact: "责任人",
    importance: "重要度",
    description: "描述",
}

export function CmdbPushPanel({
    assets,
    onClose,
}: {
    assets: Asset[]
    onClose: () => void
}) {
    const qc = useQueryClient()
    const [selected, setSelected] = useState<Set<number>>(new Set())
    const [force, setForce] = useState(false)
    const [result, setResult] = useState<string | null>(null)
    const [error, setError] = useState<string | null>(null)

    const status = useQuery({
        queryKey: ["cmdb-status"],
        queryFn: () => api.assets.cmdbStatus(),
    })

    const ids = [...selected]
    // **queryKey 必须稳定** —— ids 是每次渲染新建的数组，
    // 直接放进 key 会让 React Query 认为 key 一直在变 → 无限重取，
    // 结果就是「请求发了但预览区永远不显示」。
    const idsKey = ids.slice().sort((a, b) => a - b).join(",")
    const preview = useQuery({
        queryKey: ["cmdb-preview", idsKey],
        queryFn: () => api.assets.cmdbPreview(ids),
        enabled: ids.length > 0,
    })

    const push = useMutation({
        mutationFn: () => api.assets.cmdbPush(ids, force),
        onSuccess: (r) => {
            setResult(r.message)
            setError(null)
            setSelected(new Set())
            void qc.invalidateQueries({ queryKey: ["assets"] })
        },
        onError: (e: unknown) => {
            setError(e instanceof Error ? e.message : String(e))
        },
    })

    const toggle = (id: number) => {
        setSelected((prev) => {
            const next = new Set(prev)
            if (next.has(id)) next.delete(id)
            else next.add(id)
            return next
        })
    }

    const notPushed = assets.filter((a) => a.siem_push_status !== "ok")
    const alreadyPushed = assets.filter((a) => a.siem_push_status === "ok")

    return (
        <div className="card" style={{ padding: 14, marginBottom: 12 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10, flexWrap: "wrap" }}>
                <h3 style={{ margin: 0, fontSize: 15, whiteSpace: "nowrap" }}>推送到 FortiSIEM CMDB</h3>
                <button
                    type="button"
                    className="btn"
                    style={{ whiteSpace: "nowrap", flexShrink: 0, marginLeft: "auto" }}
                    onClick={onClose}
                >
                    关闭
                </button>
            </div>

            {status.data && !status.data.write_configured && (
                <div
                    className="card"
                    style={{
                        borderLeft: "3px solid var(--color-accent-600)",
                        padding: 10,
                        marginBottom: 10,
                        background: "var(--surface-2)",
                    }}
                >
                    <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                        <AlertTriangle size={15} style={{ color: "var(--color-accent-600)", flexShrink: 0, marginTop: 2 }} />
                        <div>
                            <strong style={{ fontSize: 13 }}>尚未配置 FortiSIEM 写凭据</strong>
                            <div className="subtle" style={{ fontSize: 12, marginTop: 3 }}>
                                读凭据正常（组织 {status.data.org}），但写 CMDB 需要单独的 Basic Auth
                                账号 —— 请在服务端 <code>backend/.env</code> 里配置
                                <code> FORTISIEM_BASIC_USER</code> 与{" "}
                                <code>FORTISIEM_BASIC_PASSWORD</code>。
                            </div>
                        </div>
                    </div>
                </div>
            )}

            <div
                className="card"
                style={{ borderLeft: "3px solid var(--color-brand-500)", padding: 10, marginBottom: 10 }}
            >
                <div style={{ fontSize: 12, lineHeight: 1.6 }}>
                    <strong>推送前请确认：</strong>
                    <ul style={{ margin: "5px 0 0", paddingLeft: 18 }}>
                        <li>CMDB 里只应该有<strong>已接入监控</strong>的设备 —— 没接监控的设备推过去会让 SIEM 的设备视图和覆盖率报表失真。</li>
                        <li>推送<strong>不会</strong>删除 SIEM 里的任何设备 —— 我方删资产不动 SIEM。</li>
                        <li>已推送过的默认跳过，避免 CMDB 里出现重复设备。</li>
                    </ul>
                </div>
            </div>

            {assets.length === 0 && (
                <p className="subtle" style={{ fontSize: 13 }}>当前筛选下没有资产。</p>
            )}

            {assets.length > 0 && (
                <div className="tbl-wrap" style={{ marginBottom: 10 }}>
                    <table style={{ minWidth: 520 }}>
                        <thead>
                            <tr>
                                <th style={{ width: 34 }}>
                                    <input
                                        type="checkbox"
                                        checked={selected.size > 0 && selected.size === assets.length}
                                        onChange={(e) =>
                                            setSelected(e.target.checked ? new Set(assets.map((a) => a.id)) : new Set())
                                        }
                                    />
                                </th>
                                <th>资产名称</th>
                                <th>安全区域</th>
                                <th>CBS 等级</th>
                                <th>推送状态</th>
                            </tr>
                        </thead>
                        <tbody>
                            {assets.map((a) => (
                                <tr key={a.id}>
                                    <td>
                                        <input type="checkbox" checked={selected.has(a.id)} onChange={() => toggle(a.id)} />
                                    </td>
                                    <td style={{ whiteSpace: "nowrap" }}>{a.name}</td>
                                    <td style={{ whiteSpace: "nowrap" }}>{a.zone ?? "—"}</td>
                                    <td style={{ whiteSpace: "nowrap" }}>{a.cbs_class ?? "—"}</td>
                                    <td style={{ whiteSpace: "nowrap" }}>
                                        <PushBadge asset={a} />
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            {alreadyPushed.length > 0 && (
                <label
                    style={{
                        display: "flex",
                        gap: 6,
                        alignItems: "center",
                        fontSize: 12,
                        marginBottom: 10,
                        flexWrap: "wrap",
                    }}
                >
                    <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
                    <span>
                        包含已推送过的 {alreadyPushed.length} 件（默认跳过；CMDB 没有按编号更新语义，重推会产生重复设备）
                    </span>
                </label>
            )}

            {/* 映射预览 —— 让人看清字段去哪了 */}
            {preview.data && preview.data.items.length > 0 && (
                <div className="card" style={{ padding: 10, marginBottom: 10 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
                        映射预览（{preview.data.items.length} 件）
                    </div>
                    <div className="tbl-wrap">
                        <table style={{ minWidth: 480 }}>
                            <thead>
                                <tr>
                                    <th>资产</th>
                                    <th>→ CMDB 字段</th>
                                </tr>
                            </thead>
                            <tbody>
                                {preview.data.items.map((item: CmdbMappedAsset) => (
                                    <tr key={item.asset_id}>
                                        <td style={{ whiteSpace: "nowrap" }}>{item.name}</td>
                                        <td>
                                            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                                                {Object.entries(item.fields).map(([f, v]) => (
                                                    <span key={f} className="bdg neutral" style={{ whiteSpace: "nowrap" }}>
                                                        {CMDB_FIELD_LABEL[f] ?? f}: {String(v)}
                                                    </span>
                                                ))}
                                                {item.missing.map((f) => (
                                                    <span key={f} className="bdg warn" style={{ whiteSpace: "nowrap" }}>
                                                        缺 {CMDB_FIELD_LABEL[f] ?? f}
                                                    </span>
                                                ))}
                                            </div>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {result && (
                <div
                    className="card"
                    style={{ borderLeft: "3px solid var(--color-sev-normal)", padding: 10, marginBottom: 10 }}
                >
                    <div style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
                        <CheckCircle2 size={15} style={{ color: "var(--color-sev-normal)" }} />
                        {result}
                    </div>
                </div>
            )}

            {error && (
                <div
                    className="card"
                    style={{ borderLeft: "3px solid var(--color-sev-critical)", padding: 10, marginBottom: 10 }}
                >
                    <div style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 13 }}>
                        <XCircle size={15} style={{ color: "var(--color-sev-critical)", flexShrink: 0, marginTop: 2 }} />
                        <span>{error}</span>
                    </div>
                </div>
            )}

            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
                <button
                    type="button"
                    className="btn primary"
                    style={{ whiteSpace: "nowrap", flexShrink: 0 }}
                    disabled={ids.length === 0 || push.isPending || !status.data?.write_configured}
                    onClick={() => push.mutate()}
                >
                    {push.isPending ? <Loader2 size={14} /> : <CloudUpload size={14} />}
                    {push.isPending ? "推送中…" : `推送 ${ids.length || ""} 件到 CMDB`}
                </button>
            </div>

            {notPushed.length === 0 && alreadyPushed.length > 0 && (
                <p className="subtle" style={{ fontSize: 12, marginTop: 8, marginBottom: 0 }}>
                    当前筛选下的资产都已推送过。
                </p>
            )}
        </div>
    )
}

function PushBadge({ asset }: { asset: Asset }) {
    if (asset.siem_push_status === "ok") {
        return (
            <span className="bdg ok" style={{ whiteSpace: "nowrap" }}>
                已推送
            </span>
        )
    }
    if (asset.siem_push_status === "failed") {
        return (
            <span className="bdg err" style={{ whiteSpace: "nowrap" }}>
                推送失败
            </span>
        )
    }
    if (asset.siem_push_status === "pending") {
        return (
            <span className="bdg warn" style={{ whiteSpace: "nowrap" }}>
                排队中
            </span>
        )
    }
    return (
        <span className="bdg neutral" style={{ whiteSpace: "nowrap" }}>
            未推送
        </span>
    )
}
