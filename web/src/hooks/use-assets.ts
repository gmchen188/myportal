import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { api, type ImportRow } from "@/api/client"

/** 资产列表。 */
export function useAssets(params: { q?: string; zone?: string; needs_review?: boolean } = {}) {
    return useQuery({
        queryKey: ["assets", params],
        queryFn: () => api.assets.list(params),
    })
}

/** 资产字段定义 —— 导入表单与手工录入表单都用它，不在前端另写一份。 */
export function useAssetSchema() {
    return useQuery({
        queryKey: ["asset-schema"],
        queryFn: () => api.assets.schema(),
        staleTime: Infinity,
    })
}

/**
 * 导入预览的状态放在组件里，不用 query cache ——
 * 预览是**一次性的工作区**，不是服务端资源。放 cache 会跨页面残留。
 */
export function useCommitImport() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (args: { rows: ImportRow[]; source?: string }) =>
            api.assets.commit(args.rows, args.source ?? "import"),
        onSuccess: () => {
            void qc.invalidateQueries({ queryKey: ["assets"] })
        },
    })
}

export function useCreateAsset() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (body: Parameters<typeof api.assets.create>[0]) => api.assets.create(body),
        onSuccess: () => {
            void qc.invalidateQueries({ queryKey: ["assets"] })
        },
    })
}

export function useDeleteAsset() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (id: number) => api.assets.remove(id),
        onSuccess: () => {
            void qc.invalidateQueries({ queryKey: ["assets"] })
        },
    })
}
