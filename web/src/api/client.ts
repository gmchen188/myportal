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
    /** 后端附带的定位信息（stage / probes）—— 没有时是 undefined */
    readonly meta?: ErrorMeta

    constructor(status: number, detail: string, meta?: ErrorMeta) {
        super(`[${status}] ${detail}`)
        this.status = status
        this.detail = detail
        this.name = "ApiError"
        this.meta = meta
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
        throw new ApiError(
            res.status,
            extractDetail(payload, res.status),
            extractErrorMeta(payload),
        )
    }
    return payload as T
}

/**
 * 后端错误里附带的定位信息。
 *
 * siem 的 502 会带上 `stage`（卡在哪一段）与 `probes`（分段实测结果）——
 * 那是运维定位问题的关键，不能只剩一句「HTTP 502」。
 */
export interface ErrorMeta {
    /** 卡在哪一段：tcp / tls / auth / api */
    stage?: string
    /** 四段探测的实测结果 */
    probes?: Record<string, { ok: boolean; detail?: string }>
}

/**
 * 从错误响应里取出**人话**。
 *
 * 后台有两种错误形状：
 *   - FastAPI 的 `{"detail": "资产名称不能为空"}`
 *   - 自定义的 `{"error": "拉取事件失败", ...}`
 *
 * siem 的 502 还会在 detail 里带上 `stage`（卡在哪一段）与 `probes`
 * （分段实测结果）—— 那是运维定位问题的关键，不能只剩一句「HTTP 502」。
 */
export function extractDetail(payload: unknown, status: number): string {
    if (payload && typeof payload === "object") {
        const obj = payload as Record<string, unknown>
        const direct = obj.error
        if (typeof direct === "string" && direct) return direct
        if (direct !== undefined && direct !== null && typeof direct !== "object") {
            return String(direct)
        }

        const detail = obj.detail
        if (typeof detail === "string" && detail) return detail
        if (detail && typeof detail === "object") {
            const inner = detail as Record<string, unknown>
            const msg =
                typeof inner.error === "string" && inner.error
                    ? inner.error
                    : typeof inner.detail === "string" && inner.detail
                      ? inner.detail
                      : null
            const stage = typeof inner.stage === "string" && inner.stage ? inner.stage : null
            if (msg && stage) return `${msg}（卡在 ${stageLabel(stage)} 这一段）`
            if (msg) return msg
            if (stage) return `请求失败（卡在 ${stageLabel(stage)} 这一段）`
        }
    }
    return `HTTP ${status}`
}

/**
 * 取出错误里附带的 stage / probes。
 *
 * 两种形状都要看：FastAPI 把自定义 dict 包在 `detail` 里
 * （`{"detail": {"error": ..., "stage": ...}}`），而我们自己的
 * `HTTPException(502, {...})` 也走同一条路。
 */
