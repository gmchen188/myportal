/**
 * 资产清单的船队 / 单船筛选 —— **级联**。
 *
 * 选了船队以后，船舶下拉里只该有那支船队的船。
 * 不然会出现「船队 A + 船队 B 的船」这种互相矛盾的组合：
 * 后端按两个条件取交集，结果是**空列表** —— 用户会以为设备丢了。
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
            fleets: {
                ...actual.api.fleets,
                list: vi.fn(),
                overview: vi.fn(),
            },
            assets: {
                ...actual.api.assets,
                list: vi.fn(),
                schema: vi.fn(),
            },
        },
    }
})

import { api } from "@/api/client"
import { AssetsPage, filterVesselsByFleet } from "@/pages/assets"

const FLEETS = [
    {
        id: 1, name: "东海船队", code: null, description: null,
        vessel_count: 2, asset_count: 0, monitor_count: 0, event_count: 0,
        events_by_severity: {}, topology_count: 0, vessels: [],
    },
    {
        id: 2, name: "南海船队", code: null, description: null,
        vessel_count: 1, asset_count: 0, monitor_count: 0, event_count: 0,
        events_by_severity: {}, topology_count: 0, vessels: [],
    },
]
const VESSELS = [
    { id: 11, fleet_id: 1, name: "海洋一号", code: null, imo: null, description: null,
      asset_count: 0, monitor_count: 0, event_count: 0, events_by_severity: {} },
    { id: 12, fleet_id: 1, name: "海洋二号", code: null, imo: null, description: null,
      asset_count: 0, monitor_count: 0, event_count: 0, events_by_severity: {} },
    { id: 21, fleet_id: 2, name: "远洋三号", code: null, imo: null, description: null,
      asset_count: 0, monitor_count: 0, event_count: 0, events_by_severity: {} },
]

describe("filterVesselsByFleet —— 船舶候选按船队过滤", () => {
    it("没选船队时，全部船都在", () => {
        expect(filterVesselsByFleet(VESSELS, "").map((v) => v.name)).toEqual([
            "海洋一号", "海洋二号", "远洋三号",
        ])
    })

    it("选了船队 1，只剩那支船队的两艘", () => {
        expect(filterVesselsByFleet(VESSELS, "1").map((v) => v.name)).toEqual([
            "海洋一号", "海洋二号",
        ])
    })

    it("选了船队 2，只剩那一艘", () => {
        expect(filterVesselsByFleet(VESSELS, "2").map((v) => v.name)).toEqual(["远洋三号"])
    })

    it("id 为 null 的（还没落库的）不进候选", () => {
        const dirty = [{ id: null, fleet_id: 1, name: "还没落库" }, ...VESSELS]
        expect(filterVesselsByFleet(dirty, "").map((v) => v.name)).not.toContain("还没落库")
    })
})

describe("资产清单 · 船队/船舶级联筛选（接线）", () => {
    beforeEach(() => {
        vi.mocked(api.fleets.list).mockResolvedValue({ fleets: FLEETS, vessels: VESSELS })
        vi.mocked(api.assets.list).mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50 })
        vi.mocked(api.assets.schema).mockResolvedValue({
            zones: [], fields: [], required: [], types: [],
        } as unknown as Awaited<ReturnType<typeof api.assets.schema>>)
    })

    function setup() {
        const qc = new QueryClient({
            defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
        })
        return render(
            <QueryClientProvider client={qc}>
                <MemoryRouter>
                    <AssetsPage />
                </MemoryRouter>
            </QueryClientProvider>,
        )
    }

    function vesselOptions(): string[] {
        const selects = screen.getAllByRole("combobox") as HTMLSelectElement[]
        const vesselSelect = selects.find((s) =>
            [...s.options].some((o) => o.textContent === "海洋一号"),
        )
        return vesselSelect ? [...vesselSelect.options].map((o) => o.textContent ?? "") : []
    }

    it("没选船队时，船舶下拉列出全部船", async () => {
        setup()
        // **超时放宽** —— 全量并发跑时渲染慢，默认 1 秒不够
        //（实测单独跑通过、全量跑挂在这行上）。
        await waitFor(() => expect(vesselOptions().length).toBeGreaterThan(1), { timeout: 15000 })
        expect(vesselOptions()).toContain("海洋一号")
        expect(vesselOptions()).toContain("远洋三号")
    })

    it("选了船队后，船舶下拉只剩那支船队的船", async () => {
        setup()
        await waitFor(() => expect(vesselOptions().length).toBeGreaterThan(1), { timeout: 15000 })

        const fleetSelect = (screen.getAllByRole("combobox") as HTMLSelectElement[]).find((s) =>
            [...s.options].some((o) => o.textContent === "东海船队"),
        )!
        fireEvent.change(fleetSelect, { target: { value: "1" } })

        await waitFor(() => {
            const opts = vesselOptions()
            expect(opts).toContain("海洋一号")
        }, { timeout: 15000 })
        expect(vesselOptions()).toContain("海洋二号")
        // **另一支船队的船不该出现**
        expect(vesselOptions()).not.toContain("远洋三号")
    })
})
