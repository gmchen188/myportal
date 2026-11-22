import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { api, type DraftRow, type ImportRow } from "@/api/client"

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


/* ── 模板 ─────────────────────────────────────────────────────── */

/** 模板列表。 */
export function useAssetTemplates() {
    return useQuery({
        queryKey: ["asset-templates"],
        queryFn: () => api.assets.templates(),
    })
}

/** 上传模板文件。 */
export function useUploadTemplate() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (args: { file: File; name?: string }) =>
            api.assets.uploadTemplate(args.file, args.name),
        onSuccess: () => {
            void qc.invalidateQueries({ queryKey: ["asset-templates"] })
        },
    })
}

export function useDeleteTemplate() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (id: number) => api.assets.removeTemplate(id),
        onSuccess: () => {
            void qc.invalidateQueries({ queryKey: ["asset-templates"] })
        },
    })
}

/* ── 草稿 ─────────────────────────────────────────────────────── */

/** 草稿列表。 */
export function useAssetDrafts() {
    return useQuery({
        queryKey: ["asset-drafts"],
        queryFn: () => api.assets.drafts(),
    })
}

/**
 * 基于模板创建草稿。
 *
 * 创建后 `draft` 会被缓存 —— 用户接着就能编辑，不用再拉一次。
 */
export function useCreateDraft() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (body: { template_id?: number | null; name?: string }) =>
            api.assets.createDraft(body),
        onSuccess: (data) => {
            qc.setQueryData(["asset-draft", data.draft.id], data.draft)
            void qc.invalidateQueries({ queryKey: ["asset-drafts"] })
        },
    })
}

/** 读单个草稿。 */
export function useAssetDraft(id: number | null) {
    return useQuery({
        queryKey: ["asset-draft", id],
        queryFn: () => api.assets.draft(id as number),
        enabled: id !== null,
    })
}

/**
 * 保存草稿。
 *
 * 保存后**用返回的草稿覆盖缓存** —— 后端保存时重新校验了每一行
 * （「可导入/待补充」标记会变），本地那份已经过期了。
 */
export function useSaveDraft() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (args: { id: number; rows: DraftRow[]; name?: string }) =>
            api.assets.saveDraft(args.id, { rows: args.rows, name: args.name }),
        onSuccess: (data, args) => {
            qc.setQueryData(["asset-draft", args.id], data.draft)
            void qc.invalidateQueries({ queryKey: ["asset-drafts"] })
        },
    })
}

export function useAddDraftRow() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (id: number) => api.assets.addDraftRow(id),
        onSuccess: (data) => {
            qc.setQueryData(["asset-draft", data.draft.id], data.draft)
        },
    })
}

/** 草稿落库。落库后资产列表要刷新。 */
export function useCommitDraft() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (id: number) => api.assets.commitDraft(id),
        onSuccess: (data) => {
            qc.setQueryData(["asset-draft", data.draft.id], data.draft)
            void qc.invalidateQueries({ queryKey: ["assets"] })
            void qc.invalidateQueries({ queryKey: ["asset-drafts"] })
        },
    })
}

export function useDeleteDraft() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (id: number) => api.assets.removeDraft(id),
        onSuccess: () => {
            void qc.invalidateQueries({ queryKey: ["asset-drafts"] })
        },
    })
}
