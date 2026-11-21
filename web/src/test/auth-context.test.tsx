/**
 * 认证状态收敛到唯一 observer —— **死循环的回归测试**。
 *
 * ## 曾经的故障
 *
 * AuthGate（app.tsx）与 AppShell（app-shell.tsx）各自
 * `useQuery(["auth-me"])` —— 两个独立 observer 共用一个 queryKey。
 *
 * 在 GitHub Pages 上（`/api/auth/me` 返回 404 + index.html）实测：
 *
 *     AuthGate 渲染 626 次  |  fetch 781 次  |  间隔 0-33ms
 *     页面永远卡在「正在检查登录状态…」
 *
 * 死循环机制：
 *
 *   1. AuthGate 的 query 失败 → error → AuthGate 渲染 children
 *      → AppShell 挂载
 *   2. AppShell 的 observer 挂到 error 状态的 query
 *      → refetchOnMount 触发重取 → 状态从 error 翻回 pending
 *   3. AuthGate 看到 isPending → 渲染 loading → AppShell 卸载
 *   4. query 再次失败 → 回到 1
 *
 * 每个循环一次 fetch —— 渲染数与 fetch 数 1:1。
 *
 * ## 这些测试锁住什么
 *
 * 1. **只有一个 observer** —— 从结构上杜绝这类循环
 * 2. 后台不可达时**要放行**（演示站不能卡在登录页）
 * 3. 请求次数**有上界** —— 不是「少一点」，是不失控
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { AuthProvider, useAuth } from "@/components/auth-context"

vi.mock("@/api/client", async () => {
    const actual = await vi.importActual<typeof import("@/api/client")>("@/api/client")
    return {
        ...actual,
        api: {
            ...actual.api,
            auth: { ...actual.api.auth, me: vi.fn(), logout: vi.fn() },
        },
    }
})

/** 造一个 QueryClient，并把它暴露出来好数 observer。 */
function makeClient() {
    const qc = new QueryClient({
        defaultOptions: { queries: { retry: false, gcTime: Infinity } },
    })
    return qc
}

describe("认证状态的 observer 唯一性", () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    it("全应用只有一个 ['auth-me'] observer —— 结构上杜绝死循环", async () => {
        const { api, ApiError } = await import("@/api/client")
        vi.mocked(api.auth.me).mockRejectedValue(new ApiError(404, "HTTP 404"))

        // **渲染整个 App**，不只渲染 AuthProvider ——
        // 只测 AuthProvider 的话，将来有人在 AppShell 或任何页面里
        // 再加一个 useQuery(["auth-me"])，这个测试照样绿，
        // 而线上又是死循环。
        const { App } = await import("@/app")
        const qc = makeClient()
        render(
            <QueryClientProvider client={qc}>
                <MemoryRouter>
                    <App />
                </MemoryRouter>
            </QueryClientProvider>,
        )

        await waitFor(() => {
            const q = qc.getQueryCache().find({ queryKey: ["auth-me"] })
            expect(q).toBeTruthy()
            // **关键断言**：同一时刻只有一个 observer。
            // 两个 observer 共用一个 queryKey 就是那个死循环的成因。
            expect(q!.getObserversCount()).toBe(1)
        })
    })

    it("请求次数有上界 —— 不是失控循环", async () => {
        const { api, ApiError } = await import("@/api/client")
        vi.mocked(api.auth.me).mockRejectedValue(new ApiError(404, "HTTP 404"))

        // 同样渲染整个 App
        const { App } = await import("@/app")
        const qc = makeClient()
        render(
            <QueryClientProvider client={qc}>
                <MemoryRouter>
                    <App />
                </MemoryRouter>
            </QueryClientProvider>,
        )

        await waitFor(() => expect(api.auth.me).toHaveBeenCalled())
        await new Promise((r) => setTimeout(r, 300))

        const calls = vi.mocked(api.auth.me).mock.calls.length
        // **上界是 5** —— 之前的死循环里 9 秒内发了几百次。
        // 放宽一点给 React 19 的并发渲染留余量，但不能没有界。
        expect(calls).toBeLessThanOrEqual(5)
    })

    it("后台不可达时标记 backendUnavailable，不当成未登录", async () => {
        const { api, ApiError } = await import("@/api/client")
        vi.mocked(api.auth.me).mockRejectedValue(new ApiError(404, "HTTP 404"))

        const seen: { backendUnavailable?: boolean } = {}
        function Probe() {
            Object.assign(seen, { backendUnavailable: useAuth().backendUnavailable })
            return null
        }

        const qc = makeClient()
        render(
            <QueryClientProvider client={qc}>
                <AuthProvider>
                    <Probe />
                </AuthProvider>
            </QueryClientProvider>,
        )

        await waitFor(() => expect(seen.backendUnavailable).toBe(true))
    })

    it("401 要当成未登录（不是后台不可达）", async () => {
        const { api, ApiError } = await import("@/api/client")
        vi.mocked(api.auth.me).mockRejectedValue(new ApiError(401, "需要 Bearer 令牌"))

        const seen: { backendUnavailable?: boolean; isChecking?: boolean } = {}
        function Probe() {
            Object.assign(seen, {
                backendUnavailable: useAuth().backendUnavailable,
                isChecking: useAuth().isChecking,
            })
            return null
        }

        const qc = makeClient()
        render(
            <QueryClientProvider client={qc}>
                <AuthProvider>
                    <Probe />
                </AuthProvider>
            </QueryClientProvider>,
        )

        await waitFor(() => expect(seen.isChecking).toBe(false))
        // 401 是「没登录」，不是「后台不可达」—— 后者会放行绕过认证
        expect(seen.backendUnavailable).toBe(false)
    })

    it("登录成功时能拿到当前用户", async () => {
        const { api } = await import("@/api/client")
        vi.mocked(api.auth.me).mockResolvedValue({
            user_id: "admin",
            tenant_id: "t-asi",
            tenant_slug: "asi",
            role: "super_admin",
            locale: "zh-CN",
            is_admin: true,
            is_super_admin: true,
            can_write: true,
        })

        const seen: { me?: unknown; canManage?: boolean } = {}
        function Probe() {
            Object.assign(seen, {
                me: useAuth().me,
                canManage: useAuth().canManage,
            })
            return null
        }

        const qc = makeClient()
        render(
            <QueryClientProvider client={qc}>
                <AuthProvider>
                    <Probe />
                </AuthProvider>
            </QueryClientProvider>,
        )

        await waitFor(() => expect(seen.me).toBeTruthy())
        expect(seen.canManage).toBe(true)
    })
})


