# 代码质量审查 —— FortiSIEM 面板

审查针对的 HEAD 是 b2f551c，审查时间 2026-11-21。

> 审查范围：`web/src/` 下的新代码 —— `components/siem-diagnostics.tsx`、`pages/siem.tsx`、
> `hooks/use-siem.ts`、`test/siem.test.tsx`、`api/client.ts` 里新增的 siem 相关部分。
> 本次是**代码质量审查**，不是规格审查。
>
> **过程说明**：审查期间代码连续变动三次（`b53f75c` 探测缓存、`23bcb2d` 规格审查修复、
> 以及后续提交）。本报告的每一条都针对 **HEAD `b2f551c`** 重新核对过行号与代码，
> 引用行号均可由 `git show b2f551c:<path>` 复现。
>
> **已验证项**（不必重跑）：tsc exit 0 / vitest 15 passed（2 files）/ biome check（见 M-7）。
> 审查过程中另外核对了 `node_modules/@tanstack/query-core@5.108.2` 的实际源码
> （`queryObserver.js:294`、`focusManager.js`、`query.js` reducer、`mutation.js` reducer），
> 以及对 `client.ts` 真实源码直接用 `node --experimental-strip-types` 跑了一遍
> `extractDetail` / `extractErrorMeta` 的实际输出。

---

## Critical（必须修）

无。没有发现会导致数据损坏或功能性崩溃的问题。

---

## Important（应该修）

### I-1 · `web/src/hooks/use-siem.ts:53-56` — 同步成功后没有作废 `events` 缓存，事件列表静默过期

> **状态：作者已确认并修复（工作区未提交）。** 下面保留原始记录，便于回溯。

同步会写入 `Incident` 行（`backend/app/routers/siem.py:204-212`，`source="fortisiem"`），
但 `onSuccess` 只作废了两条：

```js
onSuccess: () => {
    void qc.invalidateQueries({ queryKey: ["assets"] })
    void qc.invalidateQueries({ queryKey: ["siem-status"] })
},
```

事件页用 `["events", severity, source]`（`web/src/pages/events.tsx:24`）、总览用 `["events"]`
（`web/src/pages/overview.tsx:16`）—— **两个都不在作废列表里**。

这条正是「invalidateQueries 的 queryKey 是否真的能命中」要查的：
`["siem-status"]` 和 `["assets"]` 两条**是对的**（TanStack 默认 `exact: false`，
`partialMatchKey` 前缀匹配，`["assets"]` 能命中 `["assets", params]`）。
漏的是 `["events"]` —— 同步拉进 12 条事件后，事件页在下次窗口聚焦/重新挂载前一直显示旧条数，
而同步面板同时显示「事件 新增 12」，两边对不上。

**影响**：静默过期比报错更坏 —— 用户会以为同步没生效。

**修法**：`void qc.invalidateQueries({ queryKey: ["events"] })`
（前缀匹配同时命中 `["events"]` 与 `["events", severity, source]`）。
另可一并作废 `["monitor-panel"]`（监控面板节点颜色依赖事件）。

### I-2 · `web/src/pages/siem.tsx:304-317` + `web/src/api/client.ts:456-462` — 设备拉取失败被显示成「0 台设备」

后端在设备拉取失败时**捕获了异常**并记进 `dev_stats["error"]`：

```python
# backend/app/routers/siem.py:227-234
dev_stats: dict[str, Any] = {"total": 0, "created": 0, "updated": 0, "skipped": 0}
if devices:
    try:
        siem_devs = c.devices()
    except Exception as e:
        # 设备拉不到不影响事件 —— 事件已经入库了
        dev_stats["error"] = str(e)[:200]
        siem_devs = []
```

但前端的 `SiemSyncCounts` 类型只有五个字段：

```ts
// web/src/api/client.ts:456-462
export interface SiemSyncCounts {
    fetched?: number
    total?: number
    created: number
    updated: number
    skipped: number
}
```

`error` / `bind_error` / `bound` 三个字段既不在类型里，UI 也不渲染
（`pages/siem.tsx:304-317` 只用了 total/created/updated/skipped）。

**结果**：设备拉取失败时，屏幕显示「设备 共 0 / 新增 0 / 更新 0 / 跳过 0」，
**读起来跟「SIEM 里确实没有纳管设备」一模一样**。
对一个专门为了区分「漏纳管 ≠ 安全」而做的页面来说，这是最不该丢的一类信息 ——
后端已经算出来了，前端扔掉了。

