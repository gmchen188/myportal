/**
 * 应用外壳：侧栏 + 顶栏 + 内容区。
 *
 * 布局用 CSS Grid 而不是固定像素 —— 375px 窄屏下侧栏收成抽屉。
 */

import { NavLink, Outlet, useLocation } from "react-router-dom"
import {
    Boxes,
    ChevronDown,
    LayoutDashboard,
    Menu,
    MonitorSmartphone,
    Network,
    ShieldAlert,
    X,
} from "lucide-react"
import { useEffect, useState } from "react"

import { getTenant, setTenant } from "@/api/client"
import { useHealth } from "@/hooks/use-health"

const NAV = [
    { to: "/", label: "总览", icon: LayoutDashboard, end: true },
    { to: "/assets", label: "资产清单", icon: Boxes },
    { to: "/topologies", label: "网络拓扑", icon: Network },
    { to: "/monitor", label: "监控面板", icon: MonitorSmartphone },
    { to: "/events", label: "安全事件", icon: ShieldAlert },
]

const TENANTS = [
    { slug: "asi", name: "AquaSync Innovation" },
    { slug: "dongfang", name: "东方海运 / COSCO" },
]

export function AppShell() {
    const [drawer, setDrawer] = useState(false)
    const [tenant, setTenantState] = useState(getTenant())
    const [tenantOpen, setTenantOpen] = useState(false)
    const location = useLocation()
    const { data: health } = useHealth()

    // 路由变了就收起抽屉
    useEffect(() => {
        setDrawer(false)
    }, [location.pathname])

    function switchTenant(slug: string) {
        setTenant(slug)
        setTenantState(slug)
        setTenantOpen(false)
    }

    const siemOk = health?.siem?.connected ?? false
    const siemConfigured = health?.siem?.configured ?? false

    return (
        <div style={{ display: "flex", minHeight: "100vh" }}>
            <a href="#main" className="skip-link">
                跳到主内容
            </a>

            {/* 侧栏 */}
            <aside
                style={{
                    width: 216,
                    flexShrink: 0,
                    background: "var(--sidebar)",
                    color: "var(--sidebar-fg)",
                    display: "flex",
                    flexDirection: "column",
                    position: "fixed",
                    inset: "0 auto 0 0",
                    transform: drawer ? "translateX(0)" : "translateX(-100%)",
                    transition: "transform 0.2s",
                    zIndex: 40,
                }}
                className="md:static md:!transform-none"
                id="sidebar"
            >
                <div
                    style={{
                        padding: "16px 16px 12px",
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        borderBottom: "1px solid rgb(255 255 255 / 8%)",
                    }}
                >
                    <ShieldAlert size={18} color="#60a5fa" />
                    <b style={{ color: "#fff", fontSize: 15 }}>myPortal</b>
                    <button
                        type="button"
                        onClick={() => setDrawer(false)}
                        style={{ marginLeft: "auto", background: "none", border: 0, color: "#93a5c0", cursor: "pointer" }}
                        aria-label="关闭菜单"
                    >
                        <X size={16} />
                    </button>
                </div>

                <nav style={{ padding: "10px 8px", flex: 1 }}>
                    {NAV.map((n) => (
                        <NavLink
                            key={n.to}
                            to={n.to}
                            end={n.end}
                            style={({ isActive }) => ({
                                display: "flex",
                                alignItems: "center",
                                gap: 10,
                                padding: "9px 10px",
                                marginBottom: 2,
                                borderRadius: 8,
                                color: isActive ? "var(--sidebar-fg-active)" : "var(--sidebar-fg)",
                                background: isActive ? "var(--sidebar-active-bg)" : "transparent",
                                fontSize: 13,
                                fontWeight: isActive ? 600 : 500,
                                textDecoration: "none",
                            })}
                        >
                            <n.icon size={15} />
                            {n.label}
                        </NavLink>
                    ))}
                </nav>

                <div
                    style={{
                        padding: "10px 14px",
                        borderTop: "1px solid rgb(255 255 255 / 8%)",
                        fontSize: 11.5,
                        color: "#7183a0",
                    }}
                >
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        <span
                            style={{
                                width: 7,
                                height: 7,
                                borderRadius: "50%",
                                background: siemOk ? "#16a34a" : siemConfigured ? "#f59e0b" : "#94a3b8",
                            }}
                        />
                        FortiSIEM {siemOk ? "已连接" : siemConfigured ? "未连通" : "未配置"}
                    </div>
                </div>
            </aside>

            {drawer && (
                <div
                    onClick={() => setDrawer(false)}
                    style={{ position: "fixed", inset: 0, background: "rgb(0 0 0 / 40%)", zIndex: 30 }}
                />
            )}

            {/* 主区 */}
            <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
                <header
                    style={{
                        height: 52,
                        display: "flex",
                        alignItems: "center",
                        gap: 12,
                        padding: "0 16px",
                        background: "var(--surface)",
                        borderBottom: "1px solid var(--border)",
                        position: "sticky",
                        top: 0,
                        zIndex: 20,
                    }}
                >
                    <button
                        type="button"
                        className="btn md:!hidden"
                        style={{ height: 30, padding: "0 8px" }}
                        onClick={() => setDrawer(true)}
                        aria-label="打开菜单"
                    >
                        <Menu size={15} />
                    </button>

                    <div style={{ position: "relative", marginLeft: "auto" }}>
                        <button
                            type="button"
                            className="btn"
                            style={{ height: 30 }}
                            onClick={() => setTenantOpen((v) => !v)}
                            aria-expanded={tenantOpen}
                            aria-haspopup="listbox"
                        >
                            {TENANTS.find((t) => t.slug === tenant)?.name ?? tenant}
                            <ChevronDown size={14} />
                        </button>
                        {tenantOpen && (
                            <div
                                role="listbox"
                                style={{
                                    position: "absolute",
                                    right: 0,
                                    top: 36,
                                    minWidth: 190,
                                    background: "var(--surface)",
                                    border: "1px solid var(--border)",
                                    borderRadius: 8,
                                    boxShadow: "var(--shadow-lg)",
                                    overflow: "hidden",
                                    zIndex: 50,
                                }}
                            >
                                {TENANTS.map((t) => (
                                    <button
                                        key={t.slug}
                                        type="button"
                                        role="option"
                                        aria-selected={t.slug === tenant}
                                        onClick={() => switchTenant(t.slug)}
                                        style={{
                                            display: "block",
                                            width: "100%",
                                            textAlign: "left",
                                            padding: "9px 12px",
                                            background:
                                                t.slug === tenant ? "rgb(59 130 246 / 10%)" : "transparent",
                                            border: 0,
                                            color: "var(--fg)",
                                            fontSize: 13,
                                            cursor: "pointer",
                                        }}
                                    >
                                        {t.name}
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>
                </header>

                <main id="main" style={{ flex: 1, padding: 16, minWidth: 0 }}>
                    <Outlet />
                </main>
            </div>
        </div>
    )
}
