import { useQuery } from "@tanstack/react-query"

import { api } from "@/api/client"

/**
 * 后台健康状态。侧栏用它显示 FortiSIEM 的连接指示灯。
 *
 * 轮询间隔 30 秒 —— 连接状态变化不必立刻反映，但也不能太慢。
 */
export function useHealth() {
    return useQuery({
        queryKey: ["health"],
        queryFn: () => api.health(),
        refetchInterval: 30_000,
        staleTime: 20_000,
    })
}
