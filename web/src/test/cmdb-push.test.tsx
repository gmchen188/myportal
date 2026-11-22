/**
 * FortiSIEM CMDB 推送面板的测试。
 *
 * 覆盖的是**用户会踩到的地方**：
 *
 * 1. 没配写凭据时要**明确告诉用户** —— 否则他点了推送只看到一个 503，
 *    不知道是自己的配置问题还是 SIEM 的问题。
 * 2. 映射预览要显示字段对应关系 —— `zone → deviceTag` 这种不直观的映射
 *    不显示出来，用户没法确认自己填的 CBS 等级真的写进去了。
 * 3. 已推送过的资产要标出来 —— 否则用户会重复推，CMDB 里出现重复设备。
 * 4. 要说清「推送不会删 SIEM 里的设备」—— 这是用户最担心的点。
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { api, type Asset } from "@/api/client"
import { CmdbPushPanel } from "@/components/cmdb-push-panel"

vi.mock("@/api/client", async () => {
    const actual = await vi.importActual<typeof import("@/api/client")>("@/api/client")
    return {
        ...actual,
        api: {
            ...actual.api,
            assets: {
                ...actual.api.assets,
                cmdbStatus: vi.fn(),
                cmdbPreview: vi.fn(),
                cmdbPush: vi.fn(),
            },
        },
    }
})

function asset(over: Partial<Asset> = {}): Asset {
    return {
        id: 1,
        natural_id: "FW-01",
        name: "边缘防火墙",
        type: "防火墙",
        zone: "Zone 2",
        ip: "10.0.0.1",
        vendor: "Fortinet",
        model: "FortiGate 100F",
        serial: "FG100F001",
        owner: "张三",
        cbs_class: "SL2",
        status: "在用",
        source: "import",
        needs_review: false,
        notes: null,
        created_at: null,
        updated_at: null,
        siem_push_status: null,
        vessel_id: null,
        siem_pushed_at: null,
        siem_task_id: null,
        ...over,
    }
}

function setup() {
    const qc = new QueryClient({
        defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    const utils = render(
        <QueryClientProvider client={qc}>
            <CmdbPushPanel assets={[asset()]} onClose={() => {}} />
        </QueryClientProvider>,
    )
    return { ...utils, qc }
}

describe("CMDB 推送面板", () => {
    beforeEach(() => {
        vi.mocked(api.assets.cmdbStatus).mockResolvedValue({
            write_configured: true,
            org: "Super",
            base_url: "https://172.16.20.48",
            read_configured: true,
        })
        vi.mocked(api.assets.cmdbPreview).mockResolvedValue({
            items: [],
            mapped_count: 0,
            write_configured: true,
        })
        vi.mocked(api.assets.cmdbPush).mockResolvedValue({
            pushed: 1,
            skipped: [],
            task_id: "RESTAPI_1",
            message: "已提交 1 台设备到 FortiSIEM CMDB。",
        })
    })

    it("没配写凭据时要明确说明，不能让用户点了才知道", async () => {
        vi.mocked(api.assets.cmdbStatus).mockResolvedValue({
            write_configured: false,
            org: "Super",
            base_url: "https://172.16.20.48",
            read_configured: true,
        })
        setup()
        await waitFor(() => {
            expect(screen.getByText(/尚未配置 FortiSIEM 写凭据/)).toBeTruthy()
        })
        // 推送按钮应当禁用 —— 点了只会得到一个没有信息量的 503
        expect(screen.getByRole("button", { name: /推送/ })).toBeDisabled()
    })

    it("说清推送不会删 SIEM 里的设备", async () => {
        setup()
        await waitFor(() => {
            // **用函数式匹配器** —— 文案里有 <strong> 把它拆成多个文本节点，
            // 正则匹配器只看单个文本节点，找不到。
            expect(
                screen.getByText((_c, el) =>
                    el?.tagName === "LI" && /推送.*不会.*删除 SIEM 里的任何设备/.test(el.textContent ?? ""),
                ),
            ).toBeTruthy()
        })
    })

    it("说清只应推送已接入监控的设备", async () => {
        setup()
        await waitFor(() => {
            expect(
                screen.getByText((_c, el) =>
                    el?.tagName === "LI" && /已接入监控/.test(el.textContent ?? ""),
                ),
            ).toBeTruthy()
        })
    })

    it("未推送的资产标为「未推送」", async () => {
        setup()
        await waitFor(() => {
            expect(screen.getByText("未推送")).toBeTruthy()
        })
    })

    it("已推送的资产标为「已推送」并提示幂等", async () => {
        const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
        render(
            <QueryClientProvider client={qc}>
                <CmdbPushPanel assets={[asset({ siem_push_status: "ok" })]} onClose={() => {}} />
            </QueryClientProvider>,
        )
        await waitFor(() => {
            expect(screen.getByText("已推送")).toBeTruthy()
        })
        expect(screen.getByText(/已推送过的 1 件/)).toBeTruthy()
    })

    it("推送失败过的资产标为「推送失败」", async () => {
        const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
        render(
            <QueryClientProvider client={qc}>
                <CmdbPushPanel assets={[asset({ siem_push_status: "failed" })]} onClose={() => {}} />
            </QueryClientProvider>,
        )
        await waitFor(() => {
            expect(screen.getByText("推送失败")).toBeTruthy()
        })
    })

    it("映射预览要显示 zone 与 CBS 等级去了哪个 CMDB 字段", async () => {
        vi.mocked(api.assets.cmdbPreview).mockResolvedValue({
            items: [
                {
                    asset_id: 1,
                    name: "边缘防火墙",
                    natural_id: "FW-01",
                    fields: {
                        name: "边缘防火墙",
                        deviceTag: "Zone 2",
                        purdueLevel: "SL2",
                    },
                    skipped: ["natural_id", "type"],
                    missing: [],
                    monitored: true,
                },
            ],
            mapped_count: 1,
            write_configured: true,
        })

        const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
        render(
            <QueryClientProvider client={qc}>
                <CmdbPushPanel assets={[asset()]} onClose={() => {}} />
            </QueryClientProvider>,
        )

        // 空 ids 的调用是「取全部资产的监控状态」，不是映射预览
        expect(api.assets.cmdbPreview).toHaveBeenCalledWith([])
        expect(api.assets.cmdbPreview).not.toHaveBeenCalledWith([1])

        const checkbox = screen.getAllByRole("checkbox")[1] as HTMLInputElement
        fireEvent.click(checkbox)

        await waitFor(() => {
            expect(api.assets.cmdbPreview).toHaveBeenCalledWith([1])
        })

        await waitFor(() => {
            expect(screen.getByText(/映射预览/)).toBeTruthy()
        })
        // badge 里的文本是 `{label} = {value}` —— React 拆成多个文本节点，
        // 正则匹配器看不到全貌，得用函数式匹配器看 textContent。
        await waitFor(() => {
            expect(
                screen.getByText((_c, el) =>
                    Boolean(el) &&
                    String(el?.className ?? "").includes("bdg") &&
                    /设备标签（船舶安全区域）:\s*Zone 2/.test(el?.textContent ?? ""),
                ),
            ).toBeTruthy()
        })
        expect(
            screen.getByText((_c, el) =>
                Boolean(el) &&
                String(el?.className ?? "").includes("bdg") &&
                /Purdue Level（IEC 62443 分级）:\s*SL2/.test(el?.textContent ?? ""),
            ),
        ).toBeTruthy()
    })
})


describe("默认勾选范围", () => {
    beforeEach(() => {
        vi.mocked(api.assets.cmdbStatus).mockResolvedValue({
            write_configured: true,
            org: "Super",
            base_url: "https://172.16.20.48",
            read_configured: true,
        })
    })

    it("默认只勾选已接入监控的资产", async () => {
        // 实测数据形态：14 件资产里只有 7 件接了监控
        vi.mocked(api.assets.cmdbPreview).mockResolvedValue({
            items: [
                { asset_id: 1, name: "FW-EDGE-01", natural_id: "FW-EDGE-01", fields: {}, skipped: [], missing: [], monitored: true },
                { asset_id: 2, name: "REMOTE-GW", natural_id: "REMOTE-GW", fields: {}, skipped: [], missing: [], monitored: false },
                { asset_id: 3, name: "CBS-NAV-01", natural_id: "CBS-NAV-01", fields: {}, skipped: [], missing: [], monitored: true },
            ],
            mapped_count: 0,
            write_configured: true,
        } as never)

        const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
        render(
            <QueryClientProvider client={qc}>
                <CmdbPushPanel
                    assets={[
                        asset({ id: 1, name: "FW-EDGE-01" }),
                        asset({ id: 2, name: "REMOTE-GW" }),
                        asset({ id: 3, name: "CBS-NAV-01" }),
                    ]}
                    onClose={() => {}}
                />
            </QueryClientProvider>,
        )

        // 等默认勾选生效
        await waitFor(() => {
            expect(api.assets.cmdbPreview).toHaveBeenCalledWith([1, 3])
        })

        // 表格上要标出监控状态
        // 2 件已接入、1 件未接入
        await waitFor(() => {
            expect(screen.getAllByText("已接入")).toHaveLength(2)
        })
        expect(screen.getAllByText("未接入")).toHaveLength(1)
    })

    it("表头全选框也只选已接入监控的 —— 不是全部", async () => {
        vi.mocked(api.assets.cmdbPreview).mockResolvedValue({
            items: [
                { asset_id: 1, name: "FW-EDGE-01", natural_id: "FW-EDGE-01", fields: {}, skipped: [], missing: [], monitored: true },
                { asset_id: 2, name: "REMOTE-GW", natural_id: "REMOTE-GW", fields: {}, skipped: [], missing: [], monitored: false },
                { asset_id: 3, name: "CBS-NAV-01", natural_id: "CBS-NAV-01", fields: {}, skipped: [], missing: [], monitored: true },
            ],
            mapped_count: 0,
            write_configured: true,
        } as never)

        const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
        render(
            <QueryClientProvider client={qc}>
                <CmdbPushPanel
                    assets={[
                        asset({ id: 1, name: "FW-EDGE-01" }),
                        asset({ id: 2, name: "REMOTE-GW" }),
                        asset({ id: 3, name: "CBS-NAV-01" }),
                    ]}
                    onClose={() => {}}
                />
            </QueryClientProvider>,
        )

        await waitFor(() => {
            expect(api.assets.cmdbPreview).toHaveBeenCalledWith([1, 3])
        })

        // **先取消默认勾选**，再点全选框 —— 这样测的是全选框本身的行为
        const headerCheckbox = screen.getAllByRole("checkbox")[0] as HTMLInputElement
        fireEvent.click(headerCheckbox)   // 取消
        await waitFor(() => {
            expect(api.assets.cmdbPreview).toHaveBeenCalledWith([])
        })

        fireEvent.click(headerCheckbox)   // 全选
        await waitFor(() => {
            // **全选 = 只选已接入监控的 2 件**，不是全部 3 件
            expect(api.assets.cmdbPreview).toHaveBeenCalledWith([1, 3])
        })
        expect(api.assets.cmdbPreview).not.toHaveBeenCalledWith([1, 2, 3])
    })

    it("勾选里有未接入监控的资产时要警告", async () => {
        vi.mocked(api.assets.cmdbPreview).mockResolvedValue({
            items: [
                { asset_id: 1, name: "FW-EDGE-01", natural_id: "FW-EDGE-01", fields: {}, skipped: [], missing: [], monitored: true },
                { asset_id: 2, name: "REMOTE-GW", natural_id: "REMOTE-GW", fields: {}, skipped: [], missing: [], monitored: false },
            ],
            mapped_count: 0,
            write_configured: true,
        } as never)

        const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
        render(
            <QueryClientProvider client={qc}>
                <CmdbPushPanel
                    assets={[asset({ id: 1, name: "FW-EDGE-01" }), asset({ id: 2, name: "REMOTE-GW" })]}
                    onClose={() => {}}
                />
            </QueryClientProvider>,
        )

        await waitFor(() => {
            expect(api.assets.cmdbPreview).toHaveBeenCalledWith([1])
        })

        // **默认只勾了已接入的 → 不该有警告**
        await waitFor(() => {
            expect(screen.getAllByText("未推送")).toHaveLength(2)
        })
        expect(screen.queryByText(/勾选里有 1 件未接入监控的资产/)).toBeNull()

        // 手动勾上未接入的那个 → 必须警告
        const rowCheckbox = screen.getAllByRole("checkbox")[2] as HTMLInputElement
        fireEvent.click(rowCheckbox)

        await waitFor(() => {
            expect(screen.getByText(/勾选里有 1 件未接入监控的资产/)).toBeTruthy()
        })
        expect(screen.getAllByText(/REMOTE-GW/).length).toBeGreaterThan(0)
    })
})
