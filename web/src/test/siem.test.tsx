import { render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { ApiError, extractDetail, extractErrorMeta } from "@/api/client"
import type { SiemStatus } from "@/api/client"
import { SiemStageList, stageRows } from "@/components/siem-diagnostics"

// vi.mock 会被 vitest 提升到文件顶部 —— 必须写在顶层，不能放在测试体里。
vi.mock("@/hooks/use-siem", () => ({
    useSiemStatus: vi.fn(),
    useSiemSync: vi.fn(),
    useSiemRefresh: vi.fn(),
}))

function status(over: Partial<SiemStatus> = {}): SiemStatus {
    return {
        configured: true,
        connected: true,
        org: "Super",
        error: null,
        stage: "ok",
        probes: {
            tcp: { ok: true, detail: "172.16.20.48:443 可连接" },
            tls: { ok: true, detail: "TLS 握手成功，HTTP 401" },
            auth: { ok: true, detail: "token 获取成功" },
            api: { ok: true, detail: "读到 3 台设备" },
        },
        devices: [],
        ...over,
    }
}

describe("FortiSIEM 分段诊断", () => {
    it("四段都显示出来，不是一句笼统的「未连接」", () => {
        const rows = stageRows(status())
        expect(rows.map((r) => r.key)).toEqual(["tcp", "tls", "auth", "api"])
        expect(rows.every((r) => r.state === "ok")).toBe(true)
    })

    it("stage=ok 时四段全绿", () => {
        render(<SiemStageList status={status()} />)
        expect(screen.getAllByText("通过")).toHaveLength(4)
        expect(screen.queryByText("失败")).toBeNull()
    })

    it("卡在 auth：auth 标红，后面的段标成未到达", () => {
        const rows = stageRows(
            status({
                connected: false,
                stage: "auth",
                error: "未配置 FORTISIEM_CLIENT_ID / FORTISIEM_CLIENT_SECRET",
                probes: {
                    tcp: { ok: true, detail: "可连接" },
                    tls: { ok: true, detail: "握手成功" },
                    auth: { ok: false, detail: "未配置 FORTISIEM_CLIENT_ID / FORTISIEM_CLIENT_SECRET" },
                },
            }),
        )

        const byKey = Object.fromEntries(rows.map((r) => [r.key, r]))
        expect(byKey.tcp?.state).toBe("ok")
        expect(byKey.tls?.state).toBe("ok")
        expect(byKey.auth?.state).toBe("fail")
        // api 没探测到 —— 是「没走到」而不是「探测失败」
        expect(byKey.api?.state).toBe("skipped")
        expect(byKey.api?.detail).not.toBe(byKey.auth?.detail)
    })

    it("失败的那段旁边显示 error 详情", () => {
        render(
            <SiemStageList
                status={status({
                    connected: false,
                    stage: "tcp",
                    error: "网络不通：172.16.20.48:443 不可连接：TimeoutError",
                    probes: { tcp: { ok: false, detail: "172.16.20.48:443 不可连接：TimeoutError" } },
                })}
            />,
        )
        // getByText 找不到就抛异常，所以 `.toBeDefined()` 永远为真 ——
        // 那是**空断言**，看起来在测东西其实什么都没测。
        // 用 toBeInTheDocument 才是真断言（setup.ts 已引 jest-dom）。
        expect(screen.getByText("失败")).toBeInTheDocument()
        expect(screen.getByText(/网络不通/)).toBeInTheDocument()
    })

    it("颜色之外还有文字与形状 —— 不靠颜色单独传达状态", () => {
        render(<SiemStageList status={status()} />)
        // 文字通道
        expect(screen.getAllByText("通过")).toHaveLength(4)
        // 形状通道
        expect(screen.getAllByText("●")).toHaveLength(4)
    })
})


/**
 * 错误信息的提取。
 *
 * 审查指出这条路径之前零覆盖 —— 而它决定了运维看到的是
 * 「FortiSIEM 不可达（卡在认证取 Token 这一段）」还是干巴巴一句「HTTP 502」。
 */
describe("错误信息提取", () => {
    it("FastAPI 的 {detail: string} 形状", () => {
        expect(extractDetail({ detail: "资产名称不能为空" }, 400)).toBe("资产名称不能为空")
    })

    it("自定义的 {error, detail} 形状", () => {
        expect(extractDetail({ error: "拉取事件失败", detail: "boom" }, 502)).toBe("拉取事件失败")
    })

    it("嵌套的 {detail: {error, stage}} 形状 —— stage 用中文标签", () => {
        const msg = extractDetail({ detail: { error: "拉取事件失败", stage: "auth" } }, 502)
        expect(msg).toContain("拉取事件失败")
        expect(msg).toContain("认证取 Token")
        expect(msg).not.toContain("auth")
    })

    it("只有 stage 没有 message 时也给中文标签", () => {
        const msg = extractDetail({ detail: { stage: "tcp" } }, 502)
        expect(msg).toContain("TCP 连接")
        expect(msg).not.toContain("tcp 段")
    })

    it("认不出来的形状退回 HTTP 状态码", () => {
        expect(extractDetail(null, 500)).toBe("HTTP 500")
        expect(extractDetail({}, 503)).toBe("HTTP 503")
    })

    it("extractErrorMeta 能取到嵌套的 stage 与 probes", () => {
        const meta = extractErrorMeta({
            detail: {
                error: "拉取事件失败",
                stage: "tls",
                probes: { tcp: { ok: true, detail: "可连接" } },
            },
        })
        expect(meta?.stage).toBe("tls")
        expect(meta?.probes?.tcp?.ok).toBe(true)
    })
})


/**
 * 「重新检测」的失败态。
 *
 * 这个坑是我自己踩的：加了 useSiemRefresh（绕过探测缓存）之后，
 * 失败时页面什么也不说 —— 按钮从「检测中…」变回「重新检测」，
 * 屏上还是上一次的旧诊断结果，用户会以为刚测出来的就是新的。
 */
describe("重新检测的失败态", () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    it("失败时必须说出来，不能静默", async () => {
        const { useSiemStatus, useSiemSync, useSiemRefresh } = await import("@/hooks/use-siem")
        const { SiemPage } = await import("@/pages/siem")

        vi.mocked(useSiemStatus).mockReturnValue({
            data: status(),
            isPending: false,
            isFetching: false,
            isError: false,
            error: null,
            refetch: vi.fn(),
        } as never)
        vi.mocked(useSiemSync).mockReturnValue({
            mutate: vi.fn(),
            isPending: false,
            isError: false,
            error: null,
            data: undefined,
        } as never)
        vi.mocked(useSiemRefresh).mockReturnValue({
            mutate: vi.fn(),
            isPending: false,
            isError: true,
            // **真实的 ApiError 形状** —— 生产的 detail 是 extractDetail()
            // 的产物（不含 "[502] " 前缀，前缀只在 .message 里）。
            // 之前 mock 成 { detail: "[502] ..." }，于是 /502/ 断言靠 mock
            // 才成立 —— 真实生产渲染其实不显示状态码。
            error: new ApiError(502, "FortiSIEM 不可达（卡在 认证取 Token 这一段）"),
            data: undefined,
        } as never)

        render(<SiemPage />)
        expect(screen.getByText(/重新检测失败/)).toBeInTheDocument()
        // 断言真实渲染出来的内容（不是状态码 —— 状态码只在 .message 里，
        // 页面显示的是人话）
        expect(screen.getByText(/FortiSIEM 不可达/)).toBeInTheDocument()
        // 「认证取 Token」在页面里出现多次（四段诊断的标签也有它），
        // 所以用 getAllByText —— 断言的是「至少显示了一次」。
        expect(screen.getAllByText(/认证取 Token/).length).toBeGreaterThan(0)
    })
})


