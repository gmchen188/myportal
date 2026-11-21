import { useQuery } from "@tanstack/react-query"
import { ExternalLink, Network, Trash2 } from "lucide-react"

import { api } from "@/api/client"
import { useDeleteTopology } from "@/hooks/use-topologies"

/**
 * 网络拓扑列表。
 *
 * 三条画图路径（导入图片 / 自然语言语音 / 空白画布手工绘制）都在
 * networktopology 那个应用里 —— 它是 draw.io + VLM 的完整实现。
 * 这里只列出已保存的拓扑，并提供入口。
 */
export function TopologiesPage() {
    const topologies = useQuery({ queryKey: ["topologies"], queryFn: () => api.topologies.list() })
    const del = useDeleteTopology()

    const ntBase = import.meta.env.VITE_NT_BASE ?? "/networktopology/zh"

    return (
        <div>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14 }}>
                <div>
                    <h2 style={{ margin: 0, fontSize: 16 }}>网络拓扑</h2>
                    <p className="subtle" style={{ margin: "3px 0 0" }}>
                        共 {topologies.data?.items.length ?? 0} 张
                    </p>
                </div>
                <div style={{ marginLeft: "auto" }}>
                    <a
                        className="btn primary"
                        href={ntBase}
                        target="_blank"
                        rel="noreferrer"
                    >
                        <ExternalLink size={14} /> 打开画布
                    </a>
                </div>
            </div>

            <div className="card" style={{ marginBottom: 14, padding: 14 }}>
                <b style={{ fontSize: 13 }}>三条画图路径</b>
                <div className="grid g-3" style={{ marginTop: 10 }}>
                    <div>
                        <div style={{ fontSize: 12.5, fontWeight: 700 }}>导入图片</div>
                        <div className="subtle" style={{ marginTop: 3 }}>
                            导入一张网络拓扑截图，AI 识别成可编辑的 draw.io 图
                        </div>
                    </div>
                    <div>
                        <div style={{ fontSize: 12.5, fontWeight: 700 }}>自然语言 / 语音</div>
                        <div className="subtle" style={{ marginTop: 3 }}>
                            用文字或语音描述，调用资产清单里的资产生成拓扑
                        </div>
                    </div>
                    <div>
                        <div style={{ fontSize: 12.5, fontWeight: 700 }}>空白画布</div>
                        <div className="subtle" style={{ marginTop: 3 }}>
                            从空白画布手工绘制，draw.io 全功能
                        </div>
                    </div>
                </div>
                <p className="subtle" style={{ marginTop: 10, marginBottom: 0 }}>
                    三条路径都在画布应用里完成 —— 它有 draw.io 编辑器与 VLM 能力。
                    保存后回到这里，监控面板就能用这张图生成。
                </p>
            </div>

            <div className="card">
                <div className="tbl-wrap">
                    <table>
                        <thead>
                            <tr><th>名称</th><th>节点</th><th>来源</th><th>更新时间</th><th /></tr>
                        </thead>
                        <tbody>
                            {(topologies.data?.items ?? []).map((t) => (
                                <tr key={t.id}>
                                    <td className="strong">
                                        <Network size={13} style={{ verticalAlign: "-2px", marginRight: 6 }} />
                                        {t.name}
                                    </td>
                                    <td className="mono muted">{t.node_count}</td>
                                    <td><span className="bdg neutral">{t.origin}</span></td>
                                    <td className="mono muted">{t.updated_at?.slice(0, 16).replace("T", " ") ?? "—"}</td>
                                    <td style={{ width: 40 }}>
                                        <button
                                            type="button"
                                            className="btn"
                                            style={{ height: 26, padding: "0 7px" }}
                                            onClick={() => del.mutate(t.id)}
                                            aria-label={`删除 ${t.name}`}
                                        >
                                            <Trash2 size={13} />
                                        </button>
                                    </td>
                                </tr>
                            ))}
                            {!topologies.data?.items.length && (
                                <tr><td colSpan={5} className="muted" style={{ textAlign: "center", padding: 26 }}>
                                    还没有保存的拓扑图
                                </td></tr>
                            )}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    )
}
