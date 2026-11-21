/**
 * 管理后台。
 *
 * 回答运维每天实际要问的问题：
 *
 *   - 现在什么状态？（总览：几个租户、几个用户、几个接入源、有没有哑掉的通道）
 *   - 谁在用这个系统？（用户：能建、能停用、能改角色）
 *   - 我们管着哪些客户？（租户：能建、能停）
 *   - 事件从哪来？哪个通道哑了？（接入源：last_seen_at 一眼看出死活）
 *   - 谁改了什么？（审计：每条管理动作都留痕）
 *
 * ## 权限
 *
 * 后台已经做了服务端校验（tenant_admin 只能管本租户、viewer 不能改）。
 * 前端也要挡一层 —— **但那只是省一次请求，不是安全边界**。
 * 服务端的校验才是边界。
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Plus, RefreshCw, Trash2 } from "lucide-react"
import { useState } from "react"

import {
    type AdminOverview,
    type AdminTenant,
    type AdminUser,
    type AuditEntry,
    type IntakeKind,
    type IntakeSource,
    api,
} from "@/api/client"

type Tab = "overview" | "users" | "tenants" | "intake" | "audit"

const TABS: { key: Tab; label: string }[] = [
    { key: "overview", label: "总览" },
    { key: "users", label: "用户" },
    { key: "tenants", label: "租户" },
    { key: "intake", label: "接入源" },
    { key: "audit", label: "审计" },
]

const ROLE_LABEL: Record<string, string> = {
    super_admin: "超级管理员",
    tenant_admin: "租户管理员",
    analyst: "分析员",
    viewer: "只读",
}

const KIND_LABEL: Record<IntakeKind, string> = {
    fortisiem: "FortiSIEM",
    syslog: "Syslog",
    webhook: "Webhook",
    agent: "采集器",
}

/** 时间显示：空值显示「—」，不要显示 "null"。 */
function when(value: string | null): string {
    if (!value) return "—"
    const d = new Date(value)
    if (Number.isNaN(d.getTime())) return "—"
    return d.toLocaleString("zh-CN", { hour12: false })
}

function errText(e: unknown): string {
    const err = e as { detail?: string; message?: string } | null
    return err?.detail ?? err?.message ?? "未知错误"
}

export function AdminPage() {
    const [tab, setTab] = useState<Tab>("overview")

    return (
        <div>
            <div className="page-head">
                <div>
                    <h2 style={{ margin: 0, fontSize: 16 }}>管理后台</h2>
                    <p className="subtle" style={{ margin: "3px 0 0" }}>
                        用户 · 租户 · 接入源 · 审计
                    </p>
                </div>
                <div className="page-tools">
                    <div className="page-tools" style={{ gap: 4 }}>
                        {TABS.map((t) => (
                            <button
                                key={t.key}
                                type="button"
                                className={tab === t.key ? "btn primary" : "btn"}
                                onClick={() => setTab(t.key)}
                            >
                                {t.label}
                            </button>
                        ))}
                    </div>
                </div>
            </div>

            {tab === "overview" && <OverviewTab />}
            {tab === "users" && <UsersTab />}
            {tab === "tenants" && <TenantsTab />}
            {tab === "intake" && <IntakeTab />}
            {tab === "audit" && <AuditTab />}
        </div>
    )
}

