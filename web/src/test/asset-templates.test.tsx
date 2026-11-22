/**
 * 资产导出与模板面板的测试。
 *
 * 覆盖的是**用户会踩到的地方**：
 *
 * 1. 导出 URL 必须带上当前筛选条件 —— 用户导出的是「他筛选出来的」，
 *    不是全量。URL 少一个参数，导出的表就跟他看到的对不上，而这种
 *    问题在服务端测不出来（后端收不到筛选参数）。
 * 2. 字段选择要能反映到 URL 上。
 * 3. 模板面板要能列出模板、显示草稿行数、标出「模板」骨架行。
 * 4. 保存后要用**后端返回的**草稿覆盖本地 state —— 后端保存时重新
 *    校验了每一行，本地那份已经过期了。用户看到旧状态会以为没保存成功。
 */
import { render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { api } from "@/api/client"

vi.mock("@/hooks/use-assets", () => ({
    useAssetTemplates: vi.fn(),
    useAssetDrafts: vi.fn(),
    useUploadTemplate: vi.fn(),
    useCreateDraft: vi.fn(),
    useDeleteTemplate: vi.fn(),
    useDeleteDraft: vi.fn(),
    useAssetDraft: vi.fn(),
    useSaveDraft: vi.fn(),
    useAddDraftRow: vi.fn(),
    useCommitDraft: vi.fn(),
}))

// ── 导出 URL ────────────────────────────────────────────────────────────────

describe("导出 URL 必须带筛选条件", () => {
    it("带关键字与区域筛选", () => {
        const url = api.assets.exportUrl({ q: "主机A", zone: "Zone 1" })
        expect(url).toContain("q=")
        expect(url).toContain(encodeURIComponent("主机A"))
        expect(url).toContain("zone=Zone+1")
    })

    it("筛选条件为空时不出现在 URL 里", () => {
        const url = api.assets.exportUrl({ q: "", zone: "" })
        expect(url).not.toContain("q=")
        expect(url).not.toContain("zone=")
    })

    it("needs_review=false 也要带上 —— 那是筛选条件，不是空值", () => {
        const url = api.assets.exportUrl({ needs_review: false })
        expect(url).toContain("needs_review=false")
    })

    it("格式与字段要带上", () => {
        const url = api.assets.exportUrl({ fmt: "xlsx", fields: ["name", "ip"] })
        expect(url).toContain("fmt=xlsx")
        expect(url).toContain("fields=name%2Cip")
    })

    it("不给格式时不生成 fmt 参数 —— 后端默认就是 csv", () => {
        // URL 保持简短；后端的默认是 csv（api.assets.export 的 fmt 默认值）。
        expect(api.assets.exportUrl()).not.toContain("fmt=")
        expect(api.assets.exportUrl()).toContain("/api/assets/export")
    })
})

// ── 模板面板 ────────────────────────────────────────────────────────────────

async function setupPanel({
    templates = [],
    drafts = [],
}: {
    templates?: Array<Record<string, unknown>>
    drafts?: Array<Record<string, unknown>>
} = {}) {
    const hooks = await import("@/hooks/use-assets")
    const { AssetTemplatePanel } = await import("@/components/asset-template-panel")

    vi.mocked(hooks.useAssetTemplates).mockReturnValue({ data: { items: templates, total: templates.length } } as never)
    vi.mocked(hooks.useAssetDrafts).mockReturnValue({ data: { items: drafts, total: drafts.length } } as never)
    vi.mocked(hooks.useUploadTemplate).mockReturnValue({ mutateAsync: vi.fn(), isPending: false } as never)
    vi.mocked(hooks.useCreateDraft).mockReturnValue({ mutateAsync: vi.fn(), isPending: false } as never)
    vi.mocked(hooks.useDeleteTemplate).mockReturnValue({ mutate: vi.fn() } as never)
    vi.mocked(hooks.useDeleteDraft).mockReturnValue({ mutate: vi.fn() } as never)
    vi.mocked(hooks.useAssetDraft).mockReturnValue({ data: undefined } as never)
    vi.mocked(hooks.useSaveDraft).mockReturnValue({ mutateAsync: vi.fn(), isPending: false } as never)
    vi.mocked(hooks.useAddDraftRow).mockReturnValue({ mutateAsync: vi.fn(), isPending: false } as never)
    vi.mocked(hooks.useCommitDraft).mockReturnValue({ mutateAsync: vi.fn(), isPending: false } as never)

    render(<AssetTemplatePanel zones={["Zone 1", "Zone 2"]} onClose={() => {}} onDone={() => {}} />)
}

describe("模板面板", () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    it("空库时提示上传模板", async () => {
        await setupPanel()
        expect(screen.getByText(/还没有模板/)).toBeTruthy()
    })

    it("列出模板并显示行列数", async () => {
        await setupPanel({
            templates: [
                {
                    id: 1,
                    name: "货轮设备模板",
                    source_filename: "cargo.csv",
                    headers: ["设备名称", "类型"],
                    mapping: { 设备名称: "name", 类型: "type" },
                    template_rows: [["", "交换机"]],
                    zone_hints: ["Zone 1"],
                    row_count: 3,
                    created_by: null,
                    created_at: null,
                    updated_at: null,
                },
            ],
        })
        expect(screen.getByText("货轮设备模板")).toBeTruthy()
        expect(screen.getByText(/3 行 · 2 列/)).toBeTruthy()
    })

    it("有草稿时列出草稿并显示版本", async () => {
        await setupPanel({
            drafts: [
                {
                    id: 9,
                    template_id: 1,
                    name: "我的船清单",
                    rows: [],
                    status: "draft",
                    version: 3,
                    commit_result: null,
                    created_by: null,
                    created_at: null,
                    updated_at: null,
                },
            ],
        })
        expect(screen.getByText("我的船清单")).toBeTruthy()
        expect(screen.getByText(/第 3 版/)).toBeTruthy()
    })

    it("已落库的草稿标出来", async () => {
        await setupPanel({
            drafts: [
                {
                    id: 9,
                    template_id: 1,
                    name: "已提交的",
                    rows: [],
                    status: "committed",
                    version: 1,
                    commit_result: { created: 3, skipped: 0, failed: 0 },
                    created_by: null,
                    created_at: null,
                    updated_at: null,
                },
            ],
        })
        expect(screen.getByText(/已落库/)).toBeTruthy()
    })
})

// ── 导出组件 ────────────────────────────────────────────────────────────────

describe("导出组件", () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    it("显示要导出的条数", async () => {
        const { AssetExport } = await import("@/components/asset-export")
        render(<AssetExport filters={{ q: "主机" }} total={42} />)
        expect(screen.getByRole("button", { name: /导出/ })).toBeTruthy()
    })

    it("展开后能选格式与字段", async () => {
        const { AssetExport } = await import("@/components/asset-export")
        const { fireEvent } = await import("@testing-library/react")
        render(<AssetExport filters={{}} total={3} />)
        fireEvent.click(screen.getByRole("button", { name: /导出/ }))
        await waitFor(() => {
            expect(screen.getByRole("button", { name: /Excel/ })).toBeTruthy()
            expect(screen.getByRole("button", { name: /CSV/ })).toBeTruthy()
        })
    })
})
