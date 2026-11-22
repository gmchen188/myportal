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

/** 解析可能不是 JSON 的响应体 —— 出错时别抛异常，返回 null。 */
function safeJson(text: string): unknown {
    try {
        return JSON.parse(text)
    } catch {
        return null
    }
}

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
 * FastAPI 的校验错误消息 → 人话。
 *
 * 只收**实测见过**的，不搞全集 —— 收不全的会直接显示英文原文，
 * 那也没坏处（原文比「HTTP 422」强）。
 */
const VALIDATION_MESSAGES: Record<string, string> = {
    "Field required": "缺少必填字段",
    "Input should be a valid dictionary or object to extract fields from":
        "请求体不是一个 JSON 对象（前端可能把请求体序列化了两次）",
    "Input should be a valid string": "应该是字符串",
    "Input should be a valid integer": "应该是整数",
    "Input should be a valid list": "应该是列表",
    "String should have at least 1 character": "至少要 1 个字符",
    "String should have at most 64 characters": "最多 64 个字符",
    "String should have at most 200 characters": "最多 200 个字符",
    "String should have at most 32 characters": "最多 32 个字符",
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
        if (Array.isArray(detail)) {
            /*
             * **FastAPI 的 422 里 detail 是数组，不是字符串。**
             *
             * 实测踩过：新建船队报「[422] HTTP 422」，但真正的原因
             * （"Input should be a valid dictionary or object to extract
             * fields from" —— 请求体被序列化成了 JSON 字符串）被这个
             * 分支漏掉了，只剩一个 HTTP 码。
             *
             * **「HTTP 422」对用户没有任何意义** —— 他不知道该改哪里。
             * 所以这里把字段位置和消息翻译出来。
             */
            const parts = detail
                .map((d) => {
                    const item = (d ?? {}) as Record<string, unknown>
                    const loc = Array.isArray(item.loc)
                        ? item.loc
                              .filter((x) => x !== "body" && x !== "query" && x !== "path")
                              .join(".")
                        : ""
                    const raw = typeof item.msg === "string" ? item.msg : "字段不合法"
                    const msg = VALIDATION_MESSAGES[raw] ?? raw
                    return loc ? `${loc}：${msg}` : msg
                })
                .filter(Boolean)
            if (parts.length) return parts.join("；")
        }
        if (detail && typeof detail === "object") {
            const inner = detail as Record<string, unknown>
            // **error 与 detail 同时存在时要拼起来** ——
            // 后端 502 的 error 是笼统标签（"FortiSIEM 不可达"），
            // detail 才是具体原因（"未配置 FORTISIEM_CLIENT_ID"）。
            // 只取 error 会把真正有用的那半句丢掉。
            const errText = typeof inner.error === "string" && inner.error ? inner.error : null
            const detText = typeof inner.detail === "string" && inner.detail ? inner.detail : null
            const msg = errText && detText ? `${errText}：${detText}` : (errText ?? detText)
            const stage = typeof inner.stage === "string" && inner.stage ? inner.stage : null
            if (msg && stage) return `${msg}（卡在 ${stageLabel(stage)} 这一段）`
            if (msg) return msg
            if (stage) return `请求失败（卡在 ${stageLabel(stage)} 这一段）`
        }
    }

    /*
     * 兜底 —— **不能只丢一个 HTTP 码给用户**。
     *
     * 实测踩过：后端进程被杀掉后，前端页面上出现的是
     * 「fortisiem 无法获取连接状态 [502] HTTP 502」。
     *
     * 「HTTP 502」对用户毫无意义 —— 他不知道该做什么。而 502/503/504
     * 恰恰是「**上游不可用**」的语义（网关/代理连不上真正的服务），
     * 处置办法跟「SIEM 连不上」完全不同：前者要**启动后端**，
     * 后者要查 SIEM 的网络和凭据。
     *
     * 注意这里只在**没有可读诊断**时才兜底 —— 后端主动返回的 502
     * 带着 error/stage/probes，走上面的分支，不会走到这里。
     */
    //
    // **只处理 502 和 504** —— 这两个是明确的网关语义（上游连不上/超时）。
    //
    // 503 不加：Service Unavailable 语义模糊，可能是后端自己返回的
    // 「暂时不可用」，不一定是「后台没启动」。而且既有契约里
    // `extractDetail({}, 503)` 就是 "HTTP 503"（测试锁着），
    // 改了就是破坏契约。
    if (status === 502 || status === 504) {
        return "后台不可达 —— 服务可能没启动或已崩溃（这不是 FortiSIEM 的问题）"
    }
    if (status === 404) {
        return "后台找不到这个接口 —— 后端版本可能与前端不一致"
    }
    // 其它状态码保持原样 —— 「认不出来的形状退回 HTTP 状态码」是既有契约，
    // 不该为了好看就改掉（改了就得改旧测试，契约一破，以后谁都不知道
    // 原来是什么样）。只有语义明确的状态码才做特殊处理。
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
    /** FortiSIEM CMDB 推送状态：未推送 / pending / ok / failed */
    siem_push_status: string | null
    /** 归属到哪艘船 —— 资产清单按船队-单船分类的依据 */
    vessel_id: number | null
    siem_pushed_at: string | null
    siem_task_id: string | null
}