// ── 总览 ────────────────────────────────────────────────────────────────────
function OverviewTab() {
    const qc = useQueryClient()
    const overview = useQuery({
        queryKey: ["admin-overview"],
        queryFn: () => api.admin.overview(),
        refetchInterval: 30_000,
    })

    const refetch = useMutation({
        mutationFn: () => qc.invalidateQueries({ queryKey: ["admin-overview"] }),
    })

    if (overview.isPending) {
        return <div className="card" style={{ padding: 24, textAlign: "center" }}><p className="muted">正在读取…</p></div>
    }
    if (overview.isError) {
        return (
            <div className="card" style={{ padding: 24, borderColor: "var(--color-sev-critical)" }}>
                <p className="muted" style={{ color: "var(--color-sev-critical)" }}>
                    读取失败：{errText(overview.error)}
                </p>
            </div>
        )
    }

    const d = overview.data as AdminOverview
    const cards: { label: string; value: number; hint?: string; tone?: string }[] = [
        { label: "租户", value: d.tenants, hint: `${d.active_tenants} 个启用` },
        { label: "用户", value: d.users, hint: "启用中的账号" },
        { label: "资产", value: d.assets },
        { label: "拓扑", value: d.topologies },
        { label: "安全事件", value: d.incidents },
        { label: "接入源", value: d.intake_sources, hint: `${d.intake_active} 个启用` },
        { label: "审计条目", value: d.audit_entries },
    ]

    return (
        <div>
            <div className="page-tools" style={{ marginBottom: 12 }}>
                <button
                    type="button"
                    className="btn"
                    onClick={() => refetch.mutate()}
                    disabled={refetch.isPending}
                >
                    <RefreshCw size={14} />
                    刷新
                </button>
            </div>

            <div className="grid g-4">
                {cards.map((c) => (
                    <div className="card" key={c.label} style={{ padding: "12px 14px" }}>
                        <div className="subtle">{c.label}</div>
                        <div style={{ fontSize: 22, fontWeight: 700, marginTop: 2 }}>{c.value}</div>
                        {c.hint && <div className="subtle" style={{ fontSize: 11 }}>{c.hint}</div>}
                    </div>
                ))}
            </div>

            {/*
              「哑掉的通道」单独提示 —— 启用了但从来没收到过东西。
              这是最该被发现的问题，藏在数字里没人会注意。
            */}
            {d.intake_never_seen > 0 && (
                <div
                    className="card"
                    style={{
                        padding: 12,
                        marginTop: 12,
                        borderColor: "var(--color-sev-medium)",
                    }}
                >
                    <b style={{ color: "var(--color-sev-medium)" }}>
                        {d.intake_never_seen} 个接入源从未收到过事件
                    </b>
                    <div className="subtle" style={{ marginTop: 4 }}>
                        启用了但一条事件都没进来 —— 去「接入源」标签页检查配置。
                    </div>
                </div>
            )}
        </div>
    )
}

