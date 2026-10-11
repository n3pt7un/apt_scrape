import { type QueryClient, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, ApiError } from './api'
import type { Job, Listing, SearchConfigInput, TriageStatus } from './types'
import { markTriaged } from './motion'

export const keys = {
  listings: ['listings'] as const,
  listing: (id: number) => ['listing', id] as const,
  configs: ['configs'] as const,
  config: (id: number) => ['config', id] as const,
  jobs: ['jobs'] as const,
  job: (id: number) => ['job', id] as const,
  jobStats: (id: number) => ['job-stats', id] as const,
  overall: ['overall-stats'] as const,
  preferences: ['preferences'] as const,
  sites: ['sites'] as const,
  areas: (site: string) => ['areas', site] as const,
  geocode: ['geocode-status'] as const,
}

export const useListings = () => useQuery({ queryKey: keys.listings, queryFn: api.listings })

export const useListing = (id: number | null) =>
  useQuery({ queryKey: keys.listing(id ?? -1), queryFn: () => api.listing(id!), enabled: id != null })

export const useConfigs = () => useQuery({ queryKey: keys.configs, queryFn: api.configs })
export const useConfig = (id: number | null) =>
  useQuery({ queryKey: keys.config(id ?? -1), queryFn: () => api.config(id!), enabled: id != null })

export const isActive = (j: Pick<Job, 'status'>) => j.status === 'running' || j.status === 'pending'

/**
 * Jobs poll faster while something is running so the rail stays live. A hidden tab keeps polling, more
 * slowly, so a run that ends while you are elsewhere still refreshes the feed and sends its notification.
 */
export const useJobs = () =>
  useQuery({
    queryKey: keys.jobs,
    queryFn: api.jobs,
    refetchInterval: (q) => {
      const hidden = typeof document !== 'undefined' && document.hidden
      return q.state.data?.some(isActive) ? (hidden ? 10_000 : 2500) : hidden ? 60_000 : 15_000
    },
    refetchIntervalInBackground: true,
  })

/** One job with its full log (the jobs list leaves logs out). */
export const useJob = (id: number | null) =>
  useQuery({ queryKey: keys.job(id ?? -1), queryFn: () => api.job(id!), enabled: id != null })

export const useOverallStats = () => useQuery({ queryKey: keys.overall, queryFn: api.overallStats })
export const useJobStats = (id: number | null, enabled = true) =>
  useQuery({ queryKey: keys.jobStats(id ?? -1), queryFn: () => api.jobStats(id!), enabled: id != null && enabled })

export const usePreferences = () => useQuery({ queryKey: keys.preferences, queryFn: api.preferences })
export const useSites = () => useQuery({ queryKey: keys.sites, queryFn: api.sites, staleTime: 5 * 60_000 })
export const useAreas = (site: string | null) =>
  useQuery({
    queryKey: keys.areas(site ?? ''),
    queryFn: () => api.siteAreas(site!),
    enabled: !!site,
    staleTime: 5 * 60_000,
  })

/** Patch a listing in every cache that holds it, so feed, map and detail agree. */
export function usePatchListingCache() {
  const qc = useQueryClient()
  return (updated: Partial<Listing> & { id: number }) => {
    qc.setQueryData<Listing[]>(keys.listings, (old) =>
      old?.map((l) => (l.id === updated.id ? { ...l, ...updated } : l)),
    )
    qc.setQueryData(keys.listing(updated.id), (old: Listing | undefined) => (old ? { ...old, ...updated } : old))
  }
}

/**
 * A feed refetch already in flight would land after an optimistic patch and undo it: stop it, and say
 * whether one was stopped so the feed is fetched again once the change is saved.
 */
async function holdListingsRefetch(qc: QueryClient): Promise<boolean> {
  const inFlight = qc.isFetching({ queryKey: keys.listings }) > 0
  await qc.cancelQueries({ queryKey: keys.listings })
  return inFlight
}

export function useTriage() {
  const patch = usePatchListingCache()
  const qc = useQueryClient()
  const m = useMutation({
    mutationFn: ({ id, ...body }: { id: number; status?: TriageStatus | null; note?: string | null }) =>
      api.triage(id, body),
    onMutate: async ({ id, ...body }) => {
      if (body.status) markTriaged(id)
      const refetch = await holdListingsRefetch(qc)
      const prev = qc.getQueryData<Listing[]>(keys.listings)?.find((l) => l.id === id)
      patch({ id, ...(body.status !== undefined ? { triage_status: body.status } : {}), ...(body.note !== undefined ? { triage_note: body.note } : {}) })
      return { prev, refetch }
    },
    onError: (err, _vars, ctx) => {
      if (ctx?.prev) patch(ctx.prev)
      toast.error('Stato non salvato', { description: (err as Error).message })
    },
    onSettled: (_data, _err, _vars, ctx) => {
      if (ctx?.refetch) qc.invalidateQueries({ queryKey: keys.listings })
    },
    onSuccess: (data, vars, ctx) => {
      patch(data)
      // Discarding is the one triage worth an undo: the row sinks out of sight.
      if (vars.status === 'scartato') {
        toast('Scartato', {
          id: `triage-${vars.id}`,
          description: 'Resta in fondo al feed, barrato.',
          action: { label: 'Annulla', onClick: () => m.mutate({ id: vars.id, status: ctx?.prev?.triage_status ?? null }) },
        })
      }
    },
  })
  return m
}

/**
 * Listings whose automatic "seen" mark failed in this tab. The feed marks the open listing after a
 * moment whenever seen_at is empty, and a failure puts it back to empty: without this record a
 * deleted listing or a backend that is down would be retried every 1.2 s.
 */
const seenMarkFailed = new Set<number>()
export const seenMarkHasFailed = (id: number) => seenMarkFailed.has(id)

export function useMarkSeen() {
  const patch = usePatchListingCache()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.markSeen(id),
    onMutate: async (id) => {
      const refetch = await holdListingsRefetch(qc)
      patch({ id, seen_at: new Date().toISOString() })
      return { refetch }
    },
    onError: (_err, id) => {
      seenMarkFailed.add(id)
      patch({ id, seen_at: null })
    },
    onSuccess: (data) => {
      seenMarkFailed.delete(data.id)
      patch(data)
    },
    onSettled: (_data, _err, _id, ctx) => {
      if (ctx?.refetch) qc.invalidateQueries({ queryKey: keys.listings })
    },
  })
}

export function useRunConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (configId: number) => {
      try {
        return await api.runConfig(configId)
      } catch (e) {
        // The backend refuses a second run of a search that is still going.
        if (e instanceof ApiError && e.status === 409) throw new ApiError(409, 'Questa ricerca è già in corso: aspetta che finisca.')
        throw e
      }
    },
    // The end-of-run notification needs permission, and asking makes sense the moment a run starts.
    onMutate: () => {
      if (typeof Notification !== 'undefined' && Notification.permission === 'default') void Notification.requestPermission()
    },
    // Also after a refusal: the run that is already going should show up in the rail.
    onSettled: () => {
      qc.invalidateQueries({ queryKey: keys.jobs })
      qc.invalidateQueries({ queryKey: keys.configs })
    },
  })
}

export function useSaveConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: number | null; body: SearchConfigInput }) =>
      id == null ? api.createConfig(body) : api.updateConfig(id, body),
    onSuccess: (cfg) => {
      qc.invalidateQueries({ queryKey: keys.configs })
      qc.setQueryData(keys.config(cfg.id), cfg)
    },
  })
}
