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
 *   建船队 / 建船     名字、标签
 *   改名 / 改标签      船队与船都能改
 *   改归属            船必须属于某一支船队，但**可以换一支**
 *   删                **删船不删资产** —— 资产变成「未归船」，还在清单里
 *                     **删船队要先清空底下的船** —— 船不能变成无家可归
 *
 * ## 名称与标签是两回事
 *
 * 「海洋三号」是名字（唯一、给人看）；「OCEAN-3」是标签（编码、给系统用，
 * 和 CMDB 的 `deviceTag` 之类对得上）。两者都要能改，所以编辑是**两个字段**
 * 而不是把标签塞进名字。
 *
 * ## 未归船的设备怎么办
 *
 * 资产清单里「未归船」那一组是直接改归属的入口。批量归船的接口在
 * `POST /api/fleets/vessels/{id}/assets`。
 */

/**
 * 一行可编辑的文本（名字或标签）。
 *
 * **标签可以是空的** —— 所以显示时用 `emptyHint` 占位，保存时把空串转成
 * `null`（后端 `code: str | None`，空串会当成一个空标签存进去）。
 */
function EditableText({
    value,
    onSave,
    placeholder,
    emptyHint,
    mono,
}: {
    value: string | null
    onSave: (next: string | null) => void
    placeholder?: string
    emptyHint?: string
    mono?: boolean
}) {
    const [draft, setDraft] = useState(value ?? "")
    const [editing, setEditing] = useState(false)
    if (!editing) {
        return (
            <span
                style={{
                    cursor: "text",
                    borderBottom: "1px dashed var(--line)",
                    fontFamily: mono ? "ui-monospace, monospace" : undefined,
                }}
                onClick={() => {
                    setDraft(value ?? "")
                    setEditing(true)
                }}
                title="点击修改"
            >
                {value ?? <span className="subtle">{emptyHint ?? "（空）"}</span>}
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
                const next = draft.trim() || null
                if (next !== (value ?? null)) onSave(next)
            }}
            onKeyDown={(e) => {
                if (e.key === "Enter") (e.target as HTMLInputElement).blur()
                if (e.key === "Escape") {
                    setDraft(value ?? "")
                    setEditing(false)
                }
            }}
        />
    )
}

export function FleetsPage() {
    const qc = useQueryClient()
    const [error, setError] = useState<string | null>(null)
    const [newFleetName, setNewFleetName] = useState("")
    const [newFleetCode, setNewFleetCode] = useState("")
    const [newVessel, setNewVessel] = useState<{ name: string; code: string; fleet_id: number | null } | null>(null)

    const data = useQuery({ queryKey: ["fleets"], queryFn: () => api.fleets.list() })

    const refresh = () => {
        void qc.invalidateQueries({ queryKey: ["fleets"] })
        void qc.invalidateQueries({ queryKey: ["fleet-overview"] })
        void qc.invalidateQueries({ queryKey: ["assets"] })
    }

    const createFleet = useMutation({
        mutationFn: () =>
            api.fleets.createFleet({
                name: newFleetName.trim(),
                code: newFleetCode.trim() || null,
            }),
        onSuccess: () => {
            setNewFleetName("")
            setNewFleetCode("")
            setError(null)
            refresh()
        },
        onError: (e: Error) => setError(e.message),
    })
    const createVessel = useMutation({
        mutationFn: () =>
            api.fleets.create({
                name: newVessel!.name.trim(),
                code: newVessel!.code.trim() || null,
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
        mutationFn: (args: { id: number; name?: string; code?: string | null }) =>
            api.fleets.patchFleet(args.id, { name: args.name, code: args.code }),
        onSuccess: refresh,
        onError: (e: Error) => setError(e.message),
    })
    const patchVessel = useMutation({
        mutationFn: (args: { id: number; name?: string; code?: string | null; fleet_id?: number }) =>
            api.fleets.patchVessel(args.id, {
                name: args.name,
                code: args.code,
                fleet_id: args.fleet_id,
            }),
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
            <EditableText
                value={v.name}
                onSave={(name) => v.id !== null && name && patchVessel.mutate({ id: v.id, name })}
            />
            <EditableText
                value={v.code}
                mono
                emptyHint="＋标签"
                placeholder="标签，如 OCEAN-3"
                onSave={(code) => v.id !== null && patchVessel.mutate({ id: v.id, code })}
            />
            {v.imo && <span className="subtle mono" style={{ fontSize: 11 }}>IMO {v.imo}</span>}
            {/* 改归属 —— 船必须属于某一支船队，但**可以换一支** */}
            {v.id !== null && (
                <select
                    className="input"
                    style={{ width: 130, height: 24, padding: "0 4px", fontSize: 12 }}
                    value={v.fleet_id ?? ""}
                    title="改归属船队"
                    onChange={(e) => {
                        const fid = Number(e.target.value)
                        if (fid) patchVessel.mutate({ id: v.id!, fleet_id: fid })
                    }}
                >
                    {fleets.map((f: Fleet) => (
                        <option key={f.id ?? "none"} value={f.id ?? ""}>
                            {f.name}
                        </option>
                    ))}
                </select>
            )}
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
                        value={newFleetName}
                        style={{ width: 150 }}
                        onChange={(e) => setNewFleetName(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === "Enter" && newFleetName.trim()) createFleet.mutate()
                        }}
                    />
                    <input
                        className="input"
                        placeholder="标签（可选）"
                        value={newFleetCode}
                        style={{ width: 130 }}
                        onChange={(e) => setNewFleetCode(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === "Enter" && newFleetName.trim()) createFleet.mutate()
                        }}
                    />
                    <button className="btn" disabled={!newFleetName.trim()} onClick={() => createFleet.mutate()}>
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
                    <span className="subtle" style={{ fontSize: 11 }}>点名字或「＋标签」都能改</span>
                </div>
                <div style={{ padding: 14 }}>
                    {fleets.length === 0 && <div className="subtle">还没有船队</div>}
                    {fleets.map((f: Fleet) => (
                        <div key={f.id ?? "none"} style={{ marginBottom: 10 }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 0" }}>
                                <EditableText
                                    value={f.name}
                                    onSave={(name) => f.id !== null && name && patchFleet.mutate({ id: f.id, name })}
                                />
                                <EditableText
                                    value={f.code}
                                    mono
                                    emptyHint="＋标签"
                                    placeholder="标签，如 FLEET-A"
                                    onSave={(code) => f.id !== null && patchFleet.mutate({ id: f.id, code })}
                                />
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
                                    onClick={() => setNewVessel({ name: "", code: "", fleet_id: f.id })}
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
                                    <input
                                        className="input"
                                        placeholder="标签（可选）"
                                        value={newVessel.code}
                                        style={{ width: 140 }}
                                        onChange={(e) => setNewVessel({ ...newVessel, code: e.target.value })}
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
        </div>
    )
}
