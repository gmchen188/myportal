# -*- coding: utf-8 -*-
"""生成《myPortal 产品设计方案 V1.0》Word 文档。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from docx import Document

from docx_kit import (
    add_bullets,
    add_code_block,
    add_cover,
    add_footer_page_numbers,
    add_h,
    add_header_text,
    add_layer_table,
    add_para,
    add_table,
    add_tip_box,
    add_toc_field,
    add_wide_table,
    init_styles,
    verify,
)

OUT = Path(__file__).resolve().parent.parent / "Docx" / "myPortal 产品设计方案 V1.0.docx"


def build() -> None:
    doc = Document()
    init_styles(doc)

    # ══════════════════════════ 封面 ══════════════════════════
    add_cover(
        doc,
        "myPortal 产品设计方案",
        "多租户 Fortinet 安全运营门户 · 模块化架构设计",
        "版本 V1.0　|　2026-11-18　|　BinQsoft 船舶网络安全与韧性平台",
    )

    # ══════════════════════════ 致读者 ══════════════════════════
    add_h(doc, "致读者", 1)
    add_para(
        doc,
        "本方案回答一个问题：**FortiSIEM 原生门户不够好用，那我们要自己做一个什么样的门户？**"
        "它不是一个演示原型，而是一份可以直接指导开发的工程规格说明——"
        "每一个架构决策都对应一个已经在实机上验证过的接口契约，"
        "每一个模块都界定了它读什么数据、写什么数据、谁能看。",
    )
    add_para(
        doc,
        "方案中的接口契约、表结构、字段名、错误码，**不是从文档抄来的，是对着 "
        "172.16.20.48（FortiSIEM 7.5.1）与 172.16.21.12（FortiAnalyzer 7.6.5）"
        "两台实机逐条探测出来的**。凡是没有在实机上确认的，文档里明确标注为"
        "「待确认」，不写成既成事实。",
    )
    add_para(
        doc,
        "阅读路径建议：产品与业务方读第一章与第六章；架构师读第二、三、七章；"
        "开发工程师从第四章与第八章入手；项目经理看第九章的里程碑与验收口径。",
    )

    add_toc_field(doc)

    # ══════════════════════════ 一、产品定位 ══════════════════════════
    add_h(doc, "一、产品定位与设计目标", 1)

    add_h(doc, "1.1 我们要解决的问题", 2)
    add_para(
        doc,
        "FortiSIEM 7.5.1 自带的门户在 MSSP 场景下有三个结构性缺陷，"
        "它们不是界面不好看的问题，而是产品形态的问题：",
    )
    add_bullets(doc, [
        "**没有多租户运营视图。** FortiSIEM 的 Service Provider 模式提供了 Organization 级的数据隔离，"
        "但它没有提供「一个 MSSP 运营人员同时看 N 个租户」的界面。运营方要么开 N 个浏览器标签，"
        "要么放弃 SIEM 自己的门户、自己写工具——这就是我们要做的事。",
        "**没有面向船队的语义。** 船舶网络安全的核心对象是船、CBS（计算机化系统）、安全区域、"
        "以及 IACS UR E26/E27/E22 的 12 个管理维度。FortiSIEM 的 CMDB 不知道「这艘船的推进系统"
        "属于哪个安全区域」。「船舶网络安全和韧性计划」这块业务，SIEM 完全没有承载。",
        "**没有合规视角。** 船级社（IACS/DNV/ABS/LR）检验时要看的是「某船某模块的完整台账 + "
        "流程文档 + 证据包」，这需要台账模型、文档模板与证据链，"
        "而不是 SIEM 的事件时间线。",
    ])
    add_tip_box(
        doc,
        "这三个缺陷决定了 myPortal 的定位：**它不是一个 SIEM 的替代品，而是一个叠加在 "
        "FortiSIEM 之上的运营层**。FortiSIEM 负责采集、检测、事件关联；"
        "myPortal 负责把 SIEM 的数据按租户、按船、按合规条款重新组织，并加上船队视图、"
        "AI 助手、自动巡检与告警闭环。",
        "info",
    )

    add_h(doc, "1.2 目标用户与核心场景", 2)
    add_table(
        doc,
        ["角色", "所属方", "核心诉求", "在 myPortal 里的落点"],
        [
            ["平台管理员", "BinQsoft / MSSP 运营方",
             "同时掌握 N 个租户的资产、事件、许可证与告警投递健康度；新租户接入要快",
             "「船队总览面板」跨租户聚合视图 + 「租户管理」"],
            ["租户管理员", "船东 / 单个船队",
             "只看自己船队的安全态势与合规进度；告警要推到自己的群里",
             "登录即限定租户作用域，所有组件只渲染本租户数据"],
            ["安全运营工程师", "BinQsoft 安全运营团队",
             "快速定位高风险资产与事件、生成报告、驱动响应",
             "「安全 Top10」「性能 Top10」「可用性 Top10」「变更 Top10」+ AI 助手"],
            ["船舶网络负责人", "船东 / 船上 IT",
             "维护 CBS 台账、安全区域与拓扑；准备船级社检验",
             "「船舶网络安全和韧性计划」全部台账 + 检验证据包"],
            ["检验方 / 观察员", "船级社 / 审计",
             "只读取证材料，不修改",
             "只读账号 + 证据包导出 + 全量操作审计"],
        ],
        widths=[2.4, 2.6, 5.6, 5.4],
    )

    add_h(doc, "1.3 设计原则", 2)
    add_bullets(doc, [
        "**上游是边界，门户是第二道防线。** 租户隔离由 FortiSIEM 在数据层强制执行（Organization 专属 Token），"
        "门户侧的 `cust_org_id` 过滤是兜底。两者都要有，顺序不能反。",
        "**元数据驱动，前端零改动加模块。** 一个模块注册项同时生成后端 Schema、CRUD 路由、"
        "前端表单与表格。新增一个 UR 台账模块 = 加一段注册代码。",
        "**租户边界只从凭据来，永不从参数来。** API 工具参数里不允许出现租户 ID，"
        "作用域由调用者的令牌解析得出。这条规则让越权在构造上不可能发生。",
        "**每个数字都要能说清来源。** 看板上的「1240 台设备」必须能点进去看到是哪 1240 台；"
        "「许可 30 天后到期」必须能追到 FAZ 的那个字段。",
        "**实机验证优先于文档。** 未在实机上确认的接口一律标注「待确认」，并给回退链。",
    ])

    # ══════════════════════════ 二、总体架构 ══════════════════════════
    add_h(doc, "二、总体架构", 1)

    add_h(doc, "2.1 架构分层", 2)
    add_layer_table(
        doc,
        [
            ("浏览器 SPA", "React 18 + TS + Vite + Tailwind + shadcn/ui　│　"
             "看板编排 (react-grid-layout)　│　图表插件注册表 (Recharts)　│　"
             "AI 助手 (文字 / 语音)　│　i18next (zh-CN 默认 + en-US)　│　"
             "通知通道配置 / 审计查询 / UR 合规模块"),
            ("FastAPI 门户后端\n连接器层", "FortiSIEM（REST + MCP）　│　FortiAnalyzer（flatui_proxy）　│　"
             "FortiDeceptor（候选路径）"),
            ("FastAPI 门户后端\n作用域层", "OrgScope：按组织名匹配、默认拒绝、无归属即排除、"
             "过滤在截断之前、响应报告被过滤掉的数量"),
            ("FastAPI 门户后端\n目录 / 注册表层", "WidgetCatalog（26 个组件，单一事实来源）　│　"
             "ModuleRegistry（UR 台账元数据驱动）"),
            ("FastAPI 门户后端\n通知层", "企业微信 / 飞书 / Teams / 钉钉 / 邮件　│　"
             "投递结果由发送器回写"),
            ("FastAPI 门户后端\nAI 与审计层", "NLQ 引擎（固定工具目录，模型只填参数）　│　"
             "审计日志（只追加）　│　门户侧 MCP（对外暴露租户作用域能力）　│　"
             "会话与令牌（JWT + 轮换 Cookie）"),
            ("外部设备", "FortiSIEM 7.5.1（REST + MCP）　│　FortiAnalyzer 7.6.5（flatui_proxy）　│　"
             "FortiDeceptor 6.x（REST 表面仅在 FNDN，待确认）"),
        ],
        "图 2-1　myPortal 逻辑架构",
    )

    add_h(doc, "2.2 技术选型与理由", 2)
    add_table(
        doc,
        ["层次", "技术选型", "为什么是它"],
        [
            ["前端框架", "React 18 + TypeScript + Vite 5",
             "沿用 fortiportal 已验证的栈；react-grid-layout / Recharts / i18next / TanStack Query 生态成熟"],
            ["UI 体系", "Tailwind CSS 3.4 + shadcn/ui",
             "shadcn/ui 是源码分发、无运行时锁定，可完全按本项目的设计令牌定制；避免 Element Plus 的「后台模板感」"],
            ["图表", "Recharts 2.13",
             "React 原生、声明式；ApexCharts 非 OSI 许可，不可嵌入交付给客户的商业产品"],
            ["看板编排", "react-grid-layout 1.4.4",
             "拖拽 + 缩放 + 响应式断点 + 布局可序列化；布局项必须指向注册表中真实存在的组件"],
            ["状态与数据", "TanStack Query 5 + Zustand 4",
             "服务端状态交给 Query（缓存 / 失效 / 重试），UI 状态交给 Zustand（轻量、无样板）"],
            ["后端", "FastAPI + SQLAlchemy 2.0 (async) + Alembic",
             "asiSCRS 与 fortiportal 均已采用；Pydantic 原生校验 + 自动 OpenAPI"],
            ["数据库", "PostgreSQL 16 (生产) / SQLite (开发)",
             "多租户行级隔离、JSONB 存看板布局与租户配置、成熟的行级安全策略"],
            ["调度", "APScheduler 3.10",
             "告警轮询、许可证巡检、Top10 预聚合；单进程内嵌即可，不引入 Celery/Redis 的运维负担"],
            ["图表库许可", "Apache-2.0 ECharts / MIT Recharts",
             "Grafana 是 AGPL-3.0，只借鉴其「插件元数据 + JSON 选项」的架构，绝不拷贝源码"],
        ],
        widths=[2.2, 4.0, 9.8],
    )

    add_h(doc, "2.3 部署拓扑", 2)
    add_layer_table(
        doc,
        [
            ("浏览器", "HTTPS → 网关。SPA 与 API **同源**（相对 API base `/api/v1`），"
             "否则刷新 Cookie 会被静默扣留，会话每次刷新都死而服务端日志看不出异常。"),
            ("网关", "Nginx / Caddy：TLS 终止 + 反向代理 + 安全响应头（CSP / HSTS / X-Frame）。"
             "SPA 静态资源、`/api/v1`、`/ws` 同源。"),
            ("应用", "FastAPI（uvicorn 多进程）：`/api/v1`（业务）、`/api/v1/auth`（会话）、"
             "`/mcp`（门户侧 MCP）。"),
            ("数据", "PostgreSQL 16（门户自有库）　│　APScheduler（同进程调度）　│　"
             "Redis（可选，会话/缓存）"),
            ("出网 ①", "→ FortiSIEM `172.16.20.48:443`　**`trust_env=False`，走直连**。"
             "私有网段代理无法路由，走代理会变成 12 秒 TLS 超时而非快速失败。"),
            ("出网 ②", "→ FortiAnalyzer `172.16.21.12:443`　**`trust_env=False`，走直连**。"),
            ("出网 ③", "→ 通知目标（企业微信 / 飞书 / Teams / 钉钉 / 邮件）　"
             "**`trust_env=True`，走系统代理**。Teams 的 webhook 在国内只能经代理出去。"),
        ],
        "图 2-2　部署拓扑与出网策略",
    )
    add_tip_box(
        doc,
        "**出网策略必须按目的地分类，不能一刀切。** 本机注册了 Windows 系统代理 "
        "（127.0.0.1:7897，Clash）。私有网段的设备（172.16.x.x）代理无法路由，"
        "httpx 默认 `trust_env=True` 会把请求交给代理，结果是 **12.24 秒的 TLS 握手超时**"
        "而不是快速失败——路径对、令牌对、端口通，看起来却像「设备宕了」。"
        "反过来，Teams 的 webhook 在国内只能通过系统代理出去。"
        "所以：**设备连接器 `trust_env=False`，通知发送器 `trust_env=True`，两处都要有测试钉死。**",
        "warn",
    )

    # ══════════════════════════ 三、数据源契约 ══════════════════════════
    add_h(doc, "三、数据源契约（实机验证）", 1)
    add_para(
        doc,
        "这一章是整个方案的**事实基线**。下面的每一条都在 2026-11-18 对着实机验证过，"
        "并把验证方法一并记录，便于后续回归。",
    )

    add_h(doc, "3.1 FortiSIEM 7.5.1", 2)

    add_h(doc, "3.1.1 认证：只有 OAuth 一条路", 3)
    add_para(
        doc,
        "FortiSIEM 7.5.1 的 Public REST API 与原生 MCP 服务**只接受 OAuth 2.0 Client Credentials**。"
        "凭据在 GUI 的 `Admin > Settings > System > API Token` 签发。",
    )
    add_code_block(
        doc,
        """POST https://172.16.20.48/phoenix/rest/pub/security/oauth/token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&client_id=<ClientID>&client_secret=<ClientSecret>

