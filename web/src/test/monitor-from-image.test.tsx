/**
 * 监控面板的「用架构图生成」。
 *
 * 监控面板是「拓扑图 + 设备绑定」的组合 —— 没有图就什么都没有。
 * 以前图只能手工画（跳去另一个应用），现在丢一张架构图进来就有。
 */
import { beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MemoryRouter } from "react-router-dom"

vi.mock("@/api/client", async () => {
    const actual = await vi.importActual<typeof import("@/api/client")>("@/api/client")
    return {
        ...actual,
        api: {
            ...actual.api,
            topologies: { ...actual.api.topologies, list: vi.fn(), fromImage: vi.fn() },
            monitor: { ...actual.api.monitor, panel: vi.fn() },
        },
    }
})

import { api } from "@/api/client"
import { MonitorPage } from "@/pages/monitor"

const TOPO = {
    id: 1, name: "船队网络拓扑 V1", description: null, node_bindings: {},
    origin: "manual", source_image: null, node_count: 14,
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
}

describe("监控面板 · 用架构图生成", () => {
    beforeEach(() => {
        vi.mocked(api.topologies.list).mockResolvedValue({ items: [TOPO] })
        vi.mocked(api.monitor.panel).mockResolvedValue({
            nodes: [], zones: [], links: [], counts: {}, severity_colors: {},
            total_incidents: 0, parse_error: null,
            topology: { ...TOPO },
        })
        vi.mocked(api.topologies.fromImage).mockResolvedValue({
            ...TOPO, id: 2, name: "架构图", origin: "image",
            bound_assets: 11, bind_error: null, ai_message: "画好了",
        })
    })

    function setup() {
        const qc = new QueryClient({
            defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
        })
        return render(
            <QueryClientProvider client={qc}>
                <MemoryRouter>
                    <MonitorPage />
                </MemoryRouter>
            </QueryClientProvider>,
        )
    }

    it("工具条上有「用架构图生成」按钮", async () => {
        setup()
        const btn = await screen.findByRole("button", { name: /用架构图生成/ }, { timeout: 15000 })
        expect(btn).toBeTruthy()
    })

    it("选了图就调接口，并把图片转成 base64 传过去", async () => {
        setup()
        await screen.findByRole("button", { name: /用架构图生成/ }, { timeout: 15000 })
        const input = document.querySelector(
            'input[type="file"][data-testid="monitor-import-image"]',
        ) as HTMLInputElement
        expect(input).toBeTruthy()

        const file = new File(["fake-png-bytes"], "我的架构图.png", { type: "image/png" })
        await fireEvent.change(input, { target: { files: [file] } })

        await waitFor(() => expect(api.topologies.fromImage).toHaveBeenCalled(), { timeout: 15000 })
        const arg = vi.mocked(api.topologies.fromImage).mock.calls[0]![0]
        expect(arg.name).toBe("我的架构图")
        expect(arg.mime).toBe("image/png")
        // base64 —— **不能带 data: 前缀**（后端要的是纯 base64）
        expect(arg.image_base64).not.toContain("data:")
        expect(arg.image_base64.length).toBeGreaterThan(0)
    })

    it("接口报错时把原因显示出来", async () => {
        vi.mocked(api.topologies.fromImage).mockRejectedValue(
            new Error("[502] 连不上画图服务 —— 启动 networktopology"),
        )
        setup()
        await screen.findByRole("button", { name: /用架构图生成/ }, { timeout: 15000 })
        const input = document.querySelector(
            'input[type="file"][data-testid="monitor-import-image"]',
        ) as HTMLInputElement
        const file = new File(["x"], "a.png", { type: "image/png" })
        await fireEvent.change(input, { target: { files: [file] } })

        await waitFor(
            () => expect(screen.getByRole("alert")).toBeTruthy(),
            { timeout: 15000 },
        )
        expect(screen.getByRole("alert").textContent).toContain("连不上画图服务")
    })
})
