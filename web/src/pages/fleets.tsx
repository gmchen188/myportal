import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { api, type Fleet, type Vessel } from "@/api/client"

/**
 * 船队与船舶 —— 归属关系的维护页。
 *
 * 总览有船队视图与单船视图，资产清单也按船队-单船分类 —— 这一页管的就是
 * 那条归属关系。
 *
 * ## 为什么要有这一页
 *
 * 归属是**业务数据**，后台不能替用户猜。导入进来的设备往往只知道装在
 * 「Zone 1 · 船舶核心控制区」，不知道具体是哪艘船 —— 得有人填。
 *
 * 页面给三件事：
 *
 *   建船队 / 建船     名字、代号、IMO
 *   改名              船队与船都能改
 *   删                **删船不删资产** —— 资产变成「未归船」，还在清单里
 *
 * ## 未归船的设备怎么办
 *
 * 资产清单里「未归船」那一组是直接改归属的入口。批量归船的接口在
 * `POST /api/fleets/vessels/{id}/assets`。
 */

/** 一行可编辑的名字 */
function EditableName({
    value,
    onSave,
    placeholder,
}: {
    value: string
    onSave: (next: string) => void
    placeholder?: string
}) {
    const [draft, setDraft] = useState(value)
    const [editing, setEditing] = useState(false)
    if (!editing) {
        return (
            <span
                style={{ cursor: "text", borderBottom: "1px dashed var(--line)" }}
                onClick={() => {
                    setDraft(value)
                    setEditing(true)
                }}
                title="点击改名"
            >
                {value}
            </span>
        )
    }
    return (
        <input
            className="input"
            autoFocus
            value={draft}
            placeholder={placeholder}
            style={{ width: 180, padding: "3px 7px", fontSize: 13 }}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={() => {
                setEditing(false)
                if (draft.trim() && draft !== value) onSave(draft.trim())
            }}
            onKeyDown={(e) => {
                if (e.key === "Enter") (e.target as HTMLInputElement).blur()
                if (e.key === "Escape") {
                    setDraft(value)
                    setEditing(false)
                }
            }}
        />
    )
}

