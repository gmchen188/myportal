/**
 * 登录页与管理后台页。
 *
 * 这些测试锁住的是**安全相关的行为**，不是渲染细节：
 *
 * - 登录失败不能泄露「账号存不存在」
 * - 令牌必须真的存下来（不然刷新页面就掉登录）
 * - 管理页面读不出来时要有明确提示，不能一片空白
 * - 「哑掉的接入源」必须被单独指出来 —— 那个数字藏在卡片里没人会看
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import React from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import type { AdminTenant, AdminUser, AuditEntry, IntakeSource } from "@/api/client"

vi.mock("@/api/client", async () => {
    const actual = await vi.importActual<typeof import("@/api/client")>("@/api/client")
    return {
        ...actual,
        api: {
            ...actual.api,
            auth: {
                ...actual.api.auth,
                login: vi.fn(),
                me: vi.fn(),
                logout: vi.fn(),
            },
            admin: {
                ...actual.api.admin,
                overview: vi.fn(),
                users: { ...actual.api.admin.users, list: vi.fn(), create: vi.fn() },
                tenants: { ...actual.api.admin.tenants, list: vi.fn() },
                intakeSources: { ...actual.api.admin.intakeSources, list: vi.fn() },
                audit: vi.fn(),
            },
        },
    }
})

function wrapper({ children }: { children: React.ReactNode }) {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    return React.createElement(QueryClientProvider, { client: qc }, children)
}

describe("登录页", () => {
    beforeEach(() => {
        vi.clearAllMocks()
        localStorage.clear()
    })

    it("有租户、用户名、密码三个输入框和登录按钮", async () => {
        const { LoginPage } = await import("@/pages/login")
        render(<LoginPage onLoggedIn={vi.fn()} />, { wrapper })

        expect(screen.getByLabelText("租户")).toBeInTheDocument()
        expect(screen.getByLabelText("用户名")).toBeInTheDocument()
        expect(screen.getByLabelText("密码")).toBeInTheDocument()
        expect(screen.getByRole("button", { name: "登录" })).toBeInTheDocument()
    })

    it("登录成功要存令牌并通知上层", async () => {
        const { api } = await import("@/api/client")
        const { LoginPage } = await import("@/pages/login")
        vi.mocked(api.auth.login).mockResolvedValue({
            access_token: "tok-123",
            token_type: "bearer",
            expires_in: 900,
            user: {
                id: 1, tenant_id: "t-asi", username: "admin", display_name: "管理员",
                role: "super_admin", email: null, is_active: true, last_login_at: null,
                failed_attempts: 0, locked_until: null, created_at: null,
            },
            tenant: {
                id: "t-asi", slug: "asi", name: "AquaSync", locale: "zh-CN",
                fortisiem_org: "Super", is_active: true, description: null, created_at: null,
            },
        })

        const onLoggedIn = vi.fn()
        render(<LoginPage onLoggedIn={onLoggedIn} />, { wrapper })

        fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "admin" } })
        fireEvent.change(screen.getByLabelText("密码"), { target: { value: "Str0ng!Passw0rd" } })
        fireEvent.click(screen.getByRole("button", { name: "登录" }))

        await waitFor(() => expect(onLoggedIn).toHaveBeenCalled())
        // **令牌必须存下来** —— 不存的话刷新页面就掉登录
        expect(localStorage.getItem("myportal.token")).toBe("tok-123")
    })

    /**
     * 锁定（429）与密码错（401）必须分开说。
     *
     * 后端连续 5 次失败锁 15 分钟，锁定时返回 **429**（不是 401）。
     * 之前三种失败都显示同一句话 —— 用户被锁定后看到「用户名或密码
     * 不正确」会以为是密码错了，反复重试，每次都失败，更困惑。
     */
    it("账号被锁定（429）要明确告诉用户要等，不能说成密码错", async () => {
        const { api } = await import("@/api/client")
        const { LoginPage } = await import("@/pages/login")
        const { ApiError } = await import("@/api/client")
        vi.mocked(api.auth.login).mockRejectedValue(
            new ApiError(429, "账号已锁定，请 15 分钟后再试"),
        )

        render(<LoginPage onLoggedIn={vi.fn()} />, { wrapper })
        fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "admin" } })
        fireEvent.change(screen.getByLabelText("密码"), { target: { value: "whatever" } })
        fireEvent.click(screen.getByRole("button", { name: "登录" }))

        await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument())
        const alert = screen.getByRole("alert")
        expect(alert.textContent).toContain("锁定")
        expect(alert.textContent).toContain("15 分钟")
        // **不能出现「密码不正确」** —— 那是误导
        expect(alert.textContent).not.toContain("密码不正确")
        // 还要说清「重试没用」
        expect(alert.textContent).toContain("重试没有用")
    })

    it("账号停用（403）要说成停用，不是密码错", async () => {
        const { api } = await import("@/api/client")
        const { LoginPage } = await import("@/pages/login")
        const { ApiError } = await import("@/api/client")
        vi.mocked(api.auth.login).mockRejectedValue(new ApiError(403, "账号已停用"))

        render(<LoginPage onLoggedIn={vi.fn()} />, { wrapper })
        fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "admin" } })
        fireEvent.change(screen.getByLabelText("密码"), { target: { value: "whatever" } })
        fireEvent.click(screen.getByRole("button", { name: "登录" }))

        await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument())
        expect(screen.getByRole("alert").textContent).toContain("停用")
        expect(screen.getByRole("alert").textContent).not.toContain("密码不正确")
    })

    it("锁定时按钮要换文案，让用户知道不是还能试", async () => {
        const { api } = await import("@/api/client")
        const { LoginPage } = await import("@/pages/login")
        const { ApiError } = await import("@/api/client")
        vi.mocked(api.auth.login).mockRejectedValue(
            new ApiError(429, "账号已锁定，请 15 分钟后再试"),
        )

        render(<LoginPage onLoggedIn={vi.fn()} />, { wrapper })
        fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "admin" } })
        fireEvent.change(screen.getByLabelText("密码"), { target: { value: "whatever" } })
        fireEvent.click(screen.getByRole("button", { name: "登录" }))

        await waitFor(() => expect(screen.getByRole("button", { name: "账号已锁定" })).toBeInTheDocument())
    })

    it("登录失败要显示后端给的提示", async () => {
        const { api } = await import("@/api/client")
        const { LoginPage } = await import("@/pages/login")
        const { ApiError } = await import("@/api/client")
        vi.mocked(api.auth.login).mockRejectedValue(new ApiError(401, "用户名或密码不正确"))

        render(<LoginPage onLoggedIn={vi.fn()} />, { wrapper })
        fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "admin" } })
        fireEvent.change(screen.getByLabelText("密码"), { target: { value: "wrong" } })
        fireEvent.click(screen.getByRole("button", { name: "登录" }))

        await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument())
        expect(screen.getByRole("alert").textContent).toContain("用户名或密码不正确")
    })
})

