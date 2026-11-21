import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderHook, waitFor } from "@testing-library/react"
import React from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { api } from "@/api/client"

vi.mock("@/api/client", async () => {
    const actual = await vi.importActual<typeof import("@/api/client")>("@/api/client")
    return {
        ...actual,
        api: {
            ...actual.api,
            siem: {
                ...actual.api.siem,
                sync: vi.fn(async () => ({
                    org: "Super",
                    window_minutes: 1440,
                    events: { fetched: 2, created: 2, updated: 0, skipped: 0 },
                    devices: { total: 3, created: 0, updated: 0, skipped: 3 },
                    synced_at: "2026-11-21T00:00:00",
                })),
            },
        },
    }
})

describe("同步后的缓存失效", () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    it("assets / siem-status / events / monitor-panel 都要作废", async () => {
        const { useSiemSync } = await import("@/hooks/use-siem")

        const qc = new QueryClient()
        const invalidate = vi.spyOn(qc, "invalidateQueries")

        const wrapper = ({ children }: { children: React.ReactNode }) =>
            React.createElement(QueryClientProvider, { client: qc }, children)

        const { result } = renderHook(() => useSiemSync(), { wrapper })
        await result.current.mutateAsync({ minutes: 1440 })

        await waitFor(() => {
            const keys = invalidate.mock.calls.map((c) => JSON.stringify(c[0]?.queryKey))
            // 设备 → 资产清单
            expect(keys).toContain(JSON.stringify(["assets"]))
            expect(keys).toContain(JSON.stringify(["siem-status"]))
            // 事件 → 事件列表（事件页 key 是 ["events", severity, source]，
            // 总览是 ["events"]，前缀失效两种都能命中）
            expect(keys).toContain(JSON.stringify(["events"]))
            // 监控面板的节点颜色也依赖事件
            expect(keys).toContain(JSON.stringify(["monitor-panel"]))
        })
    })
})
