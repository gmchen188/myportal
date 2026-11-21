/**
 * SiemPage 的失败态与矛盾态。
 *
 * 两条来自代码质量审查：
 *   I-2 设备拉取失败被显示成「0 台设备」—— 与「SIEM 里确实没有设备」
 *        长得一模一样，而这个页面存在的意义就是区分「漏纳管 ≠ 安全」。
 *   I-3 TanStack Query v5 在 error 时**保留 data**（reducer 只改 status），
 *        所以后台挂掉后的下一次轮询失败会同时出现
 *        「无法获取连接状态」和「四段全通」—— 自相矛盾。
 *
 * 独立文件 —— 同目录的 siem.test.tsx 顶层 vi.mock 了 use-siem，
 * 测不到页面真实渲染。
 */
import { render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import type { SiemStatus } from "@/api/client"

vi.mock("@/hooks/use-siem", () => ({
    useSiemStatus: vi.fn(),
    useSiemSync: vi.fn(),
    useSiemRefresh: vi.fn(),
}))

function status(over: Partial<SiemStatus> = {}): SiemStatus {
    return {
        configured: true,
        connected: true,
        org: "Super",
        error: null,
        stage: "ok",
        probes: {
            tcp: { ok: true, detail: "可连接" },
            tls: { ok: true, detail: "握手成功" },
            auth: { ok: true, detail: "token 成功" },
            api: { ok: true, detail: "读到 3 台" },
        },
        devices: [],
        ...over,
    }
}

async function setup({
    statusResult,
    syncData,
}: {
    statusResult: Record<string, unknown>
    syncData?: Record<string, unknown>
}) {
    const { useSiemStatus, useSiemSync, useSiemRefresh } = await import("@/hooks/use-siem")
    const { SiemPage } = await import("@/pages/siem")

    vi.mocked(useSiemStatus).mockReturnValue(statusResult as never)
    vi.mocked(useSiemSync).mockReturnValue({
        mutate: vi.fn(),
        isPending: false,
        isError: false,
        error: null,
        data: syncData,
    } as never)
    vi.mocked(useSiemRefresh).mockReturnValue({
        mutate: vi.fn(),
        isPending: false,
        isError: false,
        error: null,
        data: undefined,
    } as never)

    render(<SiemPage />)
}

describe("SiemPage 的失败态", () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    it("I-2 设备拉取失败要显红，不能只显示「共 0 台」", async () => {
        await setup({
            statusResult: {
                data: status(),
                isPending: false,
                isFetching: false,
                isError: false,
                error: null,
                refetch: vi.fn(),
            },
            syncData: {
                org: "Super",
                window_minutes: 1440,
                events: { fetched: 12, created: 12, updated: 0, skipped: 0 },
                devices: {
                    total: 0,
                    created: 0,
                    updated: 0,
                    skipped: 0,
                    error: "CMDB 返回了非 XML 内容",
                },
                synced_at: "2026-11-21T00:00:00",
            },
        })

        expect(screen.getByText(/设备拉取失败/)).toBeTruthy()
        expect(screen.getByText(/CMDB 返回了非 XML 内容/)).toBeTruthy()
        // 必须说清楚「共 0 台」不代表 SIEM 里没有设备
        expect(screen.getByText(/不代表 SIEM 里没有设备/)).toBeTruthy()
    })

    it("I-3 请求失败但有旧数据时，不能同时显示「无法获取」和「四段全通」", async () => {
        await setup({
            statusResult: {
                // TanStack Query v5 在 error 时保留 data
                data: status(),
                isPending: false,
                isFetching: false,
                isError: true,
                error: new Error("[502] FortiSIEM 不可达"),
                refetch: vi.fn(),
            },
        })

        // 有旧数据 → 说「刷新失败」
        expect(screen.getByText(/刷新连接状态失败/)).toBeTruthy()
        // 不能出现「无法获取连接状态」这个说法
        expect(screen.queryByText("无法获取连接状态")).toBeNull()
        // 要说清楚下面的是上次的结果
        expect(screen.getByText(/上一次成功探测/)).toBeTruthy()
    })

    it("I-3 没有旧数据时就说「无法获取连接状态」", async () => {
        await setup({
            statusResult: {
                data: undefined,
                isPending: false,
                isFetching: false,
                isError: true,
                error: new Error("[502] FortiSIEM 不可达"),
                refetch: vi.fn(),
            },
        })

        expect(screen.getByText("无法获取连接状态")).toBeTruthy()
        expect(screen.queryByText(/刷新连接状态失败/)).toBeNull()
    })

    it("I-6 未知 stage 要显示原值，不能渲染出 undefined", async () => {
        await setup({
            statusResult: {
                data: status({ stage: "quota" as never, connected: false }),
                isPending: false,
                isFetching: false,
                isError: false,
                error: null,
                refetch: vi.fn(),
            },
        })

        expect(screen.getByText(/卡在 quota 这一段/)).toBeTruthy()
        expect(screen.queryByText(/undefined/)).toBeNull()
    })
})


/**
 * I-5 —— 502 的 probes 提取了就得用。
 *
 * 后台在 502 的 body 里塞了四段实测结果（probes），extractErrorMeta
 * 把它提取出来了，但如果没有消费者，那些信息就白带了 ——
 * 运维只看到一句「FortiSIEM 不可达」，不知道卡在哪一段、哪一段通了。
 */
describe("同步失败时的分段实测结果", () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    it("要渲染出后台带回来的四段诊断", async () => {
        const { useSiemStatus, useSiemSync, useSiemRefresh } = await import("@/hooks/use-siem")
        const { SiemPage } = await import("@/pages/siem")

        vi.mocked(useSiemStatus).mockReturnValue({
            data: status(),
            isPending: false,
            isFetching: false,
            isError: false,
            error: null,
            refetch: vi.fn(),
        } as never)
        vi.mocked(useSiemSync).mockReturnValue({
            mutate: vi.fn(),
            isPending: false,
            isError: true,
            error: Object.assign(new Error("[502] FortiSIEM 不可达"), {
                meta: {
                    stage: "auth",
                    probes: {
                        tcp: { ok: true, detail: "172.16.20.48:443 可连接" },
                        tls: { ok: true, detail: "TLS 握手成功" },
                        auth: { ok: false, detail: "未配置 FORTISIEM_CLIENT_ID" },
                    },
                },
            }),
            data: undefined,
        } as never)
        vi.mocked(useSiemRefresh).mockReturnValue({
            mutate: vi.fn(),
            isPending: false,
            isError: false,
            error: null,
            data: undefined,
        } as never)

        render(<SiemPage />)

        expect(screen.getByText(/失败时的分段实测结果/)).toBeTruthy()
        // 四段都要出现，失败那段要标红
        expect(screen.getAllByText(/TCP 连接/).length).toBeGreaterThan(0)
        expect(screen.getByText(/未配置 FORTISIEM_CLIENT_ID/)).toBeTruthy()
    })
})
