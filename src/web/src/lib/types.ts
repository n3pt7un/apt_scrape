export type TriageStatus = 'preferito' | 'scartato' | 'contattato'
export type AiStatus = 'ok' | 'error' | 'none'
export type JobStatus = 'pending' | 'running' | 'done' | 'failed'
/** Whether the portal's own listing page was read: 'missing' when it was never fetched. */
export type DetailStatus = 'ok' | 'blocked' | 'error' | 'empty' | 'missing'

/** One row of the portal's feature table, label as scraped (e.g. Contratto, Riscaldamento). */
export interface ListingFact {
  label: string
  value: string
}

export interface Listing {
  id: number
  url: string
  /** The run that first found the listing (never reassigned). */
  job_id: number
  /** The last run that saw it again. */
  last_job_id: number | null
  config_id: number
  config_name: string
  title: string
  price: string
  sqm: string
  rooms: string
  area: string
  city: string
  ai_score: number | null
  ai_verdict: string | null
  ai_status: AiStatus
  ai_reason: string | null
  ai_notes: string | null
  notion_page_id: string | null
  /** First seen; same instant as first_seen_at. */
  scraped_at: string
  first_seen_at: string
  /**
   * False for rows saved before runs kept their first-found run: there job_id / first_seen_at
   * are the last run that saw the listing before the change, so they read "visto", not "trovato".
   */
  first_seen_exact: boolean
  last_seen_at: string | null
  source: string | null
  thumbnail: string | null
  address: string | null
  description_snippet: string | null
  price_eur: number | null
  sqm_num: number | null
  rooms_num: number | null
  price_per_sqm: number | null
  energy_class: string | null
  furnished: boolean | null
  available_from: string | null
  floor: string | null
  bathrooms: string | number | null
  /** Agency name from the portal page, cleaned of scraped UI labels. */
  agency?: string | null
  /** The portal's feature table, from the detail page. */
  facts: ListingFact[]
  detail_status: DetailStatus
  detail_error: string | null
  features: string[]
  post_date: string | null
  triage_status: TriageStatus | null
  triage_note: string | null
  triage_updated_at: string | null
  seen_at: string | null
  lat: number | null
  lon: number | null
  geocode_status: 'ok' | 'failed' | null
}

export interface ListingRawDetail {
  title?: string
  description?: string
  address?: string
  size?: string
  floor?: string
  photos?: string[]
  energy_class?: string
  agency?: string
  post_date?: string
  costs?: Record<string, string>
  extra_info?: Record<string, string>
}

export interface ListingRaw {
  bathrooms?: string
  detail?: ListingRawDetail
  detail_description?: string
  detail_address?: string
  detail_features?: Record<string, string>
  detail_costs?: Record<string, string>
  detail_agency?: string
  description_snippet?: string
  notion_fields?: Record<string, unknown>
  [key: string]: unknown
}

export interface ListingDetail extends Listing {
  raw: ListingRaw
  job: { id: number; status: JobStatus; started_at: string; finished_at: string | null } | null
}

export interface SearchConfig {
  id: number
  name: string
  city: string
  area: string | null
  operation: string
  property_type: string
  min_price: number | null
  max_price: number | null
  min_sqm: number | null
  min_rooms: number | null
  start_page: number
  end_page: number
  schedule_days: string[]
  schedule_time: string
  detail_concurrency: number
  vpn_rotate_batches: number
  auto_analyse: boolean
  auto_notion_push: boolean
  enabled: boolean
  created_at: string
  site_id: string
  request_delay_sec: number
  page_delay_sec: number
  timeout_sec: number | null
  next_run_at?: string | null
  last_job?: {
    id: number
    status: JobStatus
    started_at: string
    finished_at: string | null
    listing_count: number | null
  } | null
  listing_count?: number
}

export type SearchConfigInput = Omit<SearchConfig, 'id' | 'created_at' | 'next_run_at' | 'last_job' | 'listing_count'>

export interface Job {
  id: number
  config_id: number
  config_name?: string
  status: JobStatus
  triggered_by: string
  started_at: string
  finished_at: string | null
  listing_count: number | null
  scraped_count: number | null
  dupes_removed: number | null
  ai_tokens_used: number | null
  ai_cost_usd: number | null
  /** Listings this run sent to the AI (runs only re-score what changed); null on older runs. */
  ai_scored_count?: number | null
  /**
   * True when the run's "found first" count is exact. Older runs re-stamped every listing they saw
   * as theirs, so their split between new and already-known listings is unknown.
   */
  attribution_exact?: boolean
  area_stats: string
  /** Only on GET /jobs/{id}: the jobs list leaves the log out (fetch it with useJob). */
  log?: string
}

export interface JobStats {
  job_id: number
  status: JobStatus
  duration_sec: number | null
  scraped_count: number | null
  listing_count: number | null
  dupes_removed: number | null
  ai_tokens_used: number | null
  ai_cost_usd: number | null
  avg_price_eur: number | null
  area_stats: Record<string, number>
}

export interface OverallStats {
  total_runs: number
  /** Unique listings in the database. */
  total_listings: number
  /** Listings processed summed over runs (a listing counts once per run that saw it). */
  total_processed?: number
  total_scraped: number
  total_dupes_removed: number
  total_ai_tokens: number
  total_ai_cost_usd: number
  total_duration_sec: number
  avg_price_eur: number | null
  area_distribution: Record<string, number>
}

export interface GeocodeStatus {
  running: boolean
  pending: number
  done: number
  failed: number
}

export type ChatStage = 'reading' | 'thinking' | 'writing' | 'done'

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  error?: boolean
  /** Assistant only: what Milhouse is doing right now. */
  stage?: ChatStage
  /** Readable summary of the model's reasoning, when it reasoned. */
  thinking?: string
  thinkingMs?: number | null
  elapsedMs?: number
  /** User only: asked with "Pensaci bene" (higher effort). */
  deep?: boolean
}

export type ChatEvent =
  | { type: 'status'; stage: 'reading' | 'thinking' | 'writing' }
  | { type: 'thinking'; delta: string }
  | { type: 'text'; delta: string }
  | { type: 'done'; elapsed_ms: number; thinking_ms: number | null; truncated?: boolean }
  | { type: 'error'; message: string }
