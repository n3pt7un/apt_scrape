import { explainAiError } from './aiErrors'
import { scored } from './ladder'
import { readLog } from './phases'
import { explainRunError } from './runErrors'
import type { Job, Listing } from './types'

/**
 * A run's listings: the ones it found first, plus the known ones it saw again and no later run has seen
 * since. The feed's run filter and the verbale use this same rule, so a count always matches the rows.
 */
export function inRun(l: Pick<Listing, 'job_id' | 'last_job_id'>, runId: number): boolean {
  return l.job_id === runId || l.last_job_id === runId
}

/**
 * Milhouse's verbale: the official report he files after every run.
 * Built only from the run's own facts (counts, the best score, the error line); nothing is invented
 * and no AI call is made. His one line of voice is picked by outcome, and by run number so it varies
 * between runs but never changes on reload.
 */
export interface Verbale {
  number: number
  outcome: 'done' | 'failed'
  examined: number
  /** Whether found/known are known: false for runs made before job_id stopped being reassigned. */
  exact: boolean
  /** Found by this run for the first time (0 when not exact). */
  found: number
  /** Already in the feed from earlier runs, seen again by this one (0 when not exact). */
  known: number
  fresh: number
  /** The rows the run filter shows (see inRun). */
  attributed: number
  /** Known listings this run saw that a later run has seen since: the facts below cover only the rest. */
  moved: number
  best: Listing | null
  above60: number
  failure: string | null
  /** How the AI scoring went in this run. */
  ai: AiTally
  line: string
}

export interface AiTally {
  /** Listings this run sent to the AI; null when not on record (older runs, or no AI step). */
  sent: number | null
  /** Of those, how many it scored; null when not on record. */
  scored: number | null
  /**
   * Listings left without a score. From the log when it carries the run's tally; otherwise this run's
   * listings whose valuation is in error (a failure that kept an older valid score does not show there).
   */
  failed: number
  /** The most common cause among the failures, in plain Italian. */
  cause: { title: string; fix: string } | null
  /** 'none': nothing scored; 'most': more failed than scored; 'some': a few failed; 'ok': no failure. */
  outcome: 'ok' | 'some' | 'most' | 'none'
}

/** "valutati 0 su 5", or the count of listings left without a score when the run's tally is not on record. */
export function aiCount(ai: AiTally): string {
  if (ai.sent != null && ai.scored != null) return `valutati ${ai.scored} su ${ai.sent}`
  if (ai.failed) return `${ai.failed} ${ai.failed === 1 ? 'non valutato' : 'non valutati'}`
  return 'nessuno valutato'
}

/** Whether a done run's verbale must say the scoring failed instead of filing it as seen. */
export const notScored = (v: Pick<Verbale, 'outcome' | 'ai'>) =>
  v.outcome === 'done' && (v.ai.outcome === 'none' || v.ai.outcome === 'most')

/** The cause most of the failed valuations share, falling back to the error the log quotes. */
function commonCause(nd: Listing[], logError: string | null): AiTally['cause'] {
  const tally = new Map<string, { n: number; e: { title: string; fix: string } }>()
  for (const l of nd) {
    const e = explainAiError(l.ai_reason)
    const t = tally.get(e.title)
    if (t) t.n++
    else tally.set(e.title, { n: 1, e })
  }
  let top: { n: number; e: { title: string; fix: string } } | null = null
  for (const t of tally.values()) if (!top || t.n > top.n) top = t
  if (top) return top.e
  return logError ? explainAiError(logError) : null
}

/**
 * ai_scored_count is what the runner sent to the AI (scored + failed, runner.py); the log's own
 * "Analysis complete: X scored, Y failed" is exact and wins when the full log is at hand.
 */
function tallyAi(job: Job, mine: Listing[], reading: ReturnType<typeof readLog>): AiTally {
  const ai = reading.ai
  const nd = mine.filter((l) => l.ai_status === 'error')
  let sent: number | null
  let failed: number
  let scoredN: number | null
  if (ai.scored != null && ai.failed != null) {
    sent = ai.scored + ai.failed
    failed = ai.failed
    scoredN = ai.scored
  } else {
    sent = ai.queued ?? job.ai_scored_count ?? null
    failed = ai.crashed ? Math.max(sent ?? 0, nd.length) : nd.length
    if (sent != null && failed > sent) sent = failed
    scoredN = ai.crashed ? 0 : sent != null ? sent - failed : null
  }
  let cause = failed ? commonCause(nd, ai.error) : null
  if (ai.crashed && !nd.length) {
    // The step broke as a whole: name what the log says, never a guess dressed as the cause.
    const e = explainAiError(ai.error)
    cause = e.title === UNREADABLE ? CRASHED : e
  }
  let outcome: AiTally['outcome'] = 'ok'
  if (failed || ai.crashed) {
    // Without the run's own tally, judge on its listings: the ones scored against the ones in error.
    const ok = scoredN ?? mine.filter((l) => scored(l)).length
    outcome = ok === 0 ? 'none' : failed > ok ? 'most' : 'some'
  }
  return { sent, scored: scoredN, failed, cause, outcome }
}

/** explainAiError's catch-all, which fits one listing's reply, not a step that crashed. */
const UNREADABLE = explainAiError('').title
const CRASHED = {
  title: 'Analisi AI interrotta da un errore',
  fix: 'Il dettaglio tecnico è nel log di questa run. Riprova; se si ripete, quel dettaglio dice il perché.',
}

const pick = (lines: string[], n: number) => lines[n % lines.length]