/**
 * 同步后必须作废 events 缓存。
 *
 * 漏掉的话：用户点了同步、看到「新增 2 条」，但事件列表还是同步前的
 * 旧数据 —— 直到轮询自然过期才变。**静默过期比报错更坏**。
 *
 * 这个测试放在独立文件里 —— 同文件的顶层 vi.mock 把 use-siem 整个
 * mock 掉了，测不到 hook 的真实行为。
 */


/**
 * 502 消息不能只留笼统标签。
 *
 * 后端 502 的 body：
 *   {"detail": {"error": "FortiSIEM 不可达",       ← 笼统标签
 *               "detail": "未配置 CLIENT_ID",       ← 具体原因
 *               "stage": "auth", "probes": {...}}}
 *
 * 只取 error 就把真正有用的那半句丢了 —— 用户看到「卡在认证段」，
 * 但不知道是「没配 client id」还是「凭据过期」。
 */
describe("502 消息的完整度", () => {
    it("error 与 detail 同时存在时要拼起来", () => {
        const msg = extractDetail(
            {
                detail: {
                    error: "FortiSIEM 不可达",
                    detail: "未配置 FORTISIEM_CLIENT_ID / FORTISIEM_CLIENT_SECRET",
                    stage: "auth",
                },
            },
            502,
        )
        expect(msg).toContain("FortiSIEM 不可达")
        expect(msg).toContain("未配置 FORTISIEM_CLIENT_ID")
        expect(msg).toContain("认证取 Token")
    })

    it("只有 error 时不要画蛇添足", () => {
        expect(extractDetail({ detail: { error: "拉取事件失败" } }, 502)).toBe("拉取事件失败")
    })

    it("只有 detail 时直接用它", () => {
        expect(extractDetail({ detail: { detail: "超时" } }, 502)).toBe("超时")
    })
})


