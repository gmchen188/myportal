/**
 * `request()` 这一层 —— **请求体只序列化一次**。
 *
 * ## 为什么必须是独立文件
 *
 * 这个测试要看到**真正发出去的那串字节**，所以：
 *
 *   · **不能** `vi.mock("@/api/client")` —— mock 掉 api 就等于把请求整个
 *     短路了，`fetch` 一次都不会被调用（`sent` 是空的，断言挂在长度上）
 *   · 只能 `vi.stubGlobal("fetch", ...)` 拦下真正的 fetch
 *
 * 放在有 api mock 的文件里，这条测试会**假绿** —— 变异注入后它照样通过，
 * 因为被测的那段逻辑压根没跑到。
 *
 * ## 这个 bug 长什么样
 *
 * `request()` 内部已经 `JSON.stringify(opts.body)`。调用方又写了一层
 * `JSON.stringify(body)` → body 变成**一个 JSON 字符串**：
 *
 *     期望   {"name":"新船队"}
 *     实际   "{\"name\":\"新船队\"}"
 *
 * FastAPI 收到字符串 → 请求体校验失败 → **422**。
 * 读端点全绿、创建全挂，就是这个原因。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { api } from "@/api/client"

interface Captured {
    url: string
    method: string
    body: string
    headers: Record<string, string>
}

function captureFetch(): Captured[] {
    const captured: Captured[] = []
    vi.stubGlobal(
        "fetch",
        vi.fn(async (url: string, init?: RequestInit) => {
            captured.push({
                url: String(url),
                method: init?.method ?? "GET",
                body: String(init?.body ?? ""),
                headers: (init?.headers ?? {}) as Record<string, string>,
            })
            return {
                ok: true,
                status: 200,
                text: async () => JSON.stringify({ id: 99, name: "新船队", ok: true, moved: 1 }),
            } as unknown as Response
        }),
    )
    return captured
}

describe("请求体只序列化一次", () => {
    beforeEach(() => {
        localStorage.clear()
    })
    afterEach(() => {
        vi.unstubAllGlobals()
    })

    it("createFleet 发出去的 body 是对象，不是 JSON 字符串", async () => {
        const sent = captureFetch()
        await api.fleets.createFleet({ name: "新船队" })

        expect(sent).toHaveLength(1)
        expect(sent[0]!.method).toBe("POST")
        // **双序列化会得到 "\"{\\"name\\\":\\\"新船队\\\"}\""**
        // —— 一个 JSON 字符串，不是对象。FastAPI 收到字符串就 422。
        expect(sent[0]!.body).toBe('{"name":"新船队"}')
        expect(JSON.parse(sent[0]!.body)).toEqual({ name: "新船队" })
    })

    it("assignAssets 发出去的 body 是对象", async () => {
        const sent = captureFetch()
        await api.fleets.assignAssets(2, [7, 8])
        expect(sent[0]!.body).toBe('{"asset_ids":[7,8]}')
    })

    it("create（新建船）发出去的 body 是对象", async () => {
        const sent = captureFetch()
        await api.fleets.create({ name: "海洋三号", fleet_id: 2 })
        expect(sent[0]!.body).toBe('{"name":"海洋三号","fleet_id":2}')
    })

    it("patchVessel 发出去的 body 是对象", async () => {
        const sent = captureFetch()
        await api.fleets.patchVessel(2, { name: "海洋三号" })
        expect(sent[0]!.body).toBe('{"name":"海洋三号"}')
    })

    it("既有端点同样是对象（对照：这才是正确写法）", async () => {
        const sent = captureFetch()
        await api.assets.create({ name: "FW-01", type: "防火墙" })
        expect(sent[0]!.body).toBe('{"name":"FW-01","type":"防火墙"}')
    })
})


describe("422 要说人话，不能只丢一个 HTTP 码", () => {
    beforeEach(() => {
        localStorage.clear()
    })
    afterEach(() => {
        vi.unstubAllGlobals()
    })

    it("FastAPI 的 detail 是数组时，提取出字段和原因", async () => {
        // **后端对双序列化的 body 实际返回的就是这个形状**
        vi.stubGlobal(
            "fetch",
            vi.fn(async () => ({
                ok: false,
                status: 422,
                text: async () =>
                    JSON.stringify({
                        detail: [
                            {
                                type: "model_attributes_type",
                                loc: ["body"],
                                msg: "Input should be a valid dictionary or object to extract fields from",
                                input: '{"name": "X"}',
                            },
                        ],
                    }),
            })),
        )

        await expect(api.fleets.createFleet({ name: "X" })).rejects.toThrow(/JSON 对象/)
    })

    it("缺必填字段时点名是哪个字段", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async () => ({
                ok: false,
                status: 422,
                text: async () =>
                    JSON.stringify({
                        detail: [{ type: "missing", loc: ["body", "name"], msg: "Field required" }],
                    }),
            })),
        )

        await expect(api.fleets.createFleet({ name: "X" })).rejects.toThrow(/name.*缺少必填字段/)
    })

    it("看不懂的 shape 仍然退回 HTTP 码（既有契约不变）", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async () => ({ ok: false, status: 418, text: async () => "{}" })),
        )
        await expect(api.fleets.createFleet({ name: "X" })).rejects.toThrow("HTTP 418")
    })
})


describe("405 的提示", () => {
    it("告诉用户是后台服务没更新，而不是干巴巴一个 HTTP 码", async () => {
        const { extractDetail } = await import("@/api/client")
        const msg = extractDetail({ detail: "Method Not Allowed" }, 405)
        expect(msg).toContain("后台服务还没更新")
        expect(msg).toContain("restart-all.ps1")
    })

    it("别的状态码不受影响", async () => {
        const { extractDetail } = await import("@/api/client")
        expect(extractDetail({ detail: "资产名称不能为空" }, 400)).toBe("资产名称不能为空")
    })
})
