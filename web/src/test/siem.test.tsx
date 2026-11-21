import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import type { SiemStatus } from "@/api/client"
import { SiemStageList, stageRows } from "@/components/siem-diagnostics"

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
        expect(screen.getByText("失败")).toBeDefined()
        expect(screen.getByText(/网络不通/)).toBeDefined()
    })

    it("颜色之外还有文字与形状 —— 不靠颜色单独传达状态", () => {
        render(<SiemStageList status={status()} />)
        // 文字通道
        expect(screen.getAllByText("通过")).toHaveLength(4)
        // 形状通道
        expect(screen.getAllByText("●")).toHaveLength(4)
    })
})
