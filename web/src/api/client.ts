/**
 * 后台 API 客户端。
 *
 * ## 为什么用相对路径
 *
 * 前端代码里一律用 `/api/xxx`，不用绝对 URL。开发时 vite 把 `/api` 代理到
 * `http://127.0.0.1:9102`（见 vite.config.ts），生产时 myPortal 与后台同源
 * 部署 —— 两种情况下代码一行都不用改。
 *
 * ## 租户怎么带
 *
 * 开发模式用 `X-Dev-Tenant` 头指定租户（后台 auth.py 在非生产环境允许）。
 * 生产模式用 Bearer token —— **作用域来自凭据，不来自参数**：token 里是哪个
 * 租户就只能读哪个租户，前端传别人的 tenant_id 也没用。
 */

const API_BASE = import.meta.env.VITE_API_BASE ?? ""

export class ApiError extends Error {
    readonly status: number
    readonly detail: string

    constructor(status: number, detail: string) {
        super(`[${status}] ${detail}`)
        this.status = status
        this.detail = detail
        this.name = "ApiError"
    }
}

/** 当前租户。存 localStorage —— 刷新后保持。 */
const TENANT_KEY = "myportal.tenant"

export function getTenant(): string {
    if (typeof localStorage === "undefined") return "asi"
    return localStorage.getItem(TENANT_KEY) ?? "asi"
}

export function setTenant(slug: string): void {
    if (typeof localStorage === "undefined") return
    localStorage.setItem(TENANT_KEY, slug)
}

/** access token。生产模式从登录流程拿；开发模式为空。 */
const TOKEN_KEY = "myportal.token"

export function getToken(): string | null {
    if (typeof localStorage === "undefined") return null
    return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null): void {
    if (typeof localStorage === "undefined") return
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
}

interface RequestOptions {
    method?: string
    body?: unknown
    /** 覆盖租户（导入预览时要用发起导入的租户） */
    tenant?: string
    signal?: AbortSignal
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json" }
    const tenant = opts.tenant ?? getTenant()
    headers["X-Dev-Tenant"] = tenant

    const token = getToken()
    if (token) headers.Authorization = `Bearer ${token}`

    let body: BodyInit | undefined
    if (opts.body !== undefined) {
        headers["Content-Type"] = "application/json"
        body = JSON.stringify(opts.body)
    }

    const res = await fetch(`${API_BASE}${path}`, {
        method: opts.method ?? "GET",
        headers,
        body,
        signal: opts.signal,
    })

    const text = await res.text()
    let payload: unknown = null
    if (text) {
        try {
            payload = JSON.parse(text)
        } catch {
            payload = text
        }
    }

    if (!res.ok) {
        const detail =
            payload && typeof payload === "object" && "error" in payload
                ? String((payload as { error: unknown }).error)
                : `HTTP ${res.status}`
        throw new ApiError(res.status, detail)
    }
    return payload as T
}

// ── 类型 ────────────────────────────────────────────────────────────────────

export type Severity = "critical" | "high" | "medium" | "low" | "informational" | "normal" | "unknown"

export interface Asset {
    id: number
    natural_id: string | null
    name: string
    type: string
    zone: string | null
    ip: string | null
    vendor: string | null
    model: string | null
    serial: string | null
    owner: string | null
    cbs_class: string | null
    status: string | null
    source: string
    needs_review: boolean
    notes: string | null
    created_at: string | null
    updated_at: string | null
}

export interface AssetFieldDef {
    key: string
    label: string
    required: boolean
    synonyms: string[]
}

export interface AssetSchema {
    fields: AssetFieldDef[]
    zones: string[]
}

export interface ImportIssue {
    level: "err" | "warn" | "ok"
    message: string
    row: number | null
    field: string | null
}

export interface ImportRow {
    values: Record<string, string>
    row_no: number
    issues: ImportIssue[]
    status: "ready" | "skip" | "needs_fill"
    reason: string | null
}

export interface ImportPreview {
    filename?: string
    headers: string[]
    mapping: Array<{ header: string; field: string | null; score: number }>
    rows: ImportRow[]
    issues: ImportIssue[]
    stats: { total: number; ready: number; skip: number; needs_fill: number }
}

export interface CommitResult {
    created: number
    skipped: number
    failed: number
    created_items: Array<{ row: number | null; name: string }>
    skipped_items: Array<{ row: number | null; reason: string }>
    failed_items: Array<{ row: number | null; reason: string }>
}

export interface Topology {
    id: number
    name: string
    description: string | null
    node_bindings: Record<string, unknown>
    origin: string
    source_image: string | null
    node_count: number
    created_at: string | null
    updated_at: string | null
    xml?: string
}

export interface GraphNode {
    id: string
    label: string
    zone: string | null
    zone_key: string | null
    x: number
    y: number
    w: number
    h: number
    style_names: string[]
}

export interface GraphZone {
    id: string
    label: string
    title: string | null
    subtitle: string | null
    x: number
    y: number
    w: number
    h: number
}

export interface GraphLink {
    id: string
    source: string | null
    target: string | null
    dashed: boolean
    color: string
}

export interface TopologyGraph {
    nodes: GraphNode[]
    zones: GraphZone[]
    links: GraphLink[]
    error: string | null
    topology?: Topology
}

export interface MonitorNode {
    node_id: string
    label: string
    zone: string | null
    zone_key: string | null
    x: number
    y: number
    w: number
    h: number
    natural_id: string | null
    ip: string | null
    channel: string
    enabled: boolean
    severity: Severity
    color: string
    active_incidents: number
    last_event_at: string | null
    top_title: string | null
}

