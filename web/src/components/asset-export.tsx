/**
 * 资产清单导出。
 *
 * 为什么字段要勾选：资产有 14 个字段，但交付场景要的列不一样 ——
 * 船级社检验清单只要「名称/类型/区域/编号/CBS 等级」，给船东的台账要
 * 「名称/IP/型号/序列号/责任人」。一次导出全字段，交付方还得自己删列。
 *
 * 导出的是**当前筛选后的**那一批 —— 与列表看到的完全一致（后端共用
 * 同一个筛选函数）。
 */
import { Download, FileSpreadsheet, FileText } from "lucide-react"
import { useState } from "react"

import { api } from "@/api/client"

/** 可选字段 —— 与后端 EXPORT_FIELDS 对应。 */
const FIELDS: Array<{ key: string; label: string; def?: boolean }> = [
    { key: "natural_id", label: "资产编号" },
    { key: "name", label: "资产名称", def: true },
    { key: "type", label: "类型", def: true },
    { key: "zone", label: "安全区域", def: true },
    // 船队与船 —— 清单按船分组看，导出也得能分出是哪艘船的设备
    { key: "vessel_name", label: "所属船舶", def: true },
    { key: "fleet_name", label: "所属船队" },
    { key: "ip", label: "IP 地址", def: true },
    { key: "vendor", label: "厂商" },
    { key: "model", label: "型号" },
    { key: "serial", label: "序列号" },
    { key: "owner", label: "责任人" },
    { key: "cbs_class", label: "CBS 等级" },
    { key: "status", label: "状态" },
    { key: "notes", label: "备注" },
    { key: "source", label: "来源" },
    { key: "created_at", label: "创建时间" },
]

const DEFAULT_KEYS = FIELDS.filter((f) => f.def).map((f) => f.key)

interface Props {
    /** 当前筛选条件 —— 导出的是筛选后的那一批 */
    filters: { q?: string; zone?: string; needs_review?: boolean; vessel_id?: number; fleet_id?: number }
    /** 当前总条数 —— 让用户知道会导出多少条 */
    total: number
}

export function AssetExport({ filters, total }: Props) {
    const [open, setOpen] = useState(false)
    const [fmt, setFmt] = useState<"csv" | "xlsx">("xlsx")
    const [keys, setKeys] = useState<string[]>(DEFAULT_KEYS)
    const [picking, setPicking] = useState(false)

    function toggle(key: string) {
        setKeys((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]))
    }

    function doExport() {
        // 用隐藏的 a 标签触发下载 —— 不用 window.open（会被拦截），
        // 也不用 fetch+blob（要自己处理文件名与错误）。
        const url = api.assets.exportUrl({ ...filters, fmt, fields: keys })
        const a = document.createElement("a")
        a.href = url
        a.download = ""
        document.body.appendChild(a)
        a.click()
        a.remove()
        setOpen(false)
        setPicking(false)
    }

    return (
        <div style={{ position: "relative" }}>
            <button type="button" className="btn" onClick={() => setOpen((v) => !v)}>
                <Download size={14} /> 导出
            </button>

            {open && (
                <div
                    className="card"
                    style={{
                        // **窄屏必须固定定位，不能跟着按钮走。**
                        //
                        // 用 absolute + right:0 时，面板的位置取决于按钮的
                        // 父容器在哪 —— 而窄屏下工具栏会 flex 换行，按钮被推到
                        // 左侧，面板也跟着跑到屏幕左边并被裁掉一半
                        // （实测 375px 下「Excel」按钮整个看不见）。
                        //
                        // 固定定位 + left/right 贴边 = 面板永远在视口内，
                        // 与按钮在哪个位置无关。
                        position: "fixed",
                        left: 12,
                        right: 12,
                        top: 120,
                        zIndex: 100,
                        width: "auto",
                        maxWidth: 380,
                        marginLeft: "auto",
                        marginRight: "auto",
                        padding: 14,
                        boxShadow: "0 8px 28px rgba(15,23,42,.18)",
                    }}
                >
                    <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 8 }}>
                        导出 {total} 件资产
                    </div>

                    <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
                        <button
                            type="button"
                            className={fmt === "xlsx" ? "btn primary" : "btn"}
                            style={{ flex: 1 }}
                            onClick={() => setFmt("xlsx")}
                        >
                            <FileSpreadsheet size={13} /> Excel
                        </button>
                        <button
                            type="button"
                            className={fmt === "csv" ? "btn primary" : "btn"}
                            style={{ flex: 1 }}
                            onClick={() => setFmt("csv")}
                        >
                            <FileText size={13} /> CSV
                        </button>
                    </div>

                    <div style={{ marginBottom: 10 }}>
                        <button
                            type="button"
                            className="btn"
                            style={{ width: "100%" }}
                            onClick={() => setPicking((v) => !v)}
                        >
                            {picking ? "收起字段" : `选择字段（已选 ${keys.length}）`}
                        </button>

                        {picking && (
                            <div
                                style={{
                                    marginTop: 8,
                                    maxHeight: 220,
                                    overflowY: "auto",
                                    border: "1px solid var(--border)",
                                    borderRadius: 8,
                                    padding: 8,
                                }}
                            >
                                {FIELDS.map((f) => (
                                    <label
                                        key={f.key}
                                        style={{
                                            display: "flex",
                                            alignItems: "center",
                                            gap: 6,
                                            fontSize: 12.5,
                                            padding: "2px 0",
                                        }}
                                    >
                                        <input
                                            type="checkbox"
                                            checked={keys.includes(f.key)}
                                            onChange={() => toggle(f.key)}
                                        />
                                        {f.label}
                                    </label>
                                ))}
                            </div>
                        )}
                    </div>

                    <div className="subtle" style={{ marginBottom: 10, fontSize: 12 }}>
                        {fmt === "csv" ? "CSV 带 UTF-8 BOM，Excel 打开中文不乱码。" : "Excel 已加表头样式、冻结首行与自动筛选。"}
                    </div>

                    <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
                        <button type="button" className="btn" onClick={() => setOpen(false)}>
                            取消
                        </button>
                        <button
                            type="button"
                            className="btn primary"
                            disabled={keys.length === 0}
                            onClick={doExport}
                        >
                            导出 {fmt.toUpperCase()}
                        </button>
                    </div>
                </div>
            )}
        </div>
    )
}
