/**
 * 资产模板与草稿清单。
 *
 * ## 为什么要三段式
 *
 *    上传模板  →  生成草稿清单  →  填完落库
 *                   ↑
 *            可反复编辑、可保存、明天接着填
 *
 * 模板往往是**分类骨架**（某船的设备清单模板：主交换机、雷达、传感器各
 * 若干行，名称待填），不是可入库的数据。直接上传→落库没有中间态：
 * 用户填到一半关掉页面就前功尽弃，模板里的空骨架行还会被当成
 * 「缺必填字段」的错误。
 *
 * ## 骨架行不能丢
 *
 * 草稿里名称为空但有类型/区域的行，就是模板带来的骨架 —— 它是模板的
 * **价值所在**（照着填自己船的设备）。表格里用「模板」标记高亮。
 */
import {
    CheckCircle2,
    CircleAlert,
    FileSpreadsheet,
    Loader2,
    Plus,
    Save,
    Trash2,
    Upload,
    X,
} from "lucide-react"
import { useEffect, useRef, useState } from "react"

import type { AssetDraft, AssetTemplate, DraftRow } from "@/api/client"
import {
    useAddDraftRow,
    useAssetDraft,
    useAssetDrafts,
    useAssetTemplates,
    useCommitDraft,
    useCreateDraft,
    useDeleteDraft,
    useDeleteTemplate,
    useSaveDraft,
    useUploadTemplate,
} from "@/hooks/use-assets"

/** 草稿表格里可编辑的列 —— 与后端 ASSET_FIELDS 的 key 对应。 */
const COLUMNS: Array<{ key: string; label: string; width?: number; kind?: "text" | "zone" }> = [
    { key: "natural_id", label: "资产编号", width: 110 },
    { key: "name", label: "资产名称", width: 160 },
    { key: "type", label: "类型", width: 110 },
    { key: "zone", label: "安全区域", width: 100, kind: "zone" },
    { key: "ip", label: "IP", width: 120 },
    { key: "vendor", label: "厂商", width: 90 },
    { key: "model", label: "型号", width: 100 },
    { key: "serial", label: "序列号", width: 110 },
    { key: "owner", label: "责任人", width: 90 },
    { key: "cbs_class", label: "CBS", width: 70 },
]

interface Props {
    zones: string[]
    onClose: () => void
    onDone: () => void
}

export function AssetTemplatePanel({ zones, onClose, onDone }: Props) {
    const templates = useAssetTemplates()
    const drafts = useAssetDrafts()
    const upload = useUploadTemplate()
    const createDraft = useCreateDraft()

    const [activeDraftId, setActiveDraftId] = useState<number | null>(null)
    const fileRef = useRef<HTMLInputElement>(null)
    const [error, setError] = useState<string | null>(null)
    const [busy, setBusy] = useState(false)

    async function onFile(f: File) {
        setBusy(true)
        setError(null)
        try {
            await upload.mutateAsync({ file: f, name: f.name })
        } catch (e) {
            setError(e instanceof Error ? e.message : String(e))
        } finally {
            setBusy(false)
        }
    }

    async function makeDraft(tpl: AssetTemplate) {
        setBusy(true)
        setError(null)
        try {
            const res = await createDraft.mutateAsync({ template_id: tpl.id })
            setActiveDraftId(res.draft.id)
        } catch (e) {
            setError(e instanceof Error ? e.message : String(e))
        } finally {
            setBusy(false)
        }
    }

    return (
        <div className="card" style={{ marginBottom: 14 }}>
            <div className="card-h">
                <h3>模板与清单</h3>
                <div className="right">
                    <button type="button" className="btn" onClick={onClose} aria-label="关闭">
                        <X size={14} />
                    </button>
                </div>
            </div>

            <div style={{ padding: 16 }}>
                {error && (
                    <div className="card" style={{ padding: 10, marginBottom: 12, borderColor: "var(--color-sev-critical)" }}>
                        <span style={{ color: "var(--color-sev-critical)" }}>{error}</span>
                    </div>
                )}

                {activeDraftId !== null ? (
                    <DraftEditor
                        draftId={activeDraftId}
                        zones={zones}
                        onBack={() => setActiveDraftId(null)}
                        onDone={() => {
                            setActiveDraftId(null)
                            onDone()
                        }}
                    />
                ) : (
                    <>
                        {/* ── 草稿列表 ── */}
                        {(drafts.data?.items ?? []).length > 0 && (
                            <div style={{ marginBottom: 18 }}>
                                <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 8 }}>
                                    我的清单草稿
                                </div>
                                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                                    {(drafts.data?.items ?? []).map((d) => (
                                        <DraftRowItem key={d.id} draft={d} onOpen={() => setActiveDraftId(d.id)} />
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* ── 上传模板 ── */}
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
                                padding: 22,
                                textAlign: "center",
                                cursor: "pointer",
                                background: "var(--surface-2)",
                                marginBottom: 16,
                            }}
                        >
                            <div style={{ fontSize: 13.5, fontWeight: 700, marginBottom: 5 }}>
                                上传资产模板文件
                            </div>
                            <div className="subtle">
                                支持 CSV / Excel（.xlsx / .xls）· 第一行视为表头 ·
                                模板里的分类骨架会变成待填的行
                            </div>
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
                        {busy && (
                            <p className="subtle" style={{ marginTop: -8, marginBottom: 12 }}>
                                <Loader2 size={12} style={{ verticalAlign: -2 }} /> 处理中…
                            </p>
                        )}

                        {/* ── 模板库 ── */}
                        <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 8 }}>
                            模板库
                        </div>
                        {(templates.data?.items ?? []).length === 0 ? (
                            <p className="subtle" style={{ margin: 0 }}>
                                还没有模板。上传一个 Excel/CSV 模板开始。
                            </p>
                        ) : (
                            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                                {(templates.data?.items ?? []).map((t) => (
                                    <TemplateItem
                                        key={t.id}
                                        template={t}
                                        onUse={() => void makeDraft(t)}
                                    />
                                ))}
                            </div>
                        )}
                    </>
                )}
            </div>
        </div>
    )
}

