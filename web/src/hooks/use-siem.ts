import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { api } from "@/api/client"

/**
 * FortiSIEM 连接状态。
 *
 * 轮询 30 秒 —— 后台的探测会真的去连一次 SIEM，代价比 /health 高，
 * 所以间隔比监控面板的 15 秒长。
 */
export function useSiemStatus() {
    return useQuery({
        queryKey: ["siem-status"],
        queryFn: () => api.siem.status(),
        refetchInterval: 30_000,
        staleTime: 20_000,
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
