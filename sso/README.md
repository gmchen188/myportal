# oceansite → myPortal 免密对接方案

**问题**：船东用户在 oceansite 用用户名+密码登录后，进入「网络安全模块」点击链接跳转到 myPortal。
oceansite **没有 SSO 模块**，且不能改造。用户不希望登录两次。

**结论**：可行，而且不需要给 oceansite 加 SSO 模块。
推荐 **方案 A（会话转发票据 / Cookie 换票）**——myPortal 后端替用户去 oceansite 问「他是谁」，
拿到的身份由 myPortal 自己的映射表决定租户，随后签发 myPortal 自己的会话。

本目录是**可运行的参考实现**，30 项断言全部通过，浏览器实测「一次登录」成立。

---

## 为什么不是 OIDC / SAML

这是最容易被默认带偏的地方，先说清楚：

| | OIDC | SAML |
|---|---|---|
| 谁是身份提供方 | oceansite | oceansite |
| oceansite 要做什么 | 实现 Authorization Server | 实现 IdP + 签发 Assertion |
| oceansite 要存什么 | 客户端凭据、授权码、密钥 | 证书、实体元数据 |

**两者都要求 oceansite 变成 IdP。**而 oceansite 没有 SSO 模块、不能改造 —— 所以这两个方案在这个项目里直接出局，
不是"实现成本高"，是**根本做不到**。

任何"让 oceansite 参与签发"的方案都有同样的问题。真正可行的那一类只有一个共同点：

> **让 myPortal 去问 oceansite「当前会话是谁」，而不是让 oceansite 主动交出身份。**

---

## 方案对比

### 方案 A —— 会话转发票据（推荐）

```
用户                浏览器                 myPortal 后端            oceansite
 │                   │                        │                      │
 │─ 登录 oceansite ──▶│                        │                      │
 │                   │── 用户名密码 ───────────▶│                      │
 │                   │◀── 会话 Cookie ─────────│◀─ 校验密码 ────────│
 │                   │                        │                      │
 │─ 点「网络安全模块」─▶│                        │                      │
 │                   │── GET / (myPortal) ───▶│                      │
 │                   │── Cookie: OCSESSION ──▶│                      │
 │                   │                        │── 带同一 Cookie ────▶│
 │                   │                        │◀─ JSON 身份 ────────│
 │                   │                        │                      │
 │                   │                        │ 查映射表 → 租户/角色  │
 │                   │◀─ myPortal 会话 ──────│  签发 JWT + refresh   │
 │                   │   (无二次登录表单)      │                      │
```

**对 oceansite 的要求：只有一个** —— 它已经具备的能力：
**一个"带着会话 Cookie 问它我是谁"的接口**。

这个接口几乎一定已经存在，因为 oceansite 自己也要知道当前用户是谁（显示右上角用户名、判断权限）。
如果它是 HTML 页面而不是 JSON，看「方案 B 的退化兜底」。

**优点**
- oceansite 零改造
- 用户零感知，不弹任何登录表单
- 换票完成后 myPortal 会话独立，oceansite 之后宕机不影响已登录用户
- 不引入第三方 IdP 依赖

**代价**
- myPortal 后端持有转发 Cookie 的能力，必须严格限制用途（见下文「安全边界」）
- 依赖 oceansite 的会话 Cookie 能到达 myPortal —— **这是本方案唯一的部署硬约束**，见下节

### 方案 B —— 一次性票据（oceansite 可改造时的更标准路径）

oceansite 在跳转前生成一个 60 秒有效、只能用一次的签名票据：

```
oceansite: 登录成功 → 生成票据 → 302 /myportal?ticket=xxx
myPortal:  校验签名 + 过期 + 未使用 → 建立自己的会话
```

**对 oceansite 的要求**：加一个「签发票据」的接口（约 30 行代码）。

**优点**：票据不落在浏览器 cookie 里，走 URL 参数用完即焚；标准做法，将来换成真正的 OIDC 也容易演进。

**代价**：oceansite 要改代码。

**本目录同时实现了方案 A 与 B**（`/api/sso/exchange` 与 `/api/sso/exchange-ticket`），
可以共存：**先上零改造的方案 A，oceansite 愿意改造时再切到 B**，myPortal 前端不用动。

### 方案 C —— 退化兜底（oceansite 连 JSON 接口都没有）

如果 oceansite 只有「登录后才能访问的 HTML 页面」：