`bind_error`（拓扑自动绑定失败，`siem.py:287`）同理，也是静默吞掉。
`bound`（自动绑定了多少台设备到拓扑节点，`siem.py:282-285`）是有价值的运维信息，一并丢掉。

**这正是「try/catch 吞掉错误后静默失败」**：catch 在后端，不在前端，但结果一样。

**修法**：类型补 `error?: string` / `bound?: number` / `bind_error?: string`，
UI 上设备那一行有 error 时显红提示。

### I-3 · `web/src/pages/siem.tsx:133` 与 `:150` — 「无法获取连接状态」和「四段全通」同时出现

TanStack Query v5 的 query reducer 在 error 时**保留 `data`**：

```js
// node_modules/@tanstack/query-core/build/modern/query.js:523-536
case "error": {
    const error = action.error;
    return {
        ...state,          // ← data 被保留
        error,
        errorUpdateCount: state.errorUpdateCount + 1,
        errorUpdatedAt: Date.now(),
        fetchFailureCount: state.fetchFailureCount + 1,
        fetchFailureReason: error,
        fetchStatus: "idle",
        status: "error",
        isInvalidated: true
    };
}
```

只是把 `status` 改成 `"error"`。于是页面上：

- `status.isError` → 第 133 行渲染红色「无法获取连接状态」卡片
- `data` 仍在 → 第 150 行 `{data && (...)}` 照常渲染「已连接 / 四段全通 / 全部通过」

后台挂掉 30 秒后的下一次轮询失败，就会同时出现这两个互相矛盾的面板。
这正是作者自己在 `23bcb2d` 里修掉的 `error` / `devices_error` 那一类矛盾，只是换了个位置。

**修法**：错误卡加 `&& !data` 条件（只在没有旧数据时显示），
或者在有旧数据时改成「刷新失败，以下是上次结果（HH:MM）」。

### I-4 · `web/src/api/client.ts:146-151` — 502 消息丢了具体原因，只剩笼统标签

后端 502 的 body（`backend/app/routers/siem.py:148-156`）：

```python
raise HTTPException(
    502,
    {
        "error": "FortiSIEM 不可达",   # ← 笼统标签
        "stage": st.stage,             # ← 卡在哪一段
        "detail": st.error,            # ← 具体原因（真正有用的那个）
        "probes": st.probes or {},
    },
)
```

其中 `detail` 才是**具体原因**（`"未配置 FORTISIEM_CLIENT_ID / FORTISIEM_CLIENT_SECRET"`
或 `"网络不通：172.16.20.48:443 不可连接：TimeoutError"`），`error` 只是笼统标签。

`extractDetail` 里 `inner.error` 优先于 `inner.detail`：

```js
// web/src/api/client.ts:146-151
const msg =
    typeof inner.error === "string" && inner.error
        ? inner.error
        : typeof inner.detail === "string" && inner.detail
          ? inner.detail
          : null;
```

用**真实当前源码**跑了一遍（`node --experimental-strip-types` 直接加载 `client.ts`）：

```
A. 真实 502 body {detail:{error,stage,detail,probes}}
   => "FortiSIEM 不可达（卡在 认证取 Token 这一段）"
```

认证失败的具体原因被丢了。用户看到「卡在认证段」但不知道是「没配 client id」还是「凭据过期」。

顺带验证另外几种形状（都正确）：FastAPI 字符串 detail ✓、嵌套 `{error,stage}` ✓、
`{"detail":{"error","detail","stage"}}` ✓、识别不出的形状退回 `HTTP {status}` ✓。
**问题只在 error 与 detail 同时存在时的优先级。**

**修法**：`error` 与 `detail` 同时存在时拼起来（`${error}：${detail}`）。

### I-5 · `web/src/api/client.ts:168-184` + `web/src/pages/siem.tsx:279-281` — 502 的 `probes` 提取了但没人用

`extractErrorMeta` 正确地从嵌套 body 里取出了 `stage` 和 `probes`（实测：

```
META(A)    => {"stage":"auth","probes":{"tcp":{"ok":true,"detail":"可连接"}}}
META(flat) => {"stage":"auth"}
```

✓），`ApiError` 也带了 `meta` 字段（`client.ts:23`、`client.ts:104`）。

但是 `grep -rn "\.meta" web/src` 的结果只有 `client.ts` 自己和测试文件 ——
**`meta.probes` 在生产代码里没有任何消费者**。
同步失败时 UI 只显示 `sync.error.message` 一行字
（`pages/siem.tsx:279-281`），后台特意塞进 502 的四段实测结果还是被丢在地板上。

