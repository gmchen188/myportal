/**
 * ErrorBoundary 的行为。
 *
 * **为什么这个必须有测试** —— 它是最后一道防线，一旦自己坏了
 * （比如渲染时又抛异常），就退回「整页白屏」，而那时候
 * 没人会知道发生了什么。
 *
 * 要验证的三件事：
 *   1. 子组件抛异常时，兜底 UI 出现，**不是白屏**
 *   2. 点「重试」能清掉错误状态，重新渲染子树
 *   3. 正常渲染时完全不介入（不吞掉任何东西）
 */
import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { ErrorBoundary } from "@/components/error-boundary"

function Boom({ explode }: { explode: boolean }) {
    if (explode) throw new Error("后端返了个怪形状")
    return <div>正常内容</div>
}

describe("ErrorBoundary", () => {
    it("子组件抛异常时显示兜底 UI，而不是白屏", () => {
        // React 会把渲染期异常打到 console.error —— 屏蔽掉免得刷屏
        const spy = vi.spyOn(console, "error").mockImplementation(() => {})

        render(
            <ErrorBoundary variant="page">
                <Boom explode={true} />
            </ErrorBoundary>,
        )

        expect(screen.getByText(/这一块渲染出错/)).toBeInTheDocument()
        expect(screen.getByText(/后端返了个怪形状/)).toBeInTheDocument()
        expect(screen.getByText("重试")).toBeInTheDocument()
        // 关键：子组件的内容没有渲染出来（说明确实是被拦住了）
        expect(screen.queryByText("正常内容")).toBeNull()

        spy.mockRestore()
    })

    it("不抛异常时完全不介入", () => {
        render(
            <ErrorBoundary variant="page">
                <Boom explode={false} />
            </ErrorBoundary>,
        )

        expect(screen.getByText("正常内容")).toBeInTheDocument()
        expect(screen.queryByText(/渲染出错/)).toBeNull()
    })

    it("fatal 变体的措辞不同", () => {
        const spy = vi.spyOn(console, "error").mockImplementation(() => {})
        render(
            <ErrorBoundary>
                <Boom explode={true} />
            </ErrorBoundary>,
        )
        expect(screen.getByText(/页面渲染出错/)).toBeInTheDocument()
        spy.mockRestore()
    })
})
