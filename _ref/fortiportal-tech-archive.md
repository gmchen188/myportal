# fortiportal 技术档案摘要（供 myPortal 复用参考）

> 调研对象：`C:\Users\gmche\Work\fortiportal`（项目名 **FortiSight**，FortiSIEM 7.5.1 多租户门户）
> 方法：纯静态源码实读（给出文件路径 / 行号）。**未运行服务、未连真机**；运行期状态另见 `docs/appliance-verification-status.md`。

## 0. 先对齐：fortiportal 与 myPortal 的关系（关键前提）

- myPortal 的产品域是**船舶数字资产基线 + 变更管理**（`_ref/soc_brochure.txt`：AquaSync Innovation SOC Essential；`_ref/ship_plan_v22.txt`：IACS UR E26/E27/E22、IEC 62443-3-3、SOLAS/ISM/ISPS）。
- 因此 fortiportal 的**领域层不可直接复用**（FortiSIEM 事件/诱捕/许可证语义）。可复用的是三层：
  1. **工程层（可直接搬）**：多租户与权限、认证会话、审计、i18n、看板插件机制、通知适配器、设计系统 + UI 组件、部署与测试守卫。
  2. **Fortinet 接入层（大概率要搬）**：`_ref/mcp_tools.json` 显示 myPortal 计划直连 FortiSIEM MCP，其工具名与 fortiportal 的调用完全一致（`query_fsm_postgres`、`get_trigger_events_by_incident_id`、`clear_incident_by_id` …），且已有 `fs_token.txt` 会话令牌。
  3. **领域层（要重写）**：NLQ 工具目录、widget 目录、告警 trigger、FortiAnalyzer/Deceptor 连接器。

## 1. 目录树（2–3 层）

```
fortiportal/
├─ backend/app/
│  ├─ config.py            # pydantic-settings，读 .env
│  ├─ db.py                # async engine + init_models()（create_all）
│  ├─ models.py            # ORM（9 张表）
│  ├─ security.py          # bcrypt/JWT/Fernet/refresh token
│  ├─ tenancy.py           # Principal / TenantContext / 角色
│  ├─ main.py              # FastAPI 入口 + 全局错误处理
│  ├─ mcp_server.py        # 门户自己的 MCP server（stdio / HTTP:8081）
│  ├─ connectors/          # fortisiem.py(921) fortianalyzer.py(405) fortideceptor.py(408)
│  ├─ routers/             # auth.py(1147) data.py(579) ops.py(770) → 59 个端点
│  ├─ services/            # nlq/audit/notifiers/alerts/widgets/fleet/scope/throttle/
│  │                       # bootstrap/eventlog_query/fortinet_clients + widget_catalog.json
│  ├─ i18n/                # zh_CN.json / en_US.json（服务端目录）
│  └─ tests/               # 41 个 test_*.py
├─ frontend/src/
│  ├─ api/                 # client.ts endpoints.ts errors.ts token.ts mock.ts types.ts
│  ├─ components/          # ui/ charts/ widgets/ incidents/ assets/ audit/ layout/ nlq/ licenses/ tenants/ auth/
│  ├─ pages/               # 15 个页面（Dashboard/DashboardBuilder/Nlq/Audit/Tenants…）
│  ├─ store/ hooks/ utils/ types/ i18n/ native/ widgets/ test/
│  ├─ scripts/*.mjs        # 10 个验证脚本（i18n/responsive/session/drawer…）
├─ mobile/                 # Capacitor 7 壳（android/ ios/），打包同一 SPA
├─ design-system/MASTER.md # 唯一 token 来源（浅/深色、severity ramp、图表调色）
├─ docs/                   # API_CONTRACT.md(429) fortisiem-7.5.1-setup.md(609) REQUIREMENTS-TRACEABILITY.md
├─ tools/mock_appliance/   # 单端口模拟三台设备（契约参考实现）
├─ scripts/                # probe_*/check_live_*/point_tenant_at_mock.py
├─ deploy/                 # nginx.conf security-headers.conf certs/
└─ docker-compose.yml      # portal-api / portal-web / gateway(nginx) / postgres / fortisiem / faz / fdo
```

## 2. 后端技术栈

