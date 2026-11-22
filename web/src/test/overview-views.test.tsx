/**
 * 总览的船队视图 ↔ 单船视图。
 *
 * - **点船队名** → 回船队视图（看所有船队）
 * - **点单船** → 进单船视图，顶部有**所有船舶的下拉**
 * - **下拉选另一艘** → 界面跟着换成那艘船
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
            fleets: { ...actual.api.fleets, overview: vi.fn(), vesselOverview: vi.fn() },
            assets: { ...actual.api.assets, list: vi.fn() },
            topologies: { ...actual.api.topologies, list: vi.fn() },
            monitor: { ...actual.api.monitor, events: vi.fn() },
            health: vi.fn(),
        },
    }
})

import { api } from "@/api/client"
import { OverviewPage } from "@/pages/overview"

const FLEET = {
    id: 1, name: "东海船队", code: "DF", description: null,
    vessel_count: 2, asset_count: 3, monitor_count: 2, event_count: 4,
    events_by_severity: { critical: 1, high: 1, medium: 1, low: 1 },
    topology_count: 1,
    vessels: [
        { id: 11, fleet_id: 1, name: "海洋一号", code: "HY1", imo: null, description: null,
          asset_count: 2, monitor_count: 1, event_count: 3, events_by_severity: {} },
        { id: 12, fleet_id: 1, name: "海洋二号", code: "HY2", imo: null, description: null,
          asset_count: 1, monitor_count: 1, event_count: 1, events_by_severity: {} },
    ],
}
const OTHER_FLEET = {
    id: 2, name: "南海船队", code: null, description: null,
    vessel_count: 1, asset_count: 1, monitor_count: 1, event_count: 1,
    events_by_severity: {}, topology_count: 0,
    vessels: [
        { id: 21, fleet_id: 2, name: "远洋三号", code: null, imo: null, description: null,
          asset_count: 1, monitor_count: 1, event_count: 1, events_by_severity: {} },
    ],
}

function vesselOverview(id: number, name: string) {
    return {
        vessel: { id, fleet_id: 1, name, code: null, imo: null, description: null,
                  asset_count: 2, monitor_count: 1, event_count: 3, events_by_severity: {},
                  fleet_name: "东海船队" },
        assets: [{ natural_id: "A1", name: "A1", type: "防火墙", ip: "10.0.0.1", status: "ok",
                   zone: "Zone 1", vessel_id: id }],
        monitored: [{ natural_id: "A1", node_id: "d1", node_label: "A1" }],
        topologies: [],
        events: [],
        events_by_severity: {},
    }
}

describe("总览 · 船队视图与单船视图", () => {
    beforeEach(() => {
        vi.mocked(api.fleets.overview).mockResolvedValue({
            totals: { fleet_count: 2, vessel_count: 3, asset_count: 4, monitor_count: 3, event_count: 5 },
            fleets: [FLEET, OTHER_FLEET],
        })
        vi.mocked(api.fleets.vesselOverview).mockImplementation(
            async (id: number) =>
                vesselOverview(
                    id,
                    id === 11 ? "海洋一号" : id === 12 ? "海洋二号" : "远洋三号",
                ) as unknown as Awaited<ReturnType<typeof api.fleets.vesselOverview>>,
        )
        vi.mocked(api.assets.list).mockResolvedValue({ items: [], total: 0, offset: 0, limit: 1 })
        vi.mocked(api.topologies.list).mockResolvedValue({ items: [] })
        vi.mocked(api.monitor.events).mockResolvedValue({ items: [], count: 0 })
        vi.mocked(api.health).mockResolvedValue({ status: "ok", siem: { configured: false, connected: false, error: null } })
    })

    function setup() {
        const qc = new QueryClient({
            defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
        })
        return render(
            <QueryClientProvider client={qc}>
                <MemoryRouter>
                    <OverviewPage />
                </MemoryRouter>
            </QueryClientProvider>,
        )
    }

    it("默认是船队视图 —— 两支船队都在", async () => {
        setup()
        await waitFor(() => expect(screen.getByText("东海船队")).toBeTruthy(), { timeout: 15000 })
        expect(screen.getByText("南海船队")).toBeTruthy()
    })

    it("点船名进单船视图，顶部下拉列出所有船舶", async () => {
        setup()
        fireEvent.click(await screen.findByText("海洋一号", {}, { timeout: 15000 }))
        await waitFor(() => expect(api.fleets.vesselOverview).toHaveBeenCalled(), { timeout: 15000 })

        const select = await screen.findByTitle("选择要查看的船舶", {}, { timeout: 15000 })
        const opts = [...(select as HTMLSelectElement).options].map((o) => o.textContent?.trim() ?? "")
        // **所有船舶**都在下拉里（含别的船队的）
        expect(opts.some((o) => o.includes("海洋一号"))).toBe(true)
        expect(opts.some((o) => o.includes("海洋二号"))).toBe(true)
        expect(opts.some((o) => o.includes("远洋三号"))).toBe(true)
        // 船队名带上，避免同名船分不清
        expect(opts.some((o) => o.startsWith("东海船队"))).toBe(true)
    })

    it("下拉选另一艘船 —— 界面跟着换", async () => {
        setup()
        fireEvent.click(await screen.findByText("海洋一号", {}, { timeout: 15000 }))
        const select = await screen.findByTitle("选择要查看的船舶", {}, { timeout: 15000 })
        await waitFor(() => expect((select as HTMLSelectElement).value).toBe("11"))

        fireEvent.change(select, { target: { value: "12" } })
        await waitFor(() => {
            const calls = vi.mocked(api.fleets.vesselOverview).mock.calls.map((c) => c[0])
            expect(calls).toContain(12)
        }, { timeout: 15000 })
    })

    it("点船队名回到船队视图 —— 所有船队都在", async () => {
        setup()
        fireEvent.click(await screen.findByText("海洋一号", {}, { timeout: 15000 }))
        await waitFor(() => expect(api.fleets.vesselOverview).toHaveBeenCalled(), { timeout: 15000 })

        // 回到船队视图
        fireEvent.click(screen.getByText("← 船队视图"))
        await waitFor(() => expect(screen.getByText("东海船队")).toBeTruthy(), { timeout: 15000 })
        expect(screen.getByText("南海船队")).toBeTruthy()
    })
})