/** 一件资产映射到 CMDB 字段后的预览。 */
export interface CmdbMappedAsset {
    asset_id: number
    name: string
    natural_id: string | null
    /** 资产字段 → CMDB 字段名 */
    fields: Record<string, string>
    /** 没推过去的资产字段（natural_id / type 之类） */
    skipped: string[]
    /** CMDB 必填但值为空的字段 */
    missing: string[]
    /** 这件资产是否已接入监控（device_monitors 里有绑定） */
    monitored: boolean
}

/** 一艘船 —— 资产的直接归属 */
export interface Vessel {
    /** null = 「未归船」那一档（还没确认属于哪艘船） */
    id: number | null
    fleet_id: number | null
    name: string
    code: string | null
    imo: string | null
    description: string | null
    asset_count: number
    monitor_count: number
    event_count: number
    events_by_severity: Record<string, number>
}

/** 一支船队 —— 船的上层分组 */
export interface Fleet {
    /** null = 「未归队」那一档 */
    id: number | null
    name: string
    code: string | null
    description: string | null
    vessel_count: number
    asset_count: number
    monitor_count: number
    event_count: number
    events_by_severity: Record<string, number>
    topology_count: number
    vessels: Vessel[]
}

export interface FleetOverview {
    fleets: Fleet[]
    totals: {
        fleet_count: number
        vessel_count: number
        asset_count: number
        monitor_count: number
        event_count: number
    }
}

/** 单船视图的数据 */
export interface VesselOverview {
    vessel: {
        id: number
        fleet_id: number | null
        fleet_name: string | null
        name: string
        code: string | null
        imo: string | null
        description: string | null
    }
    assets: Array<{
        id: number
        natural_id: string | null
        name: string
        type: string
        zone: string | null
        ip: string | null
        status: string | null
        siem_push_status: string | null
    }>
    monitored: Array<{
        natural_id: string
        node_label: string | null
        ip: string | null
        channel: string
        enabled: number
    }>
    topologies: Array<{ id: number; name: string; node_count: number }>
    events: Array<{
        id: number
        title: string
        severity: string
        device_natural_id: string | null
        occurred_at: string | null
    }>
    events_by_severity: Record<string, number>
}

export interface CmdbStatus {
    write_configured: boolean
    org: string
    base_url: string
    read_configured: boolean
}