export interface MonitorPanel {
    topology: Topology
    nodes: MonitorNode[]
    zones: GraphZone[]
    links: GraphLink[]
    counts: Record<string, number>
    severity_colors: Record<string, string>
    total_incidents: number
    parse_error: string | null
}

export interface Incident {
    id: number
    external_id: string | null
    title: string
    severity: Severity
    score: number | null
    source: string
    device_natural_id: string | null
    device_ip: string | null
    device_name: string | null
    src_ip: string | null
    dest_ip: string | null
    user: string | null
    occurred_at: string | null
}

export interface ModelOption {
    id: string
    name: string
    images: boolean
    image_capable: boolean
    image_note: string
    provider: string
}

export interface SiemStatus {
    configured: boolean
    connected: boolean
    org: string | null
    error: string | null
    devices: Array<{
        name: string
        natural_id: string
        access_ip: string
        vendor: string | null
        model: string | null
    }>
}

// ── 接口 ────────────────────────────────────────────────────────────────────

export const api = {
    health: () => request<{ status: string; siem: { configured: boolean; connected: boolean; error: string | null } }>("/health"),

    // 资产
    assets: {
        list: (params: { q?: string; zone?: string; needs_review?: boolean; limit?: number; offset?: number } = {}) => {
            const qs = new URLSearchParams()
            for (const [k, v] of Object.entries(params)) {
                if (v !== undefined && v !== null && v !== "") qs.set(k, String(v))
            }
            const s = qs.toString()
            return request<{ items: Asset[]; total: number; offset: number; limit: number }>(
                `/api/assets${s ? `?${s}` : ""}`,
            )
        },
        schema: () => request<AssetSchema>("/api/assets/schema"),
        create: (body: Partial<Asset> & { name: string; type: string }) =>
            request<Asset>("/api/assets", { method: "POST", body }),
        patch: (id: number, body: Partial<Asset>) =>
            request<Asset>(`/api/assets/${id}`, { method: "PATCH", body }),
        remove: (id: number) => request<{ deleted: number }>(`/api/assets/${id}`, { method: "DELETE" }),

        /** 上传文件做导入预览。不写库 —— 用户确认后再 commit。 */
        importFile: async (file: File, tenant?: string): Promise<ImportPreview> => {
            const fd = new FormData()
            fd.append("file", file)
            const headers: Record<string, string> = { "X-Dev-Tenant": tenant ?? getTenant() }
            const token = getToken()
            if (token) headers.Authorization = `Bearer ${token}`
            const res = await fetch(`${API_BASE}/api/assets/import/file`, {
                method: "POST",
                headers,
                body: fd,
            })
            const text = await res.text()
            if (!res.ok) {
                let detail = `HTTP ${res.status}`
                try {
                    const j = JSON.parse(text)
                    detail = j.error ?? detail
                } catch {
                    /* 保持原样 */
                }
                throw new ApiError(res.status, detail)
            }
            return JSON.parse(text) as ImportPreview
        },

        /** 从拓扑图节点生成初步资产行。 */
        importFromTopology: (nodes: Array<{ label: string; zone?: string | null; ip?: string | null }>) =>
            request<ImportPreview>("/api/assets/import/topology", { method: "POST", body: { nodes } }),

        /** 落库。幂等 —— 重复提交同一批会全部跳过。 */
        commit: (rows: ImportRow[], source = "import") =>
            request<CommitResult>("/api/assets/commit", { method: "POST", body: { rows, source } }),
    },

    // 拓扑
    topologies: {
        list: () => request<{ items: Topology[] }>("/api/topologies"),
        get: (id: number) => request<Topology>(`/api/topologies/${id}`),
        save: (body: { name: string; description?: string; xml: string; origin?: string; node_bindings?: Record<string, unknown> }) =>
            request<Topology>("/api/topologies", { method: "POST", body }),
        remove: (id: number) => request<{ deleted: number }>(`/api/topologies/${id}`, { method: "DELETE" }),
        graph: (id: number) => request<TopologyGraph>(`/api/topologies/${id}/graph`),
        monitors: (id: number) =>
            request<{ items: Array<{ node_id: string; node_label: string | null; natural_id: string | null; ip: string | null; channel: string; enabled: boolean }> }>(
                `/api/topologies/${id}/monitors`,
            ),
        bindMonitor: (
            id: number,
            body: { node_id: string; node_label?: string; natural_id?: string; ip?: string; channel?: string; enabled?: boolean },
        ) => request<unknown>(`/api/topologies/${id}/monitors`, { method: "POST", body }),
    },

    // 监控
    monitor: {
        panel: (topologyId: number) => request<MonitorPanel>(`/api/monitor/topologies/${topologyId}/panel`),
        events: (params: { severity?: string; device_natural_id?: string; source?: string; limit?: number } = {}) => {
            const qs = new URLSearchParams()
            for (const [k, v] of Object.entries(params)) {
                if (v) qs.set(k, String(v))
            }
            const s = qs.toString()
            return request<{ items: Incident[]; count: number }>(`/api/events${s ? `?${s}` : ""}`)
        },
    },

    // 模型选择器（图生图）
    models: {
        imageCapable: () =>
            request<{ models: ModelOption[]; source: string; default: string | null; count_image_capable: number }>(
                "/api/models/image-capable",
            ),
        imageCheck: (modelId: string) =>
            request<{ model: string; can_handle_image: boolean; reason: string }>(
                `/api/models/${encodeURIComponent(modelId)}/image-check`,
            ),
    },

    siem: {
        status: () => request<SiemStatus>("/api/siem/status"),
    },
}