→ 200 {"access_token":"eyJ0eX...","expires_in":900,"token_type":"Bearer"}""",
        "已验证可用（Client ID 712381cd-bbfe-4c51-8bd8-11070b655ce4）",
    )
    add_bullets(doc, [
        "**表单编码，不是 JSON。** JSON body 返回 415，GET 返回 405。"
        "只写 `data=`，不写 `json=`。",
        "**`/pub/` 前缀是强制的。** 不带 `/pub/` 的路径在容器层就 401。",
        "**令牌有效期 900 秒（15 分钟）。** 必须按 `(base_url, client_id)` 缓存令牌并在到期前刷新；"
        "设备拒绝同一 client 的第二次签发（`Invalid input parameters`），所以不能每请求签一次。",
        "**GUI 口令不是 API 凭据。** 实测 `admin` + GUI 口令在 `super` 与 `SYSTEM` 两个组织下"
        "均返回 `Invalid username or password.`，无法通过 API 认证。门户的凭据录入表单"
        "必须把两者建成**不同字段**。",
    ])

    add_h(doc, "3.1.2 原生 MCP 服务", 3)
    add_para(
        doc,
        "`POST https://172.16.20.48/phoenix/mcp` 可用，服务端标识为 `FortiSIEM_MCP v1.24.0`，"
        "共暴露 **17 个工具**。这是 myPortal 智能查询与事件读取的主通道。",
    )
    add_table(
        doc,
        ["工具", "用途", "myPortal 用途"],
        [
            ["`query_fsm_postgres`", "PostgreSQL 只读查询（表白名单制）", "事件 / 设备 / 规则的聚合统计"],
            ["`query_fsm_clickhouse`", "ClickHouse 只读查询（表 `events`）", "EPS 趋势、事件类型分布、日志检索"],
            ["`get_top_10_risky_devices_incidents`", "高风险设备 Top10（含风险分）", "「安全 Top10 · 设备」组件"],
            ["`get_top_10_risky_users_incidents`", "高风险用户 Top10", "「安全 Top10 · 用户」组件"],
            ["`get_incidents_by_entity`", "按实体取活跃事件", "资产详情页的事件列表"],
            ["`get_incident_by_id`", "取单条事件详情", "事件详情页"],
            ["`get_related_incidents_by_id`", "取关联事件", "事件关联图"],
            ["`get_trigger_events_by_incident_id`", "取触发事件原始日志", "事件溯源"],
            ["`get_context_by_entity`", "实体上下文富化", "资产 360 视图"],
            ["`get_iocs_by_incident_ids`", "取失陷指标", "事件详情页的 IOC 列表"],
            ["`get_reputation_by_entity`", "实体威胁信誉查询", "AI 助手与事件研判"],
            ["`update_incident_severity_by_id`", "修改事件严重级别", "事件处置动作（写操作，需审计）"],
            ["`update_incident_resolution_by_id`", "修改事件解决状态", "事件处置动作（写操作，需审计）"],
            ["`clear_incident_by_id`", "清除事件", "事件处置动作（写操作，需审计）"],
            ["`append_incident_comment_by_id`", "追加事件备注", "处置过程留痕"],
            ["`query_fsm_postgres_prompts`", "SQL 模板提示", "NLQ 工具目录的 SQL 生成参考"],
            ["`query_fsm_clickhouse_prompts`", "SQL 模板提示", "NLQ 工具目录的 SQL 生成参考"],
        ],
        widths=[5.4, 5.4, 5.2],
        font_size=8.5,
    )
    add_tip_box(
        doc,
        "**MCP 的四个协议陷阱**（每个都曾让「设备上没有数据」的错觉成立）：\n"
        "① `Accept` 必须同时含 `application/json` **和** `text/event-stream`，只写 JSON 直接 406。\n"
        "② `initialize` 响应头里的 `Mcp-Session-Id`，**之后每个请求都必须带上**。\n"
        "③ SQL 工具的答案**套两层**：JSON-RPC result → content 块 → text 里再一层 "
        "`{\"_meta\":null,\"content\":[...]}` → 最里面才是行。解包必须递归。\n"
        "④ 行是 **Python 字面量 repr**（单引号、`None`），不是 JSON —— 先 `json.loads` "
        "失败再 `ast.literal_eval`。",
        "warn",
    )

    add_h(doc, "3.1.3 数据面：表、列与实测统计", 3)
    add_para(
        doc,
        "PostgreSQL 侧白名单内确认可查的表为 `ph_device`、`ph_incident`、`ph_sys_domain`、"
        "`ph_drq_rule`；ClickHouse 侧白名单内确认可查的表为 `events`。"
        "实测列名如下（**与官方文档不同，以实测为准**）：",
    )
    add_tip_box(
        doc,
        "**实测抓到一个真实缺陷，会让 AI 助手在真机上完全失灵。** "
        "fortiportal 现有代码里有四处引用了设备上**根本不存在的表名**"
        "（`phoenix_incident` / `phoenix_device` / `phoenix_license` / `phoenix_risk` / "
        "`phoenix_ueba_risk`）：\n"
        "① `connectors/fortisiem.py` 的 `list_devices` 最后兜底分支查 `phoenix_device`；\n"
        "② 同文件 `get_incident` 查 `phoenix_incident`；\n"
        "③ 同文件 `get_license` 查 `phoenix_license`（SIEM 侧**根本没有许可证表**）；\n"
        "④ `services/nlq.py` 与 `services/eventlog_query.py` 的表白名单**只有**这五个 `phoenix_*` 名。\n"
        "**实测结果**：真机上查这些表一律返回 `Table not allowed: phoenix_incident`。"
        "第 ④ 条尤其致命——NLQ 的结构化事件日志工具**每一次调用都会被自己的白名单挡下来**，"
        "而它在界面上看起来完全正常。表名必须是 `ph_incident` / `ph_device`，"
        "ClickHouse 侧是 `events`。\n"
        "这不是「文档与实现不一致」的小事：**照搬这份白名单，AI 助手就是一座建在沙上的房子**，"
        "而且要等到用户真正提问时才会暴露。",
        "safe",
    )
    add_wide_table(
        doc,
        ["表", "关键列", "说明"],
        [
            ["ph_device", "id, cust_org_id, name, access_ip, phy_loc, asset_category, device_type_id, "
             "vuln_count_critical / _high / _medium / _low / _info, hw_serial_no, os_edition, "
             "creation_method, discover_time, approved, decommissioned",
             "设备台账。租户归属字段是 `cust_org_id`（整数），与 Organization 列表的 `domainId` 一一对应"],
            ["ph_incident", "id, cust_org_id, severity（1-10 数值）, severity_cat（HIGH/MEDIUM/LOW… 字符串）, "
             "incident_status（0=ACTIVE 1=AUTO_CLEARED 2=MANUALLY_CLEARED 3=SYSTEM_CLEARED）, "
             "incident_title, incident_et, incident_reso, ticket_status, ph_incident_category, "
             "host_ip_addr, src_ip_addr, dest_ip_addr, host_name, user, orig_device_name, "
             "creation_time, first_seen_time, last_seen_time, last_riskscore_calculation_time, cve_codes",
             "事件台账。**注意 `severity` 与 `severity_cat` 并存**，排序用数值、分类用字符串"],
            ["events (ClickHouse)", "phRecvTime, phCustId, customer, eventType, eventTypeGrp, eventName, "
             "eventSeverityCat, phEventCategory, reptDevName, reptDevIpAddr, reptVendor, "
             "collectorId, parserName, rawEventMsg, srcName, destName, user, hostName, appName",
             "原始事件日志。租户归属字段是 `phCustId` + `customer`（组织名）"],
        ],
        widths=[2.4, 12.0, 11.3],
        font_size=8,
    )
    add_para(doc, "**实机实测数据（2026-11-18 采集，用于门户字段与图表的验收基线）：**")
    add_table(
        doc,
        ["指标", "实测值", "门户用途"],
        [
            ["Organization 列表", "system(domainId=0) / service(domainId=2) / Super(domainId=1，仅 Super 已初始化)",
             "租户与 Organization 的映射表"],
            ["设备总数", "3 台（全部 `cust_org_id=1`）", "资产统计组件的字段验证"],
            ["事件总数", "4 条（HIGH 1 / MEDIUM 3；ACTIVE 2 / SYSTEM_CLEARED 2）", "Top10 与严重度分布组件"],
            ["事件日志总量", "1,249,270 条（Super 组织 1,249,210，system 60）", "EPS 组件与日志检索"],
            ["日事件量（近 7 日）", "76,347 ~ 79,702 条/日", "EPS 趋势图的时间序列基线"],
            ["Top10 高风险设备", "172.16.0.57 (51.07) / fortisiem751.binqsoft.com (36.37) / DC01.goad.lab (22.10)",
             "「安全 Top10 · 设备」组件"],
            ["Top10 高风险用户", "admin (36.37)", "「安全 Top10 · 用户」组件"],
        ],
        widths=[3.4, 7.6, 5.0],
        font_size=9,
    )
    add_tip_box(
        doc,
        "**实测发现的四张「404 陷阱」**——写死这些路径会得到一个看起来正常但永远空白的界面：\n"
        "· `/phoenix/rest/pub/v2/query/incidents` → **404**（事件必须走 MCP 的 `query_fsm_postgres`）\n"
        "· `/phoenix/rest/pub/v2/cmdb/devices` → **404**（改用 `POST /phoenix/rest/pub/device`）\n"
        "· `/phoenix/rest/pub/v2/query/license` → **404**（SIEM 侧没有许可证接口，见 3.2）\n"
        "· `/phoenix/rest/organization/list` → **200 但返回 XML**，"
        "请求头写死 `Accept: application/json` 会得到 406",
        "safe",
    )

    add_h(doc, "3.2 FortiAnalyzer 7.6.5 —— 许可证与 EPS 的权威源", 2)
    add_para(
        doc,
        "**FortiSIEM 侧完全没有许可证到期与用量的 API**（路径全部 404，EPS 只在 Performance and Health "
        "接口里间接出现）。因此许可证到期告警与 EPS 用量**必须从 FortiAnalyzer 取**。"
        "这一点决定了连接器的分工，不是可选项。",
    )
    add_code_block(
        doc,
        """# ① 登录 —— 注意：这台 7.6.5 不接受旧版 /jsonrpc + user/passwd（返回 -11）
