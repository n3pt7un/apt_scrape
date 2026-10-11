import { ArrowDown, ArrowUp, House } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { memo, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { ScoreChevron } from '@/components/ape/Chevron'
import { eur, eurSqm, imageVariant, listingName, num, splitTitle, zoneOf } from '@/lib/format'
import type { Listing } from '@/lib/types'
import { cn } from '@/lib/utils'
import type { FeedFilters, SortKey } from './filters'
import { TriageButtons, TriageStamp } from './TriageControls'

/**
 * A listing photo in its slot. No photo (or only the portal's placeholder drawing) is a plain sheet-2
 * slot with a house: the N.D. hatch belongs to scores, never to photos.
 */
export function Thumb({ src, className, size = 'xs-c' }: { src: string | null; className?: string; size?: 'xs-c' | 'm-c' | 'l-c' }) {
  const url = imageVariant(src, size)
  if (!url)
    return (
      <span className={cn('flex items-center justify-center bg-sheet-2 text-ink-3', className)} aria-hidden>
        <House className="size-4" />
      </span>
    )
  // The grey slot stays visible while the photo develops on top of it.
  return (
    <span className={cn('block overflow-hidden bg-sheet-2', className)}>
      <DevelopImg key={url} src={url} loading="lazy" className="size-full object-cover" />
    </span>
  )
}

// Photos already developed once in this session show at once when their row comes back.
const developed = new Set<string>()

/** A portal photo that develops in (grey to colour, transparent to opaque) the first time it loads. */
export function DevelopImg({ className, alt = '', ...props }: React.ImgHTMLAttributes<HTMLImageElement>) {
  const ref = useRef<HTMLImageElement>(null)
  const src = typeof props.src === 'string' ? props.src : ''
  const [loaded, setLoadedState] = useState(() => developed.has(src))
  const [broken, setBroken] = useState(false)
  const setLoaded = () => {
    developed.add(src)
    setLoadedState(true)
  }
  useLayoutEffect(() => {
    if (ref.current?.complete && ref.current.naturalWidth) setLoaded()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  // A portal photo that no longer exists becomes the same plain slot as a missing one.
  if (broken)
    return (
      <span className={cn('flex items-center justify-center bg-sheet-2 text-ink-3', className)} role={alt ? 'img' : undefined} aria-label={alt || undefined}>
        <House className="size-4" />
      </span>
    )
  return (
    <img
      ref={ref}
      alt={alt}
      {...props}
      data-loaded={loaded}
      onLoad={setLoaded}
      onError={() => setBroken(true)}
      className={cn('img-develop', className)}
    />
  )
}

/** "Nuovo" until seen; it folds away when the listing has been looked at. */
export function NewTag({ show }: { show: boolean }) {
  return (
    <AnimatePresence initial={false}>
      {show ? (
        <motion.span
          exit={{ opacity: 0, width: 0, paddingLeft: 0, paddingRight: 0, marginRight: -6 }}
          transition={{ duration: 0.24, ease: [0.16, 1, 0.3, 1] }}
          className="inline-flex h-4 shrink-0 items-center overflow-hidden rounded-[2px] bg-ink px-1 text-2xs leading-4 font-bold tracking-[0.05em] whitespace-nowrap text-white uppercase"
        >
          Nuovo
        </motion.span>
      ) : null}
    </AnimatePresence>
  )
}

/** The nearest ancestor that scrolls vertically. */
function scrollParent(el: HTMLElement | null): HTMLElement | null {
  for (let p = el?.parentElement; p; p = p.parentElement) {
    const y = getComputedStyle(p).overflowY
    if (y === 'auto' || y === 'scroll') return p
  }
  return null
}

const COLS: { key: SortKey | null; label: string; className: string }[] = [
  { key: null, label: 'Annuncio', className: 'text-left pl-4' },
  { key: 'price', label: '€/mese', className: 'text-right w-[5.25rem]' },
  { key: 'sqm', label: 'm²', className: 'text-right w-12' },
  { key: 'ppsqm', label: '€/m²', className: 'text-right w-16 hidden xl:table-cell' },
  { key: null, label: 'Locali', className: 'text-right w-[3.25rem] hidden xl:table-cell' },
  { key: 'score', label: 'Affinità', className: 'text-right w-[4.75rem]' },
  { key: null, label: '', className: 'w-[5.5rem]' },
]

/**
 * One feed row. Memoized: a cache patch keeps unchanged listings as the same objects, so a triage,
 * a seen mark or a poll re-renders only the rows that changed.
 */
const ListingRow = memo(function ListingRow({
  l,
  sel,
  tabbable,
  onSelect,
  selectedRef,
}: {
  l: Listing
  sel: boolean
  /** The feed's one tab stop: the open row, or the first one when the open listing is not in the feed. */
  tabbable: boolean
  onSelect: (id: number) => void
  selectedRef: React.RefObject<HTMLTableRowElement | null>
}) {
  const t = splitTitle(l.title)
  const zone = zoneOf(t, l)
  // Discarded rows keep full-contrast text: the struck, muted title and a grey photo say "out".
  const out = l.triage_status === 'scartato'
  const head = t.isAddress ? t.street : t.typology ?? t.street
  return (
    <tr
      ref={sel ? selectedRef : undefined}
      onClick={() => onSelect(l.id)}
      // scroll-margin clears the sticky column heads when a row is scrolled into view from below them
      className={cn('group scroll-mt-8 cursor-pointer transition-colors', sel ? 'bg-[#eef0ea]' : 'hover:bg-sheet-2')}
    >
      <td className="rule-b py-2 pr-2 pl-4">
        <div className="flex items-center gap-3">
          <Thumb src={l.thumbnail} className={cn('h-12 w-16 shrink-0 rounded-[2px] transition-[filter]', out && 'grayscale')} />
          <div className="min-w-0">
            <p className="flex min-w-0 items-center gap-1.5">
              <NewTag show={!l.seen_at && !out} />
              {/* The title is the row's real control. The feed is one tab stop (roving tabindex):
                  Tab lands on the open row, j/k or the arrows move from row to row, Enter opens it. */}
              <button
                type="button"
                data-feed-row={l.id}
                tabIndex={tabbable ? 0 : -1}
                onClick={(e) => {
                  e.stopPropagation()
                  onSelect(l.id)
                }}
                aria-current={sel ? 'true' : undefined}
                title={t.isAddress ? head : `${head} · ${t.street}`}
                className={cn(
                  'min-w-0 truncate rounded-[2px] text-left font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink',
                  out ? 'text-ink-3' : 'text-ink',
                )}
              >
                <span className={cn('strike', out && 'is-struck')}>
                  {head}
                  {!t.isAddress ? <span className="font-normal text-ink-3"> · {t.street}</span> : null}
                </span>
              </button>
            </p>
            <p className="mt-0.5 flex min-w-0 items-center gap-1.5 text-xs text-ink-3">
              {l.triage_status && l.triage_status !== 'scartato' ? <TriageStamp id={l.id} status={l.triage_status} /> : null}
              {/* The zone first: it is what decides a listing, and it must not truncate behind the typology. */}
              <span className="truncate" title={t.isAddress && t.typology ? `${zone} · ${t.typology}` : zone}>
                {zone}
                {t.isAddress && t.typology ? ` · ${t.typology}` : ''}
              </span>
            </p>
          </div>
        </div>
      </td>
      <td className="rule-b tnum px-2 text-right font-semibold text-ink">{eur(l.price_eur)}</td>
      <td className="rule-b tnum px-2 text-right text-ink-2">{num(l.sqm_num)}</td>
      <td className="rule-b tnum hidden px-2 text-right text-ink-2 xl:table-cell">{eurSqm(l.price_per_sqm)}</td>
      <td className="rule-b tnum hidden px-2 text-right text-ink-2 xl:table-cell">{l.rooms_num ?? '—'}</td>
      <td className="rule-b px-2 text-right">
        <ScoreChevron listing={l} />
      </td>
      <td className="rule-b relative pr-3 pl-1">
        <TriageButtons
          listing={l}
          name={listingName(l)}
          // only the open row's toggles take a tab stop; P, C and X reach them from the keyboard anyway
          tabbable={sel}
          className={cn(
            'justify-end transition-opacity',
            !sel && !l.triage_status && 'opacity-0 group-hover:opacity-100 focus-within:opacity-100',
          )}
        />
      </td>
    </tr>
  )
})

export function ListingTable({
  rows,
  selectedId,
  onSelect,
  filters,
  onSort,
}: {
  rows: Listing[]
  selectedId: number | null
  onSelect: (id: number) => void
  filters: FeedFilters
  onSort: (key: SortKey) => void
}) {
  const selectedRef = useRef<HTMLTableRowElement>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  const open = rows.find((r) => r.id === selectedId)
  // The open row is the feed's tab stop; with the open listing filtered out, the first row is.
  const tabId = open ? open.id : rows[0]?.id ?? null
  // Also when the open listing's verdict moves it (a listing restored from the discarded tail rises).
  const openStatus = open?.triage_status
  const focusedFor = useRef(selectedId)
  useEffect(() => {
    const tr = selectedRef.current
    if (!tr) return
    // Focus follows a new selection while it is in the feed, so j/k and the arrows rove from row to
    // row (a verdict on the open row leaves focus on the toggle that gave it).
    const focused = document.activeElement
    if (focusedFor.current !== selectedId && focused && tr.closest('tbody')?.contains(focused))
      tr.querySelector<HTMLElement>('[data-feed-row]')?.focus({ preventScroll: true })
    focusedFor.current = selectedId
    tr.scrollIntoView({ block: 'nearest' })
  }, [selectedId, openStatus])

  // The feed's scroller can shrink after the open row was scrolled into view (the verbale strip above
  // it mounts once its log arrives): bring the row back, but only if the shrink is what hid it.
  useEffect(() => {
    const scroller = scrollParent(wrapRef.current)
    if (!scroller) return
    let height = scroller.clientHeight
    const ro = new ResizeObserver(() => {
      const before = height
      height = scroller.clientHeight
      const tr = selectedRef.current
      if (!tr || height >= before) return
      const top = tr.getBoundingClientRect().top - scroller.getBoundingClientRect().top
      const bottom = top + tr.offsetHeight
      if (top >= 0 && bottom <= before + 1 && bottom > height + 1) tr.scrollIntoView({ block: 'nearest' })
    })
    ro.observe(scroller)
    return () => ro.disconnect()
  }, [])

  // One pointer for the whole feed: it slides from row to row, like the ladder pointer does from rung to rung.
  const [pointer, setPointer] = useState<{ y: number; glide: boolean } | null>(null)
  useLayoutEffect(() => {
    const place = () => {
      const tr = selectedRef.current
      const wrap = wrapRef.current
      if (!tr || !wrap) return setPointer(null)
      const y = tr.getBoundingClientRect().top - wrap.getBoundingClientRect().top + tr.offsetHeight / 2
      setPointer((p) => ({ y, glide: p != null }))
    }
    place()
    const ro = new ResizeObserver(place)
    if (wrapRef.current) ro.observe(wrapRef.current)
    return () => ro.disconnect()
  }, [selectedId, rows])

  return (
    <div ref={wrapRef} className="relative">
    {pointer ? (
      <span
        className={cn(
          'pointer-events-none absolute top-0 right-0 z-[1] h-4 w-2 bg-ink [clip-path:polygon(0_0,100%_50%,0_100%)]',
          pointer.glide && 'transition-transform duration-[220ms] ease-out-expo',
        )}
        style={{ transform: `translateY(${pointer.y - 8}px)` }}
        aria-hidden
      />
    ) : null}
    <table className="w-full table-fixed border-separate border-spacing-0 text-sm">
      <thead className="sticky top-0 z-10 bg-sheet">
        <tr>
          {COLS.map((c, i) => (
            <th
              key={i}
              scope="col"
              className={cn('label-caps h-8 border-b border-ink/80 px-2 align-middle font-semibold', c.className)}
              aria-sort={c.key && filters.sort === c.key ? (filters.dir === 'asc' ? 'ascending' : 'descending') : undefined}
            >
              {c.key ? (
                <button
                  type="button"
                  onClick={() => onSort(c.key!)}
                  className={cn(
                    'inline-flex items-center gap-0.5 uppercase transition-colors hover:text-ink',
                    filters.sort === c.key && 'text-ink',
                  )}
                >
                  {c.label}
                  {filters.sort === c.key ? (
                    filters.dir === 'asc' ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />
                  ) : null}
                </button>
              ) : (
                c.label
              )}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((l) => (
          <ListingRow
            key={l.id}
            l={l}
            sel={l.id === selectedId}
            tabbable={l.id === tabId}
            onSelect={onSelect}
            selectedRef={selectedRef}
          />
        ))}
      </tbody>
    </table>
    </div>
  )
}

/** Phone feed: one listing per row, the numbers that decide it in one line. */
export function ListingCards({ rows, onSelect }: { rows: Listing[]; onSelect: (id: number) => void }) {
  return (
    <ul className="divide-y divide-hair bg-sheet">
      {rows.map((l) => {
        const t = splitTitle(l.title)
        const zone = zoneOf(t, l)
        const out = l.triage_status === 'scartato'
        return (
          <li key={l.id}>
            <button
              type="button"
              onClick={() => onSelect(l.id)}
              className="flex w-full gap-3 px-4 py-3 text-left active:bg-sheet-2"
            >
              <Thumb src={l.thumbnail} className={cn('h-[4.5rem] w-24 shrink-0 rounded-[2px]', out && 'grayscale')} />
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="flex items-start gap-2">
                  <span className={cn('line-clamp-2 flex-1 text-sm font-semibold leading-snug', out && 'text-ink-3')}>
                    <span className={cn('strike', out && 'is-struck')}>
                    {t.isAddress ? (
                      <>
                        {t.typology ? <span className="font-normal text-ink-3">{t.typology} · </span> : null}
                        {t.street}
                      </>
                    ) : (
                      <>
                        {t.typology ?? t.street}
                        <span className="font-normal text-ink-3"> · {t.street}</span>
                      </>
                    )}
                    </span>
                  </span>
                  <ScoreChevron listing={l} size="sm" withTooltip={false} />
                </span>
                <span className="mt-0.5 line-clamp-2 text-xs text-ink-3">{zone}</span>
                <span className="tnum mt-auto flex items-center gap-2 pt-1 text-sm">
                  <span className="font-bold">{eur(l.price_eur)}</span>
                  <span className="text-ink-2">{num(l.sqm_num)} m²</span>
                  {l.rooms_num ? <span className="text-ink-2">{l.rooms_num} loc.</span> : null}
                  <span className="ml-auto flex gap-1">
                    <NewTag show={!l.seen_at && !out} />
                    {l.triage_status && !out ? <TriageStamp id={l.id} status={l.triage_status} /> : null}
                  </span>
                </span>
              </span>
            </button>
          </li>
        )
      })}
    </ul>
  )
}