- **语言/框架**：Python ≥3.11、FastAPI ≥0.115、SQLAlchemy 2.0 async、uvicorn、pydantic-settings（`backend/pyproject.toml`）。Ruff `line-length=120, select=E,F,I,UP,B`；pytest-asyncio `asyncio_mode=auto`。
- **分层**：`routers/` → `services/` → `connectors/`；`services/fortinet_clients.py` 是**唯一**按租户造客户端的地方（`load_credentials()` + `build_fortisiem/build_fortianalyzer/build_fortideceptor`），避免连接器误用他人 token。
- **统一错误契约**：`main.py:67-103` 全局 handler → `{"error":{"code","message","details"}}`；`tenancy.ApiError(status, code, message, details, headers)` 带机器码与 Retry-After。
- **数据库**：Postgres 16 + asyncpg（compose）；dev 用 `sqlite+aiosqlite:///./fortisight.db`；JSON 列用 `JSON().with_variant(JSONB(),"postgresql")`（`models.py:33`）。
- **认证**：JWT HS256 access（60min，payload=sub/email/role/tid/locale）+ bcrypt；**opaque refresh token**（`secrets.token_urlsafe`，库内只存 SHA-256，httpOnly+SameSite=Strict cookie，rotation + `family_id` 重放即撤销整族，绝对过期 30d，复用宽限 30s）；Fernet 加密 Fortinet token（`security.py:66-100`，`mask_secret()` 掩码）；登录节流按账号 5 次 / 按 IP 30 次 / 15 分钟窗口（`services/throttle.py`，只节流不锁号）。
- **Fortinet 集成方式**：REST 为主 **+ FortiSIEM 原生 MCP**（7.5.1 `https://<supervisor>/phoenix/mcp`，Streamable HTTP + JSON-RPC 2.0，**手写实现、无 MCP SDK 运行时依赖**，`fortisiem.py:695-856`）；FortiAnalyzer 走 **JSON-RPC**（`POST /jsonrpc`，`params[0].url` 风格 + session login）；FortiDeceptor 走 REST `/api/v1/...`。
- **CMDB**：设备列表三级回退 `/phoenix/rest/cmdbDeviceInfo/devices`（XML）→ `/phoenix/rest/pub/v2/cmdb/devices` → MCP `query_fsm_postgres` 查 `phoenix_device`。

**FortiSIEM 接入的四个必踩坑（务必复用其解法）**
1. `Accept: application/json` 会让内部 REST 面回 **406**，看起来像"路径对、令牌对却坏了"。用 `Accept: application/json, text/plain, */*`（`fortisiem.py:246-255`）。
2. CMDB/组织端点回 **XML** → `_xml_to_dict()`（属性→`@name`、文本→`#text`、重复兄弟→list）。
3. 公共 API 限流（每 IP 10 / 全局 50，超限 429）→ 信号量 + 指数退避 + `Retry-After`（`fortisiem.py:257-319`）。
4. 7.5.1 用 **OAuth2 Client Credentials** 取代 Refresh Token 授予；同一 client 重复铸造会被拒 → token 按 `(base_url, client_id)` 全局缓存 `_TOKEN_CACHE`（`fortisiem.py:112-234`）。

## 3. 前端技术栈

- React 18.3 + TS 5.6 + **Vite 5.4** + Tailwind 3.4（CSS 变量主题）+ @tanstack/react-query 5.59 + zustand 4.5 + react-router-dom 6.28。
- **UI 库：无第三方 UI 库**，自建 `components/ui/`（Button/Card/Table/Tabs/Dialog/Input/Select/Skeleton/Toast/Tooltip/Pagination/Dropdown/Switch/Badge），全部 Tailwind 类 + `design-system/MASTER.md` 的 token 变量。
- **图表库 recharts 2.13**：`components/charts/`（TimeSeriesChart / CategoryBarChart / PieChart / ChartTile / ChartFallbackTable 表格降级），主题色由 `chartTheme.ts` 从 CSS 变量实时读取（浅深色各一套 severity ramp）。
- **图标 lucide-react**；markdown 渲染 react-markdown + remark-gfm。
- **拖拽编排：有**。`react-grid-layout` 1.4.4 + `WidthProvider(Responsive)`，见 `pages/DashboardBuilderPage.tsx:4,22,332-352`（`onLayoutChange` 落库，按断点存多套 layout）。布局存 `dashboards.layout` JSON，条目 `{i, widget, x, y, w, h, params}`。
- PWA + 移动：`frontend/public/sw.js` + manifest；`mobile/` Capacitor 7 打包同一 SPA 为 Android/iOS。

