import { type QueryClient, useQueryClient } from '@tanstack/react-query'
import { CheckCheck, Plus, RefreshCw, Search, SlidersHorizontal, X } from 'lucide-react'
import { motion } from 'motion/react'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { toast } from 'sonner'
import { LadderFilter } from '@/components/ape/Ladder'
import { RUNGS } from '@/lib/ladder'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { api, LISTINGS_LIMIT } from '@/lib/api'
import { isActive, keys, seenMarkHasFailed, useConfigs, useJob, useJobs, useListings, useMarkSeen, useTriage } from '@/lib/queries'
import { parseDate } from '@/lib/format'
import { archiveUntil, archivedUntil, buildVerbale } from '@/lib/verbale'
import { VerbaleStrip } from '@/components/milhouse/Verbale'
import { useMediaQuery } from '@/lib/useMediaQuery'
import { cn } from '@/lib/utils'
import { RunLauncher } from '@/components/shell/RunLauncher'
import { Glasses, MilhouseLoader } from '@/components/milhouse/Glasses'
import type { Listing, SearchConfig, TriageStatus } from '@/lib/types'
import {
  type FeedFilters,
  type SortKey,
  type TriageTab,
  hiddenFilterCount,
  matchesTab,
  triageMoves,
  useFeed,
  useFeedFilters,
  useHeldDiscard,
} from './filters'
import { ListingDetail } from './ListingDetail'
import { ListingCards, ListingTable } from './ListingTable'

const TABS: { id: TriageTab; label: string }[] = [
  { id: 'tutti', label: 'Tutti' },
  { id: 'nuovi', label: 'Nuovi' },
  { id: 'preferito', label: 'Preferiti' },
  { id: 'contattato', label: 'Contattati' },
  { id: 'scartato', label: 'Scartati' },
]

const SORTS: { value: `${SortKey}:${'asc' | 'desc'}`; label: string }[] = [
  { value: 'score:desc', label: 'Affinità più alta' },
  { value: 'price:asc', label: 'Canone più basso' },
  { value: 'ppsqm:asc', label: '€/m² più basso' },
  { value: 'sqm:desc', label: 'Più grandi' },
  { value: 'recent:desc', label: 'Più recenti' },
]

function isTyping(e: KeyboardEvent) {
  const el = e.target as HTMLElement
  if (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName) || el.closest('[role="dialog"]')) return true
  // An open modal (a confirm, the palette, the filters sheet) owns the keyboard even if focus slipped behind it.
  return !!document.querySelector('[data-slot="dialog-content"][data-state="open"], [data-slot="sheet-content"][data-state="open"]')
}

/* ── "Segna tutti come visti", with an undo ───────────────────────────────────────────────────────
 * The backend can mark listings seen but not unmark them, so the mark is held back while the undo is
 * on offer: the feed drops the "Nuovo" tags at once and the request goes out only when the toast
 * closes (or the page is left: keepalive lets it finish while the page unloads). Annulla puts the
 * tags back and nothing is sent. */
const UNDO_MS = 6000
let pendingSeen: { settle: (commit: boolean) => void } | null = null

async function markAllSeenWithUndo(qc: QueryClient) {
  pendingSeen?.settle(true) // a batch still waiting for its toast to close is saved now
  const ids = (qc.getQueryData<Listing[]>(keys.listings) ?? []).filter((l) => matchesTab(l, 'nuovi')).map((l) => l.id)
  if (!ids.length) {
    toast('Nessun annuncio nuovo')
    return
  }
  // A feed refetch in flight would land on top of the local mark: stop it, and fetch again once settled.
  const refetchStopped = qc.isFetching({ queryKey: keys.listings }) > 0
  await qc.cancelQueries({ queryKey: keys.listings })
  const at = new Date().toISOString()
  const marked = new Set(ids)
  // Only the listings this batch marked go back: one opened in the meantime keeps its real mark.
  const patch = (from: string | null, to: string | null) =>
    qc.setQueryData<Listing[]>(keys.listings, (old) =>
      old?.map((l) => (marked.has(l.id) && l.seen_at === from ? { ...l, seen_at: to } : l)),
    )
  patch(null, at)

  let done = false
  const onLeave = () => settle(true, true)
  const settle = (commit: boolean, leaving = false) => {
    if (done) return
    done = true
    window.removeEventListener('pagehide', onLeave)
    if (pendingSeen === batch) pendingSeen = null
    if (!commit) {
      patch(at, null)
      if (refetchStopped) qc.invalidateQueries({ queryKey: keys.listings })
      return
    }
    // Explicit ids: only the listings the toast counted are marked, not ones a run adds meanwhile.
    api.markSeenMany(ids, { keepalive: leaving }).then(
      () => {
        if (!leaving) qc.invalidateQueries({ queryKey: keys.listings })
      },
      (e: Error) => {
        if (leaving) return
        patch(at, null)
        qc.invalidateQueries({ queryKey: keys.listings })
        toast.error('Annunci non segnati come visti', { description: e.message })
      },
    )
  }
  const batch = { settle }
  pendingSeen = batch
  window.addEventListener('pagehide', onLeave)
  toast(`${ids.length} ${ids.length === 1 ? 'annuncio segnato' : 'annunci segnati'} come visti`, {
    id: `seen-all-${at}`,
    duration: UNDO_MS,
    action: { label: 'Annulla', onClick: () => settle(false) },
    onAutoClose: () => settle(true),
    onDismiss: () => settle(true),
  })
}

