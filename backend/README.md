# myPortal 后端 —— 资产清单 / 网络拓扑 / 安全监控

真实后台的第一版。此前 myPortal 的资产、拓扑、事件全是前端硬编码数组；
这一版全部落到 SQLite，接口有持久化、有租户隔离、有校验。

```
backend/
  app/
    main.py                     FastAPI 入口
    db.py                       SQLAlchemy 模型 + SQLite
    auth.py                     JWT + 租户作用域
    routers/
      assets.py                 资产清单（含三条导入路径）
      topologies.py             拓扑图 CRUD + 节点绑定
      monitoring.py             监控面板 + 事件接入 + 模型选择器
    services/
      asset_import.py           解析 → 校验 → 预览
      topology_parse.py         draw.io XML → 节点/连线/区域
      monitoring.py             设备状态与颜色计算
      fortisiem.py              FortiSIEM 连接器
      syslog_collector.py       UDP syslog 接收器
      model_picker.py           图生图模型选择器
  tests/test_backend.py         33 项断言
```

## 跑起来

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 9102
```

开发环境免登录：请求带 `X-Dev-Tenant: asi`（或 `dongfang`）。
生产环境 `MP_ENV=prod` 时**没有 token 一律 401**。

---

## 一、资产清单的三条输入路径

三条路径共用同一个「解析 → 校验 → 预览 → 落库」流水线。
**预览与落库分成两步** —— 用户能在入库前改映射、补字段、跳过重复行。

### 路径 A：文件导入（CSV / Excel）

```
POST /api/assets/import/file     multipart，字段名 file
```

支持 `.csv` `.txt` `.tsv` `.xlsx` `.xls`。分隔符自动嗅探（逗号/制表符/分号/竖线），
编码自动识别（utf-8-sig / gbk / latin-1）。`.xls` 老格式需要 `xlrd`。

返回：

```json
{
  "mapping": [{"header":"设备名称","field":"name","score":0.99}],
  "rows":    [{"row_no":2,"values":{...},"status":"ready","issues":[...]}],
  "issues":  [{"level":"warn","message":"1 处与已有资产或本次导入重复"}],
  "stats":   {"total":5,"ready":3,"skip":1,"needs_fill":1}
}
```

**职责边界**：AI 只做列名识别与建议；必填/去重/值域/租户作用域由服务端规则判定。

去重键：`natural_id` → 名称 → 序列号。**已有资产不覆盖**，重复行跳过并列出。

### 路径 B：从拓扑图生成初步清单

```
POST /api/assets/import/topology    {"nodes":[{"label":"FW-EDGE-01","zone":"Zone3"}]}
```

从拓扑图的节点生成资产行，类型按命名惯例推断（`FW-EDGE-*` → 防火墙，
`CBS-*` → 船舶系统，`OT-DMZ-*` → DMZ，`*-GW` → 网关……）。

这些行**几乎总是缺必填字段** —— 拓扑图给的是「有哪些设备」，不是
「这些设备是什么」。缺的就标 `needs_fill`，用户补全后才能保存。

### 路径 C：手工输入

```
POST /api/assets      单条
GET  /api/assets/schema   字段定义（前端渲染表单用，不要在前端再写一份）
```

### 落库

```
POST /api/assets/commit   {"rows":[...], "mapping":[...], "source":"import"}
```

幂等：按去重键跳过已存在的。再提交一次同一批 → `created=0 skipped=N`。

---

## 二、网络拓扑

### 画图

三条路径，都产出 draw.io XML：

| 方式 | 说明 |
|---|---|
| 导入图片 | networktopology 的 `display_diagram` 工具：VLM 读图 → XML |
| 自然语言 / 语音 | 调资产清单里的资产生成拓扑 → XML |
| 空白画布手工绘制 | draw.io 编辑器 |

**保存**：`POST /api/topologies`，存整份 XML。

**这里有一个必须知道的格式差异**：`display_diagram` 工具产出的 XML
**不是标准 draw.io XML** —— 它没有 `<mxfile>` 外壳，是一串并列的
`<mxStyle>` + `<mxCell>`，几何写在属性上（`x=` `y=` `w=` `h=`），
也不写 `vertex="1"`。

解析器三种格式都吃（见 `topology_parse._parse_xml_any`），但**验证图生图
质量时不要数 `mxgraph.cisco19` 图标或 `edge="1"`** —— 那个工具本来就不
产出这些。用**设备 ID 命中率**和**区域名命中率**，那才是用户看得懂的东西。

### 图生图的模型选择器

```
GET /api/models/image-capable          全部模型 + image_capable 标记
GET /api/models/{model_id}/image-check 单个模型能不能读图
```

`MiniMax-M3` 支持图片，`MiniMax-M2.5` **不支持**。选择器返回全部模型并
标出能力 —— 前端要能显示「选这个不行」的提示，不能只列可用的那些。

能力不足时**明确说不行**，不要默默降级：用户上传了图却得到一句「我看不清」，
比直接报错更让人困惑。

### 监控面板

```
GET /api/monitor/topologies/{id}/panel
```

返回节点 + 设备状态 + 颜色 + 事件计数。监控面板是**可拖拽编排**的 ——
拖拽改的是布局，拓扑结构由 draw.io 那边维护。

节点 ↔ 设备的绑定：

```
POST /api/topologies/{id}/monitors
{"node_id":"d1","natural_id":"FW-EDGE-01","ip":"172.16.10.1","channel":"fortisiem"}
```

**没有这张表，监控面板不知道 draw.io 图里的方块对应哪台设备** ——
拓扑图存的是形状和标签，设备在 CMDB 里，两边靠它对齐。

---

## 三、监控：设备变色

### 颜色规则

| 级别 | 颜色 | 值 |
|---|---|---|
| critical | 红 | `#dc2626` |
| high | 粉红 | `#ec4899` |
| medium | 黄 | `#f59e0b` |
| low | 蓝灰 | `#64748b` |
| normal | 绿 | `#16a34a` |
| unknown | 灰 | `#94a3b8` |

