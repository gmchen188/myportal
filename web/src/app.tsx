import { useQuery } from "@tanstack/react-query"
import { Navigate, Route, Routes } from "react-router-dom"

import { api } from "@/api/client"
import { AppShell } from "@/components/app-shell"
import { ErrorBoundary } from "@/components/error-boundary"
import { AdminPage } from "@/pages/admin"
import { AssetsPage } from "@/pages/assets"
import { EventsPage } from "@/pages/events"
import { LoginPage } from "@/pages/login"
import { MonitorPage } from "@/pages/monitor"
import { OverviewPage } from "@/pages/overview"
import { SiemPage } from "@/pages/siem"
import { TopologiesPage } from "@/pages/topologies"

/**
 * 每页一个 ErrorBoundary。
 *
 * **为什么是页面级而不是包住整个 Routes** ——
 * 整页白屏意味着运维在故障时连侧边导航都没了，只能刷浏览器。
 * 页面级兜底：一页出错，显示「这一块渲染出错 + 重试」，
 * 导航还能用，可以切到别的页面看别的数据。
 */
function guarded(node: React.ReactNode) {
    return <ErrorBoundary variant="page">{node}</ErrorBoundary>
}

/**
 * 认证闸门。
 *
 * **启动时先问后台「我是谁」** —— 拿到 401 就显示登录页。
 *
 * 为什么不是「有 token 就放行」：token 可能是过期的、被撤销的、
 * 或者后台根本还没配好管理员账号。只看本地有没有 token 会让用户
 * 停在一个什么都加载不出来的页面上，还以为是系统坏了。
 *
 * 后台的 `/api/auth/me` **任何模式都要令牌**（严格认证），所以
 * 这个判断在开发模式同样有效。
 */
function AuthGate({ children }: { children: React.ReactNode }) {
    const me = useQuery({
        queryKey: ["auth-me"],
        queryFn: () => api.auth.me(),
        retry: false,
        staleTime: 60_000,
    })

    if (me.isPending) {
        return (
            <div
                style={{
                    minHeight: "100vh",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                }}
            >
                <p className="muted">正在检查登录状态…</p>
            </div>
        )
    }

    if (me.isError) {
        return <LoginPage onLoggedIn={() => void me.refetch()} />
    }

    return <>{children}</>
}

export function App() {
    return (
        <AuthGate>
            <Routes>
                <Route element={<AppShell />}>
                    <Route index element={guarded(<OverviewPage />)} />
                    <Route path="assets" element={guarded(<AssetsPage />)} />
                    <Route path="topologies" element={guarded(<TopologiesPage />)} />
                    <Route path="monitor" element={guarded(<MonitorPage />)} />
                    <Route path="events" element={guarded(<EventsPage />)} />
                    <Route path="siem" element={guarded(<SiemPage />)} />
                    <Route path="admin" element={guarded(<AdminPage />)} />
                    <Route path="*" element={<Navigate to="/" replace />} />
                </Route>
            </Routes>
        </AuthGate>
    )
}
