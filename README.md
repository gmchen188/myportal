# myPortal

船舶网络安全运营门户 —— 真实后台 + 正式前端。

| | |
|---|---|
| 后端 | FastAPI + SQLAlchemy + SQLite（`backend/`），30+ 个 API 端点 |
| 前端 | React + Vite + TypeScript + Tailwind + TanStack Query（`web/`） |
| 事件来源 | FortiSIEM（OAuth/REST）· syslog · SNMP Trap · webhook · 人工登记 |
| 部署 | GitHub Pages（静态演示）+ 同源部署（生产，带后台） |

---

## 快速开始

```bash
# 后端（需要 Python 3.11+）
cd backend
pip install -r requirements.txt
cp .env.example .env          # 填 FortiSIEM 凭据与 JWT_SECRET
python -m uvicorn app.main:app --host 127.0.0.1 --port 9102

# 前端（需要 Node 20+）
cd web
npm ci
npm run dev                   # http://127.0.0.1:5173
```

前端通过 vite proxy 把 `/api` 与 `/health` 转到 `127.0.0.1:9102`。

### 首次登录

后台的初始管理员由环境变量创建，**不设就不建**（不给默认密码）：

```bash
MP_ADMIN_USERNAME=admin
MP_ADMIN_PASSWORD=<你自己的强密码>
MP_ADMIN_TENANT=asi
```

登录后请立刻在「管理后台 → 用户」里改掉。

---

## 目录结构

| 目录 | 内容 |
|---|---|
| `backend/app/` | FastAPI 后端：`db.py`（模型）· `routers/`（端点）· `services/`（业务）· `connectors/`（FortiSIEM） |
| `backend/tests/` | 177 项测试 |
| `web/src/` | 正式前端：`pages/` · `components/` · `hooks/` · `api/` |
| `demo/` | 单文件演示原型（仅演示用，不是正式前端） |
| `sso/` | SSO 参考实现：票据签发/校验 |
| `tools/` | 构建脚本（生成 docx / pptx）+ `check_demo.py` 自检 |
| `Docx/` | 产品设计方案、开发计划、汇报材料 |
| `_ref/` | 调研参考（实机探测结果、Fortinet 技术档案摘要） |

**`demo/` 与 `web/` 的关系**：`web/` 是正式前端，连接真实后台；`demo/` 只是可双击打开的演示原型，不参与生产。

---

## 核心能力

### 资产清单
CSV / Excel 导入（字段映射 → 校验 → 预览 → 补录 → 去重保存）、手工录入、从拓扑图生成初步资产。去重键 `(tenant_id, natural_id)`。

### 网络拓扑
保存 draw.io XML 并解析为节点/区域/连线投影；资产清单里的设备可一键导入为拓扑节点，自动建立监控绑定。

### 安全监控
设备按**未解决安全事件的最高严重级**着色：

| 严重度 | 颜色 |
|---|---|
| critical | `#dc2626` |
| high | `#ec4899` |
| medium | `#f59e0b` |
| low | `#64748b` |
| normal | `#16a34a` |
| **unknown（未接入监控）** | `#94a3b8` |

**「未接入监控」与「正常」严格分离** —— 没有事件数据时显示灰色 unknown，不误报绿色。

### FortiSIEM
连接状态**分四段诊断**（tcp / tls / auth / api），一眼看出卡在哪一段，而不是一句「未连接」。支持同步事件与设备到资产清单（幂等，重复同步只 skipped）。

### 管理后台
- **用户** —— 租户内唯一、bcrypt 哈希、角色（super_admin / tenant_admin / analyst / viewer）、连续失败锁定
- **租户** —— 启用/停用、FortiSIEM 组织映射
- **接入源** —— fortisiem / syslog / webhook / agent，`last_seen_at` 一眼看出通道死活
- **审计** —— 每个管理动作留痕（谁 / 何时 / 做了什么 / 对象 / 上下文）

---

## 认证模型

**作用域来自凭据，不来自请求参数** —— 一个租户的令牌只能读它自己的资产，参数里写别人的 `tenant_id` 也没用。

| 环境 | 行为 |
|---|---|
| 开发（`MP_ENV=dev`） | 业务读接口可用 `X-Dev-Tenant` 头免登录；**管理端点与 `/api/auth/me` 任何模式都要 Bearer 令牌** |
| 生产（`MP_ENV=prod`） | 一律 Bearer 令牌，dev 头被拒 |

理由：开发模式是「省掉登录步骤」，**不是「认证关闭」**。任何能访问到后台端口的人都不该能建用户、改角色、停租户。

生产部署前必须改掉 `JWT_SECRET`。