export function FleetsPage() {
    const qc = useQueryClient()
    const [error, setError] = useState<string | null>(null)
    const [newFleet, setNewFleet] = useState("")
    const [newVessel, setNewVessel] = useState<{ name: string; fleet_id: number | null } | null>(null)

    const data = useQuery({ queryKey: ["fleets"], queryFn: () => api.fleets.list() })

    const refresh = () => {
        void qc.invalidateQueries({ queryKey: ["fleets"] })
        void qc.invalidateQueries({ queryKey: ["fleet-overview"] })
        void qc.invalidateQueries({ queryKey: ["assets"] })
    }

    const createFleet = useMutation({
        mutationFn: () => api.fleets.createFleet({ name: newFleet.trim() }),
        onSuccess: () => {
            setNewFleet("")
            setError(null)
            refresh()
        },
        onError: (e: Error) => setError(e.message),
    })
    const createVessel = useMutation({
        mutationFn: () =>
            api.fleets.create({
                name: newVessel!.name.trim(),
                fleet_id: newVessel!.fleet_id ?? undefined,
            }),
        onSuccess: () => {
            setNewVessel(null)
            setError(null)
            refresh()
        },
        onError: (e: Error) => setError(e.message),
    })
    const patchFleet = useMutation({
        mutationFn: (args: { id: number; name: string }) => api.fleets.patchFleet(args.id, { name: args.name }),
        onSuccess: refresh,
        onError: (e: Error) => setError(e.message),
    })
    const patchVessel = useMutation({
        mutationFn: (args: { id: number; name: string }) => api.fleets.patchVessel(args.id, { name: args.name }),
        onSuccess: refresh,
        onError: (e: Error) => setError(e.message),
    })
    const removeFleet = useMutation({
        mutationFn: (id: number) => api.fleets.removeFleet(id),
        onSuccess: refresh,
        onError: (e: Error) => setError(e.message),
    })
    const removeVessel = useMutation({
        mutationFn: (id: number) => api.fleets.removeVessel(id),
        onSuccess: refresh,
        onError: (e: Error) => setError(e.message),
    })

    const fleets = data.data?.fleets ?? []
    const vessels = data.data?.vessels ?? []
    const orphanVessels = vessels.filter((v) => v.id !== null && v.fleet_id === null)

    const vesselRow = (v: Vessel) => (
        <div
            key={v.id ?? "none"}
            style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "7px 0 7px 18px",
                borderTop: "1px solid var(--line)",
            }}
        >
            <EditableName
                value={v.name}
                onSave={(name) => v.id !== null && patchVessel.mutate({ id: v.id, name })}
            />
            {v.code && <span className="bdg neutral mono">{v.code}</span>}
            {v.imo && <span className="subtle mono" style={{ fontSize: 11 }}>IMO {v.imo}</span>}
            <span className="subtle" style={{ marginLeft: "auto", fontSize: 11 }}>
                {v.asset_count} 资产 · {v.monitor_count} 监控 · {v.event_count} 事件
            </span>
            {v.id !== null && (
                <button
                    className="btn"
                    style={{ height: 24, padding: "0 7px" }}
                    onClick={() => {
                        // 非空断言：外层已经判过 `v.id !== null`。
                        // 属性访问的收窄 TS 不会带进闭包，所以这里要显式断言。
                        if (window.confirm(`删除「${v.name}」？\n\n它的 ${v.asset_count} 件资产不会消失，会变成「未归船」。`)) {
                            removeVessel.mutate(v.id!)
                        }
                    }}
                >
                    删除
                </button>
            )}
        </div>
    )

    return (
        <div>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14, flexWrap: "wrap" }}>
                <h2 style={{ margin: 0, fontSize: 16 }}>船队与船舶</h2>
                <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
                    <input
                        className="input"
                        placeholder="新船队名称"
                        value={newFleet}
                        style={{ width: 160 }}
                        onChange={(e) => setNewFleet(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === "Enter" && newFleet.trim()) createFleet.mutate()
                        }}
                    />
                    <button className="btn" disabled={!newFleet.trim()} onClick={() => createFleet.mutate()}>
                        新建船队
                    </button>
                </div>
            </div>

            {error && (
                <div className="card" style={{ borderLeft: "3px solid #dc2626", marginBottom: 12 }}>
                    <span style={{ color: "#dc2626" }}>{error}</span>
                </div>
            )}

            <div className="card" style={{ marginBottom: 12 }}>
                <div className="card-h">
                    <h3>船队</h3>
                    <span className="subtle" style={{ fontSize: 11 }}>点名字可以改名</span>
                </div>
                <div style={{ padding: 14 }}>
                    {fleets.length === 0 && <div className="subtle">还没有船队</div>}
                    {fleets.map((f: Fleet) => (
                        <div key={f.id ?? "none"} style={{ marginBottom: 10 }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 0" }}>
                                <EditableName
                                    value={f.name}
                                    onSave={(name) => f.id !== null && patchFleet.mutate({ id: f.id, name })}
                                />
                                {f.code && <span className="bdg neutral mono">{f.code}</span>}
                                <span className="subtle" style={{ marginLeft: "auto", fontSize: 11 }}>
                                    {f.vessel_count} 艘船 · {f.asset_count} 资产 · {f.topology_count} 张拓扑图
                                </span>
                                {f.id !== null && (
                                    <button
                                        className="btn"
                                        style={{ height: 24, padding: "0 7px" }}
                                        onClick={() => {
                                            if (window.confirm(`删除船队「${f.name}」？\n\n船与资产都保留，船会变成「未归队」。`)) {
                                                removeFleet.mutate(f.id!)
                                            }
                                        }}
                                    >
                                        删除
                                    </button>
                                )}
                                <button
                                    className="btn"
                                    style={{ height: 24, padding: "0 7px" }}
                                    onClick={() => setNewVessel({ name: "", fleet_id: f.id })}
                                >
                                    + 加船
                                </button>
                            </div>
                            {f.vessels.map(vesselRow)}
                            {newVessel?.fleet_id === f.id && (
                                <div style={{ display: "flex", gap: 8, padding: "7px 0 7px 18px" }}>
                                    <input
                                        className="input"
                                        autoFocus
                                        placeholder="船名"
                                        value={newVessel.name}
                                        style={{ width: 180 }}
                                        onChange={(e) => setNewVessel({ ...newVessel, name: e.target.value })}
                                        onKeyDown={(e) => {
                                            if (e.key === "Enter" && newVessel.name.trim()) createVessel.mutate()
                                        }}
                                    />
                                    <button
                                        className="btn"
                                        disabled={!newVessel.name.trim()}
                                        onClick={() => createVessel.mutate()}
                                    >
                                        创建
                                    </button>
                                    <button className="btn" onClick={() => setNewVessel(null)}>取消</button>
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            </div>

            {orphanVessels.length > 0 && (
                <div className="card">
                    <div className="card-h">
                        <h3>未归队的船</h3>
                        <span className="subtle" style={{ fontSize: 11 }}>还没归到任何船队</span>
                    </div>
                    <div style={{ padding: 14 }}>{orphanVessels.map(vesselRow)}</div>
                </div>
            )}
        </div>
    )
}