myPortal 后端带上 Cookie 请求该页面，**用状态码判断**（200 = 已登录，302 = 未登录）。
不解析 HTML —— 解析 HTML 找用户名是脆的，改版就坏。
这种情况下身份来源要另想办法（例如用邮箱映射），且**租户映射表需要人工维护全部账号**。

只在 A、B 都不可行时用。

---

## 部署形态 —— 这是本方案唯一的硬约束

浏览器**不会**把 `oceansite.example.com` 的 Cookie 发给 `myportal.example.com`（不同站点）。
Cookie 属于源站。所以要拿到 oceansite 的会话 Cookie，只有三条路：

### 形态 1：反向代理同源（推荐，生产就用这个）

```
https://oceansite.example.com/            → oceansite
https://oceansite.example.com/security/   → myPortal   ← 同一主机名
```

myPortal 挂在 oceansite 的**同一个主机名**下的子路径。浏览器视之为同源，
Cookie 自动携带，**零前端改造**。

myPortal 自己的 SPA 也走这个前缀，API 相对路径 `/security/api/...`——
和 myPortal 既有原则一致（API base 必须是相对路径，否则 SameSite=Strict 的 refresh cookie 会静默不发）。

### 形态 2：网关做 Cookie 转发

myPortal 是独立主机名时，网关（nginx）把 oceansite 的 Cookie 摘出来，加 `X-Ocean-Session` 头转发给 myPortal 后端。
本实现已支持该头（`/api/sso/exchange` 会读 `X-Ocean-Session`）。

nginx 片段见 `nginx-ocean-sso.conf`。

### 形态 3：父子域共享 Cookie

若 oceansite 的 Cookie 是 `Domain=.example.com`（共享给所有子域），
则 `myportal.example.com` 能直接收到该 Cookie，无需网关。
**但这需要 oceansite 侧改 Cookie 域属性** —— 属于改造，且扩大了 Cookie 的暴露面，**不推荐**。

> **形态选择结论**：优先形态 1。它对 oceansite 零改动，对浏览器行为最可预测，也不引入网关层新的信任边界。

### ⚠ 一个会骗过本地测试的坑

**Cookie 按主机名隔离，不按端口隔离。**

本目录的本地演示是 `127.0.0.1:9101`（oceansite）与 `127.0.0.1:9102`（myPortal）——
主机名相同，浏览器就顺手把 Cookie 带过去了，**看起来跨源也能work**。

但生产环境是 `oceansite.example.com` 与 `myportal.example.com` —— **不同主机名**，
Cookie **不会**被带过去。本地测试通过，生产直接失败。

**所以本地验证不等于跨源验证。** 判断某个形态能否work，看的是主机名，不是端口：

| 部署 | 主机名 | Cookie 自动携带 | 结论 |
|---|---|---|---|
| 本地演示 | 同（127.0.0.1，端口不同） | 是 | **不代表生产** |
| 形态 1（推荐） | 同（oceansite.example.com/security/） | 是 | 成立 |
| 形态 2（网关） | 不同 | 否 —— 由网关加 `X-Ocean-Session` 头 | 成立 |
| 形态 3（父子域） | 不同，但 Cookie Domain 覆盖 | 是 | 需改 oceansite，不推荐 |

**因此**：验收时必须在**真实的跨主机名**拓扑下验证形态 2，
不能拿本地 9101→9102 的结果当证据。本目录的 `verify_sso.py` 中，
形态 2 是**直接构造 `X-Ocean-Session` 头**来测的（[4b] 段），
不依赖 Cookie 是否自动携带 —— 这才是形态 2 的真实条件。

---

## 安全边界（这几条不能松）

1. **Cookie 只在服务端转发。** 绝不在响应里回显，绝不写日志，绝不落库。
   本实现已加断言：换票响应中不出现 oceansite 会话值。

2. **转发范围限定一个端点。** 不是通用反向代理 —— 只允许 myPortal 后端访问配置的
   identity 端点，不能配成"把 oceansite 当后端用"。

3. **身份 → 租户的映射在 myPortal 侧。**
   上游只说"我是谁"，不说"我能看哪个租户"。
   映射表查不到 → **默认拒绝（403）**，不是默认放行。
   oceansite 新增一个账号，不应该自动获得某个租户的数据。

4. **未映射身份拒绝时不泄露租户信息。** 403 响应里不含租户名、组织名、FortiSIEM Organization。

5. **票据规则**：HMAC-SHA256、60 秒 TTL 上限、一次性、常数时间比较、必需声明齐全。
   超长 TTL 的票据**在签发和校验两侧都被拒绝**。

