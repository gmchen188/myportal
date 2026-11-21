import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { BrowserRouter } from "react-router-dom"

import { App } from "@/app"
import "@/styles/index.css"

const queryClient = new QueryClient({
    defaultOptions: {
        queries: {
            // 窗口重新聚焦时重取 —— 监控面板的数据要新鲜
            refetchOnWindowFocus: true,
            staleTime: 10_000,
            retry: 1,
        },
    },
})

const root = document.getElementById("root")
if (!root) throw new Error("#root 不存在")

/**
 * 路由 basename = 部署路径。
 *
 * 项目站点挂在 /myportal/ 下 —— 浏览器地址栏是 /myportal/siem，
 * 而路由内部用的是 /siem。不告诉 Router basename 的话，
 * /myportal/siem 匹配不到任何路由，会落到 "*" 通配跳回首页。
 *
 * 与 vite.config.ts 的 `base` 是同一个值，但两边各取各的 ——
 * Vite 的 base 是构建期内联的，Router 的 basename 是运行期读的。
 */
const BASE = import.meta.env.BASE_URL

createRoot(root).render(
    <StrictMode>
        <QueryClientProvider client={queryClient}>
            <BrowserRouter basename={BASE}>
                <App />
            </BrowserRouter>
        </QueryClientProvider>
    </StrictMode>,
)
