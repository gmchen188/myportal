/**
 * 监控面板。
 *
 * 从保存的拓扑图生成一个**可拖拽编排**的面板：节点按监控状态上色
 * （critical 红 / high 粉红 / medium 黄 / 正常绿 / 未知灰）。
 *
 * ## 拖拽的边界
 *
 * **拖拽只改布局，不改拓扑。** 节点在画布上的位置变了，连线跟着重算 ——
 * 但设备与设备之间「谁连谁」是拓扑图里的事实，拖一下就改不了。
 * 要改连线关系，去 draw.io 编辑器里改拓扑图。
 *
 * 位置存在浏览器本地（localStorage），按「拓扑 id」分组。
 * 后端不存布局 —— 布局是**个人的视图偏好**，不是资产数据。
 * 要团队共享布局，那是另一个需求（存到后端的 topology.node_bindings 或
 * 单独的 layouts 表），不在这一版范围里。
 */

import { useQuery } from "@tanstack/react-query"
import { useEffect, useMemo, useRef, useState } from "react"
import { Link } from "react-router-dom"

import { api } from "@/api/client"
import { SeverityBadge, SeverityShape } from "@/components/severity"

const LAYOUT_KEY = "myportal.monitor.layout"

type Layout = Record<string, Record<string, { x: number; y: number }>>

function loadLayout(): Layout {
    try {
        return JSON.parse(localStorage.getItem(LAYOUT_KEY) ?? "{}") as Layout
    } catch {
        return {}
    }
}

function saveLayout(l: Layout): void {
    try {
        localStorage.setItem(LAYOUT_KEY, JSON.stringify(l))
    } catch {
        /* 隐私模式下写不进去，不影响使用 */
    }
}