6. **审计留痕但不记凭据。** 记录 `auth.sso_exchange` / `auth.sso_ticket_exchange` /
   `auth.sso_ticket_rejected`，含 actor、tenant、outcome、来源系统 —— **不含任何会话值**。
   SSO 是绕过本地登录表单的访问路径，不记审计就等于这条路径没被监控。

7. **会话独立。** 换票后 myPortal 用自己的 JWT + refresh cookie（refresh 存哈希、可轮换），
   不再依赖 oceansite。oceansite 宕机不影响已登录用户。

8. **HttpOnly + Secure + SameSite。** 生产环境 `secure=True`。

9. **密钥长度必须在启动时校验，不是运行时警告。**
   HS256/HMAC-SHA256 的密钥至少 32 字节（RFC 7518 §3.2）。
   短密钥可被离线暴力还原 —— 票据等同明文，会话等同无认证。
   所以：
   - `JWT_SECRET` 长度不足 → **启动即失败**，不降级、不警告后继续
   - `MP_ENV=prod` 且未配置 `JWT_SECRET` → **拒绝启动**，不退回开发默认值
     （一个所有人相同的硬编码密钥等于没有认证）
   - `OCEAN_TICKET_SECRET` 长度不足 → 换票端点返回 500，**不放行**
   - 票据的 `sign()` 与 `verify()` **两侧**都拒绝短密钥

---

## 文件

| 文件 | 作用 |
|---|---|
| `sso_service.py` | myPortal 侧对接服务：落地页、换票端点、票据换票、会话、审计 |
| `mock_oceansite.py` | oceansite 模拟器（**没有 SSO 模块**，只有表单登录 + 会话 Cookie + whoami） |
| `ticket.py` | 票据编解码（HMAC-SHA256，两侧共用的唯一规则） |
| `verify_sso.py` | 端到端验证：35 项断言，含 10 项负向用例 |
| `test_key_guard.py` | 密钥长度守卫的分支验证（11 项，含扰动证明） |
| `nginx-ocean-sso.conf` | 形态 2 的网关配置片段 |

---

## 跑起来看

```bash
cd C:/Users/gmche/Work/myPortal/sso

# 密钥至少 32 字节（RFC 7518 §3.2）—— 短的会被启动检查拒绝
export OCEAN_TICKET_SECRET="local-dev-ticket-secret-0123456789-abcdef"

# 终端 1
python mock_oceansite.py     # 9101

# 终端 2
python sso_service.py         # 9102

# 浏览器打开 http://127.0.0.1:9101/login
#   账号 captain / viewer / outsider，密码 Ocean@2026
#   登录后点「网络安全模块」→ 直接进入 myPortal，没有第二次登录
```

自动验证：

```bash
python verify_sso.py
# 通过 35 项，失败 0 项

# 单独验证密钥守卫
python test_key_guard.py
# 通过 11 项，失败 0 项
```

---

## 接入生产还需要什么

| 环境变量 | 要求 | 说明 |
|---|---|---|
| `JWT_SECRET` | ≥32 字节 | 生产必配（`MP_ENV=prod` 时缺失即拒绝启动） |
| `OCEAN_TICKET_SECRET` | ≥32 字节 | 票据 HMAC 密钥，仅方案 B 需要 |
| `MP_ENV` | `dev` / `prod` | `prod` 时禁用一切开发默认值 |

| 事项 | 谁提供 | 说明 |
|---|---|---|
| oceansite 的 whoami 端点地址与响应格式 | 对方 | 若不确定，用方案 C 兜底探测 |
| oceansite 会话 Cookie 名与有效期 | 对方 | `OCSESSION` / TTL |
| 部署形态（建议形态 1） | 双方 | 反向代理挂载路径前缀 |
| 身份 → 租户映射表 | 双方 | 首批账号清单；myPortal 侧「租户管理」页面维护 |
| 双方 HTTPS 证书 | 双方 | `secure=True` 的前提 |

### 建议排期

不改动 myPortal 现有计划。放在 **M1（多租户与认证）** 同期完成 ——
它本来就要做认证与会话，接入只是多一个上游身份源，不额外占工期。

M1 增加的三个任务：

- **M1-5** 免密对接：会话转发票据 + 身份映射表 + 审计（3 人日）
- **M1-6** 部署形态落地：反向代理同源挂载 + Cookie 策略验证（2 人日）
- **M1-7** 与 oceansite 联调：真实端点探测、映射表导入、异常路径演练（2 人日）

**M1-7 依赖对方提供 whoami 端点信息** —— 建议现在就提出来，
否则它会成为 M1 收尾时的阻塞项。