**GitHub Pages 上没有后台** —— 前端检测到后台不可达（404/500）时会退回演示模式而不是卡在登录页。判定只认 401/403 才跳登录。

---

## 环境变量

见 `backend/.env.example`。关键项：

| 变量 | 说明 |
|---|---|
| `MP_ENV` | `dev` / `prod` |
| `MP_DATABASE_URL` | 默认 `sqlite:///data/myportal.db`；换 PostgreSQL 只改这个 |
| `JWT_SECRET` | 生产必须换 |
| `MP_ADMIN_PASSWORD` | 初始管理员密码，**不设就不建账号** |
| `FORTISIEM_*` | FortiSIEM 地址与 API 凭据 |

`.env` 已被双重 Git 忽略，**不要提交**。`backend/data/` 整个目录不入库（含真实 SIEM 数据）。

---

## 验证

```bash
bash scripts/verify.sh          # 后端 pytest + 前端 tsc + vitest + build
```

CI 跑同一套：后端测试、前端类型检查、前端测试、前端构建、Pages 发布。

**部署验收不能只看 CI 绿灯** —— Pages 部署曾连续 6 次「报成功但没真部署」（`continue-on-error` 吞掉了失败）。要确认日志里有 `Created deployment` 那行，且产物的 `Last-Modified` 对应你刚推的 commit。详见 skill `pages-deploy-silent-failure`。

---

## 与 networktopology 的关系

[networktopology](https://github.com/gmchen188/networktopology)（独立仓库）是 draw.io + VLM 的完整实现 —— 图生图、自然语言/语音改图都靠它。

两者通过**同源**方式组合：myPortal 挂在 `/portal`，画布应用挂在 `/networktopology`。同源是刻意的 —— 画布里的 draw.io 编辑器要能被直接控制（读 `contentWindow.EditorUi`），跨域只能退化成 postMessage 广播。

部署形态见 networktopology 仓库的 `docs/P4-LAPTOP-AS-SERVER.md`。

---

## SSO 参考实现

`sso/` 是一套可运行的参考实现，现有方向是 **oceansite → myPortal**。

```bash
cd sso
pip install fastapi uvicorn pyjwt httpx
python mock_oceansite.py     # 模拟上游，终端 A
python sso_service.py        # SSO 服务，终端 B
python verify_sso.py         # 端到端验证
```

密钥走环境变量，**不入库**：`JWT_SECRET`（签发 access/refresh token）、`OCEAN_TICKET_SECRET`（校验上游票据）。`ticket.py` 的 `_require_strong_secret()` 强制密钥长度 ≥ 32 字节。

---

## Git 约定

- 分支：`main` 为主干，功能分支用 `feature/xxx` / `fix/xxx`
- 提交信息用中文，格式 `type(scope): 摘要`

### CI 流水线

`.github/workflows/check.yml` 五个 job：

| job | 做什么 | 失败意味着 |
|---|---|---|
| Demo self-check | `tools/check_demo.py`（57 项断言） | demo 界面坏了 |
| Backend tests | `pytest`（177 项） | 后台逻辑坏了 |
| Web frontend | tsc + vitest + vite build | 前端坏了 |
| Build docx / pptx | 从源码重建产物 → artifact | 构建脚本坏了 |
| Publish demo to Pages | 部署 `web/dist` + `demo/` | **部署失败会报红**（不再吞掉） |

产物在 CI 里重建而不是靠本地跑：`Docx/` 与 `_ref/` 的素材变了，上游产物不会自己更新。

### Pages 需要手动开一次

仓库默认没启用 Pages，首次推送时 `publish-demo` 会失败：

```
Get Pages site failed. Please verify that the repository has Pages enabled
```

**开法**：仓库 → Settings → Pages → Source 选 **GitHub Actions** → Save。

### 凭据

`gh` 与 git 用同一个 fine-grained PAT：

```bash
gh auth login --with-token <<< "$TOKEN"
```

> **仓库名大小写敏感**。GitHub 保留曾用过的名字（`myPortal` 之后 `myportal` 会被拒），且 fine-grained PAT 的仓库白名单是**建仓库时**锁定的 —— 新建的仓库不在名单里会 403，需要改 PAT 的 Repository access。

### 什么不进库

`.gitignore` 已排除：Python 缓存、`.env*`、`*.key`、`*.pem`、`_ref/*.session.json`，**以及整个 `backend/data/`**（含真实 SIEM 设备与事件）。

> **FortiSIEM MCP session id 是运行时凭据**，每次 `initialize` 都变，已从 `_ref/mcp_tools.json` 脱敏。
> 仓库里只有工具清单（那部分是有用的参考资料）。
