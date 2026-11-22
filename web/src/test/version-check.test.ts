/**
 * 页面版本检测 —— 自己发现自己过期。
 *
 * ## 为什么测这个
 *
 * 同一个 bug（新建船队 422）修了两次，用户报的是两次一模一样的报错 ——
 * 因为他那个标签页跑的是**修复前的 bundle**。SPA 不会自动换代码。
 *
 * 所以「页面是不是旧的」这件事必须能被自动发现，不能靠人判断。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { renderHook, waitFor } from "@testing-library/react"

import { fetchVersion, useVersionCheck, versionUrl } from "@/hooks/use-version-check"

function mockVersionFile(payload: unknown, ok = true) {
    vi.stubGlobal(
        "fetch",
        vi.fn(async () => ({
            ok,
            status: ok ? 200 : 404,
            json: async () => payload,
        })),
    )
}

describe("页面版本检测", () => {
    beforeEach(() => {
        sessionStorage.clear()
        vi.useFakeTimers({ shouldAdvanceTime: true })
    })
    afterEach(() => {
        vi.useRealTimers()
        vi.unstubAllGlobals()
    })

    it("版本文件地址跟着 BASE_URL 走（Pages 挂在子路径下）", () => {
        expect(versionUrl()).toMatch(/version\.json$/)
    })

    it("第一次看到版本文件 —— 记下它，不提示", async () => {
        mockVersionFile({ rev: "abc123", builtAt: "2026-01-01T00:00:00Z" })
        const { result } = renderHook(() => useVersionCheck())
        await waitFor(() => expect(result.current.current).toBeNull())
        expect(result.current.stale).toBe(false)
        expect(sessionStorage.getItem("myportal.version")).toContain("abc123")
    })

    it("版本变了 —— 提示刷新", async () => {
        // 先记一个旧版本
        sessionStorage.setItem(
            "myportal.version",
            JSON.stringify({ rev: "old", builtAt: "2026-01-01T00:00:00Z" }),
        )
        mockVersionFile({ rev: "new", builtAt: "2026-01-02T00:00:00Z" })

        const { result } = renderHook(() => useVersionCheck())
        await waitFor(() => expect(result.current.stale).toBe(true))
        expect(result.current.current?.rev).toBe("new")
    })

    it("版本没变 —— 不提示", async () => {
        const v = { rev: "same", builtAt: "2026-01-01T00:00:00Z" }
        sessionStorage.setItem("myportal.version", JSON.stringify(v))
        mockVersionFile(v)

        const { result } = renderHook(() => useVersionCheck())
        await waitFor(() => expect(fetchVersion()).resolves.toBeTruthy())
        expect(result.current.stale).toBe(false)
    })

    it("版本文件拉不到 —— 静默，不报错也不提示", async () => {
        sessionStorage.setItem(
            "myportal.version",
            JSON.stringify({ rev: "old", builtAt: "2026-01-01T00:00:00Z" }),
        )
        mockVersionFile({}, false)

        const { result } = renderHook(() => useVersionCheck())
        await waitFor(() => expect(fetchVersion()).resolves.toBeNull())
        expect(result.current.stale).toBe(false)
    })

    it("用户关掉提示后 —— 同一版本不再打扰", async () => {
        const v = { rev: "new", builtAt: "2026-01-02T00:00:00Z" }
        sessionStorage.setItem(
            "myportal.version",
            JSON.stringify({ rev: "old", builtAt: "2026-01-01T00:00:00Z" }),
        )
        sessionStorage.setItem("myportal.version-dismissed", JSON.stringify(v))
        mockVersionFile(v)

        const { result } = renderHook(() => useVersionCheck())
        await waitFor(() => expect(fetchVersion()).resolves.toBeTruthy())
        expect(result.current.stale).toBe(false)
    })
})
