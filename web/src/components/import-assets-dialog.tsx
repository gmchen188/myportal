/**
 * 把资产清单里的设备导入为拓扑节点。
 *
 * ## 为什么需要这个
 *
 * 拓扑图上画的是**逻辑位置**，资产清单里是**真实设备**。两边没关联，
 * SIEM 收进来的真实事件就落不到任何节点上 —— 监控面板一片灰色 unknown，
 * 看起来像「没收到告警」，其实是「收到了但不知道对应哪台设备」。
 *
 * 导入做两件事：
 *   1. 在拓扑图上加一个节点（复用图里已有的 mxStyle，不新造样式）
 *   2. 建 device_monitors 绑定 —— **事件归集靠这个**，不是靠节点本身
 *
 * ## 幂等
 *
 * 同一个资产重复导入不会产生第二个节点：已绑到本拓扑的会被排除，
 * 图里已有同名节点的复用那个。所以这个按钮可以随便点。
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { Download, X } from "lucide-react"

import { api } from "@/api/client"
import type { ImportableAsset } from "@/api/client"

interface Props {
    /** 要导入到哪张拓扑图 */
    topologyId: number
    topologyName: string
    onClose: () => void
}

export function ImportAssetsDialog({ topologyId, topologyName, onClose }: Props) {
    const qc = useQueryClient()
    const [selected, setSelected] = useState<Set<number>>(new Set())
    const [zone, setZone] = useState("")

    const list = useQuery({
        queryKey: ["importable-assets", topologyId],
        queryFn: () => api.topologies.importableAssets(topologyId),
    })

    const run = useMutation({
        mutationFn: (ids: number[]) =>
            api.topologies.importAssets(topologyId, {
                asset_ids: ids,
                ...(zone.trim() ? { zone: zone.trim() } : {}),
            }),
        onSuccess: (r) => {
            // 拓扑图变了（节点数变了），面板也要跟着刷新
            void qc.invalidateQueries({ queryKey: ["topologies"] })
            void qc.invalidateQueries({ queryKey: ["monitor-panel"] })
            void qc.invalidateQueries({ queryKey: ["importable-assets", topologyId] })
            onClose()
            return r
        },
    })

    // 首次打开时拉一次
    const items = list.data?.items ?? []

    const toggle = (id: number) => {
        setSelected((prev) => {
            const next = new Set(prev)
            if (next.has(id)) next.delete(id)
            else next.add(id)
            return next
        })
    }

    const errText = (() => {
        const e = run.error as { detail?: string; message?: string } | null
        return e?.detail ?? e?.message ?? "未知错误"
    })()

    return (
        <div
            style={{
                position: "fixed",
                inset: 0,
                background: "rgba(8, 15, 30, 0.55)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                padding: 20,
                zIndex: 100,
            }}
            role="dialog"
            aria-modal="true"
            aria-label="导入资产到拓扑图"
        >
            <div
                className="card"
                style={{ width: "min(720px, 100%)", maxHeight: "86vh", overflow: "auto" }}
            >
                {/* 头部 */}
                <div
                    style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 10,
                        padding: "12px 14px",
                        borderBottom: "1px solid var(--border)",
                        position: "sticky",
                        top: 0,
                        background: "var(--surface, #fff)",
                        zIndex: 1,
                    }}
                >
                    <b style={{ fontSize: 14 }}>导入设备到「{topologyName}」</b>
                    <button
                        type="button"
                        className="btn"
                        style={{ marginLeft: "auto", height: 26, padding: "0 8px" }}
                        onClick={onClose}
                        aria-label="关闭"
                    >
                        <X size={13} />
                    </button>
                </div>

                <div style={{ padding: 14 }}>
                    {/* 说明 */}
                    <p className="subtle" style={{ margin: "0 0 12px" }}>
                        选中的资产会在图上新增节点，并建立监控绑定 ——
                        绑定之后，SIEM 的真实事件才能点亮对应节点的颜色。
                    </p>

                    {/* 区域 */}
                    <label className="label" style={{ display: "block", marginBottom: 10 }}>
                        放到哪个区域（留空则用默认的「导入设备」区域）
                        <input
                            className="input"
                            value={zone}
                            onChange={(e) => setZone(e.target.value)}
                            placeholder="例如：核心机房"
                            style={{ marginTop: 4 }}
                        />
                    </label>

                    {/* 资产列表 */}
                    {list.isPending && <div className="muted">正在读取可导入的资产…</div>}

                    {list.isError && (
                        <div className="bdg err">读取失败：{String((list.error as Error)?.message ?? list.error)}</div>
                    )}

                    {!list.isPending && !list.isError && items.length === 0 && (
                        <div className="muted" style={{ padding: "18px 0", textAlign: "center" }}>
                            没有可导入的资产 —— 资产清单里的设备都已绑到这张拓扑图上。
                        </div>
                    )}

                    {items.length > 0 && (
                        <div className="tbl-wrap" style={{ maxHeight: 320, overflow: "auto" }}>
                            <table>
                                <thead>
                                    <tr>
                                        <th style={{ width: 30 }} />
                                        <th>名称</th>
                                        <th>自然标识</th>
                                        <th>IP</th>
                                        <th>厂商</th>
                                        <th>提示</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {items.map((a: ImportableAsset) => (
                                        <tr key={a.id}>
                                            <td>
                                                <input
                                                    type="checkbox"
                                                    checked={selected.has(a.id)}
                                                    onChange={() => toggle(a.id)}
                                                    aria-label={`选择 ${a.name ?? a.natural_id}`}
                                                />
                                            </td>
                                            <td className="strong">{a.name ?? a.natural_id ?? "—"}</td>
                                            <td className="mono muted">{a.natural_id ?? "—"}</td>
                                            <td className="mono muted">{a.ip ?? "—"}</td>
                                            <td className="muted">{a.vendor ?? "—"}</td>
                                            <td>
                                                {a.already_in_graph && (
                                                    <span className="bdg info">图里已有同名节点</span>
                                                )}
                                                {a.bound_elsewhere && (
                                                    <span className="bdg warn">已绑到其他拓扑图</span>
                                                )}
                                                {!a.already_in_graph && !a.bound_elsewhere && (
                                                    <span className="muted">—</span>
                                                )}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}

                    {run.isError && (
                        <div className="bdg err" style={{ marginTop: 10 }}>
                            导入失败：{errText}
                        </div>
                    )}

                    {/* 底部 */}
                    <div
                        style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 10,
                            marginTop: 14,
                            paddingTop: 12,
                            borderTop: "1px solid var(--border)",
                        }}
                    >
                        <span className="muted" style={{ fontSize: 12 }}>
                            已选 {selected.size} 台
                        </span>
                        <button
                            type="button"
                            className="btn primary"
                            style={{ marginLeft: "auto" }}
                            disabled={selected.size === 0 || run.isPending}
                            onClick={() => run.mutate(Array.from(selected))}
                        >
                            <Download size={14} />
                            {run.isPending ? "导入中…" : "导入"}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    )
}