既然 `23bcb2d` 已经把这套管道修好了，就差 UI 接上：同步失败时把 `error.meta.probes`
渲染成四段列表，和状态面板用同一个 `SiemStageList` 组件即可（它已经导出了，
接收 `{ok, detail}` 形状，字段名对得上）。

### I-6 · `web/src/pages/siem.tsx:160` — 用 `STAGE_LABEL[data.stage]` 直接索引，绕过了为此专建的 `stageLabel()`

```js
// web/src/pages/siem.tsx:160
{data.stage === "ok" ? "四段全通" : data.stage ? `卡在 ${STAGE_LABEL[data.stage]} 这一段` : "未探测"}
```

`web/src/api/client.ts:409` 专门写了 `stageLabel()`，注释就是
「未知 stage 的兜底 —— 直接显示原值，别吞掉信息」；`extractDetail:153,155` 也正确地用了它
（`${msg}（卡在 ${stageLabel(stage)} 这一段）`）。但 `pages/siem.tsx:160` 直接 `STAGE_LABEL[data.stage]`。

`data.stage` 在前端被窄化成 `SiemStage | null`，后端实际发的是普通字符串。
一旦后端加一个阶段值，这里渲染出 **「卡在 undefined 这一段」**。
当前后端只发 tcp/tls/auth/api/ok，所以还触发不了 —— 但这正是 `stageLabel` 存在的理由。

**修法**：`${stageLabel(data.stage)}`。

### I-7 · `web/src/pages/siem.tsx:90-100` 与 `:257-266` — 两个一模一样的「同步到资产清单」主按钮

头部工具栏一个（旁边还有时间窗口下拉），同步卡片里一个全宽一个。行为完全相同：

```js
// :93-95（头部）
onClick={() => sync.mutate({ minutes, devices: true, overwrite })}

// :261（卡片）
onClick={() => sync.mutate({ minutes, devices: true, overwrite })}
```

文案一字不差（`:99` 与 `:265` 都是「同步到资产清单」），都是 `btn primary`。

同一屏两个一模一样的 primary CTA，运维不知道该点哪个；而且 `overwrite` 复选框只在卡片里
（`:248-255`）、头部按钮看不到，两个按钮的行为其实**依赖于一个离它很远的复选框**。

**修法**：删掉卡片里那个（保留头部的，因为窗口下拉在那儿），
或者把 overwrite 复选框移进头部工具栏。

---

## Minor（可选）

### M-1 · `web/src/api/client.ts:565-571` — 同步没有暴露后台的 `limit` 上限，30 天窗口会被静默截断

后端 `sync_from_siem(limit: int = Query(200, ge=1, le=1000))`（`backend/app/routers/siem.py:133`），
前端 `api.siem.sync` 只发 `minutes/devices/overwrite`，从不发 `limit`。
用户选「最近 30 天」（`pages/siem.tsx:28`，43200 分钟），实际最多拿 200 条事件。

UI 显示「事件 拉取 {result.events.fetched}」（`:292`）—— 数字本身是诚实的，
但没有任何提示说明还有更多。可以补一个 `limit` 参数或在 UI 上写明上限。

### M-2 · `web/src/pages/siem.tsx:254` — 「覆盖已存在的行」这个措辞对设备不成立

```js
// :254
覆盖已存在的行（默认不覆盖 —— 保留先到的那条）
```

后端 `overwrite` **只作用于事件**（`backend/app/routers/siem.py:195-201`）；
设备/资产那一支明确写着「只补空字段，不覆盖用户填的」（`siem.py:266-277`），
`overwrite` 参数在资产分支根本没被读。

用户勾上「覆盖已存在的行」，预期设备行会被覆盖 —— 不会。
建议改成「覆盖已存在的事件（设备行只补空字段）」。

### M-3 · `web/src/pages/siem.tsx:143` — 「重试」按钮用的还是不带 `refresh` 的 `refetch()`

```js
// :143
onClick={() => void status.refetch()}
```

`b53f75c` 已经识别出「`refetch()` 用原 queryFn → 拿到的还是缓存结果」这个坑
并用 `useSiemRefresh`（`hooks/use-siem.ts:32-40`）修掉了头部按钮，
但错误卡里的「重试」按钮仍然直接 `status.refetch()`。
两个「重新查一次」的入口语义不一致。