/** `log` is the run's full log (GET /jobs/{id}); the jobs list does not carry it. */
export function buildVerbale(job: Job, listings: Listing[] | undefined, log?: string): Verbale {
  const mine = (listings ?? []).filter((l) => inRun(l, job.id))
  const ok = mine.filter((l) => scored(l))
  const best = ok.reduce<Listing | null>((b, l) => (!b || l.ai_score! > b.ai_score! ? l : b), null)
  const above60 = ok.filter((l) => l.ai_score! >= 60).length
  const examined = Math.max(job.listing_count ?? 0, mine.length)
  // Runs only keep the listings they found first since 2026-10-11: older runs re-stamped every
  // listing they saw as theirs, so for them the split between new and known is not on record.
  const exact = job.attribution_exact === true
  const found = exact ? mine.filter((l) => l.job_id === job.id).length : 0
  const known = exact ? Math.max(0, examined - found) : 0
  const fresh = mine.filter((l) => !l.seen_at && l.triage_status !== 'scartato').length
  const moved = Math.max(0, examined - mine.length)
  const failed = job.status === 'failed'
  const reading = readLog(log ?? job.log ?? '', job.status)
  const failure = failed ? explainRunError(reading.error).title : null
  const ai = tallyAi(job, mine, reading)
  const aiLost = !failed && (ai.outcome === 'none' || ai.outcome === 'most')

  let line: string
  if (failed) line = 'Mi sono fermato prima della fine. Il motivo è scritto qui sotto, con il rimedio.'
  else if (aiLost && ai.outcome === 'none')
    line =
      ai.sent != null
        ? `Ho letto gli annunci, ma non sono riuscito a valutarne nessuno${ai.sent > 1 ? ` dei ${ai.sent}` : ''}. Il motivo è qui sotto, con il rimedio.`
        : 'Ho letto gli annunci, ma non sono riuscito a valutarli. Il motivo è qui sotto, con il rimedio.'
  else if (aiLost)
    line =
      ai.sent != null && ai.scored != null
        ? `Ne ho valutati solo ${ai.scored} su ${ai.sent}: per gli altri la valutazione non è riuscita. Il motivo è qui sotto.`
        : `${ai.failed} dei ${mine.length} annunci di questa run sono rimasti senza punteggio: la valutazione non è riuscita. Il motivo è qui sotto.`
  else if (examined === 0)
    line = pick(['Mani vuote: nessun annuncio su questa ricerca.', 'Oggi niente. Ricontrollo alla prossima run.'], job.id)
  else if (mine.length === 0)
    line = exact
      ? 'Erano tutti annunci già noti, e run successive li hanno ricontrollati: li trovi là.'
      : 'Run successive hanno ricontrollato tutti questi annunci: li trovi là.'
  else if (!best)
    line = mine.some((l) => l.ai_status === 'error')
      ? 'Li ho trovati, ma la valutazione non è riuscita. Il motivo è nella scheda di ciascuno.'
      : 'Non li ho ancora valutati: dalla scheda puoi chiedermelo con «Valuta adesso».'
  else if (best.ai_score! >= 80)
    line = pick(
      ['Tutto va per il verso di Milhouse! Questo vale una telefonata, oggi.', 'Ho ricontrollato due volte: questo è da chiamare subito.'],
      job.id,
    )
  else if (best.ai_score! >= 60)
    line = pick(['Ce n’è uno che merita un’occhiata seria.', 'Non è perfetto, ma questo andrei a vederlo.'], job.id)
  // "nothing above 60" is only claimed for the listings this verbale can still see
  else if (moved) line = `Tra i ${mine.length} annunci ancora legati a questa run nessuno supera 60.`
  else
    line = pick(
      ['Niente di verde stavolta. Ho riletto tutto, giuro.', 'Nessuno supera 60. Ho guardato due volte, per sicurezza.'],
      job.id,
    )

  return {
    number: job.id,
    outcome: failed ? 'failed' : 'done',
    examined,
    exact,
    found,
    known,
    fresh,
    attributed: mine.length,
    moved,
    best,
    above60,
    failure,
    ai,
    line,
  }
}

/**
 * "4 trovati per la prima volta, 8 già noti", or the one-sided version when either side is zero.
 * Null when the run's split is not on record (see Verbale.exact): show only the examined count.
 */
export function foundKnown(v: Pick<Verbale, 'exact' | 'found' | 'known'>): string | null {
  if (!v.exact) return null
  if (!v.known) return v.found === 1 ? 'trovato per la prima volta' : 'tutti trovati per la prima volta'
  if (!v.found) return v.known === 1 ? 'già noto' : 'tutti già noti'
  return `${v.found} ${v.found === 1 ? 'trovato' : 'trovati'} per la prima volta, ${v.known} già ${v.known === 1 ? 'noto' : 'noti'}`
}

// Per-viewer conveniences: up to when verbali were archived from the feed, which stamps have already landed.
const ARCHIVED_KEY = 'verbale-archiviato-fino'
const STAMPED_KEY = 'verbale-timbrati'

/** Verbali of runs that finished at or before this instant are archived. */
export function archivedUntil(): number | null {
  try {
    const v = Number(localStorage.getItem(ARCHIVED_KEY))
    return Number.isFinite(v) && v > 0 ? v : null
  } catch {
    return null
  }
}
export function archiveUntil(finishedAtMs: number) {
  try {
    localStorage.setItem(ARCHIVED_KEY, String(finishedAtMs))
  } catch {
    /* storage unavailable: the strip simply comes back next visit */
  }
}

/** True the first time this verbale's stamp is shown in this browser; the stamp thumps only then. */
export function firstStamp(id: number): boolean {
  try {
    const seen: number[] = JSON.parse(sessionStorage.getItem(STAMPED_KEY) ?? '[]')
    if (seen.includes(id)) return false
    sessionStorage.setItem(STAMPED_KEY, JSON.stringify([...seen, id].slice(-50)))
    return true
  } catch {
    return false
  }
}
