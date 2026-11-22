/**
 * 监控面板的区域导航。
 *
 * **为什么需要这个功能** ——
 * 画布按内容算宽度，实测 2010px。移动端视口只有 341px，也就是 **5.9 屏**；
 * 初始视图只露出 Zone 3 与 Zone 4，**Zone 0/1/2 的告警状态全在屏幕外**。
 *
 * 一个监控面板让用户看不见告警，比界面难看严重得多。
 * 光加一句「可横向滚动」不够 —— 用户不知道要滚多远，也不知道滚过去有什么。
 * 所以给了「按区域跳转」的入口。
 *
 * 这些测试锁住那条能力 —— 退化了用户就看不到告警区域了。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import React from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { MonitorPage } from "@/pages/monitor"

vi.mock("@/api/client", async () => {
    const actual = await vi.importActual<typeof import("@/api/client")>("@/api/client")
    return {
        ...actual,
        api: {
            ...actual.api,
            topologies: {
                ...actual.api.topologies,
                list: vi.fn(async () => ({ items: [{ id: 1, name: "船队网络拓扑 V1" }] })),
            },
            monitor: {
                ...actual.api.monitor,
                panel: vi.fn(async () => ({
                    nodes: [
                        {
                            node_id: "d1",
                            label: "FW-EDGE-01",
                            px: 135,
                            py: 178,
                            w: 190,
                            h: 60,
                            severity: "unknown",
                            color: "#94a3b8",
                            active_incidents: 0,
                        },
                    ],
                    // 三个区域横向排开 —— 模拟移动端「大部分在屏幕外」的情形
                    zones: [
                        { id: "z0", title: "Zone 0 · 通用业务区", x: 95, y: 70, w: 555, h: 340 },
                        { id: "z1", title: "Zone 1 · 船舶核心控制区", x: 740, y: 70, w: 555, h: 340 },
                        { id: "z2", title: "Zone 2 · 船员生活区", x: 1385, y: 70, w: 555, h: 340 },
                    ],
                    links: [],
                    counts: { critical: 0, high: 0, medium: 0, unknown: 1 },
                    severity_colors: {},
                    total_incidents: 0,
                    parse_error: null,
                })),
            },
        },
    }
})

/** 监控面板用 useQuery —— 必须有 QueryClientProvider。 */
function renderMonitor() {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = ({ children }: { children: React.ReactNode }) =>
        React.createElement(QueryClientProvider, { client: qc }, children)
    return render(<MonitorPage />, { wrapper })
}

describe("监控面板的区域导航", () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    it("每个区域都要有一个跳转按钮", async () => {
        renderMonitor()

        // 区域名会出现两次（导航按钮 + 画布里的区域标题），所以用 role 定位
        await screen.findByRole("button", { name: /Zone 0/ }, { timeout: 10000 })
        expect(screen.getByRole("button", { name: /Zone 0/ })).toBeInTheDocument()
        expect(screen.getByRole("button", { name: /Zone 1/ })).toBeInTheDocument()
        expect(screen.getByRole("button", { name: /Zone 2/ })).toBeInTheDocument()
    })

    it("要说明画布比屏幕宽、可以横向滚动", async () => {
        renderMonitor()

        await screen.findByText(/可横向滚动/, undefined, { timeout: 10000 })
        expect(screen.getByText(/可横向滚动/)).toBeInTheDocument()
    })

    it("按钮顺序要跟画布上的左右顺序一致（按 x 排序）", async () => {
        renderMonitor()

        await screen.findByRole("button", { name: /Zone 0/ }, { timeout: 10000 })
        const btns = screen
            .getAllByRole("button")
            .map((b) => b.textContent.trim())
            .filter((t) => t.startsWith("Zone "))
        expect(btns).toEqual([
            "Zone 0 · 通用业务区",
            "Zone 1 · 船舶核心控制区",
            "Zone 2 · 船员生活区",
        ])
    })

    it("点按钮要真的滚动画布（不能是摆设）", async () => {
        renderMonitor()

        await screen.findByRole("button", { name: /Zone 0/ }, { timeout: 10000 })

        // jsdom 不实现滚动 —— 拦下 Element.prototype.scrollTo，
        // 记录调用参数。
        //
        // 不去 DOM 里找某个具体元素打桩：React ref 指向的元素与
        // querySelector 找到的未必是同一个（那是选错元素，不是产品 bug）。
        const calls: number[] = []
        const orig = Element.prototype.scrollTo
        Element.prototype.scrollTo = function scrollTo(this: Element, ...args: unknown[]) {
            const opts = args[0] as { left?: number } | undefined
            calls.push(opts?.left ?? -1)
        } as unknown as Element["scrollTo"]

        try {
            screen.getByRole("button", { name: /Zone 2/ }).click()
            expect(calls.length).toBeGreaterThan(0)
            // Zone 2 在 x=1385，应该往右滚（不是回 0）
            expect(calls[0]).toBeGreaterThan(1000)
        } finally {
            Element.prototype.scrollTo = orig
        }
    })
})
