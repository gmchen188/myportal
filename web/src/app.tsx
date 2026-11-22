import { Navigate, Route, Routes } from "react-router-dom"

import { AppShell } from "@/components/app-shell"
import { AuthProvider, useAuth } from "@/components/auth-context"
import { ErrorBoundary } from "@/components/error-boundary"
import { AdminPage } from "@/pages/admin"
import { AssetsPage } from "@/pages/assets"
import { EventsPage } from "@/pages/events"
import { FleetsPage } from "@/pages/fleets"
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
 * ## 关键：这里**不再自己发请求**
 *
 * 认证状态全部来自 `useAuth()`（AuthProvider 里的唯一 observer）。
 *
 * 之前 AuthGate 与 AppShell 各自 `useQuery(["auth-me"])` —— 两个
 * observer 共用一个 queryKey，在后台不可达时形成死循环（实测
 * 渲染 626 次 / fetch 781 次，页面永远卡在加载）。详见
 * `components/auth-context.tsx` 的说明。
 */
function AuthGate({ children }: { children: React.ReactNode }) {
    const { isChecking, backendUnavailable, me, refresh } = useAuth()

    if (isChecking) {
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

    // 没登录（401/403）→ 显示登录页
    if (!me && !backendUnavailable) {
        return <LoginPage onLoggedIn={refresh} />
    }

    // 后台不可达（404 / 500 / 超时）→ 退回演示模式，不挡路。
    //
    // GitHub Pages 上没有后台，这是常态。演示站不能卡在登录页 ——
    // 登录也必然失败。
    return <>{children}</>
}

export function App() {
    return (
        <AuthProvider>
            <AuthGate>
                <Routes>
                <Route element={<AppShell />}>
                    <Route index element={guarded(<OverviewPage />)} />
                    <Route path="assets" element={guarded(<AssetsPage />)} />
                    <Route path="fleets" element={guarded(<FleetsPage />)} />
                    <Route path="topologies" element={guarded(<TopologiesPage />)} />
                    <Route path="monitor" element={guarded(<MonitorPage />)} />
                    <Route path="events" element={guarded(<EventsPage />)} />
                    <Route path="siem" element={guarded(<SiemPage />)} />
                    <Route path="admin" element={guarded(<AdminPage />)} />
                        <Route path="*" element={<Navigate to="/" replace />} />
                </Route>
                </Routes>
            </AuthGate>
        </AuthProvider>
    )
}
