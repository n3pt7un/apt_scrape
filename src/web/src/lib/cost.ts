import { useMemo } from 'react'
import { confirmAction } from '@/components/shell/ConfirmHost'
import { relative, usd } from './format'
import { useJobs } from './queries'
import type { Job } from './types'

/** How many of the latest paid runs the average is taken over. */
const RECENT = 10

/**
 * Average real AI cost of one listing, over the latest runs that paid for AI:
 * sum(ai_cost_usd) / sum(ai_scored_count || listing_count). ai_scored_count is what the run sent to
 * the AI (runs re-score only what changed); runs before it was recorded fall back to listing_count,
 * which makes their per-listing figure lower than it really was. Null until a run has paid for AI.
 */
export function costPerListing(jobs: Job[] | undefined): number | null {
  const paid = (jobs ?? []).filter((j) => (j.ai_cost_usd ?? 0) > 0).slice(0, RECENT)
  let cost = 0
  let n = 0
  for (const j of paid) {
    const count = j.ai_scored_count || j.listing_count || 0
    if (!count) continue
    cost += j.ai_cost_usd!
    n += count
  }
  return n ? cost / n : null
}

export function useCostPerListing(): number | null {
  const { data: jobs } = useJobs()
  return useMemo(() => costPerListing(jobs), [jobs])
}

/**
 * Ask before a run: it reads the portal again and pays the AI for the listings it has to score.
 * Resolves true only when the owner confirms.
 */
export function confirmRun(opts: {
  configName: string
  lastRunAt?: string | null
  perListing: number | null
  /** Listings the search usually brings (its last run's count): the ceiling of the estimate. */
  expectedListings?: number | null
  /** False when the search has AI scoring switched off: then the run costs nothing in AI. */
  aiEnabled?: boolean
}): Promise<boolean> {
  const { configName, lastRunAt, perListing, expectedListings, aiEnabled } = opts
  const parts = [
    `La run rilegge il portale${lastRunAt ? ` (ultima volta ${relative(lastRunAt)})` : ''} e salva gli annunci che trova.`,
  ]
  if (aiEnabled === false) {
    parts.push('L’analisi AI è spenta per questa ricerca: nessun costo AI.')
  } else {
    parts.push(
      'Milhouse valuta solo gli annunci nuovi, quelli cambiati o ancora senza punteggio; gli altri tengono il loro.',
    )
    if (perListing != null && expectedListings) {
      parts.push(
        `Costo AI: circa ${usd(perListing)} ad annuncio valutato, al massimo ${usd(perListing * expectedListings)} se fossero da valutare tutti i ${expectedListings} dell’ultima run.`,
      )
    } else if (perListing != null) {
      parts.push(`Costo AI: circa ${usd(perListing)} ad annuncio valutato, la media delle ultime run.`)
    } else {
      parts.push('Il costo AI dipende da quanti annunci sono da valutare: non c’è ancora una run pagata da cui stimarlo.')
    }
  }
  return confirmAction({
    title: `Avviare «${configName}»?`,
    body: parts.join(' '),
    confirmLabel: 'Avvia run',
  })
}
