import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { api } from "@/api/client"

export function useTopologies() {
    return useQuery({ queryKey: ["topologies"], queryFn: () => api.topologies.list() })
}

export function useDeleteTopology() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (id: number) => api.topologies.remove(id),
        onSuccess: () => {
            void qc.invalidateQueries({ queryKey: ["topologies"] })
        },
    })
}
