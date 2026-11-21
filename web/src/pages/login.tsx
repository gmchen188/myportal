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

    const errorText = (() => {
        const e = login.error as { detail?: string; message?: string } | null
        if (!e) return null
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
                            className="bdg err"
                            style={{ display: "block", marginBottom: 12 }}
                            role="alert"
                        >
                            {errorText}
                        </div>
                    )}

                    <button
                        type="submit"
                        className="btn primary"
                        style={{ width: "100%", justifyContent: "center" }}
                        disabled={login.isPending || !username.trim() || !password}
                    >
                        <LogIn size={14} />
                        {login.isPending ? "登录中…" : "登录"}
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