**一个设备的颜色由它当前未解决事件里的最高级别决定**，不是最新事件的
决定。一台设备昨天有 critical、今天没有新事件 —— 它仍然是红的，直到那条
事件被关闭。取「最新事件」的颜色会让设备闪一下就变绿，那是在骗人。

**`unknown` 是独立状态：没有数据 ≠ 正常。** 一台没接入监控的设备画成绿色，
运维会以为它安全 —— 这是最危险的一种错。灰色明确说「我不知道」。

### 严重度归一

FortiSIEM 的 `severity_cat` 只有 `HIGH`/`MEDIUM`/`LOW` —— **没有 CRITICAL**。
临界事件在 SIEM 里是数值 `severity`（9-10）。所以两列都要看：

```python
severity_from_score(9.5, "HIGH")  →  "critical"
severity_from_score(7.5, "HIGH")  →  "high"
severity_from_score(5, "MEDIUM")  →  "medium"
```

---

## 四、其他网络设备如何接收安全事件

这是本次最核心的设计问题。答案是：**myPortal 自己就是事件汇聚点。**

### 不是所有设备都要接进 FortiSIEM

工控交换机、PLC、RTU 通常只发 syslog；很多 OT 网段**不允许出站到 SOC**
（安全分区要求），但允许发到同区的采集器；老设备只支持 SNMP Trap。
把这些设备硬接进 FortiSIEM，要为每种设备类型写 parser，还要打通 OT 到
SOC 的网络通路 —— 两条都很难。

### 分通道

