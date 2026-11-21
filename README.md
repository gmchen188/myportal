# myPortal

船舶网络安全运营门户的可点击原型 + SSO 参考实现。

**演示界面不需要任何环境**：双击 `demo/index.html` 即可用浏览器打开 —— 无服务器、无联网、无构建步骤。

---

## 目录结构

| 目录 | 内容 |
|---|---|
| `demo/` | 单文件界面原型（`index.html`）+ 截图 + 说明。全部 HTML/CSS/JS 内联，无外部依赖、无 CDN |
| `demo/index.v1.html` | 早期版本快照，保留作对照（不是当前版本） |
| `sso/` | SSO 参考实现：票据签发/校验、FastAPI 服务、模拟 oceansite、Nginx 配置 |
| `tools/` | 构建脚本（生成 docx / pptx / UR 模块）+ `check_demo.py` 自检 |
| `Docx/` | 产品设计方案、开发计划、汇报材料 |
| `_ref/` | 调研参考（实机探测结果、Fortinet 技术档案摘要、素材原文） |

---

## 与 networktopology 的关系

`demo/index.html` 的「网络拓扑」菜单里有一个「AI 拓扑编排」入口，它用 iframe 内嵌
[networktopology](https://github.com/gmchen188/networktopology)（独立仓库）——一个 AI 驱动的
draw.io 拓扑画布应用。

两者通过**同源**方式组合：myPortal 挂在 `/portal`，画布应用挂在 `/networktopology`。
同源是刻意的 —— 画布里的 draw.io 编辑器要能被直接控制（读 `contentWindow.EditorUi`），
跨域就只能退化成 postMessage 广播。

iframe 的地址按这个顺序取：

```
?nt= 查询参数  >  window.__NT_APP__  >  默认 "/networktopology/zh"
```

部署形态见 networktopology 仓库的 `docs/P4-LAPTOP-AS-SERVER.md`。

---

## 本地开发

### 演示界面

直接双击 `demo/index.html`。若要用 HTTP 伺服（推荐，file:// 下个别浏览器特性受限）：

```bash
cd demo && python -m http.server 8000
```

### 自检

改完 `demo/index.html` 后跑：

```bash
python tools/check_demo.py
```

它做 57 项断言（视图完整性、路由登记、i18n 键、字段引用、死代码检测等）。
**改 demo 之前先跑一遍确认基线是绿的**，否则你分不清失败是自己造成的还是本来就有的。

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

### 密钥

密钥走环境变量，**不入库**：

| 变量 | 用途 |
|---|---|
| `JWT_SECRET` | 签发 access/refresh token |
| `OCEAN_TICKET_SECRET` | 校验上游票据 |

`JWT_SECRET` 在非 production 环境有 dev 兜底值（`_DEV_JWT_SECRET`），**production 环境下缺失会直接拒绝启动**。
`ticket.py` 的 `_require_strong_secret()` 强制密钥长度 ≥ 32 字节。

---

## Git 约定

- 分支：`main` 为主干，功能分支用 `feature/xxx` / `fix/xxx`
- `main` 推送会触发 `.github/workflows/check.yml`：跑 `check_demo.py`，绿才允许部署
- 提交信息用中文，格式 `type(scope): 摘要`

### 什么不进库

`.gitignore` 已排除：Python 缓存、`.env*`、`*.key`、`*.pem`、`_ref/*.session.json`。

> **FortiSIEM MCP session id 是运行时凭据**，每次 `initialize` 都变，已从 `_ref/mcp_tools.json` 脱敏。
> 仓库里只有工具清单（那部分是有用的参考资料）。