### M-4 · `web/src/pages/siem.tsx:348` — `key={d.natural_id || d.name}` 的兜底可能撞键

```js
// :348
<tr key={d.natural_id || d.name}>
```

`natural_id` 为空是真实存在的（后端 `siem.py:238-239` 专门 `if not nid: skipped += 1`），
两台同名且都没有 naturalId 的设备会产生重复 React key（警告 + 渲染错位）。
不是 index key，这点没问题。

### M-5 · `web/src/test/siem.test.tsx:176` — mock 的错误对象形状和生产不一致，`/502/` 断言是假的

生产里 `ApiError.detail` 是 `extractDetail()` 的产物（不含 `[502]`），
`[502] ` 前缀只在 `.message` 里（`web/src/api/client.ts:26`：`super(\`[${status}] ${detail}\`)`）。
mock 却把 `"[502] FortiSIEM 不可达"` 塞进 `detail`：

```js
// :176
error: { detail: "[502] FortiSIEM 不可达" },
```

于是 `expect(screen.getByText(/502/)).toBeTruthy()`（`:182`）靠 mock 才成立 ——
真实生产渲染其实**不显示状态码**。建议 mock 成真的
`new ApiError(502, "FortiSIEM 不可达（卡在 认证取 Token 这一段）")`，
顺便就能锁住「状态码该不该显示」这个决定。

### M-6 · `web/src/test/siem.test.tsx:80-81` — `expect(getByText(...)).toBeDefined()` 是空断言

```js
// :80-81
expect(screen.getByText("失败")).toBeDefined()
expect(screen.getByText(/网络不通/)).toBeDefined()
```

`getByText` 找不到就抛异常，所以 `.toBeDefined()` 永远为真，没断言任何东西。
`src/test/setup.ts` 已经引了 `@testing-library/jest-dom/vitest`，用 `toBeInTheDocument()` 才对。

### M-7 · import 顺序 —— biome `assist/source/organizeImports` 报了 3 处

- `web/src/components/siem-diagnostics.tsx:16-17` —— 从同一模块拆了两条 import（值 + type）应合并
- `web/src/pages/siem.tsx:21` —— 具名导入未按字母序（`useSiemStatus, useSiemSync, useSiemRefresh`）
- `web/src/test/siem.test.tsx:1-13` —— import 放在 `vi.mock` 之后

**补充说明**：`npm run lint` 目前**整个仓库都红** —— `biome.json` 根本不存在，
biome 用默认的 tab 缩进而仓库用 4 空格。既有文件 `app-shell.tsx` / `use-assets.ts` /
`use-health.ts` / `main.tsx` / `events.tsx` / `overview.tsx` 同样报 format 错，
且 CI（`.github/workflows/check.yml`）只跑 `tsc --noEmit` + `npm test` + `npm run build`，**不跑 biome**。

所以这不是这次改动引入的回归，但新增的 3 条 organizeImports 值得顺手改。

### M-8 · `web/src/components/siem-diagnostics.tsx:20` — `STAGE_ORDER` 导出后无人使用

```ts
// :20
export const STAGE_ORDER: Exclude<SiemStage, "ok">[] = ["tcp", "tls", "auth", "api"]
```

只在同文件第 43 行用了一次。

### M-9 · `web/src/components/siem-diagnostics.tsx:66` — 非权威段的失败会借用顶层 `status.error`

```js
// :66
detail: failedHere || !probe.ok ? (status.error ?? probe.detail) : probe.detail,
```

当某个 probe `ok=false` 但它**不是** `status.stage` 指的那一段时，展示的却是别段的顶层 error。
当前后端 `_probe()` 遇到第一个失败就 return，所以触发不了；属于脆弱耦合，不是现网 bug。

---

## 你问的几个点，直接回答

