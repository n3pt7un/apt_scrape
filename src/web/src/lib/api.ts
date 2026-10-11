import type {
  ChatEvent,
  ChatMessage,
  GeocodeStatus,
  Job,
  JobStats,
  Listing,
  ListingDetail,
  OverallStats,
  SearchConfig,
  SearchConfigInput,
  TriageStatus,
} from './types'

const BASE = '/api'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(BASE + path, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    })
  } catch {
    throw new ApiError(0, 'Backend non raggiungibile. È avviato su :8000?')
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* body was not JSON */
    }
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

const json = (body: unknown) => JSON.stringify(body)

/** The feed loads at most this many listings, newest first (the backend's cap). */
export const LISTINGS_LIMIT = 2000

export const api = {
  listings: () => request<Listing[]>(`/listings?limit=${LISTINGS_LIMIT}`),
  listing: (id: number) => request<ListingDetail>(`/listings/${id}`),
  triage: (id: number, body: { status?: TriageStatus | null; note?: string | null }) =>
    request<Listing>(`/listings/${id}/triage`, { method: 'PATCH', body: json(body) }),
  markSeen: (id: number) => request<Listing>(`/listings/${id}/seen`, { method: 'POST' }),
  /**
   * Mark exactly these listings seen (never-seen ones only). `keepalive` lets the request finish while
   * the page unloads, for a mark that was held back behind an undo.
   */
  markSeenMany: (ids: number[], opts?: { keepalive?: boolean }) =>
    request<{ updated: number }>('/listings/seen', { method: 'POST', body: json({ ids }), keepalive: opts?.keepalive }),
  rescore: (id: number) => request<Listing>(`/listings/${id}/rescore`, { method: 'POST' }),
  rescoreMany: (ids: number[]) =>
    request<{ updated: number; errors: number }>('/listings/rescore', { method: 'POST', body: json({ ids }) }),
  geocode: (retryFailed = false) =>
    request<GeocodeStatus>(`/listings/geocode${retryFailed ? '?retry_failed=true' : ''}`, { method: 'POST' }),
  geocodeStatus: () => request<GeocodeStatus>('/listings/geocode/status'),

  configs: () => request<SearchConfig[]>('/configs'),
  config: (id: number) => request<SearchConfig>(`/configs/${id}`),
  createConfig: (body: SearchConfigInput) => request<SearchConfig>('/configs', { method: 'POST', body: json(body) }),
  updateConfig: (id: number, body: SearchConfigInput) =>
    request<SearchConfig>(`/configs/${id}`, { method: 'PUT', body: json(body) }),
  deleteConfig: (id: number) => request<void>(`/configs/${id}`, { method: 'DELETE' }),
  toggleConfig: (id: number) => request<SearchConfig>(`/configs/${id}/toggle`, { method: 'PATCH' }),
  runConfig: (id: number) => request<{ job_id: number }>(`/configs/${id}/run`, { method: 'POST' }),

  jobs: () => request<Job[]>('/jobs'),
  job: (id: number) => request<Job>(`/jobs/${id}`),
  jobStats: (id: number) => request<JobStats>(`/jobs/${id}/stats`),
  deleteJob: (id: number) => request<void>(`/jobs/${id}`, { method: 'DELETE' }),
  overallStats: () => request<OverallStats>('/jobs/stats/overall'),

  preferences: () => request<{ content: string; last_saved: string | null }>('/preferences'),
  savePreferences: (content: string) =>
    request<{ status: string }>('/preferences', { method: 'PUT', body: json({ content }) }),

  sites: () => request<string[]>('/sites'),
  siteConfig: (site: string) => request<{ property_type_map?: Record<string, string> } & Record<string, unknown>>(`/sites/${encodeURIComponent(site)}/config`),
  siteAreas: (site: string) => request<string[]>(`/sites/${encodeURIComponent(site)}/areas`),
}

/** Stream the assistant's answer about one listing, chunk by chunk. */
export async function streamChat(
  listingId: number,
  messages: ChatMessage[],
  onChunk: (text: string) => void,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response
  try {
    res = await fetch(`${BASE}/listings/${listingId}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: json({ messages: messages.map(({ role, content }) => ({ role, content })) }),
      signal,
    })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new ApiError(0, 'Backend non raggiungibile.')
  }
  if (!res.ok || !res.body) {
    let detail = res.statusText
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    onChunk(decoder.decode(value, { stream: true }))
  }
}

export const CHAT_ERROR_MARK = '[[ERRORE]]'

/** Stream Milhouse's answer as events (stage changes, reasoning summary, text, done). */
export async function streamChatEvents(
  listingId: number,
  messages: ChatMessage[],
  opts: { deep?: boolean; signal?: AbortSignal },
  onEvent: (e: ChatEvent) => void,
): Promise<void> {
  let res: Response
  try {
    res = await fetch(`${BASE}/listings/${listingId}/chat/events`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: json({
        messages: messages.map(({ role, content }) => ({ role, content })),
        ...(opts.deep ? { effort: 'high' } : {}),
      }),
      signal: opts.signal,
    })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new ApiError(0, 'Backend non raggiungibile.')
  }
  if (!res.ok || !res.body) {
    let detail = res.statusText
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let nl: number
    while ((nl = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, nl).trim()
      buffer = buffer.slice(nl + 1)
      if (line) onEvent(JSON.parse(line) as ChatEvent)
    }
  }
}
