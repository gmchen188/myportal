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
        expect(sent[0].method).toBe("POST")
        // **双序列化会得到 "\"{\\"name\\\":\\\"新船队\\\"}\""**
        // —— 一个 JSON 字符串，不是对象。FastAPI 收到字符串就 422。
        expect(sent[0].body).toBe('{"name":"新船队"}')
        expect(JSON.parse(sent[0].body)).toEqual({ name: "新船队" })
    })

    it("assignAssets 发出去的 body 是对象", async () => {
        const sent = captureFetch()
        await api.fleets.assignAssets(2, [7, 8])
        expect(sent[0].body).toBe('{"asset_ids":[7,8]}')
    })

    it("create（新建船）发出去的 body 是对象", async () => {
        const sent = captureFetch()
        await api.fleets.create({ name: "海洋三号", fleet_id: 2 })
        expect(sent[0].body).toBe('{"name":"海洋三号","fleet_id":2}')
    })

    it("patchVessel 发出去的 body 是对象", async () => {
        const sent = captureFetch()
        await api.fleets.patchVessel(2, { name: "海洋三号" })
        expect(sent[0].body).toBe('{"name":"海洋三号"}')
    })

    it("既有端点同样是对象（对照：这才是正确写法）", async () => {
        const sent = captureFetch()
        await api.assets.create({ name: "FW-01", type: "防火墙" })
        expect(sent[0].body).toBe('{"name":"FW-01","type":"防火墙"}')
    })
})