| 问题 | 答案 |
|---|---|
| 会不会抛异常的空访问？ | 没找到真会抛的。`status.probes[key]` 的 `!probe` 分支处理了缺段（`siem-diagnostics.tsx:44-59`）；`devices ?? []`、`result.events.fetched ?? 0` 都兜住了。**但整个 app 没有 ErrorBoundary**（全仓 grep 无 `ErrorBoundary` / `componentDidCatch`），任何渲染期异常 = 整页白屏。 |
| React Query 用法对不对？ | 对。`staleTime: 20s < refetchInterval: 30s` 合理；`refetchOnWindowFocus: false` 有注释说明理由（`use-siem.ts:11-13, 21`）。`useSiemRefresh` 用 `setQueryData(["siem-status"], data)`（`:37`）**命中**了 `useSiemStatus` 的 `["siem-status"]`（`:17`）—— key 一致，没有静默失效。 |
| 轮询 30 秒会在页面不可见时打后端吗？ | **不会。** TanStack v5 默认 `refetchIntervalInBackground: false`，`queryObserver.js:294` 的条件是 `this.options.refetchIntervalInBackground \|\| focusManager.isFocused()`，而 `focusManager.isFocused()` = `document.visibilityState !== "hidden"`。隐藏标签页不轮询。路由切走 `/siem` 也会停（observer 卸载 → `destroy()` → 清定时器）。**但**侧栏 `useHealth`（`use-health.ts:12`）的 30 秒轮询常驻，`/health` 每次都跑 `get_client().status()`；加上 `/siem` 自己的 30 秒轮询，就是**两个独立 30 秒轮询器打同一个昂贵探测**，10 秒后端缓存只在两者相位恰好接近时才命中。 |
| 后端探测成本 | `/api/siem/status` 里 `c.devices()` 在 router 层、**在探测缓存之外**（`backend/app/routers/siem.py:84-87`），所以每次轮询都会真拉一次 CMDB XML。后端 10 秒缓存（`fortisiem.py:150`）只缓存 `_probe()`。 |
| 闭包捕获陈旧状态？ | 没有。`refreshErrorText`（`pages/siem.tsx:36-39`）每次渲染重算，`queryFn` / `mutationFn` 无外部依赖。 |
| 原始 Error / 堆栈渲染出来了吗？ | **没有。** `client.ts:137`、`pages/siem.tsx:279-281` 只取 `.message` / `.detail`，`ApiError` 的 message 是 `[502] <人话>`，不含堆栈。 |
| 502 的两种 body 形状都对吗？ | FastAPI 真实形状（`{"detail": {...}}`）✓、字符串 detail ✓、嵌套 `{error,stage}` ✓、不认识的退回 `HTTP {status}` ✓。**但 error 与 detail 同时存在时丢了 detail（I-4）**，且 flat 的 `{error,stage}` 顶层形状会丢 stage（`extractDetail:136-140` 提前 return；后端当前不产生这种 body，但 `extractErrorMeta` 支持 —— 两者对同一形状的处理不一致）。 |
| 有静默失败吗？ | 有两处：后端 `dev_stats["error"]` 前端不渲染（I-2）；`extractErrorMeta` 取到的 probes 前端没人用（I-5）。 |
| CSS 硬编码颜色？ | 这轮已修干净：`siem-diagnostics.tsx:96` 现在是 `color-mix(in srgb, var(--color-sev-critical) 6%, transparent)`，其余全用 token（`var(--border)` / `var(--color-sev-critical)` / `var(--color-sev-normal)` / `var(--color-sev-unknown)`）。 |
| 定时器 / 卸载后 setState？ | 干净。没有手写定时器或订阅，全靠 TanStack 生命周期；没有 `setState` after unmount 的路径。 |
| 列表 key 用 index？ | 不是。用 `natural_id || name`，兜底可能撞（M-4）。 |
| 5 个新测试测有意义行为吗？ | 前 4 个测的是真行为（状态映射、skipped vs fail 的区分、error 优先级、非颜色通道），质量不错。**但覆盖有缺口**：同步失败态（502）渲染完全没测、`devices_error` 分支（`23bcb2d` 刚修的）零覆盖、`useSiemSync` 的 invalidate 是否命中也没有断言。`extractDetail` 的五种形状现在补上了 ✓。 |

---

## Verdict：**REQUEST_CHANGES**

没有 Critical —— 没有数据损坏、没有崩溃路径，方向也对（四段诊断这个核心设计是站得住的：
颜色不是唯一信息载体、`stage` 与 `probe` 交叉验证、探测缓存与强制重测分离，这些细节都做得很认真）。

但有 7 条 Important，每一条都是「屏幕上显示的东西不是它声称的东西」：
设备拉取失败显示成 0 台（I-2）、同步后事件列表不刷新（I-1）、
错误态和旧数据同时显示（I-3）、502 消息丢掉具体原因（I-4）、`probes` 提取了没人用（I-5）、
stage 直接索引绕过兜底（I-6）、两个一模一样的主按钮（I-7）。
对一个给运维做判断依据的面板来说，「显示的值等于它说的意思」是硬要求。

---

*本报告为只读审查产物 —— 未修改任何源码，未执行 git commit。*
