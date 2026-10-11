import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router'
import { rungOf, scored } from '@/lib/ladder'
import type { Listing, TriageStatus } from '@/lib/types'
import { inRun } from '@/lib/verbale'

export type TriageTab = 'tutti' | 'nuovi' | 'preferito' | 'contattato' | 'scartato'
export type SortKey = 'score' | 'price' | 'ppsqm' | 'sqm' | 'recent'

export interface FeedFilters {
  q: string
  tab: TriageTab
  config: number | null
  minRung: number | null
  nd: boolean
  sort: SortKey
  dir: 'asc' | 'desc'
  maxPrice: number | null
  minSqm: number | null
  /** Only the listings a given run found or saw again (the run toast links here). */
  run: number | null
}

const TABS: TriageTab[] = ['tutti', 'nuovi', 'preferito', 'contattato', 'scartato']
const SORTS: SortKey[] = ['score', 'price', 'ppsqm', 'sqm', 'recent']
const numOrNull = (v: string | null) => (v == null || v === '' || Number.isNaN(Number(v)) ? null : Number(v))

/** Feed filters live in the URL so a filtered view can be bookmarked or shared to the phone. */
export function useFeedFilters() {
  const [params, setParams] = useSearchParams()
  const filters: FeedFilters = {
    q: params.get('q') ?? '',
    tab: (TABS.includes(params.get('triage') as TriageTab) ? params.get('triage') : 'tutti') as TriageTab,
    config: numOrNull(params.get('ricerca')),
    minRung: numOrNull(params.get('min')),
    nd: params.get('nd') !== '0',
    sort: (SORTS.includes(params.get('sort') as SortKey) ? params.get('sort') : 'score') as SortKey,
    dir: params.get('dir') === 'asc' ? 'asc' : 'desc',
    maxPrice: numOrNull(params.get('prezzo')),
    minSqm: numOrNull(params.get('mq')),
    run: numOrNull(params.get('run')),
  }
  const set = (patch: Partial<FeedFilters>) => {
    const next = { ...filters, ...patch }
    const p = new URLSearchParams()
    if (next.q) p.set('q', next.q)
    if (next.tab !== 'tutti') p.set('triage', next.tab)
    if (next.config != null) p.set('ricerca', String(next.config))
    if (next.minRung != null) p.set('min', String(next.minRung))
    if (!next.nd) p.set('nd', '0')
    if (next.sort !== 'score') p.set('sort', next.sort)
    if (next.dir === 'asc') p.set('dir', 'asc')
    if (next.maxPrice != null) p.set('prezzo', String(next.maxPrice))
    if (next.minSqm != null) p.set('mq', String(next.minSqm))
    if (next.run != null) p.set('run', String(next.run))
    setParams(p, { replace: true })
  }
  return [filters, set] as const
}

const SORT_VALUE: Record<SortKey, (l: Listing) => number | null> = {
  score: (l) => (scored(l) ? l.ai_score : null),
  price: (l) => l.price_eur,
  ppsqm: (l) => l.price_per_sqm,
  sqm: (l) => l.sqm_num,
  recent: (l) => new Date(l.first_seen_at ?? l.scraped_at).getTime(),
}

/** Everything except the triage tab, so tab counts reflect the other filters. */
export function applyBaseFilters(all: Listing[], f: FeedFilters): Listing[] {
  const q = f.q.trim().toLowerCase()
  return all.filter((l) => {
    if (f.config != null && l.config_id !== f.config) return false
    if (f.run != null && !inRun(l, f.run)) return false
    if (q && !`${l.title} ${l.address ?? ''} ${l.area} ${l.city}`.toLowerCase().includes(q)) return false
    if (f.maxPrice != null && l.price_eur != null && l.price_eur > f.maxPrice) return false
    if (f.minSqm != null && l.sqm_num != null && l.sqm_num < f.minSqm) return false
    if (scored(l)) {
      if (f.minRung != null && rungOf(l.ai_score) > f.minRung) return false
    } else if (!f.nd) return false
    return true
  })
}

export function matchesTab(l: Listing, tab: TriageTab): boolean {
  switch (tab) {
    case 'tutti':
      return true
    case 'nuovi':
      return !l.seen_at && l.triage_status !== 'scartato'
    default:
      return l.triage_status === tab
  }
}