## 4. 多租户实现

- **模型**：`Tenant` 1:1 对应 FortiSIEM **Organization**（`fortisiem_org_id` / `fortisiem_org_name`，`models.py:51-73`）。角色三档：`superadmin`（跨租户）/ `tenant_admin` / `viewer`（只读，`require_write()` 拦截）。
- **双层隔离**（设计核心，务必照搬）：
  1. **凭据层**：每租户持有自己 Organization 签发的 API token → 隔离由 FortiSIEM 强制，不是门户过滤。
  2. **门户层（纵深防御）**：`tenant_id` 过滤 + `services/scope.py` 的 `OrgScope.matches()`；scope 生效时**无 organization 属性的记录一律拒绝**（deny by default）；组织名按 token 化比较（`acme` 匹配 `acme (3)`，不匹配 `acmecorp`）。
- **租户解析优先级**：`X-Tenant-Id` 头 > `?tenant_id=` > JWT 内 `tid`；非 superadmin 强制钉死自身租户，跨租户请求 403（`tenancy.py:167-204`）。superadmin 无 scope 时"读全部租户"，写操作必须显式目标租户（`require_tenant()`）。
- **换租户**：`POST /auth/switch-tenant` 重签 JWT；`GET /fleet/overview` 用**各租户自己的凭据**并发聚合（有限并发 + 短缓存，单租户失败只出 warning 不拖垮全局，`services/fleet.py`）。

## 5. i18n / 多语言

- 前端 `src/i18n/index.ts`：i18next + react-i18next，886 key × zh-CN/en-US，资源**本地打包**（切换语言零网络请求）；`fallbackLng: ['zh-CN','en-US']`；`applyLocale()` 切 `i18next.changeLanguage` + `<html lang>`；`mergeServerMessages()` 用服务端目录覆盖本地（部分目录不会白屏）。
- 后端 `app/i18n/__init__.py`：`resolve_locale(user_locale, tenant_locale)` —— 用户选择 > 租户默认 > 门户默认（zh-CN）；用户 locale 为 `""` 表示"跟随租户"；`all_messages()` 以 en-US 为基叠加请求语言。
- 关键模式：**图表/表格列名用 `label_key` 而非文本**（后端 NLQ 返回 `label_key: "column.incident.severity"`），前端 `components/widgets/labels.ts` 做 key→文案映射。
- 守卫：`frontend/scripts/verify-i18n-keys.mjs` + 后端 `tests/test_i18n_parity.py`、`test_locale_precedence.py`。

## 6. AI / 自然语言查询

- `services/nlq.py`（730 行）：OpenAI 兼容 `POST {llm_base_url}/chat/completions`（默认模型 `MiniMax-M2`，temperature 0.1）+ function calling，最多 4 轮工具；系统提示词 `SYSTEM_PROMPT`（`nlq.py:518`）明令"只答本租户、不得编造、不得输出 SQL"。
- **工具目录** `TOOL_CATALOG`：query_incidents / query_assets / query_licenses / query_deception_hits / query_event_logs / query_clickhouse。
- **安全设计（可直接搬的三条铁律）**：
  1. 模型**不产 SQL**（事件日志与 ClickHouse 的 SQL 由服务端生成；`query_clickhouse` 仅在 `nlq_allow_raw_sql=true` 时才提供，且 `_validate_sql()` 白名单校验：仅 SELECT、禁注释/多语句/写关键字/UNION/子查询/表函数 `url() file() mysql() …`、表名限 `phoenix_incident|device|license|risk|ueba_risk` + 前缀 `fsm_`）。
  2. 模型**不可指定租户**（`FORBIDDEN_ARG_KEYS = {tenant_id, tenant, org, organization, user, role, token}`），租户由令牌决定，服务端注入 org 过滤。
  3. 每次工具调用都审计（`nlq.tool_call`）。
- 事件日志映射：`nlq_event_log_map` 指向一份 JSON（表名/列名/组织列），服务端 `services/eventlog_query.py` 用它拼 SQL（表名白名单 + 标识符正则 + 控制字符剔除）；未配置时功能惰性而非报错。
- 返回结构 `NlqResult{answer, chart, table, citations, tools_used, intent, duration_ms}`；intent 用关键词猜（stat/list/lookup/action）；历史落 `nlq_history` 表；语音 `POST /nlq/voice` → OpenAI 兼容 `/audio/transcriptions`（前端 Web Speech API 为主，服务端为兜底）。

