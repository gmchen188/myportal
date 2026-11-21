/**
 * 资产清单。
 *
 * 三条输入路径：
 *   1. 文件导入（CSV / Excel）—— 上传 → 映射建议 → 校验 → 预览 → 落库
 *   2. 从拓扑图生成初步清单 —— 设备缺字段，标 needs_fill 等用户补
 *   3. 手工录入 —— 字段定义来自后端 schema，前端不另写一份
 *
 * 预览与落库分两步：用户能在入库前改映射、补字段、跳过重复行。
 */

import { useQuery } from "@tanstack/react-query"
import { FileUp, Plus, Search, Trash2, X } from "lucide-react"
import { useMemo, useRef, useState } from "react"

import { api, type ImportPreview, type ImportRow } from "@/api/client"
import { useAssetSchema, useAssets, useCommitImport, useCreateAsset, useDeleteAsset } from "@/hooks/use-assets"

type Mode = "list" | "import" | "manual"

export function AssetsPage() {
    const [mode, setMode] = useState<Mode>("list")
    const [q, setQ] = useState("")
    const [zone, setZone] = useState("")
    const [needsReview, setNeedsReview] = useState<boolean | undefined>(undefined)

    const assets = useAssets({ q, zone, needs_review: needsReview })
    const schema = useAssetSchema()
    const del = useDeleteAsset()

    return (
        <div>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14 }}>
                <div>
                    <h2 style={{ margin: 0, fontSize: 16 }}>资产清单</h2>
                    <p className="subtle" style={{ margin: "3px 0 0" }}>
                        共 {assets.data?.total ?? 0} 件
                    </p>
                </div>
                <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
                    <button type="button" className="btn" onClick={() => setMode("manual")}>
                        <Plus size={14} /> 手工录入
                    </button>
                    <button type="button" className="btn primary" onClick={() => setMode("import")}>
                        <FileUp size={14} /> 导入
                    </button>
                </div>
            </div>

            {mode === "import" && (
                <ImportPanel
                    onClose={() => setMode("list")}
                    onDone={() => {
                        setMode("list")
                    }}
                    zones={schema.data?.zones ?? []}
                />
            )}

            {mode === "manual" && (
                <ManualPanel
                    fields={schema.data?.fields ?? []}
                    zones={schema.data?.zones ?? []}
                    onClose={() => setMode("list")}
                />
            )}

            {mode === "list" && (
                <>
                    <div className="card" style={{ padding: 12, marginBottom: 12 }}>
                        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                            <div style={{ position: "relative", flex: "1 1 220px", maxWidth: 320 }}>
                                <Search
                                    size={14}
                                    style={{
                                        position: "absolute",
                                        left: 10,
                                        top: 10,
                                        color: "var(--fg-subtle)",
                                    }}
                                />
                                <input
                                    className="input"
                                    style={{ paddingLeft: 30 }}
                                    placeholder="搜索名称 / 编号 / IP / 序列号"
                                    value={q}
                                    onChange={(e) => setQ(e.target.value)}
                                />
                            </div>
                            <select
                                className="select"
                                style={{ width: 150 }}
                                value={zone}
                                onChange={(e) => setZone(e.target.value)}
                            >
                                <option value="">全部区域</option>
                                {(schema.data?.zones ?? []).map((z) => (
                                    <option key={z} value={z}>
                                        {z}
                                    </option>
                                ))}
                            </select>
                            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13 }}>
                                <input
                                    type="checkbox"
                                    checked={needsReview === true}
                                    onChange={(e) => setNeedsReview(e.target.checked ? true : undefined)}
                                />
                                只看待补充
                            </label>
                        </div>
                    </div>

                    <div className="card">
                        <div className="tbl-wrap">
                            <table>
                                <thead>
                                    <tr>
                                        <th>资产</th>
                                        <th>类型</th>
                                        <th>安全区域</th>
                                        <th>IP</th>
                                        <th>厂商 / 型号</th>
                                        <th>来源</th>
                                        <th>状态</th>
                                        <th />
                                    </tr>
                                </thead>
                                <tbody>
                                    {(assets.data?.items ?? []).map((a) => (
                                        <tr key={a.id}>
                                            <td className="strong mono">{a.name}</td>
                                            <td>{a.type}</td>
                                            <td className="mono muted">{a.zone ?? "—"}</td>
                                            <td className="mono muted">{a.ip ?? "—"}</td>
                                            <td className="muted">
                                                {a.vendor ?? "—"}
                                                {a.model ? ` ${a.model}` : ""}
                                            </td>
                                            <td>
                                                <span className="bdg neutral">{a.source}</span>
                                            </td>
                                            <td>
                                                {a.needs_review ? (
                                                    <span className="bdg warn">待补充</span>
                                                ) : (
                                                    <span className="bdg ok">{a.status ?? "在用"}</span>
                                                )}
                                            </td>
                                            <td style={{ width: 40 }}>
                                                <button
                                                    type="button"
                                                    className="btn"
                                                    style={{ height: 26, padding: "0 7px" }}
                                                    onClick={() => del.mutate(a.id)}
                                                    aria-label={`删除 ${a.name}`}
                                                >
                                                    <Trash2 size={13} />
                                                </button>
                                            </td>
                                        </tr>
                                    ))}
                                    {!assets.data?.items.length && (
                                        <tr>
                                            <td colSpan={8} style={{ textAlign: "center", padding: 28 }} className="muted">
                                                没有符合条件的资产
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

// ── 导入 ────────────────────────────────────────────────────────────────────
function ImportPanel({
    onClose,
    onDone,
    zones,
}: {
    onClose: () => void
    onDone: () => void
    zones: string[]
}) {
    const [tab, setTab] = useState<"file" | "topology">("file")
    const [preview, setPreview] = useState<ImportPreview | null>(null)
    const [rows, setRows] = useState<ImportRow[]>([])
    const [busy, setBusy] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const fileRef = useRef<HTMLInputElement>(null)

    const commit = useCommitImport()
    const topologies = useQuery({ queryKey: ["topologies"], queryFn: () => api.topologies.list() })
    const [topologyId, setTopologyId] = useState<number | null>(null)

    async function onFile(f: File) {
        setBusy(true)
        setError(null)
        try {
            const p = await api.assets.importFile(f)
            setPreview(p)
            setRows(p.rows)
        } catch (e) {
            setError(e instanceof Error ? e.message : String(e))
        } finally {
            setBusy(false)
        }
    }

    async function fromTopology() {
        if (topologyId === null) return
        setBusy(true)
        setError(null)
        try {
            const g = await api.topologies.graph(topologyId)
            const p = await api.assets.importFromTopology(
                g.nodes.map((n) => ({ label: n.label, zone: n.zone_key })),
            )
            setPreview(p)
            setRows(p.rows)
        } catch (e) {
            setError(e instanceof Error ? e.message : String(e))
        } finally {
            setBusy(false)
        }
    }

    function updateRow(i: number, values: Record<string, string>) {
        setRows((prev) => prev.map((r, idx) => (idx === i ? { ...r, values: { ...r.values, ...values } } : r)))
    }

    async function doCommit() {
        const res = await commit.mutateAsync({ rows, source: preview?.filename ? "import" : "topology_image" })
        alert(`导入完成：新增 ${res.created} 条，跳过 ${res.skipped} 条，失败 ${res.failed} 条`)
        onDone()
    }

    return (
        <div className="card" style={{ marginBottom: 14 }}>
            <div className="card-h">
                <h3>导入资产</h3>
                <div className="right">
                    <button type="button" className="btn" onClick={onClose} aria-label="关闭">
                        <X size={14} />
                    </button>
                </div>
            </div>

            <div style={{ padding: 16 }}>
                <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
                    <button
                        type="button"
                        className={tab === "file" ? "btn primary" : "btn"}
                        onClick={() => setTab("file")}
                    >
                        <FileUp size={14} /> 从文件导入
                    </button>
                    <button
                        type="button"
                        className={tab === "topology" ? "btn primary" : "btn"}
                        onClick={() => setTab("topology")}
                    >
                        从拓扑图生成
                    </button>
                </div>

                {tab === "file" && (
                    <>
                        <div
                            onClick={() => fileRef.current?.click()}
                            onDragOver={(e) => e.preventDefault()}
                            onDrop={(e) => {
                                e.preventDefault()
                                const f = e.dataTransfer.files[0]
                                if (f) void onFile(f)
                            }}
                            style={{
                                border: "2px dashed var(--border-strong)",
                                borderRadius: 12,
                                padding: 26,
                                textAlign: "center",
                                cursor: "pointer",
                                background: "var(--surface-2)",
                            }}
                        >
                            <div style={{ fontSize: 13.5, fontWeight: 700, marginBottom: 5 }}>
                                拖放文件到这里，或点击选择
                            </div>
                            <div className="subtle">支持 CSV / Excel（.xlsx / .xls）· 第一行视为表头</div>
                            <input
                                ref={fileRef}
                                type="file"
                                accept=".csv,.txt,.tsv,.xlsx,.xls"
                                style={{ display: "none" }}
                                onChange={(e) => {
                                    const f = e.target.files?.[0]
                                    if (f) void onFile(f)
                                }}
                            />
                        </div>
                        {busy && <p className="subtle" style={{ marginTop: 10 }}>解析中…</p>}
                    </>
                )}

                {tab === "topology" && (
                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                        <select
                            className="select"
                            style={{ maxWidth: 260 }}
                            value={topologyId ?? ""}
                            onChange={(e) => setTopologyId(Number(e.target.value))}
                        >
                            <option value="">选择拓扑图…</option>
                            {(topologies.data?.items ?? []).map((t) => (
                                <option key={t.id} value={t.id}>
                                    {t.name}
                                </option>
                            ))}
                        </select>
                        <button type="button" className="btn primary" disabled={!topologyId || busy} onClick={() => void fromTopology()}>
                            识别设备
                        </button>
                        <span className="subtle">
                            拓扑图给的是「有哪些设备」，类型和区域可能需要人工补
                        </span>
                    </div>
                )}

                {error && (
                    <div className="card" style={{ padding: 10, marginTop: 12, borderColor: "var(--color-sev-critical)" }}>
                        <span style={{ color: "var(--color-sev-critical)" }}>{error}</span>
                    </div>
                )}

                {preview && (
                    <>
                        <div style={{ marginTop: 16, marginBottom: 8, display: "flex", alignItems: "center", gap: 12 }}>
                            <b style={{ fontSize: 13 }}>
                                预览 {preview.stats.total} 行
                                {preview.filename ? ` · ${preview.filename}` : ""}
                            </b>
                            <span className="bdg ok">可导入 {preview.stats.ready}</span>
                            <span className="bdg warn">待补充 {preview.stats.needs_fill}</span>
                            <span className="bdg neutral">跳过 {preview.stats.skip}</span>
                        </div>

                        {preview.issues.length > 0 && (
                            <ul style={{ margin: "0 0 10px", paddingLeft: 18, fontSize: 12.5 }}>
                                {preview.issues.map((i, idx) => (
                                    <li key={idx} className={i.level === "err" ? "" : "muted"}>
                                        {i.message}
                                    </li>
                                ))}
                            </ul>
                        )}

                        <div className="tbl-wrap" style={{ maxHeight: 420, overflowY: "auto" }}>
                            <table>
                                <thead>
                                    <tr>
                                        <th style={{ width: 40 }}>行</th>
                                        <th>状态</th>
                                        <th>资产名称</th>
                                        <th>类型</th>
                                        <th>安全区域</th>
                                        <th>IP</th>
                                        <th>提示</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {rows.map((r, i) => (
                                        <tr key={i}>
                                            <td className="mono muted">{r.row_no}</td>
                                            <td>
                                                <span
                                                    className={
                                                        r.status === "ready"
                                                            ? "bdg ok"
                                                            : r.status === "skip"
                                                              ? "bdg neutral"
                                                              : "bdg warn"
                                                    }
                                                >
                                                    {r.status === "ready" ? "可导入" : r.status === "skip" ? "跳过" : "待补充"}
                                                </span>
                                            </td>
                                            <td>
                                                <input
                                                    className="input"
                                                    style={{ height: 28 }}
                                                    value={r.values.name ?? ""}
                                                    onChange={(e) => updateRow(i, { name: e.target.value })}
                                                />
                                            </td>
                                            <td>
                                                <input
                                                    className="input"
                                                    style={{ height: 28 }}
                                                    value={r.values.type ?? ""}
                                                    onChange={(e) => updateRow(i, { type: e.target.value })}
                                                />
                                            </td>
                                            <td>
                                                <select
                                                    className="select"
                                                    style={{ height: 28, width: 100 }}
                                                    value={r.values.zone ?? ""}
                                                    onChange={(e) => updateRow(i, { zone: e.target.value })}
                                                >
                                                    <option value="">—</option>
                                                    {zones.map((z) => (
                                                        <option key={z} value={z}>
                                                            {z}
                                                        </option>
                                                    ))}
                                                </select>
                                            </td>
                                            <td>
                                                <input
                                                    className="input"
                                                    style={{ height: 28 }}
                                                    value={r.values.ip ?? ""}
                                                    onChange={(e) => updateRow(i, { ip: e.target.value })}
                                                />
                                            </td>
                                            <td className="subtle">
                                                {r.issues.map((i, idx) => (
                                                    <div key={idx}>{i.message}</div>
                                                ))}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>

                        <div style={{ marginTop: 12, display: "flex", gap: 8, justifyContent: "flex-end" }}>
                            <button type="button" className="btn" onClick={onClose}>
                                取消
                            </button>
                            <button
                                type="button"
                                className="btn primary"
                                disabled={commit.isPending || rows.filter((r) => r.status !== "skip").length === 0}
                                onClick={() => void doCommit()}
                            >
                                {commit.isPending ? "导入中…" : "确认导入"}
                            </button>
                        </div>
                    </>
                )}
            </div>
        </div>
    )
}

// ── 手工录入 ────────────────────────────────────────────────────────────────
function ManualPanel({
    fields,
    zones,
    onClose,
}: {
    fields: Array<{ key: string; label: string; required: boolean }>
    zones: string[]
    onClose: () => void
}) {
    const create = useCreateAsset()
    const [values, setValues] = useState<Record<string, string>>({})
    const [error, setError] = useState<string | null>(null)

    const missing = useMemo(
        () => fields.filter((f) => f.required && !values[f.key]?.trim()).map((f) => f.label),
        [fields, values],
    )

    async function submit() {
        if (missing.length) {
            setError(`必填项未填：${missing.join("、")}`)
            return
        }
        try {
            await create.mutateAsync(values as never)
            onClose()
        } catch (e) {
            setError(e instanceof Error ? e.message : String(e))
        }
    }

    return (
        <div className="card" style={{ marginBottom: 14 }}>
            <div className="card-h">
                <h3>手工录入资产</h3>
                <div className="right">
                    <button type="button" className="btn" onClick={onClose} aria-label="关闭">
                        <X size={14} />
                    </button>
                </div>
            </div>
            <div style={{ padding: 16 }}>
                <div className="grid g-3">
                    {fields.map((f) => (
                        <div key={f.key}>
                            <label className={f.required ? "label req" : "label"}>{f.label}</label>
                            {f.key === "zone" ? (
                                <select
                                    className="select"
                                    value={values[f.key] ?? ""}
                                    onChange={(e) => setValues((p) => ({ ...p, [f.key]: e.target.value }))}
                                >
                                    <option value="">—</option>
                                    {zones.map((z) => (
                                        <option key={z} value={z}>
                                            {z}
                                        </option>
                                    ))}
                                </select>
                            ) : (
                                <input
                                    className="input"
                                    value={values[f.key] ?? ""}
                                    onChange={(e) => setValues((p) => ({ ...p, [f.key]: e.target.value }))}
                                />
                            )}
                        </div>
                    ))}
                </div>
                {error && (
                    <p style={{ color: "var(--color-sev-critical)", fontSize: 13, marginTop: 10 }}>{error}</p>
                )}
                <div style={{ marginTop: 14, display: "flex", gap: 8, justifyContent: "flex-end" }}>
                    <button type="button" className="btn" onClick={onClose}>
                        取消
                    </button>
                    <button type="button" className="btn primary" onClick={() => void submit()}>
                        保存
                    </button>
                </div>
            </div>
        </div>
    )
}