/**
 * 结构性断言 —— **源码里只能有一处 useQuery(["auth-me"])**。
 *
 * ## 为什么运行时断言不够
 *
 * 「渲染整个 App 然后数 observer」这种做法**抓不住**将来有人在
 * AppShell 里加一个 useQuery(["auth-me"])：
 *
 * - 变异测试里，AppShell 因为各种原因没渲染 → observer 仍是 1 →
 *   断言照样绿 → **测试形同虚设**
 *
 * 结构性断言直接读源码：全应用只有 `auth-context.tsx` 一处订阅
 * `["auth-me"]`。**只要有人再加一处，这个测试立刻红。**
 *
 * 这是「结构上不可能出错」比「运行时恰好没出错」可靠的地方。
 */
describe("认证查询的结构约束", () => {
    it("只有 auth-context.tsx 订阅 [\"auth-me\"]", async () => {
        const { readFileSync, readdirSync, statSync } = await import("node:fs")
        const { join } = await import("node:path")

        const srcDir = join(process.cwd(), "src")
        const hits: string[] = []

        function walk(dir: string) {
            for (const name of readdirSync(dir)) {
                const p = join(dir, name)
                if (statSync(p).isDirectory()) {
                    walk(p)
                    continue
                }
                if (!/\.(ts|tsx)$/.test(name)) continue
                // 测试文件本身不算
                if (name.includes(".test.")) continue
                const src = readFileSync(p, "utf8")
                // 匹配 useQuery 里带 ["auth-me"] 的
                if (/queryKey:\s*\[\s*"auth-me"/.test(src)) {
                    hits.push(p.replace(srcDir, "src"))
                }
            }
        }
        walk(srcDir)

        expect(hits).toEqual([join("src", "components", "auth-context.tsx")])
    })

    it("auth-context 是唯一提供 useAuth 的地方 —— 组件不许自己 useQuery(['auth-me'])", async () => {
        const { readFileSync, readdirSync, statSync } = await import("node:fs")
        const { join } = await import("node:path")

        const srcDir = join(process.cwd(), "src")
        const offenders: string[] = []

        function walk(dir: string) {
            for (const name of readdirSync(dir)) {
                const p = join(dir, name)
                if (statSync(p).isDirectory()) {
                    walk(p)
                    continue
                }
                if (!/\.(ts|tsx)$/.test(name)) continue
                if (name.includes(".test.")) continue
                if (p.endsWith(join("components", "auth-context.tsx"))) continue
                const src = readFileSync(p, "utf8")
                // 任何地方 import 了 useQuery 且提到 auth-me → 违规
                if (src.includes("auth-me") && /from "@tanstack\/react-query"/.test(src)) {
                    offenders.push(p.replace(srcDir, "src"))
                }
            }
        }
        walk(srcDir)

        expect(offenders).toEqual([])
    })
})