## 7. 告警通知集成

- `services/notifiers.py`：统一适配器签名 `send(target, message, config) -> (ok, detail)`，5 通道：
  | kind | 载荷 | 备注 |
  |---|---|---|
  | wecom | markdown | 企业微信群机器人，支持 `mentioned_list` |
  | feishu | interactive card | `lark_md` + action button |
  | teams | **Adaptive Card** | Teams 已弃用 Incoming-Webhook/MessageCard；`config["legacy_message_card"]` 可回退旧 MessageCard |
  | dingtalk | markdown + HMAC-SHA256 签名 | `_dingtalk_sign()`：base64(HMAC(secret, f"{ts}\n{secret}")) |
  | email | SMTP（465→SMTPS_SSL，否则 STARTTLS） | **必须放线程** `asyncio.to_thread`，否则 SMTP 握手阻塞事件循环 |
- **网络策略坑**：appliance 连接器 `trust_env=False`（代理无法路由内网 RFC1918）；公网 webhook **必须 trust_env=True**（国内 Teams 只能经系统代理，WeCom/DingTalk/Feishu 由代理规则直连）。
- 调度：`services/alerts.py` + APScheduler，默认 60s tick，逐租户逐规则评估；trigger 类型 `incident | license | deception`；`throttle` 去重（`AlertDelivery.dedupe_key`），投递结果记 `channel_results`。

## 8. 审计日志

- `services/audit.py`：`AUDIT_ACTIONS` 元组（39 个动作，如 `auth.login`、`tenant.update`、`incident.update_status`、`mcp.tool_call`、`nlq.query`）是**唯一动作词表**；测试强制所有 `audit.record(...)` 调用必须落在该元组内（写而未列 = 测试失败）。
- `record()` 写 `AuditLog`：actor_user_id/email/role、tenant_id、action、resource_type/id、outcome、ip（取 `X-Forwarded-For` 首段）、user_agent、detail/before/after JSON。**只追加**，无更新/删除 API 面。
- 安全细节：MCP 审计**不记录 api_token**（凭据不该进审计）；凭据在 API 响应中掩码、库内 Fernet 加密；读取侧 `/audit`（过滤）、`/audit/export`、`/audit/actions`（下拉词表）。

## 9. 与 FortiSIEM 的集成点（精确清单）

**REST 路径**（`connectors/fortisiem.py`）：
`/phoenix/rest/context/user`（健康）· `/phoenix/rest/organization/list`（组织，XML）· `/phoenix/rest/cmdbDeviceInfo/devices` · `/phoenix/rest/pub/v2/cmdb/devices` · `/phoenix/rest/pub/v2/query/cmdb/devices` · `/phoenix/rest/pub/v2/query/incidents[/{id}]` · `/phoenix/rest/pub/v2/query/events`（`incidentId`）· `/phoenix/rest/pub/v2/query/license` · `/phoenix/rest/pub/incident/update/{id}`（状态/严重级别/comment）· `/phoenix/rest/pub/security/oauth/token`（client_credentials）。已废弃端点（`/phoenix/rest/query/eventQuery`、旧 cmdbDeviceInfo 列表）刻意不用。

**MCP 工具**（`/phoenix/mcp`）：`query_fsm_postgres`（参数名是 `sql`，非 `query`）、`query_fsm_clickhouse`、`get_trigger_events_by_incident_id`、`get_iocs_by_incident_ids`、`get_related_incidents_by_id`、`clear_incident_by_id`、`append_incident_comment_by_id`、`update_incident_severity_by_id` —— 与 `_ref/mcp_tools.json` 完全对应，可直接复用其会话封装（`initialize` → 取 `Mcp-Session-Id` → `notifications/initialized` → 后续带该头；响应是 SSE 帧需剥 `data:` 前缀；结果多层嵌套需 `_unwrap_mcp()` 递归解包到行数据）。

