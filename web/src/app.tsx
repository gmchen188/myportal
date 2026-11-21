import { Navigate, Route, Routes } from "react-router-dom"

import { AppShell } from "@/components/app-shell"
import { AssetsPage } from "@/pages/assets"
import { EventsPage } from "@/pages/events"
import { MonitorPage } from "@/pages/monitor"
import { OverviewPage } from "@/pages/overview"
import { TopologiesPage } from "@/pages/topologies"

export function App() {
    return (
        <Routes>
            <Route element={<AppShell />}>
                <Route index element={<OverviewPage />} />
                <Route path="assets" element={<AssetsPage />} />
                <Route path="topologies" element={<TopologiesPage />} />
                <Route path="monitor" element={<MonitorPage />} />
                <Route path="events" element={<EventsPage />} />
                <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
        </Routes>
    )
}