/**
 * 兜底错误文案 —— **用户看到的是这句话，不是 HTTP 码**。
 *
 * 实测踩过：后端进程被杀后，SIEM 页显示的是
 * 「fortisiem 无法获取连接状态 [502] HTTP 502」。
 *
 * 「HTTP 502」对用户毫无意义 —— 他不知道该做什么。而 502/503/504
 * 是「上游不可用」的语义，处置跟「SIEM 连不上」完全不同：
 * 前者要**启动后端**，后者要查 SIEM 的网络和凭据。
 */
describe("兜底错误文案", () => {
    it("502 没有可读诊断时要说「后台不可达」，不能只丢一个 HTTP 码", () => {
        const detail = extractDetail(null, 502)
        expect(detail).toContain("后台不可达")
        expect(detail).toContain("不是 FortiSIEM 的问题")
        // **不能出现裸的 HTTP 码**
        expect(detail).not.toBe("HTTP 502")
    })

    it("504 同样归到「后台不可达」（网关超时）", () => {
        expect(extractDetail(null, 504)).toContain("后台不可达")
    })

    it("503 不归到「后台不可达」—— 语义模糊，可能是后端自己返回的", () => {
        // 既有契约：extractDetail({}, 503) 就是 "HTTP 503"
        expect(extractDetail({}, 503)).toBe("HTTP 503")
    })

    it("后端主动返回的 502 带诊断时走诊断分支，不被兜底覆盖", () => {
        const detail = extractDetail(
            {
                detail: {
                    error: "FortiSIEM 不可达",
                    detail: "未配置 FORTISIEM_CLIENT_ID",
                    stage: "auth",
                },
            },
            502,
        )
        expect(detail).toContain("FortiSIEM 不可达")
        expect(detail).toContain("认证取 Token")
        expect(detail).not.toContain("后台不可达")
    })

    it("404 要说「版本不一致」，不是干巴巴一个码", () => {
        const detail = extractDetail(null, 404)
        expect(detail).toContain("版本")
        expect(detail).not.toBe("HTTP 404")
    })

    it("其它状态码仍然给 HTTP 码（不要过度包装 —— 既有契约）", () => {
        expect(extractDetail(null, 418)).toBe("HTTP 418")
        expect(extractDetail(null, 500)).toBe("HTTP 500")
    })
})
