import type { JobStatus } from './types'

export type PhaseId = 'search' | 'enrich' | 'ai' | 'notion' | 'save'
export type PhaseState = 'todo' | 'active' | 'done' | 'skipped' | 'failed'

export const PHASES: { id: PhaseId; label: string }[] = [
  { id: 'search', label: 'Ricerca pagine' },
  { id: 'enrich', label: 'Dettagli' },
  { id: 'ai', label: 'Analisi AI' },
  { id: 'notion', label: 'Notion' },
  { id: 'save', label: 'Salvataggio' },
]

const MARKERS: [PhaseId, RegExp][] = [
  ['search', /^Fetching /],
  // Older runs logged "No new listings require enrichment" / "Analysis complete."; incremental runs reword both.
  ['enrich', /^(Enriching details|Checking Notion|No (new )?listings require (detail )?enrichment)/],
  ['ai', /^(Running AI analysis|No listings need AI analysis)/],
  ['notion', /^Pushing to Notion/],
  ['save', /^Upserting listings/],
]

export interface RunReading {
  phases: Record<PhaseId, PhaseState>
  pagesFetched: number
  found: number
  unique: number | null
  dupes: number | null
  enriching: number | null
  aiCost: string | null
  /** The AI step's own tally, when the log has it: older runs logged only tokens and cost. */
  ai: AiReading
  warnings: string[]
  error: string | null
  lastLine: string | null
}

export interface AiReading {
  /** Listings handed to the AI ("Running AI analysis on N listings"). */
  queued: number | null
  /** "Analysis complete: X scored, Y failed": null on runs that logged no counts. */
  scored: number | null
  failed: number | null
  /** The whole AI step broke (exception, missing criteria): nothing was scored. */
  crashed: boolean
  /** The first raw error the runner quoted, for explainAiError. */
  error: string | null
}

/** Whether the AI step went wrong enough to mark its phase failed: nothing scored, or most not. */
export function aiFailedOutright(ai: AiReading): boolean {
  if (ai.crashed) return true
  if (ai.scored == null || !ai.failed) return false
  return ai.failed > ai.scored
}

/** Read a run's progress out of its log; the runner reports nothing else live. */
export function readLog(log: string, status: JobStatus): RunReading {
  const lines = log
    .split('\n')
    .map((l) => l.replace(/^\[\d\d:\d\d:\d\d\]\s?/, '').trimEnd())
    .filter(Boolean)

  const reached: PhaseId[] = []
  let pagesFetched = 0
  let found = 0
  let unique: number | null = null
  let dupes: number | null = null
  let enriching: number | null = null
  let aiCost: string | null = null
  let error: string | null = null
  const warnings: string[] = []
  const ai: AiReading = { queued: null, scored: null, failed: null, crashed: false, error: null }

  for (const raw of lines) {
    const line = raw.trim()
    for (const [id, re] of MARKERS) if (re.test(line) && !reached.includes(id)) reached.push(id)
    // A page counts as read once its result is logged, not when it is asked for: a page that timed
    // out or was blocked after its "Fetching" line was never read. "-> Fewer listings…" follows a
    // page already counted.
    if (/^->\s*(\d+ listings|Page \d+ is a duplicate)/.test(line) || /^No listings on page/.test(line)) pagesFetched++
    let m = line.match(/^->\s*(\d+) listings/)
    if (m) found += Number(m[1])
    m = line.match(/^Total unique listings: (\d+) \((\d+) dupes/)
    if (m) {
      unique = Number(m[1])
      dupes = Number(m[2])
    }
    m = line.match(/^Enriching details for (\d+)/)
    if (m) enriching = Number(m[1])
    m = line.match(/^Analysis complete[.:].*\$([\d.]+)/)
    if (m) aiCost = m[1]
    m = line.match(/^Running AI analysis on (\d+) listings/)
    if (m) ai.queued = Number(m[1])
    m = line.match(/^Analysis complete: (\d+) scored, (\d+) failed/)
    if (m) {
      ai.scored = Number(m[1])
      ai.failed = Number(m[2])
    }
    m = line.match(/^\[warn\] AI scoring failed for \d+ listing.*First error: (.*)$/)
    if (m && !ai.error) ai.error = m[1]
    m = line.match(/^\[warn\] AI analysis failed: (.*)$/)
    if (m) {
      ai.crashed = true
      ai.error = m[1]
    }
    if (/^\[warn\] preferences\.txt not found/.test(line)) {
      ai.crashed = true
      ai.error = 'preferences not found'
    }
    if (line.startsWith('[ERROR]')) error = line.replace('[ERROR]', '').trim()
    if (line.startsWith('[warn]')) warnings.push(line.replace('[warn]', '').trim())
  }

  const last = reached.length ? PHASES.findIndex((p) => p.id === reached[reached.length - 1]) : -1
  const phases = {} as Record<PhaseId, PhaseState>
  PHASES.forEach((p, i) => {
    const seen = reached.includes(p.id)
    if (status === 'done') phases[p.id] = seen ? 'done' : 'skipped'
    else if (i < last) phases[p.id] = seen ? 'done' : 'skipped'
    else if (i === last) phases[p.id] = status === 'failed' ? 'failed' : 'active'
    else phases[p.id] = 'todo'
  })
  if (status === 'failed' && last === -1) phases.search = 'failed'
  if ((status === 'running' || status === 'pending') && last === -1) phases.search = 'active'
  // A run can finish while its AI step failed: the run is done, the scoring is not.
  if (status === 'done' && phases.ai === 'done' && aiFailedOutright(ai)) phases.ai = 'failed'

  return {
    phases,
    pagesFetched,
    found,
    unique,
    dupes,
    enriching,
    aiCost,
    ai,
    warnings,
    error,
    lastLine: lines.at(-1) ?? null,
  }
}