POST https://172.16.21.12/cgi-bin/module/flatui_auth
{"url":"/gui/userauth","method":"login",
 "params":{"username":"admin","secretkey":"<pwd>","logintype":0}}

→ 200 Set-Cookie: CURRENT_SESSION=...; HTTP_CSRF_TOKEN=...; auth_state=; remoteauth=

# ② 数据 —— 顶层 url 平铺，不是 params[0].url
POST https://172.16.21.12/cgi-bin/module/flatui_proxy
{"method":"get","url":"/gui/sys/license"}

→ 200 {"result":[{"data":{ "licenses":{ "ADOM":{"status":"ok","css":"ok",
              "txt":"Web/在线支持 (过期 2026-12-28)"}, ... } }}]}

# ③ EPS 时间序列
POST /cgi-bin/module/flatui_proxy  {"method":"get","url":"/gui/sys/monitor"}
→ 200 {"data":[{"name":"TOTAL","data":[52,51,53,...]}], "interval":120, "samples":30}""",
        "已实机验证通过的 FortiAnalyzer 8.x flatui 契约",
    )
    add_para(doc, "**许可证载荷结构与实测到期日：**")
    add_table(
        doc,
        ["字段", "含义", "实测值 / 样例"],
        [
            ["`licenses.<CODE>.status`", "状态机（ok / warning-red / …）", "ADOM=ok；FCEM=warning-red"],
            ["`licenses.<CODE>.txt`", "可读描述，**内嵌到期日**", "「Web/在线支持 (过期 2026-12-28)」"],
            ["`licenses.<CODE>.css`", "前端配色提示", "ok / warning-red"],
            ["`account_id` / `company`", "许可账号与主体", "hnie@fortinet.com / Fortinet"],
            ["`current_num_dev` / `max_num_dev`", "已用 / 许可设备数", "12 / 10000"],
            ["`max_num_adom` / `max_gb_day`", "ADOM 数上限 / 每日 GB 上限", "10 / 10"],
            ["`is_vm` / `is_vm_trial_lic` / `duplicate_license`", "许可形态", "1 / 0 / 0"],
            ["`faz_status`", "设备健康状态", "1（正常）"],
            ["`root_adom_storage_info`", "root ADOM 存储用量", "JSON 对象"],
        ],
        widths=[4.6, 4.6, 6.8],
        font_size=9,
    )
    add_para(
        doc,
        "**实测到期日**：ADOM / COMP / ENHN / FMWR / FOAS / FRVS / PBDS / SOAR / SPRT / VMLS "
        "均在 **2026-12-28** 到期（状态 ok，距今约 40 天）；FCEM 已于 2024-04-14 过期，"
        "FCEP 已于 2022-01-14 过期。这正是「许可证到期告警」功能必须能表达的状态分布——"
        "有的正常、有的过期，需要按组件分别呈现而不是一个总数。",
    )
    add_tip_box(
        doc,
        "**FortiAnalyzer 的连接器必须做成「多候选路径 + 回退链」。** 7.x 的 `/jsonrpc` + "
        "`user`/`passwd` 契约与 8.x 的 `flatui_auth`/`flatui_proxy` 契约**互不兼容**，"
        "而公开文档大多只写了前者。myPortal 的连接器应当：先探 `/jsonrpc`，失败则探 "
        "`flatui_auth`，把探测结果缓存下来；读路径同理，并发探测时**必须间隔几秒**，"
        "否则设备返回 `-23`（登录次数达上限），把真实答案掩盖成一个误导性的错误码。",
        "warn",
    )

    add_h(doc, "3.3 FortiDeceptor 6.x", 2)
    add_para(
        doc,
        "FortiDeceptor 的完整 REST 表面自 6.7.5 起只在 FNDN（需账号）发布，公开文档无法核实。"
        "因此 myPortal 对它采取**非硬依赖**策略：候选路径 + 回退链 + 字段名多候选映射 + 自诊断告警。",
    )
    add_bullets(doc, [
        "每条未确认的路径**只会让功能变空，不会让功能坏掉**；",
        "字段名按候选列表查找（camelCase / snake_case / 嵌套包装层都要找）；",
        "若设备返回了记录但一个字段都没解析出来，门户**不显示自信的「0 条命中」**，"
        "而是给出「字段映射需要针对本设备校准」的警告——这个警告同时出现在组件上、"
        "租户总览行与告警规则日志里。",
    ])

    # ══════════════════════════ 四、多租户 ══════════════════════════
    add_h(doc, "四、多租户架构与安全模型", 1)

    add_h(doc, "4.1 三条边界", 2)
    add_table(
        doc,
        ["边界", "回答的问题", "机制", "失效后果"],
        [
            ["身份", "谁在调用", "短时效 JWT（内存持有）+ httpOnly 刷新 Cookie（轮换 + 重放检测）",
             "会话被窃取或无法在刷新页面后存活"],
            ["租户", "谁的数据", "上游组织专属凭据（第一道）+ `cust_org_id` 过滤（第二道）",
             "跨租户数据泄漏——最严重的缺陷"],
            ["传输", "会话能否跨刷新存活", "同源相对 API base + 刷新 Cookie 轮换",
             "每次刷新页面都被登出"],
        ],
        widths=[2.0, 2.8, 6.6, 4.6],
    )
    add_tip_box(
        doc,
        "**凭据是第一道边界，过滤是第二道，且永远不能只留一道。** "
        "如果把 super-global Token 误配给某个租户，该租户会看到整台设备的所有设备与事件，"
        "**只是被重新贴上了他自己的 tenant_id** —— 不报错，数字看起来还很合理。"
        "因此门户侧过滤必须满足三条：\n"
        "① 按上游报告的**组织名**匹配（FortiSIEM 报的是 `acme`、`acme (3)` 这种名字，不是数字 ID）；\n"
        "② **默认拒绝**——带不出组织归属的记录在作用域生效期间一律排除；\n"
        "③ **租户未声明组织时不启用过滤**（单组织设备上过滤反而会藏掉该租户的全部资产，"
        "这比风险本身更糟）。",
        "safe",
    )

    add_h(doc, "4.2 FortiSIEM Service Provider 模式落地", 2)
    add_para(
        doc,
        "已确认：该设备当前只有 `Super` 一个已初始化组织（`system` 与 `service` 的 "
        "`initialized=false`），处于单租户状态。要支撑真正的多租户，需要完成：",
    )
    add_bullets(doc, [
        "**在设备侧建 Organization**（GUI `Admin > Organizations` → `+ Create`），"
        "每个船东一个组织，设置 Account Type=Service Provider、Support Tier、Access Token Expires In。",
        "**为每个组织分配 Collector**——租户级日志隔离靠 Collector："
        "把 A 客户的防火墙日志源指向 A 客户的 Collector，Collector 只向该租户组织投递。",
        "**在组织内建 Full Admin 用户，由该用户签发 API Token**——"
        "Token 继承创建者权限，这是「组织即边界」的技术前提。",
        "**验证 Token 范围**：分别用租户 Token 与 Super-global Token 查询同一路径，"
        "输出必须不同。相同即说明 Token 建错了用户，隔离已失效。",
    ])
    add_para(
        doc,
        "**端口 443 是硬性要求**：FortiSIEM 7.5.1 的原生 MCP 服务仅在 ClickHouse 部署形态下可用。"
        "若当前是 PostgreSQL 部署，需先在 Supervisor 上启用 ClickHouse"
        "（`CMDB → ClickHouse`），或按官方 ClickHouse 升级指南迁移。",
    )

    add_h(doc, "4.3 租户作用域的实现规则", 2)
    add_table(
        doc,
        ["规则", "实现", "为什么"],
        [
            ["作用域只在有组织名时生效", "`OrgScope.active` 仅当 `org_name` 非空",
             "防止表单默认值把所有租户放进同一作用域，静默藏起彼此的资产"],
            ["默认拒绝无归属记录", "带不出组织属性的记录在作用域生效时排除",
             "无法归属的记录放行，等于重新打开跨租户的口子"],
            ["按名匹配，不按 ID", "分词归一后比较，`acme` 匹配 `acme (3)` 但不匹配 `acmecorp`",
             "上游报告的是名字"],
            ["过滤在截断之前", "先取全量再过滤再分页",
             "先分页后过滤会把本租户自己的记录挤掉"],
            ["过滤覆盖每一条读路径", "资产、事件、日志、看板组件全部经同一 `scope` 模块",
             "只在一半路径上过滤不是防线"],
            ["响应体报告被过滤掉了什么", "每个响应带 `filtered_out` 计数",
             "运维要能区分「边界在工作」与「组织名配错了」"],
            ["跨租户记录返回 404 而非 403", "对象级检查用 404",
             "403 会确认资源存在，404 不会"],
        ],
        widths=[3.6, 6.2, 6.2],
        font_size=9,
    )

    add_h(doc, "4.4 角色与权限", 2)
    add_table(
        doc,
        ["角色", "租户范围", "能力"],
        [
            ["`superadmin`", "不绑定，可指定任意租户",
             "全平台；跨租户聚合视图；租户与用户管理；凭据录入；全部审计读取"],
            ["`tenant_admin`", "永久绑定单一租户", "本租户全部功能；用户管理；看板编排；告警规则；通知通道"],
            ["`security_officer`", "永久绑定单一租户", "本租户读 + 事件处置；不能改租户配置"],
            ["`viewer` / `surveyor`", "永久绑定单一租户", "只读；检验方可导出证据包但不可修改"],
        ],
        widths=[3.4, 4.4, 8.2],
    )
    add_tip_box(
        doc,
        "**授权必须用「枚举路由」的方式审计，不能靠读 handler。** 一个门户有几十个端点，"
        "人工核对必然漏。正确做法是从应用自身导出 OpenAPI 文档，"
        "然后把每条路由对每种角色跑一遍，断言四件事：\n"
        "① 匿名调用者被拒（除一份刻意保留的公开清单：健康探针、登录页需要的元数据与翻译包、"
        "登录、幂等登出、API 文档）；\n"
        "② 租户用户被拒于管理员路由；\n"
        "③ 租户用户**能**到达自己的路由（403 说明权限配错，不是功能没开）；\n"
        "④ superadmin 永不被拒（403 说明权限模型有 bug）。\n"
        "还要单独做**字段级**提权测试：创建用户被拦住而**更新**用户没被拦住的形状，"
        "是藏住提权漏洞的经典位置。",
        "warn",
    )

    # ══════════════════════════ 五、功能设计 ══════════════════════════
    add_h(doc, "五、功能设计", 1)

    add_h(doc, "5.1 菜单结构", 2)
    add_code_block(
        doc,
        """一、安全态势总览（看板可由编排拖拽定制）
   1. 船队总览面板          2. IT 安全态势面板
   3. OT 安全态势面板       4. 自定义面板