/** A filter that is on but has no control of its own in the toolbar (set from a link or the verbale). */
function FilterChip({ label, title, onClear, clearLabel }: { label: string; title?: string; onClear: () => void; clearLabel: string }) {
  return (
    <span className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-sm bg-ink pr-1 pl-2.5 text-xs font-semibold text-white">
      <span title={title}>{label}</span>
      <button
        type="button"
        onClick={onClear}
        className="flex size-6 items-center justify-center rounded-sm hover:bg-white/15"
        aria-label={clearLabel}
      >
        <X className="size-3.5" />
      </button>
    </span>
  )
}

/** A ruled list of choices for the phone's filter sheet: native radios, the pointer marks the chosen one. */
function ChoiceList({
  legend,
  name,
  value,
  options,
  onChange,
}: {
  legend: string
  name: string
  value: string
  options: { value: string; label: string }[]
  onChange: (v: string) => void
}) {
  return (
    <fieldset className="mt-5">
      <legend className="label-caps mb-1.5">{legend}</legend>
      <div className="border-t border-ink/80">
        {options.map((o) => {
          const on = o.value === value
          return (
            <label
              key={o.value}
              className={cn(
                'relative flex min-h-11 cursor-pointer items-center border-b border-hair py-2 pr-2 pl-5 text-sm has-[:focus-visible]:outline-2 has-[:focus-visible]:-outline-offset-2 has-[:focus-visible]:outline-ink',
                on ? 'font-semibold text-ink' : 'text-ink-2',
              )}
            >
              <input type="radio" name={name} value={o.value} checked={on} onChange={() => onChange(o.value)} className="sr-only" />
              {on ? (
                <span
                  aria-hidden
                  className="absolute top-1/2 left-0.5 h-3 w-1.5 -translate-y-1/2 bg-ink [clip-path:polygon(0_0,100%_50%,0_100%)]"
                />
              ) : null}
              {o.label}
            </label>
          )
        })}
      </div>
    </fieldset>
  )
}