| 通道 | 接入方式 | 适合 |
|---|---|---|
| `fortisiem` | 从 FortiSIEM 同步 | Fortinet 设备，以及已在 SIEM CMDB 里的设备 |
| `syslog` | UDP 514/1514 → myPortal | 交换机、路由器、工控设备 |
| `snmp_trap` | 转成 syslog 格式走同一通道 | 不支持 syslog 的老设备 |
| `webhook` | HTTP POST | 漏洞扫描器、UEBA、OT 监控系统 |
| `manual` | 人工登记 | 巡检发现 |

**所有通道写进同一张 `incidents` 表**，按 `natural_id` / IP / 名称归集到
设备，监控面板按设备算颜色。归一在这一层做，不在各处重复。

### 接入接口

```
POST /api/events/syslog     {"text":"<134>Nov 21 21:50:12 SW-CORE-01 %LINK-3-UPDOWN: ..."}
POST /api/events/webhook    {"title":"...","severity":"HIGH","asset_id":"CBS-CCTV-01","ip":"..."}
POST /api/events            {"title":"...","severity":"critical","device_natural_id":"..."}
```

webhook 接受多种字段别名（`title`/`message`/`summary`，`severity`/`risk`/`level`，
`host`/`device`/`asset_id`）—— 各家系统叫法不同，归一在一处做。

### syslog 接收器

```bash
python -m app.services.syslog_collector --port 1514 --tenant t-asi
```

设备侧：

```
SW-CORE-01(config)# logging host 10.0.0.5 514
SW-CORE-01(config)# logging trap informational
```

支持 RFC3164 与 RFC5424。解析不出 IP 时用主机名归集；解析不出级别时
退到 `medium` —— **宁可标成中等，也不要静默丢弃一条事件**。

多租户按源 IP 前缀分派：

```bash
python -m app.services.syslog_collector --port 1514 --tenant t-asi \
  --tenant-map '{"10.1.":"t-dongfang"}'
```

端口 514 是特权端口，非 root 用 1514 再转发（`iptables -j REDIRECT`）。

### 这个设计的三个好处

1. **FortiSIEM 不可达时监控面板仍然工作** —— 直连 myPortal 的通道不依赖 SIEM
2. **不用为每种设备类型写 FortiSIEM parser** —— 归一在 myPortal 侧做
3. **OT 网络不需要开放到 FortiSIEM 的通路** —— myPortal 部署在 OT 侧即可

### FortiSIEM 连接器

`app/connectors/fortisiem.py` 按实机验证过的契约实现：

- 认证 `POST /phoenix/rest/pub/security/oauth/token`（form-encoded，
  Client Credentials，**不是** admin GUI 密码）
- 内部面 Accept 头要 `application/json, text/plain, */*` —— 严格 JSON 会 406
- 表名是 `ph_incident` 不是 `phoenix_incident`
- 租户字段：REST 面叫 `organization`，MCP 面叫 `org_name` —— 两个都认
- `httpx.Client(trust_env=False)` —— 系统代理会把到内网设备的调用劫持掉，
  表现为 12 秒后的 TLS 超时，看起来像「设备不通」

**连接不可达时优雅降级**：返回「未连接」标记，不抛异常。监控面板照常显示
（设备灰色 = 不知道，不是有问题）。

---

## 五、多租户

**作用域来自凭据，不来自请求参数。** 一个租户的 token 只能读它自己的资产，
参数里写别人的 `tenant_id` 也不行。

租户过滤之外还有第二道防线：读别的租户的记录答 **404 而不是 403** ——
403 确认了资源存在。

---

## 六、下一步

- [ ] myPortal 前端（`demo/index.html`）接上这些 API —— 现在还是硬编码数组
- [ ] 票据方向：myPortal 签发 → networktopology 校验（现有 `sso/ticket.py`
      是 oceansite→myPortal 方向，`sign`/`verify`/`build_payload` 通用可复用）
- [ ] `frame-ancestors` 加 myPortal 白名单 —— Web App 现在任何站都能嵌
- [ ] 保存落 myPortal 租户资产（现在是 myPortal 自己的库）
- [ ] PostgreSQL 迁移（模型与查询不动，只改 `DATABASE_URL`）
