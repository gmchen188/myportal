# -*- coding: utf-8 -*-
"""生成《myPortal 项目开发计划 V1.0》Word 文档。"""

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
    add_para,
    add_table,
    add_tip_box,
    add_toc_field,
    add_wide_table,
    init_styles,
    verify,
)

import os as _os
OUT = Path(_os.environ.get(
    "MP_PLAN_OUT",
    str(Path(__file__).resolve().parent.parent / "Docx" / "myPortal 项目开发计划 V1.0.docx"),
))


def build() -> None:
    doc = Document()
    init_styles(doc)

    # ══════════════════════════ 封面 ══════════════════════════
    add_cover(
        doc,
        "myPortal 项目开发计划",
        "多租户 Fortinet 安全运营门户 · 任务分解与交付节奏",
        "版本 V1.0　|　2026-11-18　|　BinQsoft 船舶网络安全与韧性平台",
    )

    # ══════════════════════════ 致读者 ══════════════════════════
    add_h(doc, "致读者", 1)
    add_para(
        doc,
        "本计划是《myPortal 产品设计方案 V1.0》的执行面。方案回答「做成什么样」，"
        "本计划回答「按什么顺序做、每一步怎么验证、什么时候能交付」。",
    )
    add_para(
        doc,
        "计划里的每一个任务都遵循同一条纪律：**先写会失败的测试，再写让它通过的最小实现，"
        "再提交**。任务粒度控制在 2–5 分钟的专注工作量，文件路径写到具体位置，"
        "验证命令连同预期输出一起给出——"
        "让任何一个接手的人都不需要猜「该改哪个文件」「怎么算做完了」。",
    )
    add_para(
        doc,
        "配套文档：《myPortal 产品设计方案 V1.0》（架构与数据契约）、"
        "`myPortal/_ref/device_probe_findings.json`（实机探测的机读记录）。",
    )

    add_toc_field(doc)

    # ══════════════════════════ 一、总体 ══════════════════════════
    add_h(doc, "一、计划总览", 1)

    add_h(doc, "1.1 目标与范围", 2)
    add_para(
        doc,
        "交付一个**多租户的 Fortinet 安全运营门户**：租户登录后只看到自己的资源，"
        "管理员可跨租户聚合；支持资产统计与许可证到期告警；"
        "支持微信 / 飞书 / Teams / 钉钉 / 邮件五类自动告警；"
        "看板可拖拽编排、图表可插件化；中英双语随设置生效自动切换；"
        "支持自然语言与语音查询；全量操作可审计；"
        "并承载 IACS UR 条款追溯与 12 项合规模块的台账能力。",
    )
    add_table(
        doc,
        ["维度", "本期交付", "本期不做（留接口）"],
        [
            ["数据源", "FortiSIEM 7.5.1（REST + 原生 MCP）、FortiAnalyzer 7.6.5",
             "FortiDeceptor（接口待确认）、FortiManager、FortiCloud"],
            ["多租户", "SP 模式：Organization + 组织专属 Token + `cust_org_id` 二道过滤",
             "跨实例联邦、计费与套餐"],
            ["AI 助手", "固定工具目录 + OpenAI 兼容 LLM + 浏览器语音 / 服务端 STT 回退",
             "多轮自主 Agent、跨租户分析、模型微调"],
            ["合规模块", "asiSCRS 的 75 表 / 68 模块元数据注册表全量并入 + 实时数据接点",
             "自动生成检验证据包（先做导出，生成放二期）"],
            ["移动端", "响应式 Web（375px 起）", "Capacitor 原生壳（复用 fortiportal 的 native 模块）"],
            ["部署", "Docker Compose 栈（网关 + API + DB）", "K8s Helm、多活、灰度发布"],
        ],
        widths=[2.0, 7.4, 6.6],
        font_size=9,
    )

    add_h(doc, "1.2 团队与角色", 2)
    add_table(
        doc,
        ["角色", "人数", "主要职责", "关键交付物"],
        [
            ["Tech Lead / 架构", "1", "接口契约裁决、跨模块一致性、代码评审",
             "连接器契约、目录格式、API 契约文档"],
            ["后端工程师", "2", "连接器、作用域、告警管道、NLQ 引擎、UR 模块后端", "backend/"],
            ["前端工程师", "2", "设计系统落地、看板编排、组件注册表、i18n、响应式", "frontend/"],
            ["测试 / 质量", "1", "契约测试、授权矩阵、浏览器验证、漂移守卫", "tests/、scripts/"],
            ["产品 / 领域", "0.5", "UR 条款映射、验收口径、船级社检验要求对齐", "需求追溯矩阵"],
        ],
        widths=[3.0, 1.4, 6.2, 5.4],
    )

    add_h(doc, "1.3 里程碑", 2)
    add_wide_table(
        doc,
        ["里程碑", "周期", "主题", "完成标志（可验证）", "依赖"],
        [
            ["M0", "第 1 周", "基座迁移与契约固化",
             "代码基线就位；**连接器契约测试对着实机全绿**；"
             "**四处失效表名已修正**（否则 AI 助手在真机上全哑）；"
             "**mock 与真机保真度测试通过**（mock 不再是假绿灯）",
             "—"],
            ["M1", "第 2–3 周", "多租户与认证",
             "租户 Token 与 Super Token 查询结果**必须不同**（设备侧隔离验证）；"
             "授权矩阵四条断言全绿；对象级与字段级提权测试全绿",
             "M0；设备侧建好 Organization"],
            ["M2", "第 4–5 周", "看板与组件目录",
             "看板可拖拽、可缩放、可保存、可跨租户复制；"
             "目录漂移守卫能变红；**每个组件在有数据载荷下渲染通过**",
             "M1"],
            ["M3", "第 6–7 周", "资产、许可证、拓扑",
             "许可证到期日与实机 FAZ 载荷逐项一致；"
             "许可证告警**确实会触发**（假 SIEM 客户端的 get_license 抛断言）；"
             "拓扑区分已核验 / 待确认连接",
             "M1；FAZ 连接器"],
            ["M4", "第 8–9 周", "AI 助手与自然语言查询",
             "模型**无法**影响 SQL 结构与租户过滤（结构化守卫全绿）；"
             "语音在缺 `SpeechRecognition` 的环境回退服务端 STT；"
             "答案可溯源到原始数据",
             "M2"],
            ["M5", "第 10–11 周", "告警管道与通知通道",
             "五类通道对着**真实 socket**（本地 HTTP 收件箱 + SMTP sink）验证；"
             "投递记录由发送器回写；事务与事件循环两条纪律有测试钉死",
             "M1、M3"],
            ["M6", "第 12–14 周", "UR 合规模块并入",
             "asiSCRS 全部 68 个模块注册进 myPortal；"
             "新增一个台账模块**前端零改动**；12 项合规模块的达成率可计算",
             "M1"],
            ["M7", "第 15 周", "i18n、审计、巡检与打磨",
             "中英键集合与取值对等；英文包不含中文字符；"
             "审计覆盖全部变更与敏感读取；巡检报告可导出",
             "M2–M6"],
            ["M8", "第 16 周", "验收与交付",
             "对着实机的端到端验收全部通过；"
             "**镜像里跑的是真门户**（伪造凭据得 401）；"
             "部署文档、运维手册、需求追溯矩阵齐备",
             "M0–M7"],
        ],
        widths=[1.4, 1.8, 3.4, 9.4, 4.0],
        font_size=8,
    )

    add_h(doc, "1.4 关键路径与前置依赖", 2)
    add_bullets(doc, [
        "**最长的一条链是 M0 → M1 → M3 → M5 → M8**，因为它同时依赖设备侧的 SP 改造。",
        "**设备侧是外部依赖，不在本仓库的控制范围内**："
        "在 172.16.20.48 上创建 Organization、分配 Collector、由组织内 Full Admin 用户签发 Token。"
        "M1 之前必须完成，否则隔离无法端到端验证。**这一条要立刻启动。**",
        "**M2（看板）与 M4（AI）的组件目录是共用契约**，必须先定目录格式再并行开发。",
        "**M6（UR 模块）可以与 M2–M5 并行**——它几乎不依赖实时数据面，"
        "但依赖 M1 的数据范围与 RBAC 模型。",
    ])
    add_tip_box(
        doc,
        "**排期上的一个现实提醒**：M1 的设备侧准备是外部依赖，"
        "不能等到 M1 开始才去推。建议在 M0 期间就把 Organization 的创建、"
        "Collector 的分配、Token 的签发走完一遍（哪怕用测试组织），"
        "这样 M1 的第一天就能写隔离测试，而不是先花两天排设备。",
        "warn",
    )

    # ══════════════════════════ 二、工程基线 ══════════════════════════
    add_h(doc, "二、工程基线与代码组织", 1)

    add_h(doc, "2.1 仓库结构", 2)
    add_code_block(
        doc,
        """myPortal/
├── backend/
│   ├── app/
│   │   ├── main.py                FastAPI 入口（CORS / 全局异常 / lifespan）
│   │   ├── config.py              pydantic-settings，全部可环境变量覆盖
│   │   ├── db.py                  异步引擎 + SessionLocal
│   │   ├── models.py              门户自有库 ORM（11 张核心表）
│   │   ├── tenancy.py             Principal / TenantContext / 角色矩阵
│   │   ├── security.py            口令哈希 + JWT 签发校验 + 刷新令牌轮换
│   │   ├── connectors/
│   │   │   ├── fortisiem.py       REST + 原生 MCP 双通道
│   │   │   ├── fortianalyzer.py   flatui_auth + flatui_proxy（多候选回退）
│   │   │   └── fortideceptor.py   候选路径 + 多候选字段映射 + 自诊断
│   │   ├── services/
│   │   │   ├── scope.py            租户作用域（OrgScope / deny-by-default）
│   │   │   ├── widgets.py          组件目录 + 取数 + 归一化
│   │   │   ├── nlq.py              NLQ 引擎 + 固定工具目录
│   │   │   ├── notifiers.py        五类通道适配器
│   │   │   ├── alerts.py           告警调度（读 / 干活 / 写 三段式）
│   │   │   ├── audit.py            审计写入（append-only）
│   │   │   ├── fleet.py            跨租户聚合
│   │   │   └── registry/           ★ 元数据驱动模块注册表（asiSCRS 移植）
│   │   ├── i18n/                  zh_CN.json / en_US.json
│   │   ├── routers/               auth / tenants / data / ops / ur
│   │   └── mcp_server.py          门户侧 MCP（对外暴露租户作用域能力）
│   └── tests/
├── frontend/
│   ├── src/
│   │   ├── components/            ui/ charts/ widgets/ layout/ ur/
│   │   ├── pages/                 17 个页面（对应菜单结构）
│   │   ├── widgets/registry.tsx   组件注册表（与后端目录同源）
│   │   ├── i18n/locales/          zh-CN.json / en-US.json
│   │   └── hooks/ store/ api/
│   └── scripts/                   verify-responsive / verify-i18n / prove-deployment-real
├── Docx/                           本方案与开发计划
├── docs/
│   ├── API_CONTRACT.md            ★ 契约文档（下一个实现者信任的东西）
│   ├── REQUIREMENTS-TRACEABILITY.md
│   └── device-contract.md         实机探测结论
├── scripts/
│   ├── probe_fortisiem.py         实机探测（凭据走环境变量）
│   ├── probe_fortianalyzer.py
│   └── check_live_*.py            用连接器本身打真实设备
└── design-system/MASTER.md        设计系统唯一事实来源""",
        "图 2-1　仓库结构",
    )

    add_h(doc, "2.2 依赖清单", 2)
    add_table(
        doc,
        ["位置", "依赖", "版本约束", "说明"],
        [
            ["backend", "fastapi / uvicorn[standard]", ">= 0.115 / >= 0.32", "异步路由与 ASGI 服务器"],
            ["backend", "sqlalchemy[asyncio] / asyncpg / aiosqlite / alembic", ">= 2.0.36",
             "异步 ORM；SQLite 供本地开发，生产 Postgres"],
            ["backend", "httpx", ">= 0.27", "**设备连接器必须 `trust_env=False`**"],
            ["backend", "pyjwt / cryptography / bcrypt", ">= 2.9 / >= 43 / >= 4.2",
             "JWT、Fernet 凭据加密、口令哈希"],
            ["backend", "apscheduler", ">= 3.10", "告警轮询、许可巡检、Top10 预聚合"],
            ["backend", "pydantic / pydantic-settings", ">= 2.9 / >= 2.6", "校验与配置"],
            ["backend", "ruff / pytest / pytest-asyncio", ">= 0.8 / >= 8.3 / >= 0.24",
             "**lint 配置放仓库根**，否则子目录外的脚本会无人审查"],
            ["frontend", "react / react-dom / typescript", "18.3 / 5.6", "沿用既有资产"],
            ["frontend", "vite / @vitejs/plugin-react / tailwindcss", "5.4 / 4.3 / 3.4",
             "构建链"],
            ["frontend", "@tanstack/react-query / zustand", "5.59 / 4.5", "服务端状态 / UI 状态"],
            ["frontend", "react-grid-layout / recharts / lucide-react", "1.4.4 / 2.13 / 0.454",
             "看板编排 / 图表 / 图标"],
            ["frontend", "i18next / react-i18next", "23.16 / 15.1", "国际化"],
            ["frontend", "vitest / @testing-library/react / jsdom", ">= 2.1 / >= 16.1 / >= 25",
             "单测；jsdom 需 `ResizeObserver` stub 否则图表测试全挂"],
        ],
        widths=[1.8, 6.0, 3.2, 5.0],
        font_size=8.5,
    )

    add_h(doc, "2.3 开发规约", 2)
    add_bullets(doc, [
        "**每个任务一个提交**，提交信息用 `feat:` / `fix:` / `docs:` / `test:` 前缀。",
        "**并行开发时按路径 `git add`，绝不 `git add -A`**——一条 blanket stage 会把别人"
        "半写的组件、还没改完的测试一起扫进你的提交。",
        "**改文件前先重读**：别的 agent 可能在你读与写之间改过它，"
        "对过期文本的 patch 要么失败，要么静默回退他们的修改。",
        "**自己创建的孤儿代码要清掉**（因你的改动而未使用的 import / 变量 / 函数），"
        "但**不要删别人留下的死代码**——发现了就在评审里提一句。",
        "**每次提交前跑**：`ruff check .` + `pytest` + `tsc --noEmit` + `vitest run`。",
    ])

    # ══════════════════════════ 三、任务分解 ══════════════════════════
    add_h(doc, "三、任务分解", 1)
    add_para(
        doc,
        "以下任务按里程碑组织。任务粒度为 2–5 分钟的专注工作量——"
        "「实现认证系统」不是任务，「创建 User 模型并加 email 字段」才是。"
        "实施时建议用 `subagent-driven-development` 技能逐任务派发，"
        "每个任务由独立的子代理执行，再经「规格符合性 → 代码质量」两阶段评审。",
    )

    # ─────────── M0 ───────────
    add_h(doc, "3.1 M0　基座迁移与契约固化（第 1 周）", 2)

    add_h(doc, "任务 M0-1　迁移代码基线", 3)
    add_bullets(doc, [
        "**Objective**：把 fortiportal 后端与前端复制为 myPortal 基线，改名与清理。",
        "**Files**：Create `backend/app/**`、`frontend/src/**`；Create `README.md`、`.gitignore`、`.env.example`。",
        "**Step 1**：复制代码，删除 `dist/`、`node_modules/`、`.venv/`、`*.db`、`__pycache__`。",
        "**Step 2**：全局替换品牌标识 `FortiSight` → `myPortal`（含包名、页面标题、邮件模板）。",
        "**Step 3**：`.env.example` 中删除全部真实凭据，只留占位与注释。",
        "**Step 4**：`git init` 并提交：`git commit -m \"chore: import fortiportal baseline as myPortal\"`。",
        "**Step 5**：`cd backend && python -m pytest -q` 应全绿；`cd frontend && npm run build` 应成功。",
    ])

    add_h(doc, "任务 M0-2　建立实机契约测试", 3)
    add_bullets(doc, [
        "**Objective**：把本次实机探测到的契约固化为可重跑的测试。",
        "**Files**：Create `backend/tests/test_fortisiem_contract.py`、"
        "`backend/tests/test_fortianalyzer_contract.py`；Create `scripts/probe_fortisiem.py`、"
        "`scripts/probe_fortianalyzer.py`。",
        "**Step 1 写失败测试**（凭据从环境变量读，脚本里不含明文）：",
    ])
    add_code_block(
        doc,
        '''def test_siem_oauth_token_shape(live_siem):
    """令牌必须是表单编码换取的 client_credentials，TTL 900s。"""
    tok = live_siem.mint_token()
    assert tok.access_token
    assert tok.expires_in == 900          # 实测值；设备若变更应显式失败


def test_siem_incident_rest_path_is_404(live_siem):
    """v2 事件 REST 路径在 7.5.1 上是 404 —— 锁死这个事实，
    防止有人改回这条永远空的路径。"""
    r = live_siem.raw_get("/phoenix/rest/pub/v2/query/incidents")
    assert r.status_code == 404


def test_siem_mcp_tools_present(live_siem):
    names = set(live_siem.list_mcp_tools())
    assert "query_fsm_postgres" in names
    assert "get_top_10_risky_devices_incidents" in names
    assert len(names) == 17


def test_faz_license_expiry_present(live_faz):
    """FAZ 许可载荷的到期日必须能解析出来 —— 许可证告警的数据源。"""
    lic = live_faz.get_license()
    assert lic["ADOM"]["status"]
    assert "过期" in lic["ADOM"]["txt"]''',
        "M0-2 契约测试（节选）",
    )
    add_bullets(doc, [
        "**Step 2**：`pytest backend/tests/test_fortisiem_contract.py -v` —— "
        "无凭据时应 **SKIP** 并给出明确原因，**不是 PASS**。",
        "**Step 3**：实现探针脚本（凭据走 `FS_HOST` / `FS_CLIENT_ID` / `FS_CLIENT_SECRET` / "
        "`FAZ_BASE` / `FAZ_USER` / `FAZ_PASS` 环境变量）。",
        "**Step 4**：`FS_HOST=... pytest backend/tests/test_fortisiem_contract.py -v` 应全绿。",
        "**Step 5**：提交 `git commit -m \"test: pin live FortiSIEM/FortiAnalyzer contracts\"`。",
    ])

    add_h(doc, "任务 M0-3　校准并加固 mock appliance", 3)
    add_bullets(doc, [
        "**Objective**：把 fortiportal 已有的 `tools/mock_appliance/app.py`（21 KB，"
        "单端口模拟三设备）**校准到实测契约**，并让它能揭穿而不是掩盖缺陷。",
        "**Files**：Modify `tools/mock_appliance/app.py`；Create `backend/tests/test_mock_fidelity.py`。",
        "**Step 1**：先补一个**保真度测试**——把「mock 服务的路径集合」与"
        "「实机实测的路径可达性表」对比。",
    ])
    add_tip_box(
        doc,
        "**现有 mock 与真机有三处偏差，照搬会让整套测试给出假绿灯：**\n"
        "① **它服务了真机上 404 的路径。** mock 实现了 "
        "`/phoenix/rest/pub/v2/query/incidents`、`/v2/cmdb/devices`、`/v2/query/license`，"
        "而这三者在 172.16.20.48 上**全部 404**。结果是：一个只对着 mock 写对的连接器，"
        "在真机上永远拿不到数据——**而测试全绿**。mock 必须让这些路径**返回 404**。\n"
        "② **它的表名是 `phoenix_*`。** mock 用 `phoenix_device` / `phoenix_incident`，"
        "真机上是 `ph_device` / `ph_incident`。mock 必须改用真表名，"
        "否则连接器照着 mock 写，连真机都连不上。\n"
        "③ **它的 MCP 工具参数名是 `query`。** 真机实测要求参数名为 **`sql`**"
        "（传 `query` 报 `Input validation error: 'sql' is a required property`）。"
        "mock 必须与真机一致。\n"
        "**这三条合起来的后果**：现有 mock 让「mock 模式全绿」与「真机可用」完全脱钩。"
        "而 mock 模式恰好是**默认**——"
        "所以一个从没连过真机的连接器，可以带着一份完美的测试报告交付。",
        "safe",
    )
    add_bullets(doc, [
        "**Step 2**：mock **必须拒绝错误的凭据**——否则它无法区分「连接器是好的」与「连接器是坏的」。",
        "**Step 3**：mock **必须带两个组织**（实测真机有 system=0 / service=2 / Super=1 三个 domainId），"
        "使租户作用域可被观察而非仅被声明。",
        "**Step 4**：mock **必须变换字段拼写**（camelCase / snake_case 混用），把归一化层的容错钉死。",
        "**Step 5**：mock **必须发布契约标记**，使该端口上的过期实例不会给出假通过。",
        "**Step 6**：无 mock 时**跳过**契约测试并让跳过原因可见——诚实的跳过。",
        "**Step 7**：**扰动证明**——把连接器里的一个 URL 改错，确认测试变红，再改回来。",
        "**Step 8**：新增一条**端到端保真测试**：同一组查询分别打 mock 与真机，"
        "断言两者返回的**字段集合一致**（不要求值一致——mock 是造的）。"
        "这条测试是「mock 不再是假绿灯」的最终保证。",
    ])

    add_h(doc, "任务 M0-4　修正四处失效的表名", 3)
    add_bullets(doc, [
        "**Objective**：把代码里引用了设备上不存在的表名的地方全部改对。",
        "**Files**：Modify `backend/app/connectors/fortisiem.py`、`backend/app/services/nlq.py`、"
        "`backend/app/services/eventlog_query.py`；Create `backend/tests/test_table_names.py`。",
        "**Step 1 写失败测试**：断言连接器与白名单里出现的表名，"
        "是**实机实测确认存在的**那些——`ph_device` / `ph_incident` / `ph_sys_domain` / "
        "`ph_drq_rule` / `events`。断言 `phoenix_*` 一个都不许出现。",
        "**Step 2**：改 `connectors/fortisiem.py` 的三处："
        "`list_devices` 兜底分支、`get_incident`、`get_license`。",
        "**Step 3**：重建 `nlq.py` 与 `eventlog_query.py` 的 `ALLOWED_TABLES`。"
        "**注意**：新白名单不能只换成 `ph_*`——还要把 ClickHouse 的 `events` 纳入，"
        "否则 EPS 与事件日志检索仍然用不了。",
        "**Step 4**：`get_license` 的正确处置是**删除这个方法**，而不是改表名——"
        "FortiSIEM 侧根本没有许可证数据（3.2 节已确认），"
        "留着它只会诱使代码去问一台没有许可证的设备。",
        "**Step 5**：把「表名白名单」改为**从实机探测结果派生**，而不是手写常量——"
        "手写常量就是这次出问题的根因。",
        "**Step 6**：测试通过；提交 `git commit -m \"fix: correct FortiSIEM table names to live schema\"`。",
    ])

    add_h(doc, "任务 M0-5　更新 FAZ 连接器到 8.x 契约", 3)
    add_bullets(doc, [
        "**Objective**：把 FAZ 连接器从 `/jsonrpc` 契约迁到实测可用的 `flatui_auth` / `flatui_proxy`。",
        "**Files**：Modify `backend/app/connectors/fortianalyzer.py`。",
        "**Step 1 写失败测试**：断言登录走 `/cgi-bin/module/flatui_auth`、"
        "请求体是 `{url, method, params}` 形状、读走 `/cgi-bin/module/flatui_proxy` 且体是顶层 `url`。",
        "**Step 2**：实现 `FortiAnalyzerClient.login()`：POST `flatui_auth`，"
        "保存 `CURRENT_SESSION` 与 `HTTP_CSRF_TOKEN` Cookie。",
        "**Step 3**：实现 `request(url)`：POST `flatui_proxy`，体 `{\"method\":\"get\",\"url\":url}`，"
        "解包 `result[0].data`。",
        "**Step 4**：保留旧 `/jsonrpc` 路径作为**回退候选**，探测顺序：先 flatui（实测可用），"
        "失败再 `/jsonrpc`；把探测结果缓存。",
        "**Step 5**：**并发探测必须间隔数秒**——设备对登录次数限流（`-23`），"
        "一次突发会把真实答案掩盖成误导性的错误码。",
        "**Step 6**：`pytest backend/tests/test_fortianalyzer_contract.py -v` 全绿；提交。",
    ])

    # ─────────── M1 ───────────
    add_h(doc, "3.2 M1　多租户与认证（第 2–3 周）", 2)

    add_h(doc, "任务 M1-1　数据模型与租户表", 3)
    add_bullets(doc, [
        "**Objective**：建立门户自有库的 11 张核心表。",
        "**Files**：Create `backend/app/models.py`；Modify `backend/app/db.py`。",
        "**Step 1 写失败测试**：断言 `Tenant.fortisiem_org_name` 可空且默认为空字符串"
        "（**不用 NULL**——`create_all` 建出来的表永远保持原可空性，"
        "已有部署上 NULL 默认会失败，空字符串表达同一件事且不需要迁移）。",
        "**Step 2**：实现模型。`tenants` 含 `fortisiem_org_id` / `fortisiem_org_name` / "
        "`fortianalyzer_adom` / `locale`。",
        "**Step 3**：`alembic revision --autogenerate -m \"init\"` 并 `alembic upgrade head`。",
        "**Step 4**：测试通过；提交 `git commit -m \"feat: portal core models\"`。",
    ])

    add_h(doc, "任务 M1-2　租户作用域模块", 3)
    add_bullets(doc, [
        "**Objective**：实现 `scope.py`，把作用域规则集中在一处、可单独测试。",
        "**Files**：Create `backend/app/services/scope.py`；Create `backend/tests/test_scope.py`。",
        "**Step 1 写失败测试**（四条，每条对应一条真实规则）：",
    ])
    add_code_block(
        doc,
        '''def test_scope_inactive_without_org_name():
    """没设组织名 -> 作用域不生效（单组织设备上过滤反而会藏掉全部资产）。"""
    assert not OrgScope(org_id=1, org_name=None).active
    assert not OrgScope(org_id=1, org_name="").active


def test_scope_drops_unattributed_records():
    """带不出组织归属的记录 -> 作用域生效时排除（默认拒绝）。"""
    scope = OrgScope(org_id=1, org_name="acme")
    kept = scope.apply([{"name": "a", "organization": "acme"},
                        {"name": "b", "organization": None}])
    assert [r["name"] for r in kept] == ["a"]


def test_scope_matches_org_name_variants():
    """上游报的是名字：acme 要匹配 'acme (3)'，但不能匹配 acmecorp。"""
    scope = OrgScope(org_id=1, org_name="acme")
    assert scope.matches("acme")
    assert scope.matches("acme (3)")
    assert not scope.matches("acmecorp")


def test_scope_reports_what_it_filtered():
    """响应体必须报告被过滤掉的数量 —— 运维要能区分边界在工作还是配错了。"""
    result = scope.apply([{"organization": "acme"}, {"organization": "other"}])
    assert result.filtered_out == 1''',
        "M1-2 作用域测试（节选）",
    )
    add_bullets(doc, [
        "**Step 2**：实现 `OrgScope`（`active` / `matches` / `apply`）。"
        "组织名比较用分词归一后比较，`acme` 匹配 `acme (3)` 但不匹配 `acmecorp`。",
        "**Step 3**：实现 `apply(records)`，返回 `(kept, filtered_out_count)`。",
        "**Step 4**：**过滤必须在截断之前**——先取全量再过滤再分页。"
        "写一个测试：另一租户的记录排在前面时，本租户的记录仍然留在结果里。",
        "**Step 5**：`pytest backend/tests/test_scope.py -v` 全绿；提交。",
    ])

    add_h(doc, "任务 M1-3　认证与令牌生命周期", 3)
    add_bullets(doc, [
        "**Objective**：实现登录、访问令牌、刷新 Cookie、轮换与重放检测。",
        "**Files**：Modify `backend/app/security.py`、`backend/app/routers/auth.py`；"
        "Create `backend/app/models.py` 的 `refresh_tokens` 表；Create `backend/tests/test_auth_flow.py`。",
        "**Step 1 写失败测试**：断言①只带 Cookie 访问受保护端点得到 **401**"
        "（刷新 Cookie 不能单独当 Bearer 凭据）；②刷新令牌轮换后旧令牌不可再用；"
        "③宽限期内重放不吊销；④超出宽限重放吊销整条会话族；"
        "⑤**访问令牌已过期时登出仍能成功**。",
        "**Step 2**：实现。刷新令牌**只存哈希**；`family_id` 串起一条会话族。",
        "**Step 3**：实现 `GET /auth/sessions`（设备、源 IP、时间）与 `DELETE /auth/sessions/{id}`，"
        "让用户能看见并吊销不认识的会话——**只做服务端接口不算交付**，前端必须有入口。",
        "**Step 4**：口令失败限流：**计数并返回 429，但绝不锁账号**"
        "（知道邮箱就能把账号锁死，是对账号所有者的拒绝服务）。成功登录清零计数。",
        "**Step 5**：测试通过；提交。",
    ])

    add_h(doc, "任务 M1-4　授权矩阵与提权测试", 3)
    add_bullets(doc, [
        "**Objective**：用机械化的方式证明授权没有洞。",
        "**Files**：Create `backend/tests/test_authorization_matrix.py`。",
        "**Step 1**：**从应用自身导出路由表**（OpenAPI 文档），不要维护一份手写清单。",
        "**Step 2**：对每条路由 × 每种角色跑四条断言（见设计方案 4.4）。",
        "**Step 3**：公开清单**从两侧断言**——清单上的路由必须仍能匿名访问，否则清单过期、登录页坏掉。",
        "**Step 4**：**对象级测试**：把受害对象放在 A 租户、调用方在 B 租户，"
        "断言每个带 id 的端点返回 403/404。",
        "**Step 5**：**字段级测试**：以攻击者身份执行提权写入（创建用户 → 改角色），"
        "再以受害者身份读取，断言看不到不该看到的内容。"
        "**从攻击者一侧写这个测试**——以管理员身份调用只能证明端点能用。",
        "**Step 6**：**同时断言管理员的能力仍然可用**——把管理员的权力一起修掉的修复是另一个 bug。",
        "**Step 7**：提交 `git commit -m \"test: authorization matrix and escalation tests\"`。",
    ])

    add_h(doc, "任务 M1-5　设备侧 SP 改造与隔离验证", 3)
    add_bullets(doc, [
        "**Objective**：让多租户隔离在真机上成立。",
        "**Files**：Create `scripts/verify_org_isolation.py`；Modify `docs/device-contract.md`。",
        "**Step 1**（设备侧，GUI 操作）：创建 Organization（船东名）、创建组织内 Full Admin 用户。",
        "**Step 2**（设备侧）：由**该组织内的用户**签发 API Token——"
        "**用 Super-global 用户签发的 Token 会看到全部租户数据，隔离即失效**。",
        "**Step 3**（设备侧）：为该组织分配 Collector。",
        "**Step 4**（脚本）：用租户 Token 与 Super Token 调同一路径，断言**两者输出不同**。"
        "输出相同即判定隔离失效，脚本失败退出非零。",
        "**Step 5**：把组织 ID ↔ `cust_org_id` ↔ `customer` 的映射写进 `docs/device-contract.md`。",
    ])
    add_tip_box(
        doc,
        "**这一步是整条链上唯一不能靠写代码解决的。** 门户侧可以做到万无一失，"
        "但如果 Token 是 Super-global 签发的，租户就是拿着放大镜看整个设备——"
        "而且**看不出任何异常**。M0 期间就应当把这条路径走通一遍，"
        "哪怕用测试组织。",
        "safe",
    )

    add_h(doc, "任务 M1-6　oceansite 免密对接（SSO 换票）", 3)
    add_bullets(doc, [
        "**Objective**：船东用户在 oceansite 登录后点「网络安全模块」进入 myPortal，"
        "**不再出现第二次登录表单**。",
        "**Files**：Create `backend/app/routers/sso.py`；Create `backend/app/services/identity_map.py`；"
        "Create `backend/tests/test_sso_exchange.py`；Modify `backend/app/routers/auth.py`。",
        "**Step 1**：实现 `POST /api/v1/sso/exchange` —— myPortal 后端拿浏览器带来的 oceansite "
        "会话 Cookie 去问 oceansite 的身份端点，拿到外部身份后**查自己的映射表**"
        "（外部 id → 租户 + 角色），再签发 myPortal 自己的 JWT + refresh cookie。",
        "**Step 2**：映射表**查不到即 403（默认拒绝）**——oceansite 新增账号不应自动获得某租户数据。"
        "403 响应**不得包含租户名、组织名、FortiSIEM Organization**。",
        "**Step 3**：写失败测试——伪造 Cookie → 401；未映射身份 → 403 且不泄露租户信息；"
        "换票响应体中**不得出现 oceansite 会话值**。",
        "**Step 4**：审计留痕 `auth.sso_exchange`，含 actor / tenant / outcome / 来源系统，"
        "**不含任何凭据**。SSO 是绕过本地登录表单的访问路径，不记审计等于这条路径没被监控。",
        "**Step 5**：部署形态落地——**首选反向代理同源挂载**"
        "（myPortal 挂在 oceansite 主机名的子路径下），网关转发形态作为备选。",
        "**Step 6**：**跨主机名拓扑下**复验形态 2（见「部署陷阱」提示框）。",
    ])
    add_tip_box(
        doc,
        "**Cookie 按主机名隔离，不按端口隔离。** 本地演示用 127.0.0.1 的两个端口，"
        "浏览器会顺手带上 Cookie，**看起来跨源也能 work**；但生产是 "
        "oceansite.example.com 与 myportal.example.com——**不同主机名，Cookie 不会被带过去**，"
        "本地通过、生产直接失败。验收必须在真实跨主机名拓扑下做，"
        "不能拿本地 9101→9102 的结果当证据。",
        "warn",
    )

    add_h(doc, "任务 M1-7　oceansite 联调与身份映射导入", 3)
    add_bullets(doc, [
        "**Objective**：与真实 oceansite 对接，导入首批账号映射。",
        "**Files**：Modify `docs/ocean-integration.md`；Create `scripts/import_identity_map.csv`；"
        "Create `scripts/probe_ocean_identity.py`。",
        "**Step 1**：探测 oceansite 的身份端点——若只有 HTML 页面，退化为**按状态码判断"
        "（200 已登录 / 302 未登录），不解析 HTML**（解析 HTML 找用户名是脆的，改版就坏）。",
        "**Step 2**：与对方确认会话 Cookie 名、有效期、以及该 Cookie 是否为 host-only"
        "（决定能否直接走形态 1）。",
        "**Step 3**：导入首批账号映射（外部 id → 租户 + 角色），导入前先跑一遍"
        "**未映射账号清单**，让对方确认没有遗漏。",
        "**Step 4**：异常路径演练——oceansite 会话过期时 myPortal 的表现；"
        "oceansite 宕机时已登录用户是否仍可用（换票后 myPortal 会话独立，应当仍可用）。",
    ])
    add_tip_box(
        doc,
        "**M1-7 依赖对方提供 oceansite 身份端点信息。** 建议在 M0 期间就提出来，"
        "否则它会成为 M1 收尾时的阻塞项。参考实现见 `sso/` 目录"
        "（33 项断言全通过，含 10 项负向用例）。",
        "warn",
    )

    # ─────────── M2 ───────────
    add_h(doc, "3.3 M2　看板与组件目录（第 4–5 周）", 2)

    add_h(doc, "任务 M2-1　组件目录（单一事实来源）", 3)
    add_bullets(doc, [
        "**Objective**：把组件定义收敛到一个文件，后端与前端都从它派生。",
        "**Files**：Modify `backend/app/services/widget_catalog.json`；"
        "Create `frontend/src/widgets/catalog.generated.ts`；Create `backend/tests/test_widget_catalogue.py`。",
        "**Step 1 写失败测试**：断言前端镜像的 **id 集合与每个 id 的 renderer** 与后端目录一致；"
        "再断言 `name_key` / `category` / `renderer` **各自**能在翻译包中解析到键"
        "（只查其中两个字段的守卫会把第三个放跑）。",
        "**Step 2**：加生成脚本 `scripts/generate_widget_catalog.py`，"
        "构建前运行，产物提交入库（前端构建需要它）。",
        "**Step 3**：**扰动证明**——把一个 id 改名，确认测试变红，再改回来。",
        "**Step 4**：提交。",
    ])

    add_h(doc, "任务 M2-2　看板编排页", 3)
    add_bullets(doc, [
        "**Objective**：拖拽 + 缩放 + 保存 + 跨租户复制。",
        "**Files**：Modify `frontend/src/pages/DashboardBuilderPage.tsx`、"
        "`frontend/src/components/widgets/*`；Create `frontend/src/pages/DashboardPage.tsx`。",
        "**Step 1**：布局项**必须指向目录里真实存在的组件**，否则渲染成「未知组件」。",
        "**Step 2**：**布局往返测试**——这是最容易被某一层悄悄丢掉的一层："
        "断言保存后逐项读回，**包含栅格几何（w/h/x/y），不只是 id**。",
        "**Step 3**：断言另一个租户**既读不到也写不了**这份布局。",
        "**Step 4**：实现组件目录侧栏、拖拽区、属性面板、预览模式。",
        "**Step 5**：`vitest run` 全绿；`npm run build` 成功；提交。",
    ])

    add_h(doc, "任务 M2-3　组件渲染器的健壮性", 3)
    add_bullets(doc, [
        "**Objective**：让每个组件在部分载荷、类型漂移、无数据三种情况下都不崩。",
        "**Files**：Modify `frontend/src/components/charts/*`、`frontend/src/components/widgets/*`。",
        "**Step 1**：**载荷字段的类型是契约的一部分**——后端发 epoch 数字而契约声明的是时间戳字符串时，"
        "图表会用一个数字没有的方法去排序，整页崩掉。发契约声明的类型，"
        "渲染侧**一次性强制转换**，两个值看起来都像数字时按数值比较，"
        "**永远不要对没检查过的值调用字符串方法**。",
        "**Step 2**：把数据整形抽成**纯函数导出**，以便直接测试——"
        "DOM 测试环境里的图表宽度为 0、什么都不渲染，断言渲染输出证明不了任何事。"
        "（测试环境还需要 `ResizeObserver` stub，否则图表测试在到达被测行为之前就全挂。）",
        "**Step 3**：空态检查**必须放在任何 `useMemo` 之前**——放在 hook 之后的守卫保护不了 hook。",
        "**Step 4**：**有数据的载荷下**逐个组件渲染通过（空态永远渲染得「看起来没问题」，"
        "而格式化、排序、聚合这些代码一行都没跑过）。",
    ])

    # ─────────── M3 ───────────
    add_h(doc, "3.4 M3　资产、许可证、拓扑（第 6–7 周）", 2)

    add_h(doc, "任务 M3-1　许可证取数与到期告警", 3)
    add_bullets(doc, [
        "**Objective**：许可证数据取自 FAZ，到期告警真的会触发。",
        "**Files**：Modify `backend/app/connectors/fortianalyzer.py`、"
        "`backend/app/services/widgets.py`、`backend/app/services/alerts.py`；"
        "Create `backend/tests/test_alert_pipeline.py`。",
        "**Step 1 写失败测试**（关键的一条）：",
    ])
    add_code_block(
        doc,
        '''def test_license_trigger_fires_for_expiring_licenses(fake_faz, fake_siem):
    """许可证告警必须挂在 FAZ 上 —— SIEM 侧根本没有这个接口。

    下面的假 SIEM 客户端的 get_license() 直接抛断言：
    如果代码去问 SIEM，测试就会红。
    """
    fake_faz.license_expiring_in_days = 10
    fake_siem.get_license.side_effect = AssertionError("许可证不能问 SIEM")

    rule = make_rule(trigger={"kind": "license", "within_days": 30},
                     channels=[make_channel()])
    deliveries = run_alert_cycle(rule)

    assert len(deliveries) == 1
    assert deliveries[0].ok is True
    assert deliveries[0].channel_kind == "wechat_work"''',
        "M3-1 许可证告警回归测试",
    )
    add_bullets(doc, [
        "**Step 2**：实现到期日解析：从 `licenses.<CODE>.txt` 解析「过期 YYYY-MM-DD」，"
        "保留原始文本供人工核对；状态取 `licenses.<CODE>.status`。",
        "**Step 3**：实现到期告警的阈值分档（>60 / 30–60 / 7–30 / <7 / 已过期）。",
        "**Step 4**：**扰动证明**：把 `faz = build_fortianalyzer(creds)` 改成 `faz = None` → 测试变红；还原 → 全绿。",
        "**Step 5**：提交。",
    ])
    add_tip_box(
        doc,
        "**这条测试的价值不在测试本身，在于它钉住了一个真实事故。** "
        "原 fortiportal 的许可证告警触发器调的是 `build_fortisiem(creds).get_license()`，"
        "而 SIEM 侧**根本没有这个接口**——那个分支永远取不到数据，"
        "**「许可证到期」告警从来不会触发**，但在界面上看起来是配置正确的。"
        "一条永不触发的告警比没有这个功能更糟：它让人以为已经有人盯着了。",
        "warn",
    )

    add_h(doc, "任务 M3-2　资产清单与拓扑", 3)
    add_bullets(doc, [
        "**Objective**：资产清单连接 SIEM CMDB 与 UR 台账；拓扑区分已核验 / 待确认连接。",
        "**Files**：Modify `backend/app/routers/data.py`；Create `frontend/src/pages/AssetsPage.tsx`、"
        "`frontend/src/pages/TopologyPage.tsx`。",
        "**Step 1**：资产合并以 `natural_id` / `name` / `hw_serial_no` 为键；"
        "**关联不上的记录并列展示并标注「未关联」，不静默合并**。",
        "**Step 2**：拓扑数据模型区分 `verified` / `pending` 两种连接状态。",
        "**Step 3**：拓扑**编排**页（系统设置第 7 项）支持定义区域、节点与连线的渲染模板。",
        "**Step 4**：写一个**跨租户遍历**：把 A 租户的资产 id 放进 B 租户的请求，断言 404。",
    ])

    # ─────────── M4 ───────────
    add_h(doc, "3.5 M4　AI 助手与自然语言查询（第 8–9 周）", 2)

    add_h(doc, "任务 M4-1　固定工具目录与结构化查询", 3)
    add_bullets(doc, [
        "**Objective**：让模型提供参数，让服务端提供语句。",
        "**Files**：Modify `backend/app/services/nlq.py`；Create `backend/tests/test_nlq_guard.py`。",
        "**Step 1 写失败测试**（每条对应一个真实的越权形状）：",
    ])
    add_code_block(
        doc,
        '''def test_model_cannot_supply_tenant_id(fake_llm):
    """租户 id 出现在工具参数里 -> 拒绝。作用域只从凭据来。"""
    fake_llm.wants_tool("query_incidents", {"tenant_id": "other-tenant"})
    with pytest.raises(ToolArgumentRejected):
        run_nlq(fake_llm)


def test_model_cannot_emit_sql(fake_llm):
    """模型不得生成 SQL —— 表、列、WHERE 形状全部服务端构建。"""
    fake_llm.wants_raw_sql("SELECT * FROM ph_incident")
    with pytest.raises(ToolArgumentRejected):
        run_nlq(fake_llm)


def test_statement_is_structurally_guarded(fake_llm):
    """关键词黑名单不是防线：表函数 / INTO OUTFILE / 集合操作 / 任意表名都要挡。"""
    for bad in ["SELECT url(...) FROM x", "SELECT * FROM t INTO OUTFILE '/tmp/x'",
                "SELECT a FROM t UNION SELECT b FROM u", "SELECT * FROM pg_catalog.pg_user"]:
        with pytest.raises(StatementRejected):
            build_statement(bad)


def test_tenant_filter_is_injected_server_side(fake_llm, tenant):
    """租户过滤在构建语句时注入 —— 省略它就是一次跨租户读。"""
    sql = build_statement("SELECT id FROM ph_incident", tenant=tenant)
    assert "cust_org_id" in sql
    assert str(tenant.org_id) in sql


def test_no_scope_declared_fails_closed(fake_llm):
    """租户未声明作用域 -> 查询失败关闭，而不是放行全量。"""
    with pytest.raises(ScopeRequired):
        run_nlq(fake_llm, tenant=Tenant(org_name=None))''',
        "M4-1 NLQ 结构化守卫测试（节选）",
    )
    add_bullets(doc, [
        "**Step 2**：实现工具目录（沿用 fortiportal 的 6 个工具："
        "`query_incidents` / `query_assets` / `query_licenses` / `query_deception_hits` / "
        "`query_event_logs` / `query_clickhouse`）。",
        "**Step 3**：实现语句构建器：表白名单、拒绝表名后跟 `(`、拒绝 `INTO OUTFILE`、"
        "拒绝集合操作、**检查每一个目标**（`JOIN` 是第二个）。",
        "**Step 4**：**只转义一次**——值走一遍字面量转义再走一遍通配符转义，结果会变成"
        "「字面反斜杠 + 活通配符」，匹配范围远超用户所问。优先用子串检索而非 `LIKE`。",
        "**Step 5**：**只传调用方真正提供的参数**——把每个字段都塞进参数字典并把未提供的设为 `None`，"
        "会覆盖被调用方自己的默认值，`int(None)` 会抛错。",
        "**Step 6**：提交。",
    ])

    add_h(doc, "任务 M4-2　语音输入与服务端 STT", 3)
    add_bullets(doc, [
        "**Objective**：文字与语音都能问。",
        "**Files**：Modify `frontend/src/components/nlq/VoiceButton.tsx`、"
        "`frontend/src/hooks/useVoice.ts`；Create `backend/app/routers/nlq.py` 的 "
        "`POST /nlq/voice/transcribe`。",
        "**Step 1**：前端**特性检测** `SpeechRecognition` / `webkitSpeechRecognition`；"
        "**iOS Safari 与 Android WebView 上不存在**，必须回退服务端 STT"
        "（MediaRecorder → OpenAI 兼容 `/audio/transcriptions`）。"
        "一个纯浏览器的语音按钮会在最需要它的平台上静默失效。",
        "**Step 2**：服务端 STT 端点做**文件大小与时长限制**，音频不落第三方。",
        "**Step 3**：中文对 `FortiWeb`、`FortiDeceptor`、CVE 编号的识别准确率是**强假设、未实测**——"
        "上线前应实测并把结果写进文档。",
        "**Step 4**：Edge 的 SpeechRecognition 支持状态各数据源互相矛盾，**必须运行时检测而非查表**。",
    ])

    # ─────────── M5 ───────────
    add_h(doc, "3.6 M5　告警管道与通知通道（第 10–11 周）", 2)

    add_h(doc, "任务 M5-1　五类通道适配器", 3)
    add_bullets(doc, [
        "**Objective**：微信 / 飞书 / Teams / 钉钉 / 邮件各一个 `send(message) -> (ok, detail)`。",
        "**Files**：Modify `backend/app/services/notifiers.py`；"
        "Create `backend/tests/test_notifiers_live.py`。",
        "**Step 1 写失败测试**：对着**真实 socket** 验证，不是打桩 HTTP 层——"
        "打桩只证明「你打算发的 JSON」，不证明「真的发出去的字节」；"
        "错误的形状不会抛异常，平台会返回 200 加一个错误码，或者干脆把消息丢掉。"
        "搭一个本地 HTTP 收件箱与本地 SMTP sink，检查请求行、头与体。",
        "**Step 2**：实现五个适配器。**飞书用 `larksuite/node-sdk`**"
        "（`larksuite/oapi-sdk-nodejs` 已归档，不要在新项目上起）；"
        "**Teams 用 Workflows / Power Automate Webhook + Adaptive Cards**"
        "（Incoming Webhook 连接器已退役）。",
        "**Step 3**：**通知发送器必须 `trust_env=True`**（与设备连接器相反）——"
        "Teams 的 webhook 在国内只能经系统代理出去；WeCom / 钉钉 / 飞书由代理规则直连。"
        "两个方向各写一条测试钉死。",
        "**Step 4**：提交。",
    ])

    add_h(doc, "任务 M5-2　告警调度与三段式事务", 3)
    add_bullets(doc, [
        "**Objective**：告警可靠触发，且不拖垮门户。",
        "**Files**：Modify `backend/app/services/alerts.py`；Create `backend/tests/test_alert_pipeline.py`。",
        "**Step 1 写失败测试**：",
    ])
    add_code_block(
        doc,
        '''async def test_no_transaction_open_during_device_call(fake_siem, session):
    """设备调用时不得持有事务 —— 否则一次不可达的调用会把写锁持有几十秒，
    症状是「别处登录时提示数据库已锁定」。"""
    seen = {}

    async def slow_get_license(*a, **kw):
        seen["in_txn"] = session.in_transaction()
        return {"ok": True}

    fake_siem.get_license = slow_get_license
    await run_alert_cycle(make_rule(), session=session)
    assert seen["in_txn"] is False


async def test_event_loop_keeps_ticking_during_slow_send(slow_smtp):
    """SMTP 握手期间事件循环不能被冻住。"""
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    task = asyncio.create_task(ticker())
    await dispatch_alert(make_delivery(), channel="email")
    task.cancel()
    assert ticks > 0        # 发送期间事件循环仍在转动


async def test_delivery_outcome_comes_from_the_sender(fake_sender):
    """投递记录由发送器回写。发送器失败却记成 delivered 比没有记录更糟 ——
    它告诉运维告警已送达，运维于是不再盯着它。"""
    fake_sender.will_fail = True
    d = await dispatch_alert(make_delivery(), channel="wechat_work")
    assert d.ok is False
    assert d.detail != ""''',
        "M5-2 告警管道纪律测试（节选）",
    )
    add_bullets(doc, [
        "**Step 2**：实现**读 / 干活 / 写**三段式：读取所需数据到普通 dataclass → 结束事务 → "
        "慢路径无事务无 ORM 对象 → 一次短事务写回。",
        "**Step 3**：**读事务用 `commit` 结束，不用 `rollback`**——`rollback` 会让调用方持有的 ORM 对象失效，"
        "下一次属性访问触发惰性刷新，而惰性刷新不能在异步上下文里跑（`MissingGreenlet`）。"
        "配合 `expire_on_commit=False`。",
        "**Step 4**：同步 SMTP 放 `asyncio.to_thread` 里。",
        "**Step 5**：提交。",
    ])

    # ─────────── M6 ───────────
    add_h(doc, "3.7 M6　UR 合规模块并入（第 12–14 周）", 2)

    add_h(doc, "任务 M6-1　移植元数据驱动注册表", 3)
    add_bullets(doc, [
        "**Objective**：把 asiSCRS 的注册表、模型、RBAC 映射整体并入。",
        "**Files**：Create `backend/app/services/registry/`（`types.py` / `helpers.py` / "
        "`modules.py` / `modules_extra.py` / `schemas.py` / `rbac_map.py`）；"
        "Create `backend/app/models/` 分包。",
        "**Step 1**：移植 75 张表的 ORM 模型与 68 个模块注册项。",
        "**Step 2**：**RBAC 资源映射必须显式**——模块 key 是 API 路径"
        "（`/api/changes`），RBAC resource 是 UR 的 12 个管理维度（`change`），"
        "两者语义不同；直接拿路径当权限名会导致鉴权错位。",
        "**Step 3**：数据范围：非全局角色按授权船舶过滤。",
        "**Step 4**：**每个模块的 create / update / delete 都写审计**；"
        "删除为逻辑删除并写审计（合规记录不可物理删除）。",
        "**Step 5**：写测试断言**模块总数 = 68**（从注册表派生，不是硬编码）。",
    ])

    add_h(doc, "任务 M6-2　前端动态表单与表格", 3)
    add_bullets(doc, [
        "**Objective**：新增台账模块前端零改动。",
        "**Files**：Create `frontend/src/components/ur/DynamicForm.tsx`、"
        "`frontend/src/components/ur/CellValue.tsx`、"
        "`frontend/src/pages/UrModulePage.tsx`。",
        "**Step 1**：字段契约从 `GET /api/meta/modules` 下发，按 `kind` 映射控件。",
        "**Step 2**：写测试：**新增一个测试模块（只在测试里注册），断言前端能自动渲染它的表单与表格**——"
        "这条测试是「前端零改动」这个承诺的唯一证据。",
        "**Step 3**：字段类型与长度校验、未知字段拒绝（防 mass-assignment）、"
        "create / update 分离（update 全可选）。",
        "**Step 4**：中文标签来自注册表，**不硬编码在前端**。",
    ])

    add_h(doc, "任务 M6-3　12 项 UR 合规聚合视图", 3)
    add_bullets(doc, [
        "**Objective**：12 个合规模块按条款聚合达成率，并给出检验时的导出清单。",
        "**Files**：Create `backend/app/services/compliance.py`；"
        "Create `frontend/src/pages/CompliancePage.tsx`。",
        "**Step 1**：达成率来自各维度台账的「已达成项 / 应达成项」比例。",
        "**Step 2**：实时计算（不落库）+ 可选写回 `ships.compliance_score`。",
        "**Step 3**：每个合规模块给出「检验时该导出哪份材料」的清单，"
        "对应《计划》各模块的「检验情况」与「记录与文档」小节。",
        "**Step 4**：证据包装配：台账快照 + 审计日志 → DOCX/PDF（放二期，本期先支持导出）。",
    ])

    # ─────────── M7 ───────────
    add_h(doc, "3.8 M7　i18n、审计、巡检与打磨（第 15 周）", 2)

    add_h(doc, "任务 M7-1　国际化", 3)
    add_bullets(doc, [
        "**Objective**：中英双语随设置生效自动切换。",
        "**Files**：Modify `backend/app/i18n/*``frontend/src/i18n/locales/*`；"
        "Create `frontend/scripts/verify-i18n-keys.mjs`。",
        "**Step 1**：**语言优先级是一条规则**：用户选择 → 租户语言 → 门户默认。"
        "返回语言的接口必须返回**当前生效**的语言，不是存储的原始值。",
        "**Step 2**：**键集合与取值对等测试**——只在一侧存在的键会渲染成原始 key。",
        "**Step 3**：**英文包不得含中文字符**——这条断言能抓住「翻译了一半」，"
        "而键集合相等抓不到。**不要断言某个字面翻译**（改个措辞就红），"
        "要断言「键存在」与「跨语言有差异」。",
        "**Step 4**：**动态键要按值域校验**——`t(\\`widget.category.${category}\\`)` "
        "在运行时拼键，扫描字面量永远看不到它。做法：枚举目录里的字段取值，断言每个都能解析到键。"
        "找动态键要 grep 反引号，不是引号。",
        "**Step 5**：**带点的值不是翻译键**——i18next 用 `.` 作分隔符，"
        "`auditAction.channel.update` 会解析成命名空间 + 键而渲染为空。拍平成单级键，"
        "拍平逻辑集中在一个 helper。",
        "**Step 6**：**从源码派生所需键集**，不要手工维护清单——扫描后端发出取值的地方"
        "（`action=\"...\"`），断言每个取值在每个语言包里都能解析。"
        "手工清单会一直绿到有人加了新动作却忘了翻译——而审计日志恰恰是运维排查时在看的屏幕。",
        "**Step 7**：**机器码放 `data-*`，不进可见文本也不进 tooltip**——"
        "否则 l10n 检查会把审计动作码当成未翻译的字符串。",
    ])

    add_h(doc, "任务 M7-2　审计与日志", 3)
    add_bullets(doc, [
        "**Objective**：全量操作可审计，且审计本身可用。",
        "**Files**：Modify `backend/app/services/audit.py`、`backend/app/routers/data.py`；"
        "Create `frontend/src/pages/AuditPage.tsx`。",
        "**Step 1**：审计表**只追加**——不提供任何更新与删除接口。",
        "**Step 2**：**敏感读取也要记录**（跨租户聚合读取、凭据查看、证据包导出）。",
        "**Step 3**：**凭据永不进审计记录**——写的是「谁改了哪个字段」，不是「值是什么」。",
        "**Step 4**：审计动作码用 `data-code` 属性承载，界面显示翻译后的标签。",
        "**Step 5**：审计查询端点**从代码派生可审计动作清单**（两端对等校验），"
        "否则代码里写了新动作，筛选下拉里却没有。",
    ])

    add_h(doc, "任务 M7-3　自动化巡检", 3)
    add_bullets(doc, [
        "**Objective**：定时替人做检查，产出可核验的报告。",
        "**Files**：Create `backend/app/services/inspection.py`、"
        "`backend/app/routers/inspections.py`；Create `frontend/src/pages/InspectionPage.tsx`。",
        "**Step 1**：巡检项是**元数据驱动**的，与 UR 台账共用注册机制。",
        "**Step 2**：每次巡检留存**执行时刻、输入快照、判定依据、结论**。",
        "**Step 3**：巡检问题可一键生成对应台账的待办记录，形成闭环。",
    ])

    # ─────────── M8 ───────────
    add_h(doc, "3.9 M8　验收与交付（第 16 周）", 2)

    add_h(doc, "任务 M8-1　端到端验收测试", 3)
    add_bullets(doc, [
        "**Objective**：一个测试走完一个租户的全流程。",
        "**Files**：Create `backend/tests/test_tenant_journey.py`。",
        "**Step 1 写测试**：建租户 → 建用户 → 登录 → 搭看板 → 加通道 → 写规则 → "
        "让规则触发并投递 → 读回投递记录 → **断言另一个租户看不到其中任何一项** → "
        "断言审计日志把整件事讲清楚了。",
        "**Step 2**：**扰动验证**：把投递归属到错误的租户、跳过投递、重命名一个审计动作——"
        "每一处扰动都要让测试变红。",
        "**Step 3**：**载荷形状要从实现与既有测试里取**，不要凭猜——"
        "规则的通道列表、触发的键名、新租户的默认值都很容易猜错，"
        "而猜错就变成了「测试在强制执行一个错误规格」。",
    ])

    add_h(doc, "任务 M8-2　部署与真实门户验证", 3)
    add_bullets(doc, [
        "**Objective**：证明部署出去的是真门户，不是 fixture。",
        "**Files**：Create `deploy/docker-compose.yml`、`deploy/nginx.conf`、"
        "`frontend/scripts/prove-deployment-real.mjs`、`backend/Dockerfile`、`frontend/Dockerfile`。",
        "**Step 1**：镜像构建时**把 mock flag 钉死**（`VITE_USE_MOCK` 未设置时默认 true，"
        "会让镜像里跑出一个接受任何密码的假门户）。**在构建产物上断言**，而不是在源码上。",
        "**Step 2**：运行时探针用**伪造凭据**，必须得到 **401 invalid credentials**；"
        "得到 200 就说明客户端还在 fixture 模式，无论页面看起来多对。",
        "**Step 3**：探针还要数**页面经网关实际发出的 `/api/` 请求数**——"
        "fixture 模式下这个数是 0，而界面照常渲染。",
        "**Step 4**：**部署是被启动证明的，不是被读配置证明的。** "
        "构建镜像、起栈、跑一个真实会话、看**是哪个服务器记下了请求**——"
        "同端口上的开发后端会让坏掉的部署看起来是健康的。",
        "**Step 5**：断言 SPA 与 API **同源**（相对 API base），"
        "否则刷新 Cookie 会被静默扣留，会话每次刷新都死而服务端日志里看不出异常。",
    ])

    add_h(doc, "任务 M8-3　浏览器验证", 3)
    add_bullets(doc, [
        "**Objective**：在真浏览器里验证渲染、响应式与无障碍。",
        "**Files**：Create `frontend/scripts/verify-responsive.mjs`、"
        "`frontend/scripts/check-session-ui.mjs`。",
        "**Step 1**：用真实浏览器（CDP，无需安装 Playwright）逐路由走一遍，"
        "统计控制台错误、检测错误页、把渲染出的文本与 API 返回对照。"
        "**只访问落地页的检查证明不了数据路由上的任何事。**",
        "**Step 2**：在 375 / 768 / 1024 / 1440 四个宽度下断言布局不变量"
        "（无横向滚动、侧栏转抽屉、表格不撑破）。",
        "**Step 3**：**导航要按用户的方式点**，不要靠输入 URL——"
        "访问令牌只在内存，整页加载会丢会话，按 URL 导航的脚本每次都在测登录页。",
        "**Step 4**：**打印 origin 与解析后的 API base**，确认被服务的模块确实反映了本次改动。",
        "**Step 5**：**确认端口属于你的进程**——同端口上遗留的旧服务会拿旧代码回答；"
        "`git worktree list` 也要看。",
    ])

    add_h(doc, "任务 M8-4　文档与交付", 3)
    add_bullets(doc, [
        "**Objective**：让下一个接手的人不需要猜。",
        "**Files**：Create `docs/API_CONTRACT.md`、`docs/REQUIREMENTS-TRACEABILITY.md`、"
        "`docs/OPERATIONS.md`、`docs/device-contract.md`、`README.md`。",
        "**Step 1**：API 契约文档**写出响应信封形状**——"
        "端点回 `{items,total,page,page_size}` 而客户端声明 `Item[]` 时，"
        "类型检查器放行、页面却把信封交给期待数组的组件，渲染出空白。"
        "把端点的形状写进契约，因为契约是下一个实现者会信任的东西。",
        "**Step 2**：需求追溯矩阵**本身要作为测试对象**——检查它引用的每个文件与函数仍然存在、"
        "它陈述的每个数字与产生它的代码一致、未完成项仍然列着。"
        "一张无人校验的追溯表是装饰品；被校验的才是证据。",
        "**Step 3**：数字用**可静态计数的口径**（测试文件数，而不是运行器报告的用例数——"
        "后者随参数化而变）；守卫要覆盖矩阵陈述的每一族数字"
        "（组件数、审计动作数、模块数、测试规模）。",
    ])

    # ══════════════════════════ 四、测试策略 ══════════════════════════
    add_h(doc, "四、测试策略与质量门禁", 1)

    add_h(doc, "4.1 测试金字塔", 2)
    add_table(
        doc,
        ["层级", "范围", "工具", "数量占比", "运行时机"],
        [
            ["单元测试", "作用域规则、语句构建守卫、日期与格式化、i18n 键",
             "pytest / vitest", "~60%", "每次提交"],
            ["契约测试", "连接器与实机 / mock 的字段形状、信封、错误码",
             "pytest + httpx", "~15%", "每次提交（无凭据时 SKIP 并显示原因）"],
            ["集成测试", "授权矩阵、对象级与字段级提权、告警管道、事务纪律",
             "pytest + pytest-asyncio", "~15%", "每次提交"],
            ["端到端测试", "一个租户走完整个产品；另一个租户看不到任何一项",
             "pytest + 真实浏览器", "~5%", "每日 + 合并前"],
            ["浏览器验证", "逐路由走查、控制台错误计数、四个宽度下的布局断言",
             "CDP 脚本（零新依赖）", "~5%", "每日 + 发布前"],
        ],
        widths=[2.2, 6.0, 3.4, 2.0, 2.4],
        font_size=9,
    )

    add_h(doc, "4.2 必须有的守卫（每一条都要能变红）", 2)
    add_table(
        doc,
        ["守卫", "断言", "怎么证明它能变红"],
        [
            ["组件目录漂移", "前后端 id 集合与 renderer 一致；`name_key` / `category` / `renderer` 各自可解析",
             "改一个 id，测试变红，改回"],
            ["i18n 对等", "两侧键集合与取值一致；英文包无中文字符；动态键按值域可解析",
             "删一个翻译键，变红"],
            ["授权矩阵", "匿名被拒 / 租户被拒于管理路由 / 租户可达自己路由 / superadmin 永不被拒",
             "去掉一个 `Depends`，变红"],
            ["提权", "创建与更新用户对权限字段的守卫一致",
             "去掉更新路径的守卫，变红"],
            ["NLQ 结构化", "模型无法影响 SQL 结构与租户过滤；作用域缺失时失败关闭",
             "去掉注入，变红"],
            ["许可证触发", "触发器走 FAZ；问 SIEM 的路径直接断言失败",
             "把 `faz` 置 None，变红"],
            ["投递结果", "记录由发送器回写，失败不记为 delivered",
             "让发送器失败，变红"],
            ["事务纪律", "设备调用时无事务；慢发送期间事件循环仍在转",
             "去掉 `commit`，变红"],
            ["部署真实", "构建产物里 mock flag 为 false；伪造凭据得 401",
             "把 flag 改回 true，变红"],
            ["代理方向", "设备连接器 `trust_env=False`；通知发送器 `trust_env=True`",
             "改任一方向的 flag，变红"],
            ["表名存在性", "代码与白名单里的表名都在实机实测存在的集合内；`phoenix_*` 一个都不许出现",
             "把 `ph_incident` 改回 `phoenix_incident`，变红"],
            ["mock 保真度", "mock 与真机对同一组查询返回一致的字段集合；mock 不服务真机上 404 的路径",
             "让 mock 在 404 路径上返回 200，变红"],
        ],
        widths=[2.4, 8.0, 5.6],
        font_size=8.5,
    )
    add_tip_box(
        doc,
        "**「证明守卫能失败」不是形式主义。** 一条从来没红过的守卫，"
        "和一个不存在的守卫在证据上无法区分。做法固定为三步："
        "扰动一侧 → 确认测试变红 → 还原并确认变绿。\n"
        "还有两个常见的假绿来源：\n"
        "① 测试读的是**环境固定的值**而不是代码自己的默认值——"
        "要断言 `Settings.model_fields[\"x\"].default`；\n"
        "② 测试只走失败路径，成功路径没人走过。\n"
        "另外，**用正则匹配文本只能证明文本在，证明指令是活的**——"
        "把匹配锚定到行首，并把自己的检查注释掉来确认守卫会红。",
        "warn",
    )

    add_h(doc, "4.3 CI 门禁", 2)
    add_code_block(
        doc,
        """# 每次提交
ruff check .                                  # lint 作用域 = 整个仓库
pytest -q --backend                            # 单测 + 集成
npx tsc --noEmit                               # 前端类型
npx vitest run                                 # 前端单测

# 每日 + 合并前
pytest -q -m contract --live                   # 实机契约（凭据来自 CI secret）
node frontend/scripts/verify-i18n-keys.mjs      # i18n 键对等
node frontend/scripts/verify-responsive.mjs     # 响应式
python backend/scripts/authorization_matrix.py  # 授权矩阵
node frontend/scripts/prove-deployment-real.mjs # 部署是真实门户

# 发布前
docker compose -f deploy/docker-compose.yml up -d --build
node frontend/scripts/prove-deployment-real.mjs --base https://<gateway>
# + 逐路由浏览器走查与控制台错误计数""",
        "图 4-1　CI 门禁",
    )

    # ══════════════════════════ 五、风险 ══════════════════════════
    add_h(doc, "五、风险登记册", 1)
    add_wide_table(
        doc,
        ["ID", "风险", "概率", "影响", "缓解措施", "触发信号", "责任人"],
        [
            ["R1", "设备侧 SP 改造未按期完成", "中", "高",
             "M0 期间就走通一遍（哪怕用测试组织）；"
             "门户保留「单组织 + 门户过滤」的降级开关，但明确标注隔离强度降低",
             "M1 第 3 天仍未拿到组织专属 Token", "Tech Lead"],
            ["R2", "FAZ 8.x 契约在其他版本上不同", "中", "中",
             "连接器做多候选路径 + 契约探测缓存 + 降级为空；"
             "契约探测结果写入文档",
             "另一台 FAZ 上探测失败", "后端"],
            ["R3", "许可与 EPS 的取数口径与预期不符", "中", "中",
             "先跑探针脚本确认字段；契约测试固化",
             "组件显示「未采集」而非数值", "后端"],
            ["R4", "FortiDeceptor 字段名需逐台校准", "高", "低",
             "非硬依赖；多候选映射 + 自诊断告警；校准只改一个文件里的一张表",
             "组件提示「字段映射需校准」", "后端"],
            ["R5", "i18n 键漂移在迭代中反复出现", "高", "中",
             "键对等测试进 CI；动态键按值域校验；动作码从代码派生",
             "界面上出现原始 key", "前端"],
            ["R6", "看板布局在某一层被丢掉", "中", "中",
             "往返测试逐项断言（含几何尺寸）；跨租户读写都断言",
             "保存后刷新布局丢失", "前端"],
            ["R7", "系统代理导致设备连接超时被误判", "中", "高",
             "连接器 `trust_env=False` + 两条测试钉死；诊断时先测直连耗时",
             "连接耗时稳定在 12 秒左右", "后端"],
            ["R8", "构建产物默认启用 mock", "低", "极高",
             "构建期钉死 flag 并在**产物**上断言；运行时用伪造凭据探针",
             "任何密码都能登录", "Tech Lead"],
            ["R9", "性能：跨租户聚合触发 429 限流", "中", "中",
             "并发压到单源 IP 上限以下；退避重试并遵循 `Retry-After`；"
             "复用单租户组件的采集助手，保证看板与舰队页口径一致",
             "聚合页偶发 429", "后端"],
            ["R10", "范围蔓延（UR 模块数量大）", "高", "中",
             "模块注册表让新增模块成本极低；排期按「先移植、后增强」；"
             "证据包生成放二期",
             "单模块开发超过 3 天", "产品"],
            ["R11", "移动端布局无人验证", "中", "中",
             "四个宽度的浏览器验证进 CI；侧栏固定宽度会挤压内容区这类问题只有真浏览器能发现",
             "375px 下出现横向滚动", "前端"],
            ["R12", "并发开发互相覆盖代码", "中", "中",
             "按路径 `git add`；提交前重读文件；看 mtime 判断对方是否还在写",
             "提交里出现半写的组件", "全体"],
            ["R13", "代码引用设备上不存在的表名（**已实测确认存在**）", "**高**", "**高**",
             "M0-4 一次性修正四处；表名白名单改为从实机探测结果派生；"
             "契约测试对表名做存在性断言",
             "真机上返回 `Table not allowed`", "后端"],
            ["R14", "mock 与真机契约漂移，导致假绿灯", "**高**", "**高**",
             "M0-3 校准 mock 的三处偏差（404 路径、表名、MCP 参数名）；"
             "新增 mock↔真机的字段集合一致性测试",
             "mock 全绿但真机取不到数据", "测试"],
            ["R15", "白名单按设备差异硬编码", "中", "中",
             "允许每租户配置「事件日志表映射」（asiSCRS 的 `eventlog_query.py` "
             "已经把这个形状做出来了），门户只校验标识符合法性，"
             "不替设备决定表名",
             "换一个 FortiSIEM 版本后白名单失效", "后端"],
        ],
        widths=[1.0, 4.0, 1.2, 1.2, 6.6, 3.6, 1.8],
        font_size=7.5,
    )

    # ══════════════════════════ 六、交付物 ══════════════════════════
    add_h(doc, "六、交付物清单与验收口径", 1)

    add_h(doc, "6.1 交付物", 2)
    add_table(
        doc,
        ["类别", "交付物", "验收口径"],
        [
            ["代码", "`backend/`、`frontend/`、`deploy/`、`scripts/`",
             "CI 全绿；镜像可启动；实机契约测试全绿"],
            ["文档", "产品设计方案、开发计划（本目录）、`docs/API_CONTRACT.md`、"
             "`docs/REQUIREMENTS-TRACEABILITY.md`、`docs/device-contract.md`、"
             "`docs/OPERATIONS.md`、README",
             "契约文档写出了响应信封形状；追溯矩阵的引用与数字经自动校验"],
            ["设计系统", "`design-system/MASTER.md`（唯一事实来源）+ 前后端令牌实现",
             "令牌不散落在组件里；改令牌只改一处"],
            ["验证证据", "实机探测记录 `device_probe_findings.json`、"
             "浏览器走查报告、授权矩阵报告、部署真实性探针报告",
             "每份证据标明**来自哪一次运行**（origin、端口归属、进程）"],
        ],
        widths=[2.0, 7.0, 7.0],
        font_size=9,
    )

    add_h(doc, "6.2 需求到证据的追溯", 2)
    add_para(
        doc,
        "需求追溯矩阵把「需求 → 实现 → 哪个测试证明它 → 还有什么未证明」四列并排。"
        "**这张表本身必须作为测试对象**：检查它引用的每个文件与函数仍然存在、"
        "它陈述的每个数字与产生它的代码一致、未完成项仍然列着。"
        "否则它会静默腐烂——测试改名了、数量变了、某行指向的文件被删了，"
        "而读者看不出来。",
    )
    add_table(
        doc,
        ["需求", "实现位置", "证明方式", "状态"],
        [
            ["多租户登录与资源隔离", "`services/scope.py`、各 router 的 `Depends`",
             "`test_scope.py`、`test_authorization_matrix.py`、`verify_org_isolation.py`", "M1 完成"],
            ["管理员可见全部资源", "`services/fleet.py`、`routers/data.py` 的跨租户端点",
             "跨租户聚合测试 + 审计断言", "M1 完成"],
            ["各租户资产统计", "`services/widgets.py` 的 `cmdb.assets.*` 组件",
             "实机载荷下的组件渲染测试", "M2 完成"],
            ["许可证到期告警", "`connectors/fortianalyzer.py`、`services/alerts.py`",
             "`test_alert_pipeline.py::test_license_trigger_fires_for_expiring_licenses`", "M3 完成"],
            ["五类通知通道", "`services/notifiers.py`", "`test_notifiers_live.py`（真实 socket）", "M5 完成"],
            ["看板拖拽编排", "`frontend/src/pages/DashboardBuilderPage.tsx`",
             "布局往返测试 + 浏览器走查", "M2 完成"],
            ["图表插件化", "`widget_catalog.json` + `widgets/registry.tsx`",
             "目录漂移守卫", "M2 完成"],
            ["多语言随设置生效", "`i18n/`、`hooks/useLocale.ts`",
             "i18n 对等测试 + 语言优先级测试", "M7 完成"],
            ["自然语言查询", "`services/nlq.py`", "NLQ 结构化守卫测试", "M4 完成"],
            ["语音输入", "`hooks/useVoice.ts`、STT 端点", "特性检测测试 + STT 回退测试", "M4 完成"],
            ["完整日志与审计", "`services/audit.py`", "审计动作码派生测试 + 端到端审计断言", "M7 完成"],
            ["UR 条款追溯与 12 项合规", "`services/registry/`、`services/compliance.py`",
             "模块数断言 + 达成率计算测试 + 文档模板生成测试", "M6 完成"],
        ],
        widths=[3.6, 5.0, 5.4, 2.0],
        font_size=8.5,
    )

    add_h(doc, "6.3 开工前需要确认的外部依赖", 2)
    add_bullets(doc, [
        "**设备侧 SP 改造**（最高优先级）：在 172.16.20.48 上创建 Organization、"
        "组织内 Full Admin 用户、分配 Collector、由该用户签发 Token。"
        "**M1 的第一天就需要它。**",
        "**FortiSIEM 的 API Token 轮换策略**：令牌 TTL 900 秒，"
        "需确认能否签发长期 Token，还是必须走 OAuth 刷新流程。",
        "**FortiDeceptor 设备地址与凭据**（若本期纳入）。",
        "**LLM 服务端点**：base_url、model、API Key，以及是否有速率与配额限制。",
        "**五类通知通道的接入信息**：各平台的 Webhook URL / SMTP 主机与凭据、"
        "以及每类通道要推送到哪个群。",
        "**船级社检验的具体清单**：12 项合规模块的达成率口径要能对检验方的要求，"
        "需要确认检验时实际看哪几项。",
    ])

    # 页眉页脚
    add_header_text(doc, "myPortal 项目开发计划 V1.0　|　BinQsoft")
    add_footer_page_numbers(doc, "myPortal 项目开发计划 V1.0")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(OUT))
    print(f"saved: {OUT}")
    print(verify(str(OUT)))


if __name__ == "__main__":
    build()
