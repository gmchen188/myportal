import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { api } from "@/api/client"

/**
 * FortiSIEM 连接状态。
 *
 * 轮询 30 秒 —— 后台的探测会真的去连一次 SIEM，代价比 /health 高，
 * 所以间隔比监控面板的 15 秒长。
 *
 * `refetchOnWindowFocus: false` —— 切回标签页就重取的话，用户在 SIEM
 * 面板和别的页之间来回切，每次切回都触发一轮完整探测。后台已经对探测
 * 结果做了 10 秒缓存，轮询本身够用了。
 */
export function useSiemStatus() {
    return useQuery({
        queryKey: ["siem-status"],
        queryFn: () => api.siem.status(),
        refetchInterval: 30_000,
        staleTime: 20_000,
        refetchOnWindowFocus: false,
    })
}

/**
 * 强制重新检测 —— 绕过后台的探测缓存。
 *
 * 普通 refetch() 会用原 queryFn（不带 refresh），拿到的还是缓存结果；
 * 用户点了「重新检测」就该真测一次，所以这里直接调带 refresh 的接口
 * 再把结果写回缓存。
 */
export function useSiemRefresh() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: () => api.siem.status({ refresh: true }),
        onSuccess: (data) => {
            qc.setQueryData(["siem-status"], data)
        },
    })
}

/**
 * 同步 SIEM 的事件与设备。
 *
 * 同步会把设备写进资产清单 —— 所以成功后要把 assets 的缓存作废，
 * 否则资产页还显示同步前的数量。
 */
export function useSiemSync() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (params: { minutes?: number; devices?: boolean; overwrite?: boolean } = {}) =>
            api.siem.sync(params),
        onSuccess: () => {
            void qc.invalidateQueries({ queryKey: ["assets"] })
            void qc.invalidateQueries({ queryKey: ["siem-status"] })
        },
    })
}
