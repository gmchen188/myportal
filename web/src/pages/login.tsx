/**
 * 登录页。
 *
 * ## 为什么必须有这个页面
 *
 * 后台的认证是「有锁没钥匙」—— 生产模式要求 Bearer 令牌，
 * 但之前没有任何办法拿到令牌。这个页面就是那把钥匙。
 *
 * ## 什么时候显示
 *
 * 应用启动时先问后台「我是谁」（`/api/auth/me`）：
 * - 401 → 没登录 → 显示登录页
 * - 200 → 已登录 → 进主界面
 *
 * **开发模式也走这条路** —— 后台的管理端点与 `/api/auth/me` 在任何
 * 模式下都要令牌（`principal_from_request_strict`）。所以登录页
 * 不是「生产才用」，是**一直都要用**。
 */

import { useMutation } from "@tanstack/react-query"
import { LogIn } from "lucide-react"
import { useState } from "react"

import { api, setTenant, setToken } from "@/api/client"

export function LoginPage({ onLoggedIn }: { onLoggedIn: () => void }) {
    const [username, setUsername] = useState("")
    const [password, setPassword] = useState("")
    const [tenant, setTenantSlug] = useState("asi")

    const login = useMutation({
        mutationFn: () => api.auth.login(username.trim(), password, tenant.trim()),
        onSuccess: (result) => {
            // **令牌必须存下来** —— 后台的 request() 会自动带上它
            setToken(result.access_token)
            // 租户也记住 —— 业务接口的 dev 头要用
            setTenant(result.tenant.slug)
            onLoggedIn()
        },
    })

    /**
     * 三种失败要分开说 —— 说错了用户会做错事。
     *
     * | 状态码 | 含义 | 用户该做什么 |
     * |---|---|---|
     * | 401 | 用户名或密码不对 | 换密码重试 |
     * | 429 | 连续失败被锁定 | **等 N 分钟**，再试也没用 |
     * | 403 | 账号被停用 | 找管理员 |
     *
     * 之前三种都显示成同一句话。用户被锁定后看到「用户名或密码不正确」
     * 会以为是密码错了，反复重试 —— 每次都失败，更困惑。
     */
    const errorKind = (() => {
        const e = login.error as { status?: number } | null
        if (!e) return null
        if (e.status === 429) return "locked" as const
        if (e.status === 403) return "disabled" as const
        if (e.status === 401) return "credentials" as const
        return "unknown" as const
    })()

    const errorText = (() => {
        const e = login.error as { detail?: string; message?: string } | null
        if (!e) return null
        if (errorKind === "locked") {
            // 后端 detail 已经带了剩余分钟数（「账号已锁定，请 15 分钟后再试」）
            return e.detail ?? "账号已锁定，请稍后再试"
        }
        if (errorKind === "disabled") {
            return e.detail ?? "账号已停用，请联系管理员"
        }
        return e.detail ?? e.message ?? "登录失败"
    })()

    return (
        <div
            style={{
                minHeight: "100vh",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                padding: 20,
                background: "var(--bg)",
            }}
        >
            <div className="card" style={{ width: "100%", maxWidth: 380, padding: 28 }}>
                <h2 style={{ margin: 0, fontSize: 18 }}>登录 myPortal</h2>
                <p className="subtle" style={{ margin: "6px 0 20px" }}>
                    船舶网络安全运营门户
                </p>

                <form
                    onSubmit={(e) => {
                        e.preventDefault()
                        login.mutate()
                    }}
                >
                    <div style={{ marginBottom: 12 }}>
                        <label className="label" htmlFor="login-tenant">
                            租户
                        </label>
                        <input
                            id="login-tenant"
                            className="input"
                            value={tenant}
                            onChange={(e) => setTenantSlug(e.target.value)}
                            placeholder="asi"
                            autoComplete="organization"
                        />
                    </div>

                    <div style={{ marginBottom: 12 }}>
                        <label className="label" htmlFor="login-username">
                            用户名
                        </label>
                        <input
                            id="login-username"
                            className="input"
                            value={username}
                            onChange={(e) => setUsername(e.target.value)}
                            autoComplete="username"
                            autoFocus
                        />
                    </div>

                    <div style={{ marginBottom: 16 }}>
                        <label className="label" htmlFor="login-password">
                            密码
                        </label>
                        <input
                            id="login-password"
                            className="input"
                            type="password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            autoComplete="current-password"
                        />
                    </div>

                    {login.isError && (
                        <div
                            // **锁定不是「密码错了」** —— 红色错误块会让人
                            // 以为是密码问题反复重试。锁定用警示色，
                            // 并且明确告诉用户要等。
                            className={errorKind === "locked" ? "bdg warn" : "bdg err"}
                            style={{ display: "block", marginBottom: 12 }}
                            role="alert"
                        >
                            {errorText}
                            {errorKind === "locked" && (
                                <div style={{ marginTop: 4, fontSize: 12, opacity: 0.85 }}>
                                    锁定期间重试没有用 —— 等提示里的分钟数到了再来。
                                </div>
                            )}
                        </div>
                    )}

                    <button
                        type="submit"
                        className="btn primary"
                        style={{ width: "100%", justifyContent: "center" }}
                        disabled={login.isPending || !username.trim() || !password}
                    >
                        <LogIn size={14} />
                        {login.isPending
                            ? "登录中…"
                            : errorKind === "locked"
                              ? "账号已锁定"
                              : "登录"}
                    </button>
                </form>

                <p className="subtle" style={{ marginTop: 18, marginBottom: 0, fontSize: 12 }}>
                    首次部署的初始管理员由后端的{" "}
                    <code className="mono">MP_ADMIN_PASSWORD</code> 环境变量创建，
                    登录后请立刻在后台修改。
                </p>
            </div>
        </div>
    )
}