**CMDB 字段与表**（snake_case）：
- `ph_incident`：incident_id, incident_title, rule_id, severity_cat, severity(分值), incident_status(0=active/1=cleared/2=in progress), first_seen_time, last_seen_time, incident_count, src_ip_addr, dest_ip_addr, host_ip_addr, src_name, dest_name, host_name, user_attr, cust_org_id
- JOIN：`ph_sys_domain`(domain_id, name) 取组织名；`ph_drq_rule`(id, name) 取规则名
- 其它：`phoenix_incident` / `phoenix_device` / `phoenix_license` / `phoenix_risk` / `phoenix_ueba_risk`；ClickHouse 日志表前缀 `fsm_*`
- 设备字段：id, name, accessIp, deviceType{vendor,model,version}, organization, unmanaged, approved
- 事件命中资产（无 affectedAssets 数组时）：host_ip_addr / host_name / device_type
- severity 映射：≥9 critical，≥7 high，≥4 medium，>0 low，否则 informational

**FortiAnalyzer（JSON-RPC）**：`/sys/login/user`（key 为 `user`/`passwd`）· `/sys/logout` · `/sys/status` · `/ioc/license/state` · `/dvmdb/adom` · `/logview/adom/{adom}/logstats`（EPS/配额）· 设备/事件/告警/端点列表。
**FortiDeceptor（REST）**：`/api/v1/incident/alert/list` · `/api/v1/deception/response/decoy/list` · `/api/v1/deception/decoy-template/list` · `/api/v1/system/license/status`。

## 10. 可复用资产 / 工具函数 / 配置模式

**整块可搬**
- 多租户与权限：`tenancy.py` + `services/scope.py`（双层隔离 + deny-by-default）
- 认证会话：`security.py`（refresh token rotation + family 撤销）
- 审计：`services/audit.py` + `AUDIT_ACTIONS` 词表
- i18n：前后端双份实现 + key 一致性守卫脚本
- 看板插件机制：后端 `services/widget_catalog.json`（26 项，含 id/renderer/name_key/category/default_size/params/source）↔ 前端 `components/widgets/registry.tsx`（renderer→组件映射）；**加组件 = 往 JSON 加一行 + 加一个渲染器**，存量看板零改版即可用
- 通知适配器 `notifiers.py`；告警引擎 `alerts.py`（trigger + throttle + delivery）
- 设计系统 `design-system/MASTER.md`（唯一 token 源）+ `components/ui/` 组件库
- `tools/mock_appliance/app.py`：一个 FastAPI 同时模拟三台设备（路径不冲突 `/phoenix/*` `/jsonrpc` `/api/v1/*`），是**契约参考实现**，并由测试驱动真实连接器把契约钉在仓库里
- 部署：`docker-compose.yml`（portal-api / portal-web / gateway nginx / postgres16 / fortisiem7.5.1 / faz7.6.0 / fdo6.3.0）、`deploy/security-headers.conf`（严格 CSP、无 inline script、Permissions-Policy）
- 验证脚本：`frontend/scripts/*.mjs`（10 个：i18n keys、responsive、session UI、severity contrast、CDP smoke…）

**需替换领域层**：NLQ `TOOL_CATALOG`（→ 船舶资产/变更/拓扑/漏洞语义）、widget 目录（→ 资产基线、拓扑图、变更记录、CVE 候选）、告警 trigger 类型、FortiAnalyzer/Deceptor 连接器（视 myPortal 需求）。

**值得复制的模式**
1. **单一凭据工厂**：`load_credentials(session, tenant)` + `build_*(creds)`，连接器永不自行取 token。
2. **数据归一化契约**：`_empty()` 给出全键集（value/series/categories/columns/rows/items/licenses + meta.warnings），一个渲染器服务多个组件。
3. **错误契约**：`{error:{code,message,details}}` + 机器码词表。
4. **租户不变式测试**：现有测试名已覆盖关键不变式，myPortal 应照抄——`test_authorization_matrix`、`test_cross_tenant_object_access`、`test_tenant_scoping`、`test_privilege_escalation`、`test_nlq_sql_guard`、`test_widget_scope`、`test_audit_secrets`、`test_i18n_parity`、`test_requirements_traceability`、`test_repository_lint`。
5. **文档即契约**：`docs/API_CONTRACT.md` 为权威接口契约（编号 §1–§11），README 与代码数字对齐并由测试守卫。

**非证据声明**：本次为静态源码阅读，未启动服务、未连真实 FortiSIEM/FortiAnalyzer/FortiDeceptor，未验证 59 个端点的运行时行为；"已接通实机"仅依据仓库最近提交信息（`95d57f5 feat(fortisiem): 接通实机`）与 `docs/appliance-verification-status.md` 的自述。