// ── 用户 ────────────────────────────────────────────────────────────────────
function UsersTab() {
    const qc = useQueryClient()
    const users = useQuery({ queryKey: ["admin-users"], queryFn: () => api.admin.users.list() })
    const [adding, setAdding] = useState(false)
    const [form, setForm] = useState({ username: "", password: "", role: "viewer", display_name: "" })
    const [formError, setFormError] = useState<string | null>(null)

    const invalidate = () => {
        void qc.invalidateQueries({ queryKey: ["admin-users"] })
        void qc.invalidateQueries({ queryKey: ["admin-overview"] })
        void qc.invalidateQueries({ queryKey: ["admin-audit"] })
    }

    const create = useMutation({
        mutationFn: () =>
            api.admin.users.create({
                username: form.username.trim(),
                password: form.password,
                role: form.role,
                display_name: form.display_name.trim() || undefined,
            }),
        onSuccess: () => {
            setAdding(false)
            setForm({ username: "", password: "", role: "viewer", display_name: "" })
            setFormError(null)
            invalidate()
        },
        onError: (e) => setFormError(errText(e)),
    })

    const update = useMutation({
        mutationFn: ({ id, body }: { id: number; body: { role?: string; is_active?: boolean } }) =>
            api.admin.users.update(id, body),
        onSuccess: invalidate,
    })

    const remove = useMutation({
        mutationFn: (id: number) => api.admin.users.remove(id),
        onSuccess: invalidate,
    })

    if (users.isPending) {
        return <div className="card" style={{ padding: 24, textAlign: "center" }}><p className="muted">正在读取…</p></div>
    }
    if (users.isError) {
        return (
            <div className="card" style={{ padding: 24, borderColor: "var(--color-sev-critical)" }}>
                <p className="muted" style={{ color: "var(--color-sev-critical)" }}>
                    读取失败：{errText(users.error)}
                </p>
            </div>
        )
    }

    const rows = (users.data ?? []) as AdminUser[]

    return (
        <div>
            <div className="page-tools" style={{ marginBottom: 12 }}>
                <button type="button" className="btn primary" onClick={() => setAdding((v) => !v)}>
                    <Plus size={14} />
                    新建用户
                </button>
            </div>

            {adding && (
                <div className="card" style={{ padding: 16, marginBottom: 12 }}>
                    <div className="grid g-4">
                        <div>
                            <label className="label" htmlFor="nu-username">用户名</label>
                            <input
                                id="nu-username"
                                className="input"
                                value={form.username}
                                onChange={(e) => setForm({ ...form, username: e.target.value })}
                            />
                        </div>
                        <div>
                            <label className="label" htmlFor="nu-display">显示名</label>
                            <input
                                id="nu-display"
                                className="input"
                                value={form.display_name}
                                onChange={(e) => setForm({ ...form, display_name: e.target.value })}
                            />
                        </div>
                        <div>
                            <label className="label" htmlFor="nu-role">角色</label>
                            <select
                                id="nu-role"
                                className="select"
                                value={form.role}
                                onChange={(e) => setForm({ ...form, role: e.target.value })}
                            >
                                {Object.entries(ROLE_LABEL).map(([k, v]) => (
                                    <option key={k} value={k}>{v}</option>
                                ))}
                            </select>
                        </div>
                        <div>
                            <label className="label" htmlFor="nu-password">
                                密码 <span className="req" />
                            </label>
                            <input
                                id="nu-password"
                                className="input"
                                type="password"
                                value={form.password}
                                onChange={(e) => setForm({ ...form, password: e.target.value })}
                            />
                        </div>
                    </div>
                    {formError && (
                        <div className="bdg err" style={{ display: "block", marginTop: 10 }} role="alert">
                            {formError}
                        </div>
                    )}
                    <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
                        <button
                            type="button"
                            className="btn primary"
                            onClick={() => create.mutate()}
                            disabled={create.isPending || !form.username.trim() || !form.password}
                        >
                            {create.isPending ? "创建中…" : "创建"}
                        </button>
                        <button type="button" className="btn" onClick={() => setAdding(false)}>
                            取消
                        </button>
                    </div>
                </div>
            )}

            <div className="card" style={{ padding: 0, overflow: "hidden" }}>
                <div className="tbl-wrap">
                    <table className="table">
                        <thead>
                            <tr>
                                <th>用户名</th>
                                <th>显示名</th>
                                <th>角色</th>
                                <th>状态</th>
                                <th>最后登录</th>
                                <th style={{ width: 200 }}>操作</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows.map((u) => (
                                <tr key={u.id}>
                                    <td className="mono">{u.username}</td>
                                    <td>{u.display_name ?? "—"}</td>
                                    <td>
                                        <select
                                            className="select"
                                            value={u.role}
                                            onChange={(e) =>
                                                update.mutate({ id: u.id, body: { role: e.target.value } })
                                            }
                                            aria-label={`${u.username} 的角色`}
                                        >
                                            {Object.entries(ROLE_LABEL).map(([k, v]) => (
                                                <option key={k} value={k}>{v}</option>
                                            ))}
                                        </select>
                                    </td>
                                    <td>
                                        {u.is_active ? (
                                            <span className="bdg ok">启用</span>
                                        ) : (
                                            <span className="bdg neutral">停用</span>
                                        )}
                                        {u.locked_until && new Date(u.locked_until) > new Date() && (
                                            <span className="bdg err" style={{ marginLeft: 4 }}>锁定</span>
                                        )}
                                    </td>
                                    <td className="subtle">{when(u.last_login_at)}</td>
                                    <td>
                                        <button
                                            type="button"
                                            className="btn"
                                            onClick={() =>
                                                update.mutate({ id: u.id, body: { is_active: !u.is_active } })
                                            }
                                        >
                                            {u.is_active ? "停用" : "启用"}
                                        </button>
                                        <button
                                            type="button"
                                            className="btn danger"
                                            style={{ marginLeft: 6 }}
                                            onClick={() => remove.mutate(u.id)}
                                            disabled={!u.is_active}
                                            title="停用账号（保留审计上下文）"
                                            aria-label={`停用用户 ${u.username}`}
                                        >
                                            <Trash2 size={13} />
                                        </button>
                                    </td>
                                </tr>
                            ))}
                            {rows.length === 0 && (
                                <tr>
                                    <td colSpan={6} className="muted" style={{ textAlign: "center", padding: 20 }}>
                                        还没有用户
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    )
}

// ── 租户 ────────────────────────────────────────────────────────────────────
function TenantsTab() {
    const qc = useQueryClient()
    const tenants = useQuery({ queryKey: ["admin-tenants"], queryFn: () => api.admin.tenants.list() })
    const [adding, setAdding] = useState(false)
    const [form, setForm] = useState({ slug: "", name: "", fortisiem_org: "" })
    const [formError, setFormError] = useState<string | null>(null)

    const invalidate = () => {
        void qc.invalidateQueries({ queryKey: ["admin-tenants"] })
        void qc.invalidateQueries({ queryKey: ["admin-overview"] })
        void qc.invalidateQueries({ queryKey: ["admin-audit"] })
    }

    const create = useMutation({
        mutationFn: () =>
            api.admin.tenants.create({
                slug: form.slug.trim(),
                name: form.name.trim(),
                fortisiem_org: form.fortisiem_org.trim() || undefined,
            }),
        onSuccess: () => {
            setAdding(false)
            setForm({ slug: "", name: "", fortisiem_org: "" })
            setFormError(null)
            invalidate()
        },
        onError: (e) => setFormError(errText(e)),
    })

    const update = useMutation({
        mutationFn: ({ id, body }: { id: string; body: { is_active?: boolean } }) =>
            api.admin.tenants.update(id, body),
        onSuccess: invalidate,
    })

    if (tenants.isPending) {
        return <div className="card" style={{ padding: 24, textAlign: "center" }}><p className="muted">正在读取…</p></div>
    }
    if (tenants.isError) {
        return (
            <div className="card" style={{ padding: 24, borderColor: "var(--color-sev-critical)" }}>
                <p className="muted" style={{ color: "var(--color-sev-critical)" }}>
                    读取失败：{errText(tenants.error)}
                </p>
            </div>
        )
    }

    const rows = (tenants.data ?? []) as AdminTenant[]

    return (
        <div>
            <div className="page-tools" style={{ marginBottom: 12 }}>
                <button type="button" className="btn primary" onClick={() => setAdding((v) => !v)}>
                    <Plus size={14} />
                    新建租户
                </button>
            </div>

            {adding && (
                <div className="card" style={{ padding: 16, marginBottom: 12 }}>
                    <div className="grid g-3">
                        <div>
                            <label className="label" htmlFor="nt-slug">标识 slug</label>
                            <input
                                id="nt-slug"
                                className="input"
                                value={form.slug}
                                onChange={(e) => setForm({ ...form, slug: e.target.value })}
                                placeholder="dongfang"
                            />
                        </div>
                        <div>
                            <label className="label" htmlFor="nt-name">名称</label>
                            <input
                                id="nt-name"
                                className="input"
                                value={form.name}
                                onChange={(e) => setForm({ ...form, name: e.target.value })}
                                placeholder="东方海运"
                            />
                        </div>
                        <div>
                            <label className="label" htmlFor="nt-org">FortiSIEM 组织</label>
                            <input
                                id="nt-org"
                                className="input"
                                value={form.fortisiem_org}
                                onChange={(e) => setForm({ ...form, fortisiem_org: e.target.value })}
                                placeholder="DONGFANG"
                            />
                        </div>
                    </div>
                    {formError && (
                        <div className="bdg err" style={{ display: "block", marginTop: 10 }} role="alert">
                            {formError}
                        </div>
                    )}
                    <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
                        <button
                            type="button"
                            className="btn primary"
                            onClick={() => create.mutate()}
                            disabled={create.isPending || !form.slug.trim() || !form.name.trim()}
                        >
                            {create.isPending ? "创建中…" : "创建"}
                        </button>
                        <button type="button" className="btn" onClick={() => setAdding(false)}>取消</button>
                    </div>
                </div>
            )}

            <div className="card" style={{ padding: 0, overflow: "hidden" }}>
                <div className="tbl-wrap">
                    <table className="table">
                        <thead>
                            <tr>
                                <th>名称</th>
                                <th>slug</th>
                                <th>FortiSIEM 组织</th>
                                <th>状态</th>
                                <th>创建时间</th>
                                <th style={{ width: 100 }}>操作</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows.map((t) => (
                                <tr key={t.id}>
                                    <td>{t.name}</td>
                                    <td className="mono">{t.slug}</td>
                                    <td className="mono">{t.fortisiem_org ?? "—"}</td>
                                    <td>
                                        {t.is_active ? (
                                            <span className="bdg ok">启用</span>
                                        ) : (
                                            <span className="bdg neutral">停用</span>
                                        )}
                                    </td>
                                    <td className="subtle">{when(t.created_at)}</td>
                                    <td>
                                        <button
                                            type="button"
                                            className="btn"
                                            onClick={() =>
                                                update.mutate({ id: t.id, body: { is_active: !t.is_active } })
                                            }
                                        >
                                            {t.is_active ? "停用" : "启用"}
                                        </button>
                                    </td>
                                </tr>
                            ))}
                            {rows.length === 0 && (
                                <tr>
                                    <td colSpan={6} className="muted" style={{ textAlign: "center", padding: 20 }}>
                                        没有可见的租户
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    )
}

// ── 接入源 ──────────────────────────────────────────────────────────────────
function IntakeTab() {
    const qc = useQueryClient()
    const sources = useQuery({
        queryKey: ["admin-intake"],
        queryFn: () => api.admin.intakeSources.list(),
        refetchInterval: 30_000,
    })
    const [adding, setAdding] = useState(false)
    const [form, setForm] = useState({ kind: "syslog" as IntakeKind, name: "", port: "" })
    const [formError, setFormError] = useState<string | null>(null)

    const invalidate = () => {
        void qc.invalidateQueries({ queryKey: ["admin-intake"] })
        void qc.invalidateQueries({ queryKey: ["admin-overview"] })
        void qc.invalidateQueries({ queryKey: ["admin-audit"] })
    }

    const create = useMutation({
        mutationFn: () =>
            api.admin.intakeSources.create({
                kind: form.kind,
                name: form.name.trim(),
                config: form.port ? { port: Number(form.port) } : {},
            }),
        onSuccess: () => {
            setAdding(false)
            setForm({ kind: "syslog", name: "", port: "" })
            setFormError(null)
            invalidate()
        },
        onError: (e) => setFormError(errText(e)),
    })

    const update = useMutation({
        mutationFn: ({ id, body }: { id: number; body: { enabled?: boolean } }) =>
            api.admin.intakeSources.update(id, body),
        onSuccess: invalidate,
    })

    const remove = useMutation({
        mutationFn: (id: number) => api.admin.intakeSources.remove(id),
        onSuccess: invalidate,
    })

    if (sources.isPending) {
        return <div className="card" style={{ padding: 24, textAlign: "center" }}><p className="muted">正在读取…</p></div>
    }
    if (sources.isError) {
        return (
            <div className="card" style={{ padding: 24, borderColor: "var(--color-sev-critical)" }}>
                <p className="muted" style={{ color: "var(--color-sev-critical)" }}>
                    读取失败：{errText(sources.error)}
                </p>
            </div>
        )
    }

    const rows = (sources.data ?? []) as IntakeSource[]
    const neverSeen = rows.filter((s) => s.enabled && !s.last_seen_at).length

    return (
        <div>
            <div className="page-tools" style={{ marginBottom: 12 }}>
                <button type="button" className="btn primary" onClick={() => setAdding((v) => !v)}>
                    <Plus size={14} />
                    登记接入源
                </button>
            </div>

            {neverSeen > 0 && (
                <div
                    className="card"
                    style={{ padding: 12, marginBottom: 12, borderColor: "var(--color-sev-medium)" }}
                >
                    <b style={{ color: "var(--color-sev-medium)" }}>
                        {neverSeen} 个启用的接入源从未收到过事件
                    </b>
                    <div className="subtle" style={{ marginTop: 4 }}>
                        通道配置了但没数据进来 —— 检查地址、端口、凭据。
                    </div>
                </div>
            )}

            {adding && (
                <div className="card" style={{ padding: 16, marginBottom: 12 }}>
                    <div className="grid g-3">
                        <div>
                            <label className="label" htmlFor="is-kind">通道类型</label>
                            <select
                                id="is-kind"
                                className="select"
                                value={form.kind}
                                onChange={(e) => setForm({ ...form, kind: e.target.value as IntakeKind })}
                            >
                                {Object.entries(KIND_LABEL).map(([k, v]) => (
                                    <option key={k} value={k}>{v}</option>
                                ))}
                            </select>
                        </div>
                        <div>
                            <label className="label" htmlFor="is-name">名称</label>
                            <input
                                id="is-name"
                                className="input"
                                value={form.name}
                                onChange={(e) => setForm({ ...form, name: e.target.value })}
                                placeholder="岸基 syslog 514"
                            />
                        </div>
                        <div>
                            <label className="label" htmlFor="is-port">端口（可选）</label>
                            <input
                                id="is-port"
                                className="input"
                                type="number"
                                value={form.port}
                                onChange={(e) => setForm({ ...form, port: e.target.value })}
                                placeholder="514"
                            />
                        </div>
                    </div>
                    {formError && (
                        <div className="bdg err" style={{ display: "block", marginTop: 10 }} role="alert">
                            {formError}
                        </div>
                    )}
                    <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
                        <button
                            type="button"
                            className="btn primary"
                            onClick={() => create.mutate()}
                            disabled={create.isPending || !form.name.trim()}
                        >
                            {create.isPending ? "登记中…" : "登记"}
                        </button>
                        <button type="button" className="btn" onClick={() => setAdding(false)}>取消</button>
                    </div>
                </div>
            )}

            <div className="card" style={{ padding: 0, overflow: "hidden" }}>
                <div className="tbl-wrap">
                    <table className="table">
                        <thead>
                            <tr>
                                <th>名称</th>
                                <th>通道</th>
                                <th>状态</th>
                                <th>上次收到</th>
                                <th>累计条数</th>
                                <th style={{ width: 140 }}>操作</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows.map((s) => (
                                <tr key={s.id}>
                                    <td>
                                        {s.name}
                                        {s.description && (
                                            <div className="subtle" style={{ fontSize: 11 }}>{s.description}</div>
                                        )}
                                    </td>
                                    <td><span className="bdg info">{KIND_LABEL[s.kind] ?? s.kind}</span></td>
                                    <td>
                                        {s.enabled ? (
                                            <span className="bdg ok">启用</span>
                                        ) : (
                                            <span className="bdg neutral">停用</span>
                                        )}
                                    </td>
                                    <td className="subtle">
                                        {s.last_seen_at ? (
                                            when(s.last_seen_at)
                                        ) : s.enabled ? (
                                            <span className="bdg warn">从未收到</span>
                                        ) : (
                                            "—"
                                        )}
                                    </td>
                                    <td className="mono">{s.events_received}</td>
                                    <td>
                                        <button
                                            type="button"
                                            className="btn"
                                            onClick={() =>
                                                update.mutate({ id: s.id, body: { enabled: !s.enabled } })
                                            }
                                        >
                                            {s.enabled ? "停用" : "启用"}
                                        </button>
                                        <button
                                            type="button"
                                            className="btn danger"
                                            style={{ marginLeft: 6 }}
                                            onClick={() => remove.mutate(s.id)}
                                            title="删除接入源"
                                            aria-label={`删除接入源 ${s.name}`}
                                        >
                                            <Trash2 size={13} />
                                        </button>
                                    </td>
                                </tr>
                            ))}
                            {rows.length === 0 && (
                                <tr>
                                    <td colSpan={6} className="muted" style={{ textAlign: "center", padding: 20 }}>
                                        还没有登记接入源
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    )
}

// ── 审计 ────────────────────────────────────────────────────────────────────
function AuditTab() {
    const [action, setAction] = useState("")
    const audit = useQuery({
        queryKey: ["admin-audit", action],
        queryFn: () => api.admin.audit({ action: action || undefined, limit: 200 }),
    })

    if (audit.isPending) {
        return <div className="card" style={{ padding: 24, textAlign: "center" }}><p className="muted">正在读取…</p></div>
    }
    if (audit.isError) {
        return (
            <div className="card" style={{ padding: 24, borderColor: "var(--color-sev-critical)" }}>
                <p className="muted" style={{ color: "var(--color-sev-critical)" }}>
                    读取失败：{errText(audit.error)}
                </p>
            </div>
        )
    }

    const rows = (audit.data ?? []) as AuditEntry[]

    return (
        <div>
            <div className="page-tools" style={{ marginBottom: 12 }}>
                <select
                    className="select"
                    value={action}
                    onChange={(e) => setAction(e.target.value)}
                    aria-label="按动作过滤"
                >
                    <option value="">全部动作</option>
                    <option value="auth.login">登录</option>
                    <option value="auth.login_failed">登录失败</option>
                    <option value="user.create">建用户</option>
                    <option value="user.update">改用户</option>
                    <option value="tenant.update">改租户</option>
                    <option value="intake.create">建接入源</option>
                    <option value="intake.update">改接入源</option>
                </select>
            </div>

            <div className="card" style={{ padding: 0, overflow: "hidden" }}>
                <div className="tbl-wrap">
                    <table className="table">
                        <thead>
                            <tr>
                                <th>时间</th>
                                <th>操作人</th>
                                <th>动作</th>
                                <th>对象</th>
                                <th>详情</th>
                                <th>来源 IP</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows.map((e) => (
                                <tr key={e.id}>
                                    <td className="subtle">{when(e.created_at)}</td>
                                    <td className="mono">{e.username ?? "—"}</td>
                                    <td><span className="bdg neutral">{e.action}</span></td>
                                    <td className="subtle">
                                        {e.target_type ? `${e.target_type}#${e.target_id}` : "—"}
                                    </td>
                                    <td className="mono subtle wrap" style={{ fontSize: 11, maxWidth: 320 }}>
                                        {Object.keys(e.detail ?? {}).length > 0
                                            ? JSON.stringify(e.detail)
                                            : "—"}
                                    </td>
                                    <td className="mono subtle">{e.ip ?? "—"}</td>
                                </tr>
                            ))}
                            {rows.length === 0 && (
                                <tr>
                                    <td colSpan={6} className="muted" style={{ textAlign: "center", padding: 20 }}>
                                        没有审计记录
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    )
}
