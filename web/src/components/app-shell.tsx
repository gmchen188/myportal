/**
 * 应用外壳：侧栏 + 顶栏 + 内容区。
 *
 * 布局用 CSS Grid 而不是固定像素 —— 375px 窄屏下侧栏收成抽屉。
 */

import {
    NavLink,
    Outlet,
    useLocation } from "react-router-dom"
import {
    Boxes,
    ChevronDown,
    LayoutDashboard,
    LogOut,
    Menu,
    MonitorSmartphone,
    Network,
    Radar,
    Settings2,
    ShieldAlert,
    X,
    Ship,
} from "lucide-react"
import { useEffect, useState } from "react"

import { getTenant, setTenant } from "@/api/client"
import { useAuth } from "@/components/auth-context"
import { useHealth } from "@/hooks/use-health"
import { useVersionCheck } from "@/hooks/use-version-check"

const NAV = [
    { to: "/", label: "总览", icon: LayoutDashboard, end: true },
    { to: "/assets", label: "资产清单", icon: Boxes },
    // 船队与船舶 —— 总览的船队/单船视图与资产清单的分组都靠它
    { to: "/fleets", label: "船队与船舶", icon: Ship },
    { to: "/topologies", label: "网络拓扑", icon: Network },
    { to: "/monitor", label: "监控面板", icon: MonitorSmartphone },
    { to: "/events", label: "安全事件", icon: ShieldAlert },
    { to: "/siem", label: "FortiSIEM", icon: Radar },
    // 管理后台 —— **只对能管的人显示**。
    // 服务端也会拦（viewer 拿到 403），但入口不该摆在那儿让人白点一次。
    { to: "/admin", label: "管理后台", icon: Settings2, adminOnly: true },
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

    // 当前是谁 —— **从 context 取，不自己发请求**。
    //
    // 之前这里自己 useQuery(["auth-me"])，与 AuthGate 构成两个
    // observer 共用一个 queryKey —— 后台不可达时形成死循环。
    // 详见 components/auth-context.tsx。
    const { me, canManage, logout } = useAuth()

    // **页面是不是旧代码** —— 自己发现自己过期，比让用户去猜该不该 F5 靠谱
    const version = useVersionCheck()

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
            {/*
              **桌面端用 md:!static 而不是内联 position:fixed** ——
              内联样式的优先级高于 Tailwind class，原来写的是
              className="md:static" + style={{position:"fixed"}}，结果
              class 根本没生效：1440px 下侧栏仍是 fixed，position:fixed 的
              aside 会盖在主区上（实测 main left=0 / width=1440），
              表格左侧「严重度」「设备」两列被压在侧栏下面看不见。

              所以桌面端的 position 交给 class（md:!static 带 !important，
              能压过内联），内联只保留移动端需要的 fixed/inset/transform。
              md:!transform-none 同理 —— 桌面端不要位移。
            */}
            <aside
                style={{
                    width: 216,
                    flexShrink: 0,
                    background: "var(--sidebar)",
                    color: "var(--sidebar-fg)",
                    display: "flex",
                    flexDirection: "column",
                    // 移动端：抽屉，固定在左侧
                    position: "fixed",
                    inset: "0 auto 0 0",
                    transform: drawer ? "translateX(0)" : "translateX(-100%)",
                    transition: "transform 0.2s",
                    zIndex: 40,
                }}
                className="md:!static md:!transform-none"
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
                    {NAV.filter((n) => !("adminOnly" in n) || !n.adminOnly || canManage).map((n) => (
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
                    {/* 版本号 —— **让人一眼看出自己跑的是新代码还是旧代码**。
                        同一个 bug 修了两次、用户报了两次一模一样的报错，
                        就是因为没人能看出那个页面是旧的。 */}
                    {version.mine && (
                        <div
                            style={{ marginTop: 6, fontFamily: "ui-monospace, monospace", fontSize: 10.5 }}
                            title={`构建于 ${version.mine.builtAt}`}
                        >
                            版本 {version.mine.rev || version.mine.builtAt.slice(0, 10)}
                        </div>
                    )}
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
                        // **minWidth: 0** —— flex 子项默认 min-width:auto，
                        // 内容不换行就会把父容器撑破。375px 下顶栏有
                        // 菜单按钮 + 用户名 + 登出 + 租户按钮，不加这个
                        // 整页横向溢出 65px。
                        minWidth: 0,
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

                    {/*
                      当前用户 + 登出。
                      **登录了却不知道是谁、也没法退出** —— 那是半个登录系统。
                    */}
                    {me && (
                        <div
                            style={{
                                display: "flex",
                                alignItems: "center",
                                gap: 8,
                                // 可收缩 —— 否则长用户名撑破顶栏
                                minWidth: 0,
                            }}
                        >
                            {/*
                              窄屏只显示用户名，租户名收进 title ——
                              375px 放不下「初始管理员 · AquaSync Innovation」
                              加登出按钮加租户按钮。
                            */}
                            <span
                                className="subtle hidden md:inline"
                                style={{
                                    fontSize: 12,
                                    whiteSpace: "nowrap",
                                    overflow: "hidden",
                                    textOverflow: "ellipsis",
                                    maxWidth: 220,
                                }}
                                title={`${me.user?.display_name || me.user?.username || me.user_id} · ${me.tenant?.name ?? me.tenant_slug}（角色：${me.role}）`}
                            >
                                {me.user?.display_name || me.user?.username || me.user_id}
                                {/* 分隔符 —— 「初始管理员AquaSync Innovation」连成一片读不出边界 */}
                                <span className="muted" style={{ marginLeft: 6 }}>
                                    · {me.tenant?.name ?? me.tenant_slug}
                                </span>
                            </span>
                            {/*
                              窄屏只留登出图标，但**必须有可访问名** ——
                              只剩图标时 aria-label 是唯一的可访问标识。
                            */}
                            <button
                                type="button"
                                className="btn"
                                style={{ height: 30, flexShrink: 0 }}
                                onClick={() => void logout()}
                                title={`退出登录（${me.user?.display_name || me.user?.username || me.user_id}）`}
                                aria-label="退出登录"
                            >
                                <LogOut size={14} />
                            </button>
                        </div>
                    )}

                    <div
                        style={{
                            position: "relative",
                            marginLeft: me ? 0 : "auto",
                            // 可收缩
                            minWidth: 0,
                        }}
                    >
                        <button
                            type="button"
                            className="btn"
                            style={{
                                height: 30,
                                // 文字过长时截断而不是撑破顶栏
                                maxWidth: 160,
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                                whiteSpace: "nowrap",
                                flexShrink: 0,
                            }}
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

                {version.stale && (
                    <div
                        role="status"
                        style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 10,
                            padding: "8px 14px",
                            background: "#fef3c7",
                            borderBottom: "1px solid #fcd34d",
                            color: "#78350f",
                            fontSize: 13,
                        }}
                    >
                        <span>
                            页面已更新（{version.current?.rev || "新版本"}）—— 刷新后生效
                        </span>
                        <button className="btn" style={{ height: 24 }} onClick={version.reload}>
                            立即刷新
                        </button>
                        <button
                            className="btn"
                            style={{ height: 24 }}
                            onClick={version.dismiss}
                            title="这次先不提示"
                        >
                            稍后
                        </button>
                    </div>
                )}
                <main id="main" style={{ flex: 1, padding: 16, minWidth: 0 }}>
                    <Outlet />
                </main>
            </div>
        </div>
    )
}