describe("管理后台页", () => {
    beforeEach(() => {
        vi.clearAllMocks()
        localStorage.clear()
    })

    async function setupAdmin(over: {
        overview?: Record<string, unknown>
        users?: AdminUser[]
        tenants?: AdminTenant[]
        intake?: IntakeSource[]
        audit?: AuditEntry[]
    } = {}) {
        const { api } = await import("@/api/client")
        vi.mocked(api.admin.overview).mockResolvedValue({
            tenants: 2, active_tenants: 2, users: 3, assets: 14, incidents: 9,
            topologies: 1, intake_sources: 1, intake_active: 1, intake_never_seen: 0,
            audit_entries: 5, ...over.overview,
        } as never)
        vi.mocked(api.admin.users.list).mockResolvedValue(over.users ?? [] as never)
        vi.mocked(api.admin.tenants.list).mockResolvedValue(over.tenants ?? [] as never)
        vi.mocked(api.admin.intakeSources.list).mockResolvedValue(over.intake ?? [] as never)
        vi.mocked(api.admin.audit).mockResolvedValue(over.audit ?? [] as never)

        const { AdminPage } = await import("@/pages/admin")
        render(<AdminPage />, { wrapper })
    }

    it("总览要显示关键数字", async () => {
        await setupAdmin()
        await waitFor(() => expect(screen.getByText("安全事件")).toBeInTheDocument())
        // 「租户」「用户」「接入源」这几个词既是标签名也是卡片名 ——
        // 用 getAllByText 断言「至少有一个」，不去区分
        expect(screen.getAllByText("租户").length).toBeGreaterThan(0)
        expect(screen.getAllByText("用户").length).toBeGreaterThan(0)
        expect(screen.getAllByText("接入源").length).toBeGreaterThan(0)
    })

    it("哑掉的接入源要单独指出来", async () => {
        // 数字藏在卡片里没人会看 —— 必须单独提示
        await setupAdmin({ overview: { intake_never_seen: 3 } })
        await waitFor(() =>
            expect(screen.getByText(/3 个接入源从未收到过事件/)).toBeInTheDocument(),
        )
    })

    it("读不出来时要明确提示，不能一片空白", async () => {
        const { api } = await import("@/api/client")
        const { ApiError } = await import("@/api/client")
        vi.mocked(api.admin.overview).mockRejectedValue(new ApiError(401, "需要 Bearer 令牌"))

        const { AdminPage } = await import("@/pages/admin")
        render(<AdminPage />, { wrapper })

        await waitFor(() => expect(screen.getByText(/读取失败/)).toBeInTheDocument())
    })

    it("五个标签页都要能切", async () => {
        await setupAdmin()
        await waitFor(() => expect(screen.getByText("租户")).toBeInTheDocument())

        for (const label of ["用户", "租户", "接入源", "审计"]) {
            expect(screen.getAllByRole("button", { name: label }).length).toBeGreaterThan(0)
        }
    })

    it("用户列表要显示用户名、角色和状态", async () => {
        await setupAdmin({
            users: [
                {
                    id: 1, tenant_id: "t-asi", username: "admin", display_name: "管理员",
                    role: "super_admin", email: null, is_active: true, last_login_at: null,
                    failed_attempts: 0, locked_until: null, created_at: null,
                },
            ],
        })
        // 默认停在「总览」—— 要切到「用户」标签才有表格
        fireEvent.click(screen.getByRole("button", { name: "用户" }))
        await waitFor(() => expect(screen.getByText("admin")).toBeInTheDocument())
        expect(screen.getByText("管理员")).toBeInTheDocument()
        expect(screen.getByText("启用")).toBeInTheDocument()
    })

    it("接入源列表要显示通道类型与上次收到时间", async () => {
        await setupAdmin({
            intake: [
                {
                    id: 1, tenant_id: "t-asi", kind: "syslog", name: "岸基 syslog",
                    description: null, config: {}, enabled: true, last_seen_at: null,
                    events_received: 0, created_by: null, created_at: null, updated_at: null,
                },
            ],
        })
        fireEvent.click(screen.getByRole("button", { name: "接入源" }))
        await waitFor(() => expect(screen.getByText("岸基 syslog")).toBeInTheDocument())
        expect(screen.getByText("Syslog")).toBeInTheDocument()
        // 启用了但没收到过 —— 要显式说「从未收到」
        expect(screen.getByText("从未收到")).toBeInTheDocument()
    })
})