export interface CmdbPushResult {
    pushed: number
    skipped: { id: number; name: string; reason: string }[]
    task_id: string | null
    message: string
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

/** 资产模板 —— 用户上传的 Excel/CSV 解析结果（骨架，不是数据）。 */
export interface AssetTemplate {
    id: number
    name: string
    source_filename: string | null
    headers: string[]
    /** 列 → 资产字段 key */
    mapping: Record<string, string | null>
    template_rows: string[][]
    zone_hints: string[]
    row_count: number
    created_by: string | null
    created_at: string | null
    updated_at: string | null
}

/** 草稿清单 —— 基于模板创建，可反复编辑保存，最后落库。 */
export interface AssetDraft {
    id: number
    template_id: number | null
    name: string
    rows: ImportRow[]
    status: "draft" | "committed"
    version: number
    commit_result: { created: number; skipped: number; failed: number } | null
    created_by: string | null
    created_at: string | null
    updated_at: string | null
}

export interface AssetDraftStats {
    total: number
    ready: number
    skip: number
    needs_fill: number
}

/** 草稿里的行比 ImportRow 多了 from_template —— 标记「这行是从模板带来的骨架」。 */
export interface DraftRow extends ImportRow {
    from_template?: boolean
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
    /**
     * 设备拉取失败的原因。
     *
     * **必须透出** —— 没有它，「设备 0 台」跟「SIEM 里确实没有纳管设备」
     * 长得一模一样。而这个页面存在的意义就是区分「漏纳管 ≠ 安全」。
     */
    error?: string
    /** 自动绑定了多少台设备到拓扑节点 —— 运维想看这个数 */
    bound?: number
    /** 拓扑自动绑定失败的原因 */
    bind_error?: string
}

export interface SiemSyncResult {
    org: string
    window_minutes: number
    events: SiemSyncCounts
    devices: SiemSyncCounts
    synced_at: string
}

// ── 接口 ────────────────────────────────────────────────────────────────────

// ── 认证 ─────────────────────────────────────────────────────────────────────
export interface LoginResult {
    access_token: string
    token_type: string
    expires_in: number
    user: AdminUser
    tenant: AdminTenant
}

export interface CurrentUser {
    user_id: string
    tenant_id: string
    tenant_slug: string
    role: string
    locale: string
    is_admin: boolean
    is_super_admin: boolean
    can_write: boolean
    user?: AdminUser
    tenant?: AdminTenant
}

// ── 管理后台 ─────────────────────────────────────────────────────────────────
export interface AdminUser {
    id: number
    tenant_id: string
    username: string
    display_name: string | null
    role: string
    email: string | null
    is_active: boolean
    last_login_at: string | null
    failed_attempts: number
    locked_until: string | null
    created_at: string | null
}

export interface AdminTenant {
    id: string
    slug: string
    name: string
    locale: string
    fortisiem_org: string | null
    is_active: boolean
    description: string | null
    created_at: string | null
}

export type IntakeKind = "fortisiem" | "syslog" | "webhook" | "agent"

export interface IntakeSource {
    id: number
    tenant_id: string
    kind: IntakeKind
    name: string
    description: string | null
    config: Record<string, unknown>
    enabled: boolean
    last_seen_at: string | null
    events_received: number
    created_by: string | null
    created_at: string | null
    updated_at: string | null
}

export interface AuditEntry {
    id: number
    tenant_id: string
    user_id: number | null
    username: string | null
    action: string
    target_type: string | null
    target_id: string | null
    detail: Record<string, unknown>
    ip: string | null
    created_at: string | null
}

export interface AdminOverview {
    tenants: number
    active_tenants: number
    users: number
    assets: number
    incidents: number
    topologies: number
    intake_sources: number
    intake_active: number
    intake_never_seen: number
    audit_entries: number
}

export const api = {
    health: () => request<{ status: string; siem: { configured: boolean; connected: boolean; error: string | null } }>("/health"),

    // 资产
    assets: {
        list: (params: { q?: string; zone?: string; needs_review?: boolean; vessel_id?: number; fleet_id?: number; limit?: number; offset?: number } = {}) => {
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

        // ── FortiSIEM CMDB 推送 ─────────────────────────────────────
        //
        // **推送是手动动作**，不是保存资产时的副作用 —— 理由见
        // backend/app/services/cmdb_push.py。
        cmdbStatus: () => request<CmdbStatus>("/api/assets/cmdb/status"),
        cmdbPreview: (ids: number[]) =>
            request<{ items: CmdbMappedAsset[]; mapped_count: number; write_configured: boolean }>(
                `/api/assets/cmdb/preview?ids=${ids.join(",")}`,
            ),
        cmdbPush: (assetIds: number[], force = false) =>
            request<CmdbPushResult>("/api/assets/cmdb/push", {
                method: "POST",
                body: { asset_ids: assetIds, force },
            }),

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

        /* ── 模板 ─────────────────────────────────────────────── */

        /** 上传模板文件。返回解析后的模板（骨架，不是数据）。 */
        uploadTemplate: async (file: File, name?: string): Promise<AssetTemplate> => {
            const fd = new FormData()
            fd.append("file", file)
            if (name) fd.append("name", name)
            const headers: Record<string, string> = { "X-Dev-Tenant": getTenant() }
            const token = getToken()
            if (token) headers.Authorization = `Bearer ${token}`
            const res = await fetch(`${API_BASE}/api/assets/templates`, {
                method: "POST",
                headers,
                body: fd,
            })
            const text = await res.text()
            if (!res.ok) {
                throw new ApiError(res.status, extractDetail(safeJson(text), res.status))
            }
            return JSON.parse(text) as AssetTemplate
        },

        templates: () => request<{ items: AssetTemplate[]; total: number }>("/api/assets/templates"),

        template: (id: number) => request<AssetTemplate>(`/api/assets/templates/${id}`),

        removeTemplate: (id: number) =>
            request<{ deleted: number }>(`/api/assets/templates/${id}`, { method: "DELETE" }),

        /* ── 草稿 ─────────────────────────────────────────────── */

        /** 基于模板创建草稿清单。 */
        createDraft: (body: { template_id?: number | null; name?: string }) =>
            request<{ draft: AssetDraft; stats: AssetDraftStats; issues: ImportIssue[] }>(
                "/api/assets/drafts",
                { method: "POST", body },
            ),

        drafts: () => request<{ items: AssetDraft[]; total: number }>("/api/assets/drafts"),

        draft: (id: number) => request<AssetDraft>(`/api/assets/drafts/${id}`),

        /** 保存草稿（版本 +1，返回重新校验后的状态）。 */
        saveDraft: (id: number, body: { rows: DraftRow[]; name?: string }) =>
            request<{ draft: AssetDraft; stats: AssetDraftStats; issues: ImportIssue[] }>(
                `/api/assets/drafts/${id}`,
                { method: "PUT", body },
            ),

        addDraftRow: (id: number) =>
            request<{ draft: AssetDraft }>(`/api/assets/drafts/${id}/rows`, { method: "POST", body: {} }),

        /** 草稿落库到 assets。 */
        commitDraft: (id: number) =>
            request<{ draft: AssetDraft; result: CommitResult; stats: AssetDraftStats }>(
                `/api/assets/drafts/${id}/commit`,
                { method: "POST", body: {} },
            ),

        removeDraft: (id: number) =>
            request<{ deleted: number }>(`/api/assets/drafts/${id}`, { method: "DELETE" }),

        /* ── 导出 ─────────────────────────────────────────────── */

        /**
         * 导出资产清单。**下载文件**，不是返回 JSON —— 所以不走 request()。
         *
         * 导出的是当前筛选后的那一批 —— 与列表看到的完全一致。
         */
        exportUrl: (params: { q?: string; zone?: string; needs_review?: boolean; vessel_id?: number; fleet_id?: number; fmt?: string; fields?: string[] } = {}) => {
            const qs = new URLSearchParams()
            for (const [k, v] of Object.entries(params)) {
                if (v !== undefined && v !== null && v !== "") qs.set(k, String(v))
            }
            if (params.fields?.length) qs.set("fields", params.fields.join(","))
            const s = qs.toString()
            return `${API_BASE}/api/assets/export${s ? `?${s}` : ""}`
        },

        /** 从拓扑图节点生成初步资产行。 */
        importFromTopology: (nodes: Array<{ label: string; zone?: string | null; ip?: string | null }>) =>
            request<ImportPreview>("/api/assets/import/topology", { method: "POST", body: { nodes } }),

        /** 落库。幂等 —— 重复提交同一批会全部跳过。 */
        commit: (rows: ImportRow[], source = "import") =>
            request<CommitResult>("/api/assets/commit", { method: "POST", body: { rows, source } }),
    },

    // 拓扑
    fleets: {
        list: () => request<{ fleets: Fleet[]; vessels: Vessel[] }>("/api/fleets"),
        overview: () => request<FleetOverview>("/api/fleets/overview"),
        vesselOverview: (id: number) =>
            request<VesselOverview>(`/api/fleets/vessels/${id}/overview`),
        vessels: (params: { fleet_id?: number } = {}) => {
            const q = params.fleet_id ? `?fleet_id=${params.fleet_id}` : ""
            return request<{ vessels: Vessel[] }>(`/api/fleets/vessels${q}`)
        },
        create: (body: { name: string; fleet_id?: number | null; code?: string | null; imo?: string | null; description?: string | null }) =>
            request<{ id: number; name: string }>("/api/fleets/vessels", {
                method: "POST",
                body,
            }),
        createFleet: (body: { name: string; code?: string | null; description?: string | null }) =>
            request<{ id: number; name: string }>("/api/fleets", {
                method: "POST",
                body,
            }),
        patchVessel: (id: number, body: { name?: string; fleet_id?: number | null; code?: string | null; imo?: string | null; description?: string | null }) =>
            request<{ id: number; name: string }>(`/api/fleets/vessels/${id}`, {
                method: "PATCH",
                body,
            }),
        patchFleet: (id: number, body: { name?: string; code?: string | null; description?: string | null }) =>
            request<{ id: number; name: string }>(`/api/fleets/${id}`, {
                method: "PATCH",
                body,
            }),
        removeVessel: (id: number) =>
            request<{ ok: boolean }>(`/api/fleets/vessels/${id}`, { method: "DELETE" }),
        removeFleet: (id: number) =>
            request<{ ok: boolean }>(`/api/fleets/${id}`, { method: "DELETE" }),
        assignAssets: (vesselId: number, assetIds: number[]) =>
            request<{ ok: boolean; moved: number }>(`/api/fleets/vessels/${vesselId}/assets`, {
                method: "POST",
                // **传对象，不要自己 stringify** —— request() 内部会 JSON.stringify
                body: { asset_ids: assetIds },
            }),
    },
    topologies: {
        list: () => request<{ items: Topology[] }>("/api/topologies"),
        get: (id: number) => request<Topology>(`/api/topologies/${id}`),
        save: (body: { name: string; description?: string; xml: string; origin?: string; node_bindings?: Record<string, unknown> }) =>
            request<Topology>("/api/topologies", { method: "POST", body }),
        remove: (id: number) => request<{ deleted: number }>(`/api/topologies/${id}`, { method: "DELETE" }),
        graph: (id: number) => request<TopologyGraph>(`/api/topologies/${id}/graph`),

        /**
         * **用一张架构图生成拓扑图**，并顺手把资产绑上去。
         *
         * 图由 networktopology 的 AI 识别（它有 VLM 凭据和画图规范），
         * 这边只是代理：图片进去，draw.io XML 出来，顺带建好 device_monitors
         * 绑定 —— 绑定好了监控面板才有颜色。
         *
         * **慢** —— 模型要读图、画图、再改图，通常十几秒。
         */
        fromImage: (body: {
            name: string
            image_base64: string
            mime?: string
            prompt?: string
            bind_assets?: boolean
        }) =>
            request<
                Topology & {
                    bound_assets: number
                    bind_error: string | null
                    ai_message: string
                }
            >("/api/topologies/from-image", { method: "POST", body }),

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
        sync: (params: { minutes?: number; devices?: boolean; overwrite?: boolean; limit?: number } = {}) => {
            const qs = new URLSearchParams()
            qs.set("minutes", String(params.minutes ?? 1440))
            qs.set("devices", String(params.devices ?? true))
            qs.set("overwrite", String(params.overwrite ?? false))
            // 显式发 limit —— 后端默认只给 200 条，上限 1000。
            // 不发的话用户选「最近 30 天」实际最多拿 200 条，
            // 数字看着是诚实的但没人知道还有更多。
            qs.set("limit", String(params.limit ?? 1000))
            return request<SiemSyncResult>(`/api/siem/sync?${qs.toString()}`, { method: "POST" })
        },
    },

    /**
     * 认证。
     *
     * 登录成功后**必须把令牌存起来**（setToken）—— 后台在生产模式
     * 下只认 Bearer 令牌，而令牌是无状态的，服务端不持有，登出也
     * 作废不了它（只能靠过期）。
     */
    auth: {
        login: (username: string, password: string, tenant: string) =>
            request<LoginResult>("/api/auth/login", {
                method: "POST",
                body: { username, password, tenant },
            }),

        /** 当前是谁。前端启动时调它 —— 401 就跳登录页。 */
        me: () => request<CurrentUser>("/api/auth/me"),

        logout: () => request<{ ok: boolean; note: string }>("/api/auth/logout", { method: "POST" }),

        changePassword: (oldPassword: string, newPassword: string) =>
            request<{ ok: boolean }>("/api/auth/change-password", {
                method: "POST",
                body: { old_password: oldPassword, new_password: newPassword },
            }),

        /** 最近的登录失败 —— 排查是不是有人在撞库。 */
        loginAttempts: () => request<AuditEntry[]>("/api/auth/login-attempts"),
    },

    /**
     * 管理后台。
     *
     * 这些端点**任何模式都要令牌**（后台的严格认证）—— 开发模式
     * 的免登录头只对业务读接口有效。
     */
    admin: {
        overview: () => request<AdminOverview>("/api/admin/overview"),

        users: {
            list: () => request<AdminUser[]>("/api/admin/users"),
            create: (body: {
                username: string
                password: string
                role?: string
                display_name?: string
                email?: string
                tenant_id?: string
            }) => request<AdminUser>("/api/admin/users", { method: "POST", body }),
            update: (id: number, body: Partial<{
                display_name: string
                role: string
                email: string
                is_active: boolean
                password: string
            }>) => request<AdminUser>(`/api/admin/users/${id}`, { method: "PATCH", body }),
            remove: (id: number) => request<AdminUser>(`/api/admin/users/${id}`, { method: "DELETE" }),
        },

        tenants: {
            list: () => request<AdminTenant[]>("/api/admin/tenants"),
            create: (body: {
                slug: string
                name: string
                fortisiem_org?: string
                locale?: string
                description?: string
            }) => request<AdminTenant>("/api/admin/tenants", { method: "POST", body }),
            update: (id: string, body: Partial<{
                name: string
                fortisiem_org: string
                locale: string
                description: string
                is_active: boolean
            }>) => request<AdminTenant>(`/api/admin/tenants/${id}`, { method: "PATCH", body }),
        },

        intakeSources: {
            list: () => request<IntakeSource[]>("/api/admin/intake-sources"),
            create: (body: {
                kind: IntakeKind
                name: string
                description?: string
                config?: Record<string, unknown>
                enabled?: boolean
                tenant_id?: string
            }) => request<IntakeSource>("/api/admin/intake-sources", { method: "POST", body }),
            update: (id: number, body: Partial<{
                name: string
                description: string
                config: Record<string, unknown>
                enabled: boolean
            }>) => request<IntakeSource>(`/api/admin/intake-sources/${id}`, { method: "PATCH", body }),
            remove: (id: number) =>
                request<{ ok: boolean; deleted: IntakeSource }>(`/api/admin/intake-sources/${id}`, {
                    method: "DELETE",
                }),
        },

        audit: (params: { action?: string; limit?: number } = {}) => {
            const qs = new URLSearchParams()
            if (params.action) qs.set("action", params.action)
            if (params.limit) qs.set("limit", String(params.limit))
            const s = qs.toString()
            return request<AuditEntry[]>(`/api/admin/audit${s ? `?${s}` : ""}`)
        },
    },
}