二、安全事件
   1. 安全 Top10（Critical / High / Medium / Low 分类汇总）
   2. 性能 Top10            3. 可用性 Top10            4. 变更 Top10
三、资产与许可
   1. 资产清单              2. 网络拓扑                3. 许可证管理
四、AI 助手
五、自动化巡检
六、系统设置
   1. 租户管理   2. 用户管理   3. 告警规则   4. 通知通道
   5. 资产编排   6. 仪表板编排 7. 网络拓扑编排  8. AI 助手配置
七、船舶网络安全和韧性计划
   A. UR 条款追溯
      1. 船舶与资产   船舶台账 / 安全区域 / CBS 系统资产
      2. 变更与软件   变更管理 / 变更审批 / 变更风险评估 /
                      软件清单 / 补丁计划
      3. 网络与防护   防火墙设备 / 防火墙规则 / 防火墙审计 /
                      防病毒状态 / 病毒库更新 / 病毒扫描记录 /
                      防护效果评估 / 恶意软件事件 / 访问控制账户 /
                      权限分配 / 账户变更记录 / 密码策略 /
                      可移动介质管控 / 访问控制日志 / 物理访问登记 /
                      保密信息 / 保密访问审批 / 凭据保险箱 / 保密文档 /
                      文档分发销毁 / 远程访问申请 / 远程访问策略 /
                      远程访问审计 / 远程会话 / 移动及便携设备 /
                      端点安全客户端 / 设备安全检查 / 端点安全策略
      4. 监测与验证   安全异常告警 / 告警处置 / 检测规则库 /
                      网络监测日志 / 日志采集源 / 安全验证计划 /
                      验证范围 / 验证项与整改 / 验证执行 /
                      问题整改 / 诊断工具
      5. 响应与恢复   事件响应预案 / 安全事件 / 事件处置动作 /
                      事件通知升级 / 隔离断点 / 影响评估 / 应急演练 /
                      恢复计划 / 恢复目标 / 恢复演练 / 恢复联系人 /
                      冗余与独立设计 / 受控关机回滚 / 备份记录 /
                      恢复操作记录
      6. 其他         检验证据包 / 证据文档条目 / 检验记录 /
                      UR 条款追溯 / 培训记录 / 组织架构 / 操作审计
   B. 12 项 UR 合规模块
      变更管理 / 软件更新 / 防火墙管理 / 恶意软件防护 /
      访问控制管理 / 保密信息管理 / 远程访问管理 / 移动设备管理 /
      安全异常检测 / 安全功能验证 / 事件响应计划 / 恢复计划""",
        "图 5-1　myPortal 菜单结构（按需求方给定的模块化清单落地）",
    )

    add_h(doc, "5.2 安全态势总览", 2)
    add_para(
        doc,
        "总览页的每一个面板都是**可拖拽编排的看板**。四种预设面板对应四种使用场景，"
        "但它们底层是同一套组件注册表——预设只是「一组预先摆好的组件」，用户可以随时改。",
    )
    add_table(
        doc,
        ["预设面板", "面向", "默认组件组合", "数据来源"],
        [
            ["船队总览", "MSSP 管理员 / 船东高管",
             "租户资产总数、许可证倒计时、事件严重度堆叠条、Top10 风险设备、EPS 趋势",
             "跨租户聚合（superadmin）或本租户"],
            ["IT 安全态势", "岸基 IT 安全团队",
             "边界设备事件、IPS 命中、恶意软件事件、用户风险 Top10、可用性 Top10",
             "FortiSIEM MCP + FAZ EPS"],
            ["OT 安全态势", "船舶网络负责人",
             "按安全区域的事件分布、CBS 资产清单、变更窗口、隔离断点状态",
             "FortiSIEM CMDB + UR 台账"],
            ["自定义面板", "所有人",
             "用户从组件目录中拖拽自选，布局随租户保存",
             "组件目录声明的数据源"],
        ],
        widths=[2.4, 3.2, 6.4, 4.0],
    )

    add_h(doc, "5.3 看板编排与图表插件", 2)
    add_para(
        doc,
        "组件目录（Widget Catalogue）由**一份 JSON 定义**同时驱动后端取数与前端渲染。"
        "后端通过 HTTP 把目录暴露给前端，因此一个租户搭好的看板可以原样交给另一个租户，无需重新部署。",
    )
    add_code_block(
        doc,
        """{
  "id": "siem.incidents.by_severity",
  "version": 1,
  "renderer": "bar",
  "name_key": "widget.siem.incidents.by_severity",
  "category": "incidents",
  "default_size": { "w": 6, "h": 4 },
  "params": {},
  "source": {
    "connector": "fortisiem",
    "op": "incidents.group_by",
    "group_by": "severity"
  },
  "required_params": []
}""",
        "组件目录条目（沿用 fortiportal 已有 26 个组件的定义）",
    )
    add_para(
        doc,
        "**目录的四个渲染器**：`tile`（大数字 + 变化量 + 严重度强调）、`timeseries`（时间轴折线/面积）、"
        "`bar` / `pie`（分类）、`table`（密集数据表，吸顶表头）、`license`（按产品分卡的许可状态）、"
        "`alerts`（近期告警投递）。数据形状由后端归一化成单一契约，"
        "这样一个渲染器能服务多个组件。",
    )
    add_tip_box(
        doc,
        "**目录与渲染器必须共用一份事实来源，并配套漂移守卫。** 具体三条：\n"
        "① 后端组件定义与前端副本必须来自**同一个文件**，守卫比较 id 集合**与**每个 id 的 renderer；\n"
        "② 凡是「另一个文件按名字查找」的字段都要单独守卫——`name_key`、`category`、`renderer` "
        "各自漂移一次，界面就会渲染出一个原始 key（比如 `widget.category.alerting`）；\n"
        "③ 枚举列表（类别、产品、严重度）必须在**两侧都从目录派生**，不能各写一份。\n"
        "守卫要能**失败**：改一个 id 让测试变红，再改回来。永远不会红的守卫等于没写。",
        "warn",
    )

    add_h(doc, "5.4 安全事件的四类 Top10", 2)
    add_table(
        doc,
        ["榜单", "排序依据", "数据来源", "口径说明"],
        [
            ["安全 Top10", "事件严重度（Critical/High/Medium/Low）分类汇总；"
             "设备与用户按风险分排序",
             "`ph_incident.severity_cat` / `severity`；"
             "`get_top_10_risky_devices_incidents` / `get_top_10_risky_users_incidents`",
             "**必须用 `severity` 数值排序、`severity_cat` 字符串分类**——两者并存，用错会得到错误顺序"],
            ["性能 Top10", "资源消耗（CPU / 内存 / 连接数 / 带宽）",
             "FortiSIEM Performance & Health API + 设备 CMDB",
             "无数据时显示「未采集」而非 0；缺数据与数值为零是两件事"],
            ["可用性 Top10", "设备在线率、采集成功率、服务中断时长",
             "`ph_device` 的 discover/event_pulling 状态 + 事件日志心跳",
             "离线判定要有明确的观测窗口写进组件说明"],
            ["变更 Top10", "变更频次、变更失败率、变更引入的事件数",
             "UR 变更管理台账 + `ph_incident.incident_et` 关联",
             "变更窗口内产生的事件要能反查到变更单，这是船级社检验的取证点"],
        ],
        widths=[2.2, 4.4, 5.2, 4.2],
        font_size=9,
    )

    add_h(doc, "5.5 资产清单与网络拓扑", 2)
    add_bullets(doc, [
        "**资产清单**分两个来源：FortiSIEM CMDB 的实时设备（`ph_device`）+ "
        "UR 台账的 CBS 设备清单（`cbs_systems`）。两者通过 `natural_id` / 名称关联，"
        "关联不上时并列展示并标注「未关联」，而不是悄悄合并。",
        "**网络拓扑**从「安全区域 + 设备 + 接口 + 通信关系」生成图，"
        "区分「已核验」与「待确认」两种连接状态——这正是 SOC Essential 产品宣传册里"
        "「工程复核后发布，标明已核验和待确认连接」的业务要求。",
        "**资产编排**（系统设置第 5 项）定义资产的字段、来源映射与展示模板，"
        "让不同租户看到自己那一套资产口径。",
    ])

    add_h(doc, "5.6 许可证管理", 2)
    add_para(
        doc,
        "许可证页与许可证告警**共用同一份取数逻辑**（3.2 节的 FAZ 契约），"
        "按组件而非按总数呈现。到期日从 `licenses.<CODE>.txt` 文本中解析，"
        "状态从 `licenses.<CODE>.status` 取值，原始文本保留在「详情」里供人工核对。",
    )
    add_bullets(doc, [
        "阈值分档：> 60 天（正常）/ 30–60 天（关注）/ 7–30 天（预警）/ < 7 天（紧急）/ 已过期（严重）；",
        "已过期组件（如实测的 FCEM、FCEP）用红色并单独成组，不被正常组件稀释；",
        "**许可证告警规则的触发器只能挂在 FAZ 连接器上**——挂在 SIEM 上的规则永远不触发，"
        "而它在界面上看起来是配置正确的。一条永不触发的告警比没有这个功能更糟。",
    ])

    add_h(doc, "5.7 AI 助手", 2)
    add_para(
        doc,
        "AI 助手由两部分组成：**受控的查询工具目录**（决定能问什么、怎么取数）与"
        "**LLM 编排层**（决定怎么理解问题、怎么表达结果）。两者职责必须分开。",
    )
    add_table(
        doc,
        ["能力", "输入", "实现", "安全边界"],
        [
            ["自然语言查询", "文字或语音转写的问句",
             "LLM 从固定工具目录中挑选工具并填参数 → 门户后端执行 → LLM 组织答案",
             "模型**永不提供租户 ID**（从参数里出现即拒绝）；"
             "模型**永不生成 SQL**（表、列、WHERE 形状、租户过滤全部服务端构建）"],
            ["语音输入", "麦克风音频",
             "优先浏览器 `SpeechRecognition`（特性检测）；iOS Safari / Android WebView 缺失时"
             "回退服务端 STT（MediaRecorder → OpenAI 兼容 `/audio/transcriptions`）",
             "录音不上传到第三方；STT 走门户自有配置"],
            ["数据溯源", "任一答案",
             "答案附带「数据来源」与「取数时刻」",
             "答案必须能点回原始事件 / 资产 / 条款"],
        ],
        widths=[2.2, 2.6, 6.4, 4.8],
        font_size=9,
    )
    add_tip_box(
        doc,
        "**AI 查询面最关键的一条：让模型提供参数，绝不让模型提供语句。** "
        "自然语言查询框把不可信的自由文本放在查询引擎前面一步，用户的问句就是一次提示注入机会。"
        "所以表名、列名、WHERE 形状、租户过滤**全部由服务端构建**，"
        "模型只填值——模型不该影响的东西，根本就不该是参数。\n"
        "另外：**关键词黑名单不是防线**。它挡得住 `DELETE`，挡不住表函数、"
        "`SELECT ... INTO OUTFILE`、集合操作或任意表名。必须做结构化约束："
        "表白名单、拒绝任何表名后跟 `(`、拒绝 `INTO OUTFILE`、拒绝集合操作，"
        "并**检查每一个目标**（`JOIN` 是第二个目标）。",
        "safe",
    )

    add_h(doc, "5.8 通知通道与告警闭环", 2)
    add_para(
        doc,
        "五种通道各是一个 `send(message) -> (ok, detail)` 适配器，统一由调度器调用。",
    )
    add_table(
        doc,
        ["通道", "协议 / SDK", "关键注意"],
        [
            ["企业微信", "群机器人 Webhook，Markdown", "URL 含 `key`，凭据加密存储，API 永不回显"],
            ["飞书 / Lark", "`larksuite/node-sdk`（或 `oapi-sdk-python`）",
             "**不要用 `larksuite/oapi-sdk-nodejs`**，该仓库已归档"],
            ["Microsoft Teams", "Workflows / Power Automate Webhook + Adaptive Cards",
             "**Incoming Webhook 连接器已退役**，不要按旧文档实现"],
            ["钉钉", "机器人 Webhook", "签名校验（加签模式）需带时间戳与 HMAC"],
            ["Email", "SMTP + 可选 STARTTLS", "**同步 SMTP 客户端会阻塞事件循环**，必须放线程里执行"],
        ],
        widths=[2.6, 5.0, 8.4],
    )
    add_tip_box(
        doc,
        "**告警管道是一个整体，它的记录结果必须来自发送器本身。** "
        "规则触发 → 选通道 → 组消息 → 调发送器 → 写投递记录，这条链必须端到端跑一次；"
        "把各部分分开测，测的正是缺陷最容易藏身的接线处。\n"
        "**发送器失败了却记成 `delivered`，比没有记录更糟**——它告诉运维「告警已送达」，"
        "运维于是不再盯着它。\n"
        "还有两条异步纪律：\n"
        "① **绝不在数据库事务里跨越一次设备调用。** 读 → 结束事务 → 干活 → 短事务写回。"
        "否则一次不可达的设备调用会把写锁持有几十秒，症状是「别处登录时提示数据库已锁定」。\n"
        "② **绝不在异步路径里调阻塞 I/O。** SMTP 握手期间整个事件循环被冻住。",
        "warn",
    )

    add_h(doc, "5.9 自动化巡检", 2)
    add_para(
        doc,
        "巡检是「谁来定时替人做检查」的落地：按租户配置巡检项（资产合规、规则有效性、"
        "许可状态、补丁窗口、证据完整性），调度器按计划执行，产出可核验的巡检报告，"
        "问题项自动转成待办并进入对应的 UR 台账模块。",
    )
    add_bullets(doc, [
        "巡检项本身是**元数据驱动的**——与 UR 台账模块共用同一套注册机制，"
        "新增一个巡检项不需要改调度器；",
        "每次巡检留存**执行时刻、输入快照、判定依据、结论**，这是船级社检验时"
        "「证明系统持续有效」的材料；",
        "巡检发现的问题可以一键生成对应台账的待办记录，形成「发现 → 记录 → 整改 → 复核」闭环。",
    ])

    add_h(doc, "5.10 船舶网络安全和韧性计划（UR 合规模块）", 2)
    add_para(
        doc,
        "这一大块是 asiSCRS 已验证的资产：**元数据驱动的模块注册表**。"
        "一个模块注册项同时生成三样东西——",
    )
    add_code_block(
        doc,
        """一个 ModuleSpec 注册项，同时驱动三样东西：

        ┌──────────────────────┐
        │   ModuleSpec 注册项    │
        │  字段 / 选项 / 必填 /  │
        │  搜索 / 筛选 / 权限维度 │
        └──────────┬───────────┘
           ┌───────┼───────────┐
           ▼       ▼           ▼
        ┌────────┐ ┌────────┐ ┌────────┐
        │Pydantic│ │FastAPI │ │前端表单│
        │Schema  │ │CRUD路由│ │与表格  │
        │(自动)  │ │(自动)  │ │(自动)  │
        └────────┘ └────────┘ └────────┘
                     ▲
                     │  /api/meta/modules 下发字段契约""",
        "图 5-2　元数据驱动的三合一生成",
    )
    add_para(
        doc,
        "asiSCRS 已实现 **75 张表 / 68 个业务模块**，覆盖《船舶网络安全和韧性计划 v2.2》"
        "第 3 章的 12 个管理维度。myPortal 直接复用其注册表与 RBAC 映射，"
        "并把它与 FortiSIEM 实时数据接起来——例如「防火墙规则」模块的规则清单来自 "
        "`ph_device` 的策略基线，「变更管理」模块的变更记录同时关联 FortiSIEM 的事件。",
    )
    add_table(
        doc,
        ["UR 条款组", "覆盖的台账模块（摘要）", "与实时数据的接点"],
        [
            ["船舶与资产", "船舶台账、安全区域、CBS 系统资产",
             "CBS 设备与 FortiSIEM `ph_device` 按名称/serial 关联"],
            ["变更与软件", "变更管理、变更审批、变更风险评估、软件清单、补丁计划",
             "变更窗口内的 `ph_incident` 自动关联到变更单"],
            ["网络与防护", "防火墙设备/规则/审计、防病毒状态、病毒库更新、扫描记录、"
             "防护效果评估、恶意软件事件、访问控制账户、权限分配、账户变更、密码策略、"
             "可移动介质、访问控制日志、物理访问登记、保密信息/审批/保险箱/文档、"
             "远程访问申请/策略/审计/会话、移动便携设备、端点客户端/安全检查/策略",
             "防火墙规则与恶意软件事件取自 SIEM 事件；端点安全状态取自 EPP 采集源"],
            ["监测与验证", "安全异常告警、告警处置、检测规则库、网络监测日志、日志采集源、"
             "安全验证计划/范围/验证项与整改/验证执行、问题整改、诊断工具",
             "告警与处置直接对接 SIEM 事件与门户告警投递记录"],
            ["响应与恢复", "事件响应预案、安全事件、处置动作、通知升级、隔离断点、影响评估、"
             "应急演练、恢复计划/目标/演练/联系人、冗余与独立设计、受控关机回滚、"
             "备份记录、恢复操作记录",
             "隔离断点与恢复操作对应 SIEM 事件状态变更（写操作，全程审计）"],
            ["其他", "检验证据包、证据文档条目、检验记录、UR 条款追溯、培训记录、组织架构、操作审计",
             "证据包由台账快照 + 审计日志自动装配，导出为 DOCX/PDF"],
        ],
        widths=[2.2, 8.2, 5.6],
        font_size=8.5,
    )
    add_para(
        doc,
        "**12 项 UR 合规模块**（变更管理、软件更新、防火墙管理、恶意软件防护、访问控制管理、"
        "保密信息管理、远程访问管理、移动设备管理、安全异常检测、安全功能验证、"
        "事件响应计划、恢复计划）不是另一套数据，而是上面 6 组的**聚合视图**——"
        "每个合规模块按条款号聚合对应台账的达成率，并直接给出「检验时该导出哪份材料」。",
    )

    # ══════════════════════════ 六、界面与体验 ══════════════════════════
    add_h(doc, "六、界面与体验设计", 1)

    add_h(doc, "6.1 设计系统", 2)
    add_para(
        doc,
        "沿用 fortiportal 已落盘的设计系统 `design-system/MASTER.md`，"
        "经 `ui-ux-pro-max` 检索复核：企业级安全运营控制台，"
        "风格为「专业深蓝 + 数据密集」，密度档位 8（仪表盘级），"
        "浅色与深色双主题。**深蓝主 + 浅蓝辅 + 红橙强调**，"
        "符合既定的硅谷现代化视觉偏好，不使用赛博朋克 / 矩阵绿。",
    )
    add_table(
        doc,
        ["令牌", "浅色", "深色", "用途"],
        [
            ["`--color-primary`", "#1E40AF", "#3B82F6", "页头、激活导航、主操作"],
            ["`--color-secondary`", "#3B82F6", "#60A5FA", "链接、图表序列 1、次级 chip"],
            ["`--color-accent`", "#D97706", "#F59E0B", "CTA、许可预警、强调"],
            ["`--color-background`", "#F8FAFC", "#0B1220", "页面底色"],
            ["`--color-card`", "#FFFFFF", "#111A2E", "卡片底色"],
            ["`--color-border`", "#DBEAFE", "#24334F", "边框"],
            ["`--severity-critical`", "#C81E1E", "#F87171", "严重级别"],
            ["`--severity-high`", "#B23A0B", "#FB923C", "高危"],
            ["`--severity-medium`", "#A35208", "#FBBF24", "中危"],
            ["`--severity-low`", "#0369A1", "#38BDF8", "低危"],
        ],
        widths=[4.0, 2.6, 2.6, 6.8],
        font_size=9,
    )
    add_bullets(doc, [
        "**字体**：界面与标题 `Inter`（回退 `Microsoft YaHei`）；数字 / 编号 / IP / 时间戳用 "
        "`JetBrains Mono`。**中文必须落到 Microsoft YaHei**，不要用 PingFang SC。",
        "**严重度绝不只靠颜色传达**——颜色 + 文字标签 + 图标三重编码；"
        "浅色深色主题各有独立严重度色阶（同一个色值在两种底色上必须都过 WCAG AA 4.5:1）。",
        "**图标用 Lucide SVG**，不用 emoji；所有可点击元素有 `cursor-pointer` 与可见焦点环。",
        "**响应式断点** 375 / 768 / 1024 / 1440；移动端侧栏转抽屉；表格横向滚动或转卡片；"
        "触摸目标 ≥ 44×44px。",
        "**尊重 `prefers-reduced-motion`**；加载态用骨架屏 + `aria-busy`，不用冻结的空白页。",
    ])

    add_h(doc, "6.2 交互规范要点", 2)
    add_table(
        doc,
        ["范畴", "规范", "常见反模式"],
        [
            ["无障碍", "标题层级连续（h1→h2→h3）、跳过导航链接、键盘可达、"
             "图表有数据表替代视图、装饰性图标 `aria-hidden`",
             "图标按钮无标签、移除焦点环、颜色单独承载语义"],
            ["数据表", "吸顶表头、密度可调、横向滚动有明确提示、导出与筛选状态可见",
             "宽表在手机上溢出、筛选条件被重置"],
            ["图表", "悬停提示 + 键盘聚焦显示数值、缩放可重置、"
             "多序列用不同线型 + 直接标签（不靠色相区分）",
             "六条以上序列、缺数据时崩溃、图表空态看起来像成功"],
            ["表单", "可见标签、就地报错、帮助文字、渐进披露",
             "只有 placeholder、错误只出现在顶部、一上来就抛 20 个字段"],
            ["导航", "三级以内深度的面包屑、URL 可深链、返回行为可预期",
             "返回键失效、导航过载"],
        ],
        widths=[2.0, 7.4, 6.6],
        font_size=9,
    )

    add_h(doc, "6.3 国际化", 2)
    add_bullets(doc, [
        "**默认中文**（`zh-CN`），提供 `en-US`；翻译包在前后端各存一份，"
        "**键集合与取值必须做对等校验**，只在一侧存在的键会在界面上渲染成原始 key。",
        "**语言优先级是一条规则**：用户自己的选择 → 租户的语言 → 门户默认值。"
        "返回语言的接口必须返回**当前生效**的语言，不是存储的原始值——只有服务端知道"
        "「跟随租户」最终解析成什么。",
        "**插值用双大括号**：`{{count}}` 才插值，`{count}` 会原样显示。",
        "**带点的值不是翻译键**：i18next 用 `.` 作分隔符，"
        "`auditAction.channel.update` 会被解析成命名空间 `auditAction.channel` + 键 `update` 而渲染为空。"
        "这类值要拍平成单级键（`auditAction.channel_update`），拍平逻辑集中在一个 helper。",
        "**机器码放 `data-*` 属性**，不进可见文本，也不进 tooltip——否则任何 l10n 检查"
        "都会把它误判为未翻译的字符串。",
        "**英文包不得含中文字符**——这条简单的断言能抓住「翻译了一半」的包，"
        "而键集合相等是抓不到的。",
    ])

    add_h(doc, "6.4 会话与浏览器安全", 2)
    add_bullets(doc, [
        "**访问令牌只放内存**（抗 XSS），**刷新令牌放 httpOnly Cookie**（跨刷新存活），"
        "Cookie 存哈希、每次刷新轮换、重放即视为窃取并吊销整条会话族；"
        "保留几十秒的宽限期，两个标签页同时刷新不是攻击。",
        "**刷新 Cookie 不能单独当 Bearer 凭据**——只带 Cookie 访问受保护端点必须仍然 401，"
        "否则内存里的访问令牌毫无意义。",
        "**登出必须在访问令牌已过期时也能工作**——刷新 Cookie 还活着时会话就还活着，两个都要杀。",
        "**API base 用相对路径**（`/api/v1`）。跨源调用时浏览器会静默扣留 `SameSite=Strict` 的 Cookie，"
        "会话在服务端活着、在前端每次刷新都死，日志里看不出任何异常。",
        "**Service Worker 绝不缓存 `/api`、`/auth`、`/ws`**；只缓存带指纹的构建产物与应用外壳。",
        "**CSP 默认严格**，外壳不得有内联脚本；`style-src 'unsafe-inline'` 在框架设置内联样式时保留。",
        "**nginx 的 `add_header` 只在内层块未声明时才继承**——某个 location 自己设了缓存头，"
        "就会静默丢掉包括外壳页在内的安全响应头。用共享片段，所有相关块都 include。",
    ])

    # ══════════════════════════ 七、数据模型 ══════════════════════════
    add_h(doc, "七、数据模型", 1)

    add_h(doc, "7.1 门户自有库的核心表", 2)
    add_table(
        doc,
        ["表", "关键字段", "说明"],
        [
            ["`tenants`", "id, name, slug, status, locale, fortisiem_org_id, fortisiem_org_name, "
             "fortianalyzer_adom, default_locale",
             "与 FortiSIEM Organization 一一对应。**org_name 才是作用域开关**，org_id 只是辅助"],
            ["`users`", "id, email, display_name, password_hash, role, tenant_id, locale, is_active, last_login_at",
             "`tenant_id` 为空即 superadmin；其余角色永久绑定单一租户"],
            ["`credentials`", "id, tenant_id, product, base_url, token_encrypted, token_expires_at, "
             "client_id, client_secret_encrypted, adom, extra",
             "凭据**只写**：token 与 secret 加密存储，任何接口都不回显；"
             "空值表示「保留原值」而不是「清空」"],
            ["`dashboards`", "id, tenant_id, name, layout(jsonb), is_default, created_by",
             "看板布局存 JSONB，含栅格几何与组件参数"],
            ["`alert_rules`", "id, tenant_id, name, trigger(jsonb), conditions(jsonb), "
             "channel_ids(jsonb), severity, enabled, last_fired_at",
             "**trigger 指向的连接器必须是真正拥有该数据的那个**，否则规则永不触发"],
            ["`notification_channels`", "id, tenant_id, kind, name, config_encrypted, enabled, "
             "health_status, last_test_at",
             "五类通道统一模型；`config_encrypted` 存 Webhook URL / SMTP 口令"],
            ["`alert_deliveries`", "id, rule_id, tenant_id, channel_id, sent_at, ok, detail, "
             "payload_hash",
             "**投递结果由发送器回写**，不是由规则自己声明"],
            ["`audit_logs`", "id, tenant_id, actor_id, action, resource_type, resource_id, "
             "before(jsonb), after(jsonb), ip, user_agent, request_id, created_at",
             "**只追加**，无更新与删除接口；敏感读取也记录"],
            ["`refresh_tokens`", "id, user_id, token_hash, family_id, rotated_at, expires_at, "
             "revoked_at, user_agent, ip",
             "轮换 + 重放检测的落点；给用户「查看并吊销会话」的能力"],
            ["`nlq_history`", "id, tenant_id, user_id, question, tool_name, answer_summary, "
             "latency_ms, created_at",
             "自然语言查询历史；参数与结果摘要可审计"],
            ["`inspection_runs` / `inspection_items`", "id, tenant_id, template_id, started_at, "
             "finished_at, result, snapshot(jsonb)",
             "自动化巡检的执行记录与逐项结论"],
        ],
        widths=[3.4, 6.6, 6.0],
        font_size=8.5,
    )

    add_h(doc, "7.2 与设备数据的映射", 2)
    add_bullets(doc, [
        "**门户库不复制 SIEM 的事件与设备明细**——需要时实时查，避免双写与漂移。"
        "门户只存「自己产生的」数据：看板布局、规则、通道、审计、巡检记录、NLQ 历史。",
        "**资产关联靠外键表**：FortiSIEM 设备（`natural_id` / `name` / `hw_serial_no`）"
        "↔ UR 台账的 CBS 资产。关联不上的记录并列展示并标注，不静默合并。",
        "**所有读接口的响应都带租户作用域元信息**：`scope_active`、`filtered_out`、"
        "`scope_source`，让运维一眼看出边界是在工作还是配错了。",
    ])

    # ══════════════════════════ 八、API 契约 ══════════════════════════
    add_h(doc, "八、API 契约", 1)
    add_para(
        doc,
        "REST 风格，一级前缀 `/api/v1`。列表统一返回 `{items, total, page, page_size}` 信封——"
        "**客户端的类型声明必须与这个信封一致**，否则类型检查器放行、页面却把信封交给"
        "期待数组的组件，渲染出空白。",
    )
    add_table(
        doc,
        ["分组", "端点", "权限"],
        [
            ["认证", "`POST /auth/login`、`POST /auth/refresh`、`POST /auth/logout`、"
             "`GET /auth/me`、`GET /auth/sessions`、`DELETE /auth/sessions/{id}`", "公开 / 登录后"],
            ["租户", "`GET/POST /tenants`、`GET/PATCH /tenants/{id}`、"
             "`GET/PUT /tenants/{id}/credentials`、`POST /tenants/{id}/test-connection`", "superadmin"],
            ["用户", "`GET/POST /users`、`PATCH /users/{id}`、`POST /users/{id}/password`", "superadmin / tenant_admin"],
            ["看板", "`GET/POST /dashboards`、`GET/PATCH/DELETE /dashboards/{id}`、"
             "`GET /widgets/catalog`、`GET /widgets/{id}/data`", "登录后"],
            ["事件与资产", "`GET /incidents`、`GET /incidents/{id}`、`GET /assets`、"
             "`GET /assets/stats`、`GET /assets/{id}`、`GET /top10/{dimension}`", "登录后（自动限租户）"],
            ["拓扑", "`GET /topology`、`GET /topology/nodes`、`PUT /topology/templates/{id}`", "登录后"],
            ["许可证", "`GET /licenses`、`GET /licenses/summary`", "登录后"],
            ["告警", "`GET/POST /alert-rules`、`PATCH/DELETE /alert-rules/{id}`、"
             "`GET /alert-deliveries`、`POST /channels`、`POST /channels/{id}/test`", "登录后"],
            ["AI 助手", "`POST /nlq/query`、`GET /nlq/history`、`POST /nlq/voice/transcribe`、"
             "`GET/PUT /ai/config`", "登录后"],
            ["巡检", "`GET/POST /inspections`、`GET /inspections/{id}`、`POST /inspections/{id}/run`", "登录后"],
            ["审计", "`GET /audit-logs`、`GET /audit-logs/actions`", "superadmin / tenant_admin"],
            ["元数据", "`GET /meta/modules`、`GET /meta/locales`、`GET /meta/menus`", "登录后"],
        ],
        widths=[2.2, 10.0, 3.8],
        font_size=8.5,
    )
    add_tip_box(
        doc,
        "**门户自己也要暴露一个 MCP server。** 它与 FortiSIEM 原生 MCP 是两层："
        "原生 MCP 是**数据源**，门户 MCP 是**面向外部 AI 客户端与自动化执行器的出口**，"
        "因此它继承门户的授权模型——每个工具都带门户的 API Token，"
        "**租户作用域从令牌解析而来，工具参数里永远不出现租户 ID**。"
        "任何绕过 Web UI 触达租户数据的路径（MCP、CLI、Webhook），都必须在审计日志里留痕，"
        "否则租户的记录是不完整的。",
        "info",
    )

    # ══════════════════════════ 九、实施与验收 ══════════════════════════
    add_h(doc, "九、实施路线与验收口径", 1)

    add_h(doc, "9.1 与现有项目的关系", 2)
    add_para(
        doc,
        "经确认，myPortal **以 fortiportal 为基座迭代**：保留已对 172.16.20.48 实机验证过的 "
        "FortiSIEM 连接器、MCP 通道、看板编排、通知适配器与 NLQ 引擎，"
        "替换前端视觉层，并并入 asiSCRS 的 UR 合规模块与元数据驱动注册表。",
    )
    add_table(
        doc,
        ["来源", "直接复用", "需要改造", "不复用及原因"],
        [
            ["fortiportal", "连接器三件套、MCP 通道、看板编排、通知适配器、NLQ 引擎、"
             "会话与审计、设计系统令牌、"
             "**`tools/mock_appliance/app.py`（21 KB 单端口三设备模拟器）**、"
             "**`mobile/`（Capacitor 7 原生壳）**、"
             "**10 个前端验证脚本**（`verify-i18n-keys` / `verify-responsive` / "
             "`prove-deployment-real` / `check-session-ui` 等）、"
             "**11 个后端探测脚本**（`probe_fortisiem` / `probe_fortianalyzer` / "
             "`check_live_*` / `verify_real_device`）",
             "**FAZ 连接器需按 3.2 的 8.x 契约重写**（7.x 的 `/jsonrpc` 在本机返回 -11）；"
             "许可证取数改挂 FAZ；"
             "**四处 `phoenix_*` 表名必须改为 `ph_incident` / `ph_device`（见 3.1.3）**；"
             "NLQ 与事件日志的表白名单需重建；"
             "前端视觉层按本方案重做",
             "旧的 `/jsonrpc` FAZ 契约（在本机不可用）、mock 适配器默认值"
             "（必须证明是关的，否则镜像里跑的是假门户）"],
            ["asiSCRS", "元数据驱动模块注册表（`ModuleSpec` + `FieldSpec`，13 种控件 kind）、"
             "75 张表模型、**68 条 module→resource 显式映射**、"
             "数据范围（按船）、`crud.py` 路由工厂、"
             "**声明式 DOCX 模板引擎（`docgen.py`，783 行）**、证据包、审计日志",
             "接入 FortiSIEM 实时数据；补 i18n（asiSCRS **完全没有** i18n，文案硬编码中文）；"
             "补通知发送（asiSCRS **只有台账模型，没有发送通道**）；"
             "补多租户（asiSCRS **没有 `tenant_id`**，只有船舶维度数据范围）；"
             "**补 Alembic**（现靠 `create_all`，无迁移）",
             "asiSCRS 的 Vue 前端（与技术栈决策不符）"],
            ["fcs-master", "**`--asi-*` 设计令牌体系（110 个变量，8 级严重度的文字/底色/边框三件套）**、"
             "深色侧栏与响应式抽屉、状态色映射表、三态容器模式、"
             "移动端与打印样式",
             "仅作视觉参考，不引入代码；**严重度色阶建议取 fcs-master 的三件套**"
             "（`--asi-critical` + `--asi-critical-bg` + `--asi-critical-border`），"
             "比 fortiportal 的单色阶更完整",
             "其单体 Demo 形态与后端结构；**该项目的 `style.css` 有 7 个被引用但未定义的变量**"
             "（`--asi-danger-bg/border/text`、`--asi-warning-bg/border/text`、`--asi-info-text`），"
             "抄令牌时须一并补齐"],
        ],
        widths=[2.4, 5.0, 5.0, 3.6],
        font_size=8.5,
    )

    add_h(doc, "9.2 验收口径（不是「看起来正常」）", 2)
    add_bullets(doc, [
        "**空看板不等于验收通过。** 每个组件都要在有数据的条件下渲染过——"
        "空态永远渲染得「看起来没问题」，而格式化时间戳、排序序列、聚合计数这些代码一行都没跑过。",
        "**对着实机验收，不能只对着 mock。** mock 模式恰好掩盖这类缺陷：字段名错、缺键、载荷不全。",
        "**明确记录证据来自哪一次运行。** 多个开发服务器并存时，浏览器可能连的是另一个源"
        "（甚至是另一个环境）。要打印 origin 与解析后的 API base，并确认被服务的模块确实反映了本次改动。",
        "**确认端口属于你的进程。** 同端口上遗留的旧服务会拿旧代码回答，"
        "让改动看起来没生效；`git worktree list` 也要看，同仓库的另一个 worktree 会占着你以为属于自己的端口。",
        "**按用户的方式导航，不要靠输入 URL。** 访问令牌只在内存（刻意的 XSS 加固），"
        "整页加载会丢会话，于是按 URL 导航的验证脚本每次都在测登录页。",
        "**每个组件都要在真实载荷下渲染，并在真实后端上走一遍每条路由，统计控制台错误。**",
        "**手机宽度下验证布局。** `tsc` 与单元测试对 375px 下的横向溢出一无所知。",
    ])

    add_h(doc, "9.3 GitHub 参照", 2)
    add_para(
        doc,
        "需求要求「参考 GitHub 上相关的项目」。结论先行：**社区里没有能直接替代 "
        "FortiSIEM 原生门户的多租户门户**。找到的东西分三类，都有各自的用处，"
        "但没有一个能整体满足需求。",
    )
    add_table(
        doc,
        ["项目", "星标 / 许可", "我们取了什么", "明确没取什么，为什么"],
        [
            ["`rstierli/fortianalyzer-mcp`", "★17 · MIT · Python",
             "按功能域拆工具的目录结构；FAZ 的 JSON-RPC 认证与端点形状",
             "**不直接依赖其代码**——它是给 AI 客户端用的 MCP server，"
             "会话模型、租户模型、审计模型与人用 Web 门户完全不同"],
            ["`rstierli/fortianalyzer-api-docs`", "★8 · Fortinet 维护",
             "FAZ 调用形状、登录登出流程、ADOM 语义",
             "在本机 7.6.5 上 `/jsonrpc` 契约已不适用，实测需改用 `flatui_auth`/`flatui_proxy`"],
            ["`paoloamato2/fortinet-mcp-server`", "★11 · MIT · Python",
             "「类型化工具 + 少量透传」的取舍；最小权限原则；异步 httpx 客户端形状",
             "**通用透传工具不做**——把整个 API 面交给模型，租户隔离立刻失效"],
            ["`alpadalar/fortigate-mcp-server`", "★43 · MIT · Python",
             "`allow_writes` 默认 false（模型侧只读）；HTTP 模式须 `auth.require_auth`；"
             "未认证 HTTP 不绑定到比回环更宽的范围",
             "面向 FortiOS 防火墙，不是 SOC 数据面"],
            ["`ry-ops/fortigate-mcp-server`", "★5 · MIT · Python",
             "工具参数要「友好」（用 CIDR 而不是 ip mask）",
             "同上是防火墙侧，不是数据面"],
            ["`react-grid-layout/react-grid-layout`", "★22.4k · MIT · TS",
             "**直接依赖**（1.4.4）——拖拽、缩放、响应式断点、布局可序列化",
             "注意 npm 最新是 2.x（模块化导出），升级需改 `WidthProvider` 用法"],
            ["`fortinet-fortisoar/solution-pack-soc-overview-sankey`", "MIT · Fortinet 官方组织",
             "官方组件的形状：Sankey 类组件也需声明元数据（标题键、分类、默认尺寸、参数、来源）",
             "不拷贝代码"],
            ["`BESTSELLER/pyfortianalyzer`", "★5 · Apache-2.0",
             "调用约定（`adom` 默认 root、`verify` 默认 True）与「状态对象」判定",
             "本机需按实测契约重写"],
        ],
        widths=[4.4, 2.6, 5.0, 4.0],
        font_size=8,
    )
    add_para(
        doc,
        "**明确不参考的方向**：复用 `wazuh/wazuh` 的门户前端（体量与数据模型完全不同）；"
        "直接套用 `tabler` / `react-admin` / `ant-design-pro` 这类后台模板"
        "（是通用 CRUD 后台的壳，没有 SOC 的信息密度，也没有审计与租户模型）；"
        "自己造一个通用 MCP 透传 server（多一层，且丢掉 FortiSIEM 的鉴权语义）；"
        "拷贝 Grafana 源码（AGPL-3.0，只借鉴其「插件元数据 + JSON 选项」的架构思想）。",
    )

    add_h(doc, "9.4 主要风险与对策", 2)
    add_table(
        doc,
        ["风险", "影响", "对策"],
        [
            ["FortiSIEM 设备仍为单租户（仅 Super 一个组织）",
             "多租户隔离无法端到端验证", "P0 前置任务：在设备侧建 Organization 与 Collector，"
             "并用「租户 Token 与 Super Token 查询结果必须不同」验证隔离"],
            ["FAZ 8.x 契约与公开文档不一致",
             "许可证与 EPS 功能不可用", "连接器做多候选路径 + 回退链 + 契约探测缓存；"
             "已实测出可用契约并写入本方案"],
            ["SIEM 侧无许可证 API",
             "许可证告警的触发器选错就永不触发", "触发器只挂 FAZ 连接器；"
             "回归测试让假 SIEM 客户端的 `get_license()` 直接抛断言——"
             "「如果代码去问 SIEM 就会红」"],
            ["FortiDeceptor REST 表面只在 FNDN",
             "诱捕命中字段名需校准", "非硬依赖；候选路径 + 多候选字段映射 + 自诊断告警"],
            ["系统代理劫持私有网段请求",
             "连接超时被误判为设备宕机", "连接器 `trust_env=False`、通知器 `trust_env=True`，"
             "两处各有一条测试钉死"],
            ["前端构建产物默认启用 mock 适配器",
             "镜像里跑的是假门户，任何密码都能登录", "构建期把 flag 钉死，"
             "并在**构建产物**上断言；运行时探针用伪造凭据必须得到 401"],
            ["i18n 键漂移（后端与前端各一份翻译包）",
             "界面渲染出原始 key", "键集合与取值的对等测试 + 英文包不含中文字符的断言"],
            ["看板布局这类「用户自己创作的状态」最容易在某一层被丢掉",
             "租户搭的看板在不同层之间不翼而飞", "往返测试：逐项断言回来，包含几何尺寸；"
             "并断言另一个租户既读不到也写不了"],
        ],
        widths=[4.6, 4.0, 7.4],
        font_size=8.5,
    )

    # ══════════════════════════ 附录 ══════════════════════════
    add_h(doc, "附录 A　实机探测记录", 1)
    add_para(
        doc,
        "探测时间 2026-11-18。完整机读记录见 `myPortal/_ref/device_probe_findings.json`。",
    )
    add_table(
        doc,
        ["设备", "地址", "版本", "认证方式", "探测结论"],
        [
            ["FortiSIEM", "172.16.20.48:443", "7.5.1（MCP 服务端 FortiSIEM_MCP v1.24.0）",
             "OAuth 2.0 Client Credentials（表单编码，TTL 900s）",
             "REST + MCP 均可用；17 个 MCP 工具全部枚举成功；"
             "`ph_device`/`ph_incident`/`events` 均可查；"
             "4 条 v2 事件类 REST 路径确认 404"],
            ["FortiAnalyzer", "172.16.21.12:443", "v7.6.5-build3653 251215 (GA.M)",
             "`flatui_auth` + `flatui_proxy`（Cookie 会话）",
             "登录成功并取得 `CURRENT_SESSION`；`/gui/sys/license` 与 `/gui/sys/monitor` 取数成功；"
             "旧版 `/jsonrpc` 契约返回 -11"],
            ["FortiDeceptor", "—", "—", "—", "本次未提供设备，接口契约待确认"],
        ],
        widths=[2.2, 2.6, 3.4, 3.4, 4.4],
        font_size=8,
    )

    add_h(doc, "附录 B　设计决策速查", 1)
    add_table(
        doc,
        ["决策点", "选择", "否定的替代方案与原因"],
        [
            ["项目基座", "以 fortiportal 迭代", "全新绿地：重复验证已验证过的接口契约，浪费时间；"
             "monorepo：本期无跨项目发布需求，增加复杂度"],
            ["前端栈", "React 18 + TS + Vite + Tailwind + shadcn/ui",
             "Vue 3 + Element Plus：asiSCRS 现成，但与 fortiportal 的看板/NLQ/i18n 资产割裂；"
             "Ant Design Pro：定制成本高、偏通用 CRUD 风格"],
            ["租户隔离", "FortiSIEM SP 模式 + `cust_org_id` 二道过滤",
             "单组织 + 门户过滤：隔离强度弱；每租户独立实例：成本过高"],
            ["LLM 后端", "OpenAI 兼容接口 + FortiSIEM MCP 受控数据源",
             "只用 FortiSIEM 内置 AI：能力受限，无法支撑自由问句"],
            ["许可证数据源", "FortiAnalyzer（与 SIEM 并列的连接器）",
             "门户侧配置维护：数据不可信；Deceptor 一起纳入：本期无设备，扩大范围"],
        ],
        widths=[2.4, 5.0, 8.6],
        font_size=8.5,
    )

    # 页眉页脚
    add_header_text(doc, "myPortal 产品设计方案 V1.0　|　BinQsoft")
    add_footer_page_numbers(doc, "myPortal 产品设计方案 V1.0")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(OUT))
    print(f"saved: {OUT}")
    print(verify(str(OUT)))


if __name__ == "__main__":
    build()