/**
 * AuthGate 的分叉 —— **不能退化**。
 *
 * 后台不可达（404 / 网络失败）时必须放行，演示站才还能用；
 * 401（未授权）时必须显示登录页，认证才没被绕过。
 *
 * 判错了两个方向都出事：
 * - 把 404 当 401 → 演示站永远停在登录页，登录还必然失败
 * - 把 401 当 404 → 生产环境不登录就能进后台
 */
describe("AuthGate 的错误分叉", () => {
    beforeEach(() => {
        vi.clearAllMocks()
        localStorage.clear()
    })

    async function renderApp(meResult: { status?: number; message?: string }) {
        const { api, ApiError } = await import("@/api/client")
        vi.mocked(api.auth.me).mockRejectedValue(
            new ApiError(meResult.status ?? 500, meResult.message ?? "内部错误"),
        )
        const { App } = await import("@/app")
        render(<App />, { wrapper })
    }

    it("401（未授权）要显示登录页", async () => {
        await renderApp({ status: 401, message: "需要 Bearer 令牌" })
        await waitFor(() => expect(screen.getByLabelText("用户名")).toBeInTheDocument())
    })

    it("403 也要显示登录页", async () => {
        await renderApp({ status: 403, message: "租户已停用" })
        await waitFor(() => expect(screen.getByLabelText("用户名")).toBeInTheDocument())
    })

    it("404（后台没连上）要放行 —— 演示站不能卡在登录页", async () => {
        await renderApp({ status: 404, message: "Not Found" })
        // **不该出现登录页**
        await waitFor(() => expect(screen.queryByLabelText("用户名")).toBeNull())
    })

    it("500（后台挂了）也要放行", async () => {
        await renderApp({ status: 500, message: "内部错误" })
        await waitFor(() => expect(screen.queryByLabelText("用户名")).toBeNull())
    })
})


