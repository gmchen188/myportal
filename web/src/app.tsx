import { Navigate, Route, Routes } from "react-router-dom"

import { AppShell } from "@/components/app-shell"
import { ErrorBoundary } from "@/components/error-boundary"
import { AssetsPage } from "@/pages/assets"
import { EventsPage } from "@/pages/events"
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

export function App() {
    return (
        <Routes>
            <Route element={<AppShell />}>
                <Route index element={guarded(<OverviewPage />)} />
                <Route path="assets" element={guarded(<AssetsPage />)} />
                <Route path="topologies" element={guarded(<TopologiesPage />)} />
                <Route path="monitor" element={guarded(<MonitorPage />)} />
                <Route path="events" element={guarded(<EventsPage />)} />
                <Route path="siem" element={guarded(<SiemPage />)} />
                <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
        </Routes>
    )
}