export function MonitorPage() {
    const topologies = useQuery({ queryKey: ["topologies"], queryFn: () => api.topologies.list() })
    const [topologyId, setTopologyId] = useState<number | null>(null)
    const [layout, setLayout] = useState<Layout>(() => loadLayout())
    const [dragging, setDragging] = useState<string | null>(null)
    const dragOffset = useRef({ x: 0, y: 0 })
    const canvasRef = useRef<HTMLDivElement>(null)

    // 选中第一张拓扑
    useEffect(() => {
        const first = topologies.data?.items[0]
        if (topologyId === null && first) {
            setTopologyId(first.id)
        }
    }, [topologies.data, topologyId])

    const panel = useQuery({
        queryKey: ["monitor-panel", topologyId],
        queryFn: () => api.monitor.panel(topologyId as number),
        enabled: topologyId !== null,
        refetchInterval: 15_000,
    })

    // 拖拽中：跟着鼠标走
    useEffect(() => {
        if (!dragging) return

        function onMove(e: MouseEvent) {
            if (!dragging) return
            const rect = canvasRef.current?.getBoundingClientRect()
            if (!rect) return
            const x = e.clientX - rect.left - dragOffset.current.x
            const y = e.clientY - rect.top - dragOffset.current.y
            setLayout((prev) => {
                const key = String(topologyId)
                const forTopo = { ...(prev[key] ?? {}) }
                forTopo[dragging] = { x: Math.max(0, x), y: Math.max(0, y) }
                return { ...prev, [String(topologyId)]: forTopo }
            })
        }
        function onUp() {
            setDragging(null)
            saveLayout(layout)
        }
        window.addEventListener("mousemove", onMove)
        window.addEventListener("mouseup", onUp)
        return () => {
            window.removeEventListener("mousemove", onMove)
            window.removeEventListener("mouseup", onUp)
        }
    }, [dragging, layout, topologyId])

    // 切换拓扑时保存当前布局
    useEffect(() => {
        saveLayout(layout)
    }, [layout])

    const nodes = panel.data?.nodes ?? []
    const zones = panel.data?.zones ?? []
    const links = panel.data?.links ?? []
    const counts = panel.data?.counts ?? {}

    // 节点位置：优先用本地布局，没有就用拓扑图里的坐标
    const positioned = useMemo(() => {
        const saved = layout[String(topologyId ?? "")] ?? {}
        return nodes.map((n) => ({
            ...n,
            px: saved[n.node_id]?.x ?? n.x,
            py: saved[n.node_id]?.y ?? n.y,
        }))
    }, [nodes, layout, topologyId])

    const byId = useMemo(() => new Map(positioned.map((n) => [n.node_id, n])), [positioned])

    /**
     * 画布尺寸 —— **按内容算，不能写死**。
     *
     * 写死 900×2000 的时候，导入的设备落在 y=988~1220，被裁在画布外 ——
     * 用户滚到底也看不到自己刚导入的设备。内容有多高，画布就有多高。
     */
    const canvasSize = useMemo(() => {
        const PAD = 60
        let maxX = 1200
        let maxY = 700
        for (const z of zones) {
            maxX = Math.max(maxX, (z.x ?? 0) + (z.w ?? 0))
            maxY = Math.max(maxY, (z.y ?? 0) + (z.h ?? 0))
        }
        for (const n of positioned) {
            maxX = Math.max(maxX, (n.px ?? 0) + (n.w ?? 0))
            maxY = Math.max(maxY, (n.py ?? 0) + (n.h ?? 0))
        }
        return { w: maxX + PAD, h: maxY + PAD }
    }, [zones, positioned])

    if (topologies.isLoading) return <p className="muted">加载中…</p>
    if (!topologies.data?.items.length) {
        return (
            <div className="card" style={{ padding: 24, textAlign: "center" }}>
                <p className="muted">还没有拓扑图。</p>
                <p className="subtle" style={{ marginTop: 6 }}>
                    先到 <Link to="/topologies" className="link">网络拓扑</Link> 保存一张，再回来做监控。
                </p>
            </div>
        )
    }

    return (
        <div>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14 }}>
                <div>
                    <h2 style={{ margin: 0, fontSize: 16 }}>监控面板</h2>
                    <p className="subtle" style={{ margin: "3px 0 0" }}>
                        拖动节点可调整布局；位置只存在本机，不改拓扑结构
                    </p>
                </div>
                <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
                    <select
                        className="select"
                        style={{ width: 200 }}
                        value={topologyId ?? ""}
                        onChange={(e) => setTopologyId(Number(e.target.value))}
                    >
                        {topologies.data.items.map((t) => (
                            <option key={t.id} value={t.id}>
                                {t.name}
                            </option>
                        ))}
                    </select>
                </div>
            </div>

            {/* 严重度统计 */}
            <div className="grid g-4" style={{ marginBottom: 14 }}>
                {(["critical", "high", "medium", "unknown"] as const).map((sev) => (
                    <div className="card" key={sev} style={{ padding: "12px 14px" }}>
                        <div className="subtle">{sev === "unknown" ? "未接入" : sev}</div>
                        <div style={{ fontSize: 22, fontWeight: 700, marginTop: 2 }}>
                            {counts[sev] ?? 0}
                        </div>
                    </div>
                ))}
            </div>

            {panel.data?.parse_error && (
                <div className="card" style={{ padding: 12, marginBottom: 12, borderColor: "var(--color-sev-critical)" }}>
                    <b style={{ color: "var(--color-sev-critical)" }}>拓扑解析失败</b>
                    <div className="subtle" style={{ marginTop: 4 }}>{panel.data.parse_error}</div>
                </div>
            )}

            {/* 画布 */}
            <div className="card" style={{ padding: 0, overflow: "hidden" }}>
                <div
                    ref={canvasRef}
                    style={{
                        position: "relative",
                        height: 560,
                        overflow: "auto",
                        background:
                            "repeating-linear-gradient(0deg, transparent 0 19px, var(--border) 19px 20px), repeating-linear-gradient(90deg, transparent 0 19px, var(--border) 19px 20px)",
                    }}
                >
                    <div
                        style={{
                            position: "relative",
                            width: canvasSize.w,
                            height: canvasSize.h,
                        }}
                    >
                        {/* 区域框 */}
                        {zones.map((z) => (
                            <div
                                key={z.id}
                                style={{
                                    position: "absolute",
                                    left: z.x,
                                    top: z.y,
                                    width: z.w,
                                    height: z.h,
                                    border: "1.5px solid var(--border-strong)",
                                    borderRadius: 12,
                                    background: "rgb(59 130 246 / 4%)",
                                    pointerEvents: "none",
                                }}
                            >
                                <div
                                    style={{
                                        position: "absolute",
                                        left: 12,
                                        top: 10,
                                        fontSize: 12,
                                        fontWeight: 700,
                                        color: "var(--fg-muted)",
                                    }}
                                >
                                    {z.title ?? z.id}
                                </div>
                            </div>
                        ))}

                        {/* 连线 */}
                        <svg
                            style={{
                                position: "absolute",
                                inset: 0,
                                width: canvasSize.w,
                                height: canvasSize.h,
                                pointerEvents: "none",
                            }}
                            aria-hidden="true"
                        >
                            {links.map((l) => {
                                const s = l.source ? byId.get(l.source) : undefined
                                const t = l.target ? byId.get(l.target) : undefined
                                if (!s || !t) return null
                                return (
                                    <line
                                        key={l.id}
                                        x1={s.px + s.w / 2}
                                        y1={s.py + s.h / 2}
                                        x2={t.px + t.w / 2}
                                        y2={t.py + t.h / 2}
                                        stroke={l.color || "#94a3b8"}
                                        strokeWidth={2}
                                        strokeDasharray={l.dashed ? "6 4" : undefined}
                                    />
                                )
                            })}
                        </svg>

                        {/* 设备节点 */}
                        {positioned.map((n) => (
                            <div
                                key={n.node_id}
                                onMouseDown={(e) => {
                                    setDragging(n.node_id)
                                    const rect = canvasRef.current?.getBoundingClientRect()
                                    dragOffset.current = {
                                        x: e.clientX - (rect?.left ?? 0) - n.px,
                                        y: e.clientY - (rect?.top ?? 0) - n.py,
                                    }
                                }}
                                title={
                                    n.top_title
                                        ? `${n.label}\n${n.top_title}\n活跃事件 ${n.active_incidents} 条`
                                        : `${n.label}\n未接入监控`
                                }
                                style={{
                                    position: "absolute",
                                    left: n.px,
                                    top: n.py,
                                    width: Math.max(n.w, 120),
                                    minHeight: Math.max(n.h, 40),
                                    padding: "6px 10px",
                                    background: "var(--surface)",
                                    border: `2px solid ${n.color}`,
                                    borderRadius: 8,
                                    cursor: dragging === n.node_id ? "grabbing" : "grab",
                                    userSelect: "none",
                                    boxShadow: "var(--shadow)",
                                    display: "flex",
                                    alignItems: "center",
                                    gap: 6,
                                }}
                            >
                                <SeverityShape severity={n.severity} color={n.color} />
                                <span style={{ fontSize: 12, fontWeight: 600 }}>{n.label}</span>
                                {n.active_incidents > 0 && (
                                    <span className="bdg err" style={{ marginLeft: "auto" }}>
                                        {n.active_incidents}
                                    </span>
                                )}
                            </div>
                        ))}
                    </div>
                </div>
            </div>

            {/* 图例 */}
            <div className="card" style={{ padding: 12, marginTop: 14 }}>
                <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "center" }}>
                    {(["critical", "high", "medium", "normal", "unknown"] as const).map((s) => (
                        <span key={s} style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
                            <SeverityShape severity={s} color={panel.data?.severity_colors?.[s] ?? "#94a3b8"} />
                            <SeverityBadge severity={s} />
                        </span>
                    ))}
                    <span className="subtle" style={{ marginLeft: "auto" }}>
                        灰色 = 未接入监控，**不是**正常
                    </span>
                </div>
            </div>
        </div>
    )
}