/** Phone: search, ricerca and order live in a sheet, so the first listing sits high on the screen. */
function FiltersSheet({
  open,
  onOpenChange,
  filters,
  setFilters,
  configs,
  shown,
  returnFocus,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  filters: FeedFilters
  setFilters: (patch: Partial<FeedFilters>) => void
  configs: SearchConfig[] | undefined
  shown: number
  /** The "Filtri" button: the sheet opens without a trigger of its own, so focus is handed back by hand. */
  returnFocus: React.RefObject<HTMLButtonElement | null>
}) {
  const active = hiddenFilterCount(filters) > 0
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="bottom"
        showCloseButton={false}
        onCloseAutoFocus={(e) => {
          e.preventDefault()
          returnFocus.current?.focus()
        }}
        className="max-h-[85dvh] gap-0 rounded-t-md border-t border-hair-strong bg-sheet p-0 shadow-[0_6px_24px_-6px_rgb(29_29_27/0.28),0_1px_2px_rgb(29_29_27/0.12)]"
      >
        <div className="flex items-center justify-between border-b border-ink pr-2 pl-4">
          <SheetTitle className="py-3 text-lg leading-snug font-semibold text-ink">Filtri</SheetTitle>
          <SheetClose
            className="flex size-11 items-center justify-center rounded-sm text-ink-2 hover:bg-accent hover:text-ink focus-visible:outline-2 focus-visible:outline-ink"
            aria-label="Chiudi i filtri"
          >
            <X className="size-5" />
          </SheetClose>
        </div>
        <SheetDescription className="sr-only">Cerca negli annunci, scegli la ricerca e l’ordine del feed.</SheetDescription>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 pt-4 pb-5">
          <label className="block">
            <span className="label-caps mb-1.5 block">Cerca</span>
            <span className="relative block">
              <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-ink-3" />
              <input
                type="search"
                value={filters.q}
                onChange={(e) => setFilters({ q: e.target.value })}
                placeholder="Via, zona, città…"
                enterKeyHint="search"
                className="h-11 w-full rounded-sm border border-hair-strong bg-sheet pr-11 pl-8 text-base placeholder:text-ink-3 focus:border-ink focus:outline-none"
              />
              {filters.q ? (
                <button
                  type="button"
                  onClick={() => setFilters({ q: '' })}
                  className="absolute top-0 right-0 flex size-11 items-center justify-center rounded-sm text-ink-3 hover:text-ink focus-visible:-outline-offset-2"
                  aria-label="Cancella ricerca"
                >
                  <X className="size-4" />
                </button>
              ) : null}
            </span>
          </label>
          <ChoiceList
            legend="Ricerca"
            name="feed-ricerca"
            value={filters.config == null ? 'all' : String(filters.config)}
            options={[{ value: 'all', label: 'Tutte le ricerche' }, ...(configs ?? []).map((c) => ({ value: String(c.id), label: c.name }))]}
            onChange={(v) => setFilters({ config: v === 'all' ? null : Number(v) })}
          />
          <ChoiceList
            legend="Ordina per"
            name="feed-ordine"
            value={`${filters.sort}:${filters.dir}`}
            options={SORTS}
            onChange={(v) => {
              const [sort, dir] = v.split(':') as [SortKey, 'asc' | 'desc']
              setFilters({ sort, dir })
            }}
          />
        </div>
        <div className="flex gap-2 border-t border-hair px-4 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
          <Button
            variant="outline"
            className="h-11 flex-1"
            disabled={!active}
            onClick={() => setFilters({ q: '', config: null, sort: 'score', dir: 'desc' })}
          >
            Azzera
          </Button>
          <SheetClose asChild>
            <Button className="h-11 flex-[2]">
              {shown === 0 ? 'Nessun annuncio' : `Mostra ${shown} ${shown === 1 ? 'annuncio' : 'annunci'}`}
            </Button>
          </SheetClose>
        </div>
      </SheetContent>
    </Sheet>
  )
}