export function extractErrorMeta(payload: unknown): ErrorMeta | undefined {
    if (!payload || typeof payload !== "object") return undefined
    const obj = payload as Record<string, unknown>
    const sources: Record<string, unknown>[] = [obj]
    const d = obj.detail
    if (d && typeof d === "object") sources.push(d as Record<string, unknown>)

    for (const src of sources) {
        const stage = typeof src.stage === "string" && src.stage ? src.stage : undefined
        const probes =
            src.probes && typeof src.probes === "object"
                ? (src.probes as Record<string, { ok: boolean; detail?: string }>)
                : undefined
        if (stage || probes) return { stage, probes }
    }
    return undefined
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

/** 可导入为拓扑节点的资产 —— 还没绑到这张图上的。 */
export interface ImportableAsset {
    id: number
    natural_id: string | null
    name: string | null
    type: string | null
    ip: string | null
    vendor: string | null
    model: string | null
    zone: string | null
    status: string | null
    source: string | null
    /** 图里已经有同名的节点 —— 导入会复用它，不新画 */
    already_in_graph: boolean
    /** 已经绑到别的拓扑图上了 */
    bound_elsewhere: boolean
}

/** 导入的结果。skipped 说明为什么没导。 */
export interface ImportAssetsResult {
    added: number
    nodes: Array<{ node_id: string; label: string; natural_id: string; ip: string | null }>
    skipped: Array<{ asset_id: number; natural_id: string; name: string | null; reason: string }>
    bound_existing: number
    monitors: number
    warnings: string[]
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

/** FortiSIEM 连接诊断停在哪一段。 */
export type SiemStage = "tcp" | "tls" | "auth" | "api" | "ok"

/**
 * 四段的中文标签。
 *
 * 放在这里而不是组件里 —— 后台的 stage 值是英文契约值，
 * 但**用户看到的应该是中文**。错误文案（client.ts 的 extractDetail）
 * 和诊断面板都要用同一份，避免两处各写一个。
 */
export const STAGE_LABEL: Record<Exclude<SiemStage, "ok">, string> = {
    tcp: "TCP 连接",
    tls: "TLS 握手",
    auth: "认证取 Token",
    api: "读取设备",
}

/** 未知 stage 的兜底 —— 直接显示原值，别吞掉信息。 */
export function stageLabel(stage: string): string {
    return STAGE_LABEL[stage as Exclude<SiemStage, "ok">] ?? stage
}

/** 单段探测的结果。 */
export interface SiemProbe {
    ok: boolean
    detail: string
}

/** 四段探测 —— 键就是 stage 的取值。 */
export type SiemProbes = Partial<Record<Exclude<SiemStage, "ok">, SiemProbe>>

export interface SiemDevice {
    name: string
    natural_id: string
    access_ip: string
    sn: string
    org: string | null
    org_id: string | null
    vendor: string | null
    model: string | null
    version: string | null
}

export interface SiemStatus {
    configured: boolean
    connected: boolean
    org: string | null
    /** 连接失败的原因 —— 为空表示连接没问题 */
    error: string | null
    /**
     * 设备清单拉取失败的原因。
     *
     * 与 `error` 分开：连接可能是通的（四段全绿），只是拉设备那一步
     * 挂了。混在一起前端会同时显示「四段全通」和红色「连接失败」，
     * 自相矛盾，还会让运维去查根本没问题的那一段。
     */
    devices_error?: string | null
    /** 卡在哪一段。`"ok"` 表示四段全通。 */
    stage: SiemStage | null
    /** 各段的实测结果。缺哪段就是没走到哪段。 */
    probes: SiemProbes
    devices: SiemDevice[]
}

/** 同步的计数。事件与设备各一份。 */
export interface SiemSyncCounts {
    fetched?: number
    total?: number
    created: number
    updated: number
    skipped: number
}

export interface SiemSyncResult {
    org: string
    window_minutes: number
    events: SiemSyncCounts
    devices: SiemSyncCounts
    synced_at: string
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

        /**
         * 可导入为拓扑节点的资产 —— 还没绑到这张图上的。
         *
         * 「已绑到本拓扑」的会被排除 —— 重复导入不产生重复节点。
         */
        importableAssets: (id: number) =>
            request<{ items: ImportableAsset[] }>(`/api/topologies/${id}/importable-assets`),

        /**
         * 把资产导入成拓扑节点，并建立 device_monitors 绑定。
         *
         * 绑定建好之后，SIEM 的真实事件才能点亮对应节点的色 ——
         * 没有绑定，事件收进来了也看不到。
         */
        importAssets: (
            id: number,
            body: { asset_ids: number[]; zone?: string; link_from_node_id?: string },
        ) =>
            request<ImportAssetsResult>(`/api/topologies/${id}/import-assets`, {
                method: "POST",
                body,
            }),
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
        /**
         * 连接状态与四段诊断。
         *
         * `refresh=true` 绕过后台的探测缓存 —— 「重新检测」按钮要用它，
         * 否则用户点了看到的是 10 秒前的旧结果。
         */
        status: (params: { refresh?: boolean } = {}) => {
            const qs = new URLSearchParams()
            if (params.refresh) qs.set("refresh", "true")
            const s = qs.toString()
            return request<SiemStatus>(`/api/siem/status${s ? `?${s}` : ""}`)
        },

        /**
         * 把 SIEM 的事件与设备同步进 myPortal。
         *
         * 默认回溯 24 小时、同时同步设备、不覆盖已有行 —— 与后台默认值一致。
         */
        sync: (params: { minutes?: number; devices?: boolean; overwrite?: boolean } = {}) => {
            const qs = new URLSearchParams()
            qs.set("minutes", String(params.minutes ?? 1440))
            qs.set("devices", String(params.devices ?? true))
            qs.set("overwrite", String(params.overwrite ?? false))
            return request<SiemSyncResult>(`/api/siem/sync?${qs.toString()}`, { method: "POST" })
        },
    },
}
