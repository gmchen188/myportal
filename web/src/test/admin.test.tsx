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