/** What is narrowing the feed, in words, so an empty feed says why it is empty. */
function activeFilters(f: FeedFilters, configs: SearchConfig[] | undefined): string[] {
  const why: string[] = []
  if (f.q.trim()) why.push(`il testo «${f.q.trim()}»`)
  if (f.config != null) why.push(`la ricerca «${configs?.find((c) => c.id === f.config)?.name ?? `#${f.config}`}»`)
  if (f.minRung != null) why.push(`affinità da ${RUNGS[f.minRung].floor} in su`)
  if (!f.nd) why.push('senza i non valutati')
  if (f.maxPrice != null) why.push(`canone fino a ${f.maxPrice.toLocaleString('it-IT')} €`)
  if (f.minSqm != null) why.push(`almeno ${f.minSqm} m²`)
  if (f.tab !== 'tutti') why.push(`solo ${TABS.find((t) => t.id === f.tab)!.label}`)
  return why
}

function EmptyState({
  hasAny,
  onReset,
  run,
  why,
}: {
  hasAny: boolean
  onReset: () => void
  run: number | null
  why: string[]
}) {
  if (!hasAny)
    return (
      <div className="mx-auto max-w-md px-6 py-20 text-center">
        <Glasses animate className="mx-auto mb-4 w-20 text-ink" />
        <p className="text-lg font-semibold">Milhouse non ha ancora niente da mostrarti</p>
        <p className="mt-1 text-sm text-ink-2">
          Gli annunci arrivano dalle ricerche: scegli città, zone e filtri, poi avviala. Ogni annuncio verrà valutato
          sui tuoi criteri.
        </p>
        <div className="mt-5 flex justify-center gap-2">
          <Button asChild>
            <Link to="/ricerche/nuova">
              <Plus className="size-4" /> Nuova ricerca
            </Link>
          </Button>
          <Button asChild variant="outline">
            <Link to="/preferenze">Scrivi i criteri</Link>
          </Button>
        </div>
      </div>
    )
  return (
    <div className="mx-auto max-w-md px-6 py-16 text-center">
      <Glasses className="mx-auto mb-3 w-14 text-ink-3" />
      <p className="text-base font-semibold">Neanche Milhouse trova qualcosa con questi filtri</p>
      <p className="mt-1 text-sm text-ink-2">
        {run != null
          ? `Nessun annuncio della run #${run} passa gli altri filtri, oppure quelli già noti sono stati ricontrollati da run successive.`
          : why.length
            ? `Filtri attivi: ${why.join(', ')}.`
            : 'Allarga la fascia di affinità o includi gli annunci non valutati.'}
      </p>
      <Button variant="outline" size="sm" className="mt-4" onClick={onReset}>
        Azzera i filtri
      </Button>
    </div>
  )
}

/**
 * Milhouse's last verbale above the feed. Its own component, so the jobs poll re-renders only the
 * strip and never the feed under it.
 */
function FeedVerbale({
  listings,
  listingsAt,
  filters,
  setFilters,
  onSelect,
}: {
  listings: Listing[] | undefined
  listingsAt: number
  filters: FeedFilters
  setFilters: (patch: Partial<FeedFilters>) => void
  onSelect: (id: number) => void
}) {
  const navigate = useNavigate()
  const { data: jobs } = useJobs()
  const [archived, setArchived] = useState(archivedUntil)

  // Milhouse's last verbale (the run that finished last, not the one that started last) stays above
  // the feed for three days, or until archived. With a run filter on, that run's verbale is shown.
  const lastFinished = useMemo(() => {
    if (filters.run != null) return jobs?.find((j) => j.id === filters.run && !isActive(j)) ?? null
    let best: { job: NonNullable<typeof jobs>[number]; at: number } | null = null
    for (const j of jobs ?? []) {
      const at = parseDate(j.finished_at)?.getTime()
      if (!isActive(j) && at != null && (!best || at > best.at)) best = { job: j, at }
    }
    return best?.job ?? null
  }, [jobs, filters.run])
  const lastAt = parseDate(lastFinished?.finished_at)?.getTime() ?? 0
  // An idle jobs poll no longer re-renders anything, so the three-day window closes on its own timer.
  const [, expire] = useState(0)
  useEffect(() => {
    const left = lastAt + 3 * 86400_000 - Date.now()
    if (!lastAt || filters.run != null || left <= 0) return
    const t = setTimeout(() => expire((n) => n + 1), left + 1000)
    return () => clearTimeout(t)
  }, [lastAt, filters.run])
  const verbaleJob =
    lastFinished && (filters.run != null || (lastAt > (archived ?? 0) && Date.now() - lastAt <= 3 * 86400_000))
      ? lastFinished
      : null
  // The verbale reads the full log, which the jobs list does not carry: a failed run's error, and the
  // AI step's own tally ("X scored, Y failed"), so the strip says what the run page and the toast say.
  const { data: fullJob, isError: fullJobMissing } = useJob(verbaleJob?.id ?? null)
  // A copy fetched while the run was still going holds half a log: wait for the finished one.
  const finishedCopy = fullJob != null && !isActive(fullJob)
  const log = finishedCopy ? (fullJob.log ?? undefined) : undefined
  const logReady = !verbaleJob || finishedCopy || fullJobMissing
  // Filed only when the listings were fetched after the run ended (a run that just finished needs its upsert).
  const verbaleReady = !!verbaleJob && !!listings && listingsAt >= lastAt && logReady
  const verbale = useMemo(
    () => (verbaleReady ? buildVerbale(verbaleJob!, listings, log) : null),
    [verbaleReady, verbaleJob, listings, log],
  )
  if (!verbale || !verbaleJob) return null

  return (
    <VerbaleStrip
      v={verbale}
      finishedAt={verbaleJob.finished_at}
      onOpenBest={onSelect}
      onShowRun={
        filters.run == null
          ? // only this run, whatever else was filtered, so the count on the button is the count you see
            () => setFilters({ run: verbaleJob.id, tab: 'tutti', q: '', config: null, minRung: null, nd: true, maxPrice: null, minSqm: null })
          : undefined
      }
      onOpenLog={() => navigate(`/run/${verbaleJob.id}`)}
      onArchive={
        filters.run == null
          ? () => {
              archiveUntil(lastAt)
              setArchived(lastAt)
            }
          : undefined
      }
    />
  )
}

export function AnnunciPage() {
  const { id: idParam } = useParams()
  const selectedId = idParam ? Number(idParam) : null
  const navigate = useNavigate()
  const [search] = useSearchParams()
  const { data: listings, isLoading, error, refetch, isFetching, dataUpdatedAt: listingsAt } = useListings()
  const { data: configs } = useConfigs()
  const [filters, setFilters] = useFeedFilters()
  const heldId = useHeldDiscard(listings)
  // The open listing keeps its row in the tab it was opened from, even once it stops matching it
  // (Nuovi drops a listing as soon as it has been seen), so j/k carry on from its place.
  const sticky = useRef<{ id: number; tab: TriageTab } | null>(null)
  const keepId = sticky.current?.id === selectedId && sticky.current?.tab === filters.tab ? selectedId : null
  const { rows, counts, rungCounts, total } = useFeed(listings, filters, heldId, keepId)
  if (selectedId != null && rows.some((r) => r.id === selectedId)) sticky.current = { id: selectedId, tab: filters.tab }
  const desktop = useMediaQuery('(min-width: 1024px)')
  const compact = useMediaQuery('(max-width: 767px)')
  const [filtersOpen, setFiltersOpen] = useState(false)
  const markSeen = useMarkSeen()
  const triage = useTriage()
  const qc = useQueryClient()
  const searchRef = useRef<HTMLInputElement>(null)
  const filtersButtonRef = useRef<HTMLButtonElement>(null)
  const feedRef = useRef<HTMLDivElement>(null)

  const qs = search.toString() ? `?${search.toString()}` : ''
  // Stable between renders, so the memoized feed rows skip re-rendering.
  const select = useCallback((id: number | null) => navigate(id == null ? `/${qs}` : `/annunci/${id}${qs}`), [navigate, qs])

  // Desktop opens the best match straight away; the phone waits for a tap.
  useEffect(() => {
    if (desktop && selectedId == null && rows.length) navigate(`/annunci/${rows[0].id}${qs}`, { replace: true })
  }, [desktop, selectedId, rows, navigate, qs])

  const selected = useMemo(() => listings?.find((l) => l.id === selectedId), [listings, selectedId])

  // Triage loop: when a verdict (key or button) moves the open listing (X sinks it to the foot of
  // Tutti) or takes it out of the tab, the selection steps to the row that followed it before the
  // change, so the next j/k and the next verdict carry on from the same place.
  const before = useRef<{ ids: number[]; id: number | null; status: TriageStatus | null | undefined; tab: TriageTab } | null>(null)
  useLayoutEffect(() => {
    const prev = before.current
    before.current = { ids: rows.map((r) => r.id), id: selectedId, status: selected?.triage_status, tab: filters.tab }
    if (!desktop || !selected || !prev || prev.id !== selected.id || prev.tab !== filters.tab) return
    if (prev.status === undefined || prev.status === selected.triage_status) return
    if (!triageMoves(selected, prev.status, filters.tab)) return
    const tutti = filters.tab === 'tutti'
    // A listing restored from the discarded tail of Tutti stays open at its new place.
    if (tutti && selected.triage_status !== 'scartato') return
    const at = prev.ids.indexOf(selected.id)
    if (at < 0) return
    const byId = new Map(rows.map((r) => [r.id, r]))
    // After a discard in Tutti, the next listing still in play: never one from the discarded tail,
    // which the next X would quietly restore. Then the one before it; else the selection stays.
    const fits = (id: number) => {
      const r = byId.get(id)
      return !!r && r.id !== selected.id && !(tutti && r.triage_status === 'scartato')
    }
    const next = prev.ids.slice(at + 1).find(fits) ?? prev.ids.slice(0, at).reverse().find(fits)
    if (next != null) navigate(`/annunci/${next}${qs}`, { replace: true })
  }, [rows, selected, selectedId, filters.tab, desktop, navigate, qs])

  // A listing stops being "nuovo" once it has been on screen for a moment (once per tab if that fails).
  useEffect(() => {
    if (!selected || selected.seen_at || seenMarkHasFailed(selected.id)) return
    const t = setTimeout(() => markSeen.mutate(selected.id), 1200)
    return () => clearTimeout(t)
  }, [selected?.id, selected?.seen_at]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || isTyping(e)) return
      // A held verdict key gives one verdict: auto-repeat would walk it down the feed, listing after
      // listing, as the selection moves on. A held O would open a tab per repeat.
      if (e.repeat && ['p', 'c', 'x', 'o'].includes(e.key)) return
      // Arrows belong to whatever has focus (a select, the ladder, the certificate's scroll): they
      // switch listings only from the feed itself or from nowhere in particular. j/k work anywhere.
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        const t = e.target as Node
        if (t !== document.body && t !== document.documentElement && !feedRef.current?.contains(t)) return
      }
      const i = rows.findIndex((l) => l.id === selectedId)
      if (e.key === 'j' || e.key === 'ArrowDown') {
        e.preventDefault()
        const next = rows[Math.min(rows.length - 1, i + 1)]
        if (next) select(next.id)
      } else if (e.key === 'k' || e.key === 'ArrowUp') {
        e.preventDefault()
        const prev = rows[Math.max(0, i - 1)]
        if (prev) select(prev.id)
      } else if (e.key === '/') {
        e.preventDefault()
        if (searchRef.current) searchRef.current.focus()
        else setFiltersOpen(true)
      } else if (selected && ['p', 'c', 'x'].includes(e.key)) {
        const status = ({ p: 'preferito', c: 'contattato', x: 'scartato' } as const)[e.key as 'p' | 'c' | 'x']
        triage.mutate({ id: selected.id, status: selected.triage_status === status ? null : status })
      } else if (selected && e.key === 'o') {
        window.open(selected.url, '_blank', 'noreferrer')
      } else if (e.key === 'Escape' && selectedId != null && !desktop) {
        select(null)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const markAll = () => void markAllSeenWithUndo(qc)

  const sortBy = (key: typeof filters.sort) =>
    setFilters(filters.sort === key ? { dir: filters.dir === 'asc' ? 'desc' : 'asc' } : { sort: key, dir: key === 'price' || key === 'ppsqm' ? 'asc' : 'desc' })

  // The feed asks for at most LISTINGS_LIMIT rows: a full page means older listings were left out.
  const capped = total >= LISTINGS_LIMIT

  const resetFilters = () =>
    setFilters({ q: '', config: null, minRung: null, nd: true, tab: 'tutti', maxPrice: null, minSqm: null, run: null })

  // Phone: the detail replaces the feed.
  if (!desktop && selectedId != null) {
    return (
      <div className="h-[calc(100dvh-6.5rem)] md:h-full">
        <ListingDetail id={selectedId} summary={selected} onClose={() => select(null)} mobile />
      </div>
    )
  }

  const ladder = (
    <div className={cn('flex items-center gap-2', compact && 'w-full')}>
      <span className="label-caps hidden md:inline">Affinità</span>
      <LadderFilter
        minRung={filters.minRung}
        onChange={(r) => setFilters({ minRung: r })}
        includeUnscored={filters.nd}
        onIncludeUnscoredChange={(v) => setFilters({ nd: v })}
        counts={rungCounts}
        fill
      />
    </div>
  )

  // Filters with no control of their own: the verbale's run, and price or size limits from a link.
  const chips = (
    <>
      {filters.run != null ? (
        <FilterChip
          label={`Dalla run #${filters.run}`}
          title="Gli annunci che questa run ha trovato per la prima volta o rivisto"
          onClear={() => setFilters({ run: null })}
          clearLabel="Mostra tutti gli annunci, non solo questa run"
        />
      ) : null}
      {filters.maxPrice != null ? (
        <FilterChip
          label={`Fino a ${filters.maxPrice.toLocaleString('it-IT')} €/mese`}
          onClear={() => setFilters({ maxPrice: null })}
          clearLabel="Togli il limite di canone"
        />
      ) : null}
      {filters.minSqm != null ? (
        <FilterChip
          label={`Da ${filters.minSqm} m²`}
          onClear={() => setFilters({ minSqm: null })}
          clearLabel="Togli il limite di superficie"
        />
      ) : null}
    </>
  )
  const hasChips = filters.run != null || filters.maxPrice != null || filters.minSqm != null
  const hidden = hiddenFilterCount(filters)

  const toolbar = (
    <div className={cn('flex flex-col border-b border-hair bg-sheet px-4 pt-3 pb-0 lg:px-5', compact ? 'gap-2' : 'gap-2.5')}>
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="mr-1 text-xl font-bold">Annunci</h1>
        <span
          className="tnum text-sm text-ink-3"
          title={capped ? `Il feed mostra i ${LISTINGS_LIMIT} annunci trovati più di recente` : undefined}
        >
          {rows.length === total ? total : `${rows.length} di ${total}`}
          {capped ? '+' : ''}
        </span>
        <div className="ml-auto flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => refetch()}
            className="flex size-8 items-center justify-center rounded-sm text-ink-3 hover:bg-accent hover:text-ink"
            aria-label="Aggiorna"
            title="Aggiorna"
          >
            <RefreshCw className={cn('size-4', isFetching && 'animate-spin')} />
          </button>
          {counts.nuovi ? (
            <Button variant="ghost" size="sm" onClick={markAll} className="hidden text-ink-2 sm:inline-flex">
              <CheckCheck className="size-4" /> Segna tutti come visti
            </Button>
          ) : null}
          {compact ? (
            <Button
              ref={filtersButtonRef}
              variant="outline"
              size="sm"
              onClick={() => setFiltersOpen(true)}
              aria-label={hidden ? `Filtri, ${hidden} ${hidden === 1 ? 'attivo' : 'attivi'}` : 'Filtri'}
              aria-haspopup="dialog"
            >
              <SlidersHorizontal className="size-4" /> Filtri
              {hidden ? (
                <span className="tnum -mr-1 inline-flex h-4 min-w-4 items-center justify-center rounded-[2px] bg-ink px-1 text-2xs font-bold text-white">
                  {hidden}
                </span>
              ) : null}
            </Button>
          ) : null}
          <div className="hidden md:block">
            <RunLauncher />
          </div>
        </div>
      </div>
      {compact ? (
        <>
          {hasChips ? <div className="flex flex-wrap items-center gap-2">{chips}</div> : null}
          {ladder}
        </>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-48 flex-1 sm:max-w-72">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-ink-3" />
            <input
              ref={searchRef}
              value={filters.q}
              onChange={(e) => setFilters({ q: e.target.value })}
              placeholder="Via, zona, città…"
              className="h-8 w-full rounded-sm border border-hair-strong bg-sheet pr-7 pl-8 text-sm placeholder:text-ink-3 focus:border-ink focus:outline-none"
              aria-label="Cerca negli annunci"
            />
            {filters.q ? (
              <button
                type="button"
                onClick={() => setFilters({ q: '' })}
                className="absolute top-1/2 right-1.5 -translate-y-1/2 text-ink-3 hover:text-ink"
                aria-label="Cancella ricerca"
              >
                <X className="size-3.5" />
              </button>
            ) : null}
          </div>
          {chips}
          <Select
            value={filters.config == null ? 'all' : String(filters.config)}
            onValueChange={(v) => setFilters({ config: v === 'all' ? null : Number(v) })}
          >
            <SelectTrigger size="sm" className="h-8 w-auto min-w-40 rounded-sm border-hair-strong bg-sheet text-sm" aria-label="Ricerca">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Tutte le ricerche</SelectItem>
              {configs?.map((c) => (
                <SelectItem key={c.id} value={String(c.id)}>
                  {c.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {!desktop ? (
            <Select
              value={`${filters.sort}:${filters.dir}`}
              onValueChange={(v) => {
                const [sort, dir] = v.split(':') as [SortKey, 'asc' | 'desc']
                setFilters({ sort, dir })
              }}
            >
              <SelectTrigger size="sm" className="h-8 w-auto rounded-sm border-hair-strong bg-sheet text-sm" aria-label="Ordina">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SORTS.map((o) => (
                  <SelectItem key={o.value} value={o.value}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : null}
          {ladder}
        </div>
      )}
      <nav className="-mb-px flex gap-4 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden" aria-label="Stato">
        {TABS.map((t) => {
          const on = filters.tab === t.id
          return (
            <button
              key={t.id}
              type="button"
              onClick={() => setFilters({ tab: t.id })}
              aria-current={on ? 'true' : undefined}
              className={cn(
                'relative flex h-9 shrink-0 items-center gap-1.5 text-sm font-semibold transition-colors',
                on ? 'text-ink' : 'text-ink-3 hover:text-ink',
              )}
            >
              {on ? (
                <motion.span
                  layoutId="triage-tab"
                  className="absolute inset-x-0 bottom-0 h-0.5 bg-ink"
                  transition={{ type: 'tween', duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
                />
              ) : null}
              {t.label}
              <span className={cn('tnum text-xs font-normal', on ? 'text-ink-2' : 'text-ink-3')}>{counts[t.id]}</span>
            </button>
          )
        })}
      </nav>
      {compact ? (
        <FiltersSheet
          open={filtersOpen}
          onOpenChange={setFiltersOpen}
          filters={filters}
          setFilters={setFilters}
          configs={configs}
          shown={rows.length}
          returnFocus={filtersButtonRef}
        />
      ) : null}
    </div>
  )

  const body = error ? (
    <div className="mx-auto max-w-md px-6 py-16 text-center">
      <p className="font-semibold">Non riesco a caricare gli annunci</p>
      <p className="mt-1 text-sm text-ink-2">{(error as Error).message}</p>
      <Button variant="outline" size="sm" className="mt-4" onClick={() => refetch()}>
        Riprova
      </Button>
    </div>
  ) : isLoading ? (
    <div className="flex flex-col">
      <MilhouseLoader
        className="border-b border-hair px-4 py-3"
        lines={['Milhouse sfoglia gli annunci…', 'Li mette in fila per affinità…', 'Segna quelli nuovi…']}
      />
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="flex items-center gap-3 border-b border-hair px-4 py-2">
          <Skeleton className="h-12 w-16" />
          <div className="flex-1 space-y-1.5">
            <Skeleton className="h-3.5 w-2/3" />
            <Skeleton className="h-3 w-1/3" />
          </div>
          <Skeleton className="h-6 w-12" />
        </div>
      ))}
    </div>
  ) : rows.length === 0 ? (
    <EmptyState hasAny={total > 0} onReset={resetFilters} run={filters.run} why={activeFilters(filters, configs)} />
  ) : desktop ? (
    <ListingTable rows={rows} selectedId={selectedId} onSelect={select} filters={filters} onSort={sortBy} />
  ) : (
    <ListingCards rows={rows} onSelect={select} />
  )

  const strip = <FeedVerbale listings={listings} listingsAt={listingsAt} filters={filters} setFilters={setFilters} onSelect={select} />

  if (!desktop) {
    return (
      <div className="flex flex-col md:h-full md:overflow-y-auto">
        {toolbar}
        {strip}
        <div ref={feedRef}>{body}</div>
      </div>
    )
  }

  return (
    <div className="grid h-full grid-cols-[minmax(0,1fr)_minmax(26rem,40%)]">
      <section className="flex min-h-0 flex-col border-r border-hair bg-sheet" aria-label="Elenco annunci">
        {toolbar}
        {strip}
        <div ref={feedRef} className="min-h-0 flex-1 overflow-y-auto">
          {body}
        </div>
        <footer className="flex h-8 shrink-0 items-center gap-4 border-t border-hair px-5 text-2xs text-ink-3">
          <span><kbd className="font-semibold text-ink-2">J</kbd>/<kbd className="font-semibold text-ink-2">K</kbd> scorri</span>
          <span><kbd className="font-semibold text-ink-2">P</kbd> preferito</span>
          <span><kbd className="font-semibold text-ink-2">C</kbd> contattato</span>
          <span><kbd className="font-semibold text-ink-2">X</kbd> scarta</span>
          <span><kbd className="font-semibold text-ink-2">O</kbd> apri portale</span>
          <span className="ml-auto"><kbd className="font-semibold text-ink-2">/</kbd> cerca</span>
        </footer>
      </section>
      {/* Nothing to read when nothing is open: the feed opens its best match itself, and an empty
          feed explains itself on the left instead of a half-screen prompt on the right. */}
      <div className="min-h-0">
        {selectedId != null ? <ListingDetail id={selectedId} summary={selected} onClose={() => select(null)} /> : null}
      </div>
    </div>
  )
}