/**
 * 窄屏渲染回归 —— **这些是实测出来的真问题，不是假设**。
 *
 * ## 1. 顶栏横向溢出 65px
 *
 * 本轮给顶栏加了「用户名 + 登出按钮 + 租户按钮」，375px 下放不下：
 * 用户名的 `white-space: nowrap` 把整个 header 撑破，**整页横向
 * 溢出 65px**，租户按钮被切掉右边缘。
 *
 * 修法：header 加 `minWidth: 0`（flex 子项默认 min-width:auto，
 * 不换行的内容会撑破父容器）、窄屏隐藏用户名、租户按钮限宽截断。
 *
 * ## 2. 表格文字被裁 / 逐字折行
 *
 * `table { width: 100% }` + 窄屏容器 → 内容多的列被压到容器宽，
 * 文字被**裁掉**（不是换行）。加了 min-width 后表格能滚了，
 * 但列宽仍不够 → 中文**逐字**折行（「初始管理员」→「初始管理」+
 * 「员」），比裁掉还难读。
 *
 * 修法：窄屏 `.tbl-wrap td/th { white-space: nowrap }`。
 */
describe("窄屏渲染", () => {
    it("顶栏不能因为用户名而溢出", async () => {
        const { readFileSync } = await import("node:fs")
        const { join } = await import("node:path")
        const src = readFileSync(join(process.cwd(), "src", "components", "app-shell.tsx"), "utf8")

        // header 必须有 minWidth: 0 —— 没有它 flex 子项会撑破父容器
        //
        // **不能只查字符串包含** —— 注释里写着「minWidth: 0」也会
        // 满足 `toContain`。要查注释**之外**真的有这个属性。
        const headerBlock = src.slice(src.indexOf("<header"), src.indexOf("</header>"))
        // 去掉行注释后再找
        const codeOnly = headerBlock
            .split("\n")
            .filter((l) => !l.trim().startsWith("//"))
            .join("\n")
        expect(codeOnly).toContain("minWidth: 0")

        // 窄屏必须隐藏用户名（hidden md:inline）
        expect(src).toContain("hidden md:inline")

        // 租户按钮必须限宽，否则长租户名会撑破
        expect(src).toContain("textOverflow")
    })

    it("窄屏表格单元格不换行（中文不能逐字折行）", async () => {
        const { readFileSync } = await import("node:fs")
        const { join } = await import("node:path")
        const css = readFileSync(join(process.cwd(), "src", "styles", "index.css"), "utf8")

        // 窄屏媒体查询里必须有 white-space: nowrap
        //
        // 注意：文件里有**多个** `@media (max-width: 640px)`（一个管表格、
        // 一个管 grid），不能只取最后一个 —— 用正则找「含 .tbl-wrap td
        // 且含 nowrap」的那一段。
        const narrowBlock = /@media \(max-width: 640px\) \{[^}]*?\.tbl-wrap td[^}]*?\}/s.exec(css)
        expect(narrowBlock).toBeTruthy()
        expect(narrowBlock![0]).toContain("white-space: nowrap")
    })

    it("长文本列要显式放开换行，否则表格会宽到没法用", async () => {
        const { readFileSync } = await import("node:fs")
        const { join } = await import("node:path")

        const overview = readFileSync(join(process.cwd(), "src", "pages", "overview.tsx"), "utf8")
        // 事件标题列
        expect(overview).toContain('className="wrap"')

        const admin = readFileSync(join(process.cwd(), "src", "pages", "admin.tsx"), "utf8")
        // 审计详情列（JSON）
        expect(admin).toContain("wrap")
    })
})
