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

createRoot(root).render(
    <StrictMode>
        <QueryClientProvider client={queryClient}>
            <BrowserRouter>
                <App />
            </BrowserRouter>
        </QueryClientProvider>
    </StrictMode>,
)
