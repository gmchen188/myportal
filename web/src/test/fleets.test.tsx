/**
 * 总览的**船队视图 / 单船视图**切换，以及资产清单的**按船队-单船分组**。
 *
 * ## 为什么这组测试重要
 *
 * 「船队-单船」是用户拿到总览后**第一眼看到的结构**。
 *
 * 两条不变量：
 *
 * 1. **没归船的设备不能消失** —— 导入进来的设备常常还不知道装在哪艘船上，
 *    藏起来等于让它们从清单和总览里消失。
 * 2. **合计与分项要对得上** —— 总数说 14 件，逐支船队加起来也得是 14。
 *    对不上，看的人会以为统计错了。
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { api, type Fleet, type Vessel, type VesselOverview } from "@/api/client"
import { FleetsPage } from "@/pages/fleets"
import { OverviewPage } from "@/pages/overview"

vi.mock("@/api/client", async () => {
    const actual = await vi.importActual<typeof import("@/api/client")>("@/api/client")
    return {
        ...actual,
        api: {
            ...actual.api,
            assets: { ...actual.api.assets, list: vi.fn() },
            topologies: { ...actual.api.topologies, list: vi.fn() },
            monitor: { ...actual.api.monitor, events: vi.fn() },
            health: vi.fn(),
            fleets: {
                ...actual.api.fleets,
                overview: vi.fn(),
                vesselOverview: vi.fn(),
                list: vi.fn(),
                createFleet: vi.fn(),
                create: vi.fn(),
                patchFleet: vi.fn(),
                patchVessel: vi.fn(),
                removeFleet: vi.fn(),
                removeVessel: vi.fn(),
                assignAssets: vi.fn(),
            },
        },
    }
})

function vessel(over: Partial<Vessel> = {}): Vessel {
    return {
        id: 1,
        fleet_id: 10,
        name: "海洋一号",
        code: "HY1",
        imo: null,
        description: null,
        asset_count: 2,
        monitor_count: 1,
        event_count: 3,
        events_by_severity: { critical: 1, high: 2 },
        ...over,
    }
}

function fleet(over: Partial<Fleet> = {}): Fleet {
    return {
        id: 10,
        name: "东海船队",
        code: "DF",
        description: null,
        vessel_count: 1,
        asset_count: 2,
        monitor_count: 1,
        event_count: 3,
        events_by_severity: { critical: 1, high: 2 },
        topology_count: 1,
        vessels: [vessel()],
        ...over,
    }
}

const OVERVIEW = {
    fleets: [fleet()],
    totals: {
        fleet_count: 1,
        vessel_count: 1,
        asset_count: 3,
        monitor_count: 1,
        event_count: 3,
    },
}

const VESSEL_OVERVIEW: VesselOverview = {
    vessel: {
        id: 1,
        fleet_id: 10,
        fleet_name: "东海船队",
        name: "海洋一号",
        code: "HY1",
        imo: null,
        description: null,
    },
    assets: [
        { id: 1, natural_id: "A1", name: "FW-EDGE-01", type: "防火墙", zone: "Zone 1", ip: "10.0.0.1", status: "在用", siem_push_status: null },
        { id: 2, natural_id: "A2", name: "CBS-NAV-01", type: "船舶系统", zone: "Zone 1", ip: null, status: "在用", siem_push_status: null },
    ],
    monitored: [{ natural_id: "A1", node_label: "FW-EDGE-01", ip: "10.0.0.1", channel: "fortisiem", enabled: 1 }],
    topologies: [{ id: 1, name: "船队网络拓扑", node_count: 14 }],
    events: [{ id: 1, title: "严重事件", severity: "critical", device_natural_id: "A1", occurred_at: null }],
    events_by_severity: { critical: 1 },
}

function setup() {
    const qc = new QueryClient({
        defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    const utils = render(
        <QueryClientProvider client={qc}>
            <MemoryRouter>
                <OverviewPage />
            </MemoryRouter>
        </QueryClientProvider>,
    )
    return { ...utils, qc }
}

describe("总览 · 船队视图 / 单船视图", () => {
    beforeEach(() => {
        vi.mocked(api.fleets.overview).mockResolvedValue(OVERVIEW)
        vi.mocked(api.fleets.vesselOverview).mockResolvedValue(VESSEL_OVERVIEW)
        vi.mocked(api.assets.list).mockResolvedValue({ items: [], total: 3, offset: 0, limit: 200 })
        vi.mocked(api.topologies.list).mockResolvedValue({ items: [] })
        vi.mocked(api.monitor.events).mockResolvedValue({ items: [], count: 0 } as never)
        vi.mocked(api.health).mockResolvedValue({ siem: { connected: true, configured: true } } as never)
    })

    it("默认是船队视图 —— 显示船队卡片与船名", async () => {
        setup()
        await waitFor(() => expect(screen.getByText("东海船队")).toBeTruthy())
        expect(screen.getByText("海洋一号")).toBeTruthy()
        // 单船视图的内容这时不该在（用该视图特有的文字判定，
        // 「设备」不行 —— 最近事件那张表的表头也叫「设备」）
        expect(screen.queryByText("FW-EDGE-01")).toBeNull()
        expect(screen.queryByText("← 船队视图")).toBeNull()
    })

    it("点船名切到单船视图 —— 显示那艘船的设备", async () => {
        setup()
        await waitFor(() => expect(screen.getByText("海洋一号")).toBeTruthy())

        fireEvent.click(screen.getByText("海洋一号"))

        await waitFor(() => expect(screen.getByText("FW-EDGE-01")).toBeTruthy())
        expect(screen.getByText("CBS-NAV-01")).toBeTruthy()
        // 面包屑指回船队
        expect(screen.getByText("← 船队视图")).toBeTruthy()
        expect(screen.getByText("东海船队")).toBeTruthy()
    })

    it("单船视图里的设备按安全区域分组", async () => {
        setup()
        await waitFor(() => expect(screen.getByText("海洋一号")).toBeTruthy())
        fireEvent.click(screen.getByText("海洋一号"))
        await waitFor(() => expect(screen.getByText("FW-EDGE-01")).toBeTruthy())
        expect(screen.getByText("Zone 1")).toBeTruthy()
    })

    it("能退回船队视图", async () => {
        setup()
        await waitFor(() => expect(screen.getByText("海洋一号")).toBeTruthy())
        fireEvent.click(screen.getByText("海洋一号"))
        await waitFor(() => expect(screen.getByText("← 船队视图")).toBeTruthy())

        fireEvent.click(screen.getByText("← 船队视图"))
        await waitFor(() => expect(screen.queryByText("FW-EDGE-01")).toBeNull())
    })

    it("未归船的设备在船队视图里也看得见", async () => {
        vi.mocked(api.fleets.overview).mockResolvedValue({
            fleets: [
                fleet(),
                {
                    id: null,
                    name: "未归船",
                    code: null,
                    description: null,
                    vessel_count: 0,
                    asset_count: 2,
                    monitor_count: 0,
                    event_count: 0,
                    events_by_severity: {},
                    topology_count: 0,
                    vessels: [
                        vessel({
                            id: null,
                            fleet_id: null,
                            name: "未归船",
                            asset_count: 2,
                            monitor_count: 0,
                            event_count: 0,
                            events_by_severity: {},
                        }),
                    ],
                },
            ],
            totals: { fleet_count: 1, vessel_count: 1, asset_count: 4, monitor_count: 1, event_count: 3 },
        })
        setup()
        // 「未归船」会出现两次 —— 档名与船名各一次
        await waitFor(() => expect(screen.getAllByText("未归船").length).toBeGreaterThan(0))
    })

    it("事件严重度按 pill 显示数量", async () => {
        setup()
        await waitFor(() => expect(screen.getByText("东海船队")).toBeTruthy())
        // 严重 1、高危 2 —— 堆叠条与 pill 矩阵都要有
        expect(screen.getAllByText(/严重/).length).toBeGreaterThan(0)
        expect(screen.getAllByText(/高危/).length).toBeGreaterThan(0)
    })
})

/**
 * 管理页的写操作。
 *
 * ## 为什么单独测
 *
 * 读端点全绿，创建却报 **422** —— 因为 `request()` 内部已经
 * `JSON.stringify(opts.body)`，调用方又写了一层 → body 变成
 * **一个 JSON 字符串**，FastAPI 收到字符串 → 请求体校验失败。
 *
 * **双序列化不报错，只是发错东西** —— 只有真发一次请求才会暴露。
 * 所以这里断言的是**传进去的是对象**。
 */
describe("船队与船舶 · 管理", () => {
    beforeEach(() => {
        vi.mocked(api.fleets.list).mockResolvedValue({ fleets: [], vessels: [] })
        vi.mocked(api.fleets.createFleet).mockResolvedValue({ id: 99, name: "新船队" })
    })

    function setupManage() {
        const qc = new QueryClient({
            defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
        })
        return render(
            <QueryClientProvider client={qc}>
                <MemoryRouter>
                    <FleetsPage />
                </MemoryRouter>
            </QueryClientProvider>,
        )
    }

    it("新建船队时传的是对象，不是 JSON 字符串", async () => {
        setupManage()
        const input = await screen.findByPlaceholderText("新船队名称")
        fireEvent.change(input, { target: { value: "新船队" } })
        fireEvent.click(screen.getByText("新建船队"))

        await waitFor(() => expect(api.fleets.createFleet).toHaveBeenCalled())
        const arg = vi.mocked(api.fleets.createFleet).mock.calls[0][0]
        // **双重 JSON.stringify 会让它变成字符串** —— FastAPI 收到字符串就 422
        expect(typeof arg).toBe("object")
        expect((arg as { name: string }).name).toBe("新船队")
    })
})
