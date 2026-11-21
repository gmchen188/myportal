/**
 * 认证状态 —— 全应用**唯一**的数据源。
 *
 * ## 为什么必须收敛到一处
 *
 * 之前 AuthGate（app.tsx）与 AppShell 各自 `useQuery(["auth-me"])`，
 * 是**两个独立的 observer 共用同一个 queryKey**。在 GitHub Pages
 * 上（`/api/auth/me` 返回 404 + index.html）实测：
 *
 *     AuthGate 渲染 626 次  |  fetch 781 次  |  间隔 0-33ms
 *
 * 死循环的机制：
 *
 *   1. AuthGate 的 query 失败 → 状态 error → AuthGate 渲染 children
 *      → **AppShell 挂载**
 *   2. AppShell 的 observer 挂到一个 **error 状态的 query**
 *      → `refetchOnMount` 触发重取 → **状态从 error 翻回 pending**
 *   3. AuthGate 看到 isPending → 渲染 loading → **AppShell 卸载**
 *   4. query 再次失败 → 回到第 1 步
 *
 * 每个循环一次 fetch —— 渲染数与 fetch 数 1:1，页面永远卡在
 * 「正在检查登录状态…」，站点完全不可用。
 *
 * `assets` / `topologies` / `events` 只有一个 observer，所以能正常
 * 进入 error 状态 —— 这个对比就是定位的关键线索。
 *
 * **收敛到 context 后只有一个 observer，循环无从形成。**
 *
 * ## 顺带解决
 *
 * - 重复请求：`/api/auth/me` 之前每次渲染都可能发一次
 * - 「当前用户」在两处各算一遍，可能显示不一致
 */

import { useQuery, useQueryClient } from "@tanstack/react-query"
import { createContext, useContext, useEffect, useMemo, useState } from "react"

import { type CurrentUser, api, setToken } from "@/api/client"

/** 检查登录状态最多等多久（毫秒）。超时就当「后台不可达」。 */
const AUTH_CHECK_TIMEOUT_MS = 8000

export interface AuthState {
    /** 当前用户。null = 未登录或后台不可达。 */
    me: CurrentUser | null
    /** 还在检查登录状态 */
    isChecking: boolean
    /** 后台不可达（演示模式）—— 与「未登录」是两回事 */
    backendUnavailable: boolean
    /** 能不能管（显示「管理后台」入口） */
    canManage: boolean
    /** 重新检查（登录成功后调用） */
    refresh: () => void
    /** 退出登录 */
    logout: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function useAuth(): AuthState {
    const ctx = useContext(AuthContext)
    if (!ctx) throw new Error("useAuth 必须在 AuthProvider 内使用")
    return ctx
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
    const qc = useQueryClient()
    const [timedOut, setTimedOut] = useState(false)

    /**
     * **全应用唯一的 `["auth-me"]` observer**。
     *
     * `retry: false` —— 后台不可达时不该反复重试。
     * `staleTime: 60_000` —— 登录状态变化不频繁，别反复问。
     */
    const me = useQuery({
        queryKey: ["auth-me"],
        queryFn: () => api.auth.me(),
        retry: false,
        staleTime: 60_000,
    })

    /**
     * 超时兜底。
     *
     * query 可能永远不结束（网络挂起、服务端不回）。闸门卡住 =
     * 整个站点不可用。8 秒还没结果就当「后台不可达」。
     *
     * 依赖是 `[me.fetchStatus]` —— 每次进入 fetching 重置计时。
     * **不能在 effect 里 setState(false) 再依赖 fetchStatus** ——
     * 那会自己触发自己（实测 1229 次 fetch 的循环）。
     */
    useEffect(() => {
        if (me.fetchStatus !== "fetching") return
        setTimedOut(false)
        const timer = setTimeout(() => setTimedOut(true), AUTH_CHECK_TIMEOUT_MS)
        return () => clearTimeout(timer)
    }, [me.fetchStatus])

    const value = useMemo<AuthState>(() => {
        const errorStatus = (me.error as { status?: number } | null)?.status
        // 401/403 = 真的没登录；其它 = 后台不可达
        const unauthorized = errorStatus === 401 || errorStatus === 403
        const backendUnavailable =
            me.isError ? !unauthorized : me.isPending && timedOut

        return {
            me: me.isSuccess ? me.data : null,
            isChecking: me.isPending && !timedOut,
            backendUnavailable,
            canManage: me.isSuccess ? (me.data?.can_write ?? false) : false,
            refresh: () => void qc.invalidateQueries({ queryKey: ["auth-me"] }),
            logout: async () => {
                try {
                    await api.auth.logout()
                } finally {
                    // **令牌必须清掉** —— 服务端不持有它，
                    // 留着的话刷新页面还能继续用。
                    setToken(null)
                    qc.clear()
                    window.location.reload()
                }
            },
        }
    }, [me.isSuccess, me.data, me.isError, me.isPending, timedOut, qc])

    return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
