import { Component, type ErrorInfo, type ReactNode } from "react"

/**
 * 渲染期错误兜底。
 *
 * **为什么必须有**
 *
 * React 的默认行为是：渲染期抛异常 → 整棵组件树卸载 → **白屏**。
 * 对一个安全运营门户来说这意味着「后端返了个我没见过的数据形状」
 * 就能让运维看不到监控面板 —— 而这时候恰恰是最需要看面板的时候。
 *
 * 审查发现的问题：全仓没有 ErrorBoundary（也没有 componentDidCatch），
 * 任何渲染期异常都是整页白屏。
 *
 * ## 边界
 *
 * **只兜渲染期错误** —— 不兜事件处理器里的异常（那需要各自的 try/catch），
 * 也不兜异步错误。数据加载失败本来就有 loading/error 态处理。
 *
 * 页面级错误显示「出错了 + 重试」；整体错误显示一块兜底 UI，
 * 保留侧边导航（运维至少还能切到别的页面）。
 */
interface Props {
    children: ReactNode
    /** 局部兜底：出错时显示在原位置，而不是替换整棵树 */
    variant?: "page" | "fatal"
}

interface State {
    error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
    state: State = { error: null }

    static getDerivedStateFromError(error: Error): State {
        return { error }
    }

    componentDidCatch(error: Error, info: ErrorInfo) {
        // 记进控制台，别让错误悄悄消失
        console.error("[ErrorBoundary]", error, info.componentStack)
    }

    private reset = () => {
        this.setState({ error: null })
    }

    render() {
        const { error } = this.state
        if (!error) return this.props.children

        const fatal = this.props.variant !== "page"

        return (
            <div
                style={{
                    padding: fatal ? 32 : 20,
                    margin: fatal ? 24 : 0,
                    border: "1px solid var(--color-sev-critical)",
                    borderRadius: 10,
                    background: "color-mix(in srgb, var(--color-sev-critical) 5%, transparent)",
                }}
            >
                <b style={{ color: "var(--color-sev-critical)" }}>
                    {fatal ? "页面渲染出错" : "这一块渲染出错"}
                </b>
                <div className="subtle" style={{ marginTop: 6 }}>
                    {error.message}
                </div>
                <button type="button" className="btn" style={{ marginTop: 12 }} onClick={this.reset}>
                    重试
                </button>
            </div>
        )
    }
}