/**
 * Whether a triage change moves a listing out of its place in this tab: the verdict takes it out of
 * the tab (or into it), or it sinks to (or rises from) the discarded tail of Tutti. Decided on the
 * verdict alone: the seen mark is held still, so in Nuovi a P or C behaves the same whether or not
 * the 1.2 s seen timer has fired yet.
 */
export function triageMoves(l: Listing, before: TriageStatus | null, tab: TriageTab): boolean {
  const fits = (status: TriageStatus | null) => matchesTab({ ...l, seen_at: null, triage_status: status }, tab)
  if (fits(before) !== fits(l.triage_status)) return true
  return tab === 'tutti' && (before === 'scartato') !== (l.triage_status === 'scartato')
}

/** How many of the settings the phone tucks behind "Filtri" (search, ricerca, order) differ from the defaults. */
export function hiddenFilterCount(f: FeedFilters): number {
  return [!!f.q.trim(), f.config != null, f.sort !== 'score' || f.dir !== 'desc'].filter(Boolean).length
}

/**
 * A listing just marked scartato stays where it is for a moment, so the rule can be drawn
 * through its title in place, then sinks to the bottom of Tutti like the others.
 */
export function useHeldDiscard(all: Listing[] | undefined): number | null {
  const seen = useRef<{ list: Listing[]; status: Map<number, Listing['triage_status']> } | null>(null)
  const held = useRef<{ id: number; until: number } | null>(null)
  const [, bump] = useState(0)
  if (all && seen.current?.list !== all) {
    const before = seen.current?.status
    if (before)
      for (const l of all)
        if (l.triage_status === 'scartato' && before.has(l.id) && before.get(l.id) !== 'scartato')
          held.current = { id: l.id, until: Date.now() + 650 }
    seen.current = { list: all, status: new Map(all.map((l) => [l.id, l.triage_status])) }
  }
  const id = held.current && held.current.until > Date.now() ? held.current.id : null
  useEffect(() => {
    if (id == null || !held.current) return
    const t = setTimeout(() => bump((n) => n + 1), held.current.until - Date.now() + 10)
    return () => clearTimeout(t)
  }, [id])
  return id
}

/**
 * The feed in order. `heldId` is a listing just discarded, held in place for a moment; `keepId` is the
 * open listing, kept on screen in its tab even after it stops matching (Nuovi drops a listing the
 * moment it has been seen), so j/k carry on from where it was.
 */
export function useFeed(all: Listing[] | undefined, f: FeedFilters, heldId: number | null = null, keepId: number | null = null) {
  return useMemo(() => {
    const base = applyBaseFilters(all ?? [], f)
    const counts: Record<TriageTab, number> = { tutti: 0, nuovi: 0, preferito: 0, contattato: 0, scartato: 0 }
    for (const l of base) for (const t of TABS) if (matchesTab(l, t)) counts[t]++
    // Each rung counts what picking it would show: every other filter applies, the rung itself does not.
    const rungCounts = Array(10).fill(0)
    for (const l of applyBaseFilters(all ?? [], { ...f, minRung: null })) if (scored(l)) rungCounts[rungOf(l.ai_score)]++

    const value = SORT_VALUE[f.sort]
    const rows = base
      .filter((l) => matchesTab(l, f.tab) || l.id === keepId)
      .sort((a, b) => {
        // Discarded listings sink unless you are looking at them on purpose.
        if (f.tab === 'tutti') {
          const da = a.triage_status === 'scartato' && a.id !== heldId ? 1 : 0
          const db = b.triage_status === 'scartato' && b.id !== heldId ? 1 : 0
          if (da !== db) return da - db
        }
        const va = value(a)
        const vb = value(b)
        if (va == null && vb == null) return b.id - a.id
        if (va == null) return 1
        if (vb == null) return -1
        return f.dir === 'asc' ? va - vb : vb - va
      })
    return { rows, counts, rungCounts, total: all?.length ?? 0 }
  }, [all, f.q, f.tab, f.config, f.minRung, f.nd, f.sort, f.dir, f.maxPrice, f.minSqm, f.run, heldId, keepId]) // eslint-disable-line react-hooks/exhaustive-deps
}