/* ── 模板条目 ─────────────────────────────────────────────────────────────── */

function TemplateItem({ template, onUse }: { template: AssetTemplate; onUse: () => void }) {
    const del = useDeleteTemplate()
    const [open, setOpen] = useState(false)

    return (
        <div className="card" style={{ padding: 10 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <FileSpreadsheet size={16} style={{ color: "var(--fg-subtle)" }} />
                <div style={{ minWidth: 0, flex: 1 }}>
                    <div className="strong" style={{ fontSize: 13 }}>
                        {template.name}
                    </div>
                    <div className="subtle" style={{ fontSize: 12 }}>
                        {template.row_count} 行 · {template.headers.length} 列
                        {template.source_filename ? ` · ${template.source_filename}` : ""}
                    </div>
                </div>
                <button type="button" className="btn" onClick={() => setOpen((v) => !v)}>
                    {open ? "收起" : "预览"}
                </button>
                <button type="button" className="btn primary" onClick={onUse}>
                    <Plus size={13} /> 创建清单
                </button>
                <button
                    type="button"
                    className="btn"
                    style={{ height: 26, padding: "0 7px" }}
                    onClick={() => del.mutate(template.id)}
                    aria-label={`删除模板 ${template.name}`}
                >
                    <Trash2 size={13} />
                </button>
            </div>

            {open && (
                <div style={{ marginTop: 10 }}>
                    <div className="subtle" style={{ fontSize: 12, marginBottom: 4 }}>
                        列映射
                    </div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
                        {template.headers.map((h) => (
                            <span key={h} className="bdg neutral" style={{ fontSize: 11.5 }}>
                                {h}
                                {template.mapping[h] ? ` → ${template.mapping[h]}` : " → 忽略"}
                            </span>
                        ))}
                    </div>
                    {template.template_rows.length > 0 && (
                        <>
                            <div className="subtle" style={{ fontSize: 12, marginBottom: 4 }}>
                                前几行（骨架）
                            </div>
                            <div className="tbl-wrap" style={{ maxHeight: 180, overflowY: "auto" }}>
                                <table>
                                    <thead>
                                        <tr>
                                            {template.headers.map((h) => (
                                                <th key={h}>{h}</th>
                                            ))}
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {template.template_rows.slice(0, 8).map((r, i) => (
                                            <tr key={i}>
                                                {r.map((c, j) => (
                                                    <td key={j} className="muted">
                                                        {c || "—"}
                                                    </td>
                                                ))}
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </>
                    )}
                </div>
            )}
        </div>
    )
}

/* ── 草稿条目 ─────────────────────────────────────────────────────────────── */

function DraftRowItem({ draft, onOpen }: { draft: AssetDraft; onOpen: () => void }) {
    const del = useDeleteDraft()
    const total = draft.rows.length
    const ready = draft.rows.filter((r) => r.status === "ready").length

    return (
        <div className="card" style={{ padding: 10 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <div style={{ minWidth: 0, flex: 1 }}>
                    <div className="strong" style={{ fontSize: 13 }}>
                        {draft.name}
                    </div>
                    <div className="subtle" style={{ fontSize: 12 }}>
                        {total} 行 · 可落库 {ready} · 第 {draft.version} 版
                        {draft.status === "committed" ? " · 已落库" : ""}
                    </div>
                </div>
                <button type="button" className="btn primary" onClick={onOpen}>
                    打开
                </button>
                <button
                    type="button"
                    className="btn"
                    style={{ height: 26, padding: "0 7px" }}
                    onClick={() => del.mutate(draft.id)}
                    aria-label={`删除清单 ${draft.name}`}
                >
                    <Trash2 size={13} />
                </button>
            </div>
        </div>
    )
}

/* ── 草稿编辑器 ───────────────────────────────────────────────────────────── */

function DraftEditor({
    draftId,
    zones,
    onBack,
    onDone,
}: {
    draftId: number
    zones: string[]
    onBack: () => void
    onDone: () => void
}) {
    const save = useSaveDraft()
    const addRow = useAddDraftRow()
    const commit = useCommitDraft()

    const [rows, setRows] = useState<DraftRow[] | null>(null)
    const [name, setName] = useState("")
    const [error, setError] = useState<string | null>(null)
    const [loaded, setLoaded] = useState(false)

    // 直接拉这个草稿 —— 不从列表里找（列表可能还没刷新）
    const draft = useAssetDraft(draftId)
    const found = draft.data

    // 用 effect 而不是渲染期 setState —— 渲染期改 state 会触发 React
    // 的「渲染期间更新」警告，并多跑一轮渲染。
    useEffect(() => {
        if (!loaded && found) {
            setRows(found.rows)
            setName(found.name)
            setLoaded(true)
        }
    }, [loaded, found])

    if (!loaded) {
        return (
            <p className="subtle" style={{ margin: 0 }}>
                <Loader2 size={12} style={{ verticalAlign: -2 }} /> 载入中…
            </p>
        )
    }

    function update(i: number, key: string, value: string) {
        setRows((prev) =>
            (prev ?? []).map((r, idx) =>
                idx === i ? { ...r, values: { ...r.values, [key]: value } } : r,
            ),
        )
    }

    async function doSave() {
        setError(null)
        try {
            const res = await save.mutateAsync({ id: draftId, rows: rows ?? [], name })
            // **用后端返回的草稿覆盖本地 state** —— 后端保存时重新校验了
            // 每一行（「可落库/待填」标记会变、可能被丢弃的行会消失），
            // 本地那份已经过期了。
            //
            // 不同步的话：用户保存后界面还显示旧状态，看起来像没保存成功。
            setRows(res.draft.rows)
            setName(res.draft.name)
        } catch (e) {
            setError(e instanceof Error ? e.message : String(e))
        }
    }

    async function doAddRow() {
        setError(null)
        try {
            const res = await addRow.mutateAsync(draftId)
            setRows(res.draft.rows)
        } catch (e) {
            setError(e instanceof Error ? e.message : String(e))
        }
    }

    async function doCommit() {
        setError(null)
        try {
            // 先保存再落库 —— 否则用户改完没保存，落库的是旧内容
            await save.mutateAsync({ id: draftId, rows: rows ?? [], name })
            const res = await commit.mutateAsync(draftId)
            setRows(res.draft.rows)
            alert(
                `落库完成：新增 ${res.result.created} 条，跳过 ${res.result.skipped} 条，失败 ${res.result.failed} 条`,
            )
            onDone()
        } catch (e) {
            setError(e instanceof Error ? e.message : String(e))
        }
    }

    const list = rows ?? []
    const readyCount = list.filter((r) => r.status === "ready").length
    const needsFill = list.filter((r) => r.status === "needs_fill").length

    return (
        <>
            {error && (
                <div className="card" style={{ padding: 10, marginBottom: 12, borderColor: "var(--color-sev-critical)" }}>
                    <span style={{ color: "var(--color-sev-critical)" }}>{error}</span>
                </div>
            )}

            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10, flexWrap: "wrap" }}>
                <button type="button" className="btn" style={{ whiteSpace: "nowrap", flexShrink: 0 }} onClick={onBack}>
                    ← 返回
                </button>
                <input
                    className="input"
                    style={{ maxWidth: 280 }}
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    aria-label="清单名称"
                />
                <span className="bdg ok" style={{ whiteSpace: "nowrap" }}>
                    {readyCount} 可落库
                </span>
                <span className="bdg warn" style={{ whiteSpace: "nowrap" }}>
                    {needsFill} 待补充
                </span>
                {found && (
                    <span className="bdg neutral" style={{ whiteSpace: "nowrap" }} title="每次保存版本 +1">
                        第 {found.version} 版
                    </span>
                )}
                <div
                    style={{
                        marginLeft: "auto",
                        display: "flex",
                        gap: 8,
                        flexWrap: "wrap",
                        justifyContent: "flex-end",
                    }}
                >
                    {/* 按钮文字不许被压扁 ——
                        flex 子项默认可收缩到内容宽度以下，窄屏下
                        「加一行」会竖成「加/一/行」、「保存」竖成「保/存」。 */}
                    <button
                        type="button"
                        className="btn"
                        style={{ whiteSpace: "nowrap", flexShrink: 0 }}
                        onClick={() => void doAddRow()}
                        disabled={addRow.isPending}
                    >
                        <Plus size={13} /> 加一行
                    </button>
                    <button
                        type="button"
                        className="btn"
                        style={{ whiteSpace: "nowrap", flexShrink: 0 }}
                        onClick={() => void doSave()}
                        disabled={save.isPending}
                    >
                        <Save size={13} /> {save.isPending ? "保存中…" : "保存"}
                    </button>
                    <button
                        type="button"
                        className="btn primary"
                        style={{ whiteSpace: "nowrap", flexShrink: 0 }}
                        onClick={() => void doCommit()}
                        disabled={commit.isPending}
                    >
                        <Upload size={13} /> {commit.isPending ? "落库中…" : "落库到资产清单"}
                    </button>
                </div>
            </div>

            <div className="subtle" style={{ marginBottom: 8, fontSize: 12.5 }}>
                标「模板」的行是从模板带来的骨架 —— 填上名称就能落库。改完记得先「保存」。
            </div>

            <div className="tbl-wrap" style={{ maxHeight: 460, overflowY: "auto" }}>
                <table>
                    <thead>
                        <tr>
                            <th style={{ width: 40 }}>行</th>
                            <th style={{ width: 70 }}>状态</th>
                            {COLUMNS.map((c) => (
                                <th key={c.key} style={{ width: c.width }}>
                                    {c.label}
                                </th>
                            ))}
                            <th style={{ whiteSpace: "nowrap" }}>提示</th>
                        </tr>
                    </thead>
                    <tbody>
                        {list.map((r, i) => (
                            <tr key={i}>
                                <td className="mono muted">{r.row_no}</td>
                                <td style={{ whiteSpace: "nowrap" }}>
                                    {r.status === "ready" ? (
                                        <span className="bdg ok" title="可直接落库">
                                            <CheckCircle2 size={11} style={{ verticalAlign: -1 }} /> 可落库
                                        </span>
                                    ) : (
                                        <span className="bdg warn" title="还缺必填字段">
                                            <CircleAlert size={11} style={{ verticalAlign: -1 }} /> 待填
                                        </span>
                                    )}
                                    {r.from_template && (
                                        <span className="bdg neutral" style={{ marginLeft: 4 }} title="来自模板的骨架行">
                                            模板
                                        </span>
                                    )}
                                </td>
                                {COLUMNS.map((c) => (
                                    <td key={c.key}>
                                        {c.kind === "zone" ? (
                                            <select
                                                className="select"
                                                style={{ height: 26, width: c.width }}
                                                value={r.values[c.key] ?? ""}
                                                onChange={(e) => update(i, c.key, e.target.value)}
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
                                                style={{ height: 26 }}
                                                value={r.values[c.key] ?? ""}
                                                onChange={(e) => update(i, c.key, e.target.value)}
                                            />
                                        )}
                                    </td>
                                ))}
                                <td
                                    className="subtle"
                                    style={{
                                        // **不能逐字折行** —— 中文竖排成一列完全读不了。
                                        // 给最小宽度让它横向展开，表格自己横向滚动。
                                        minWidth: 180,
                                        whiteSpace: "nowrap",
                                    }}
                                >
                                    {r.issues.map((iss, idx) => (
                                        <div key={idx} style={iss.level === "err" ? { color: "var(--color-sev-critical)" } : undefined}>
                                            {iss.message}
                                        </div>
                                    ))}
                                </td>
                            </tr>
                        ))}
                        {!list.length && (
                            <tr>
                                <td colSpan={COLUMNS.length + 3} style={{ textAlign: "center", padding: 24 }} className="muted">
                                    这个清单还没有行 —— 点「加一行」开始填
                                </td>
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>
        </>
    )
}
