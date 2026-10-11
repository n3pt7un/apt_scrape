import { ExternalLink, X } from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { EnergyChevron } from '@/components/ape/Chevron'
import { Ladder } from '@/components/ape/Ladder'
import { Button } from '@/components/ui/button'
import { eur, eurSqm, listingName, num, splitTitle } from '@/lib/format'
import { scored, verdictLabel } from '@/lib/ladder'
import { useListings } from '@/lib/queries'
import { compareStore, useCompare } from '@/lib/store'
import type { Listing } from '@/lib/types'
import { useMediaQuery } from '@/lib/useMediaQuery'
import { Glasses } from '@/components/milhouse/Glasses'
import { cn } from '@/lib/utils'
import { Thumb } from '../listings/ListingTable'
import { TriageButtons } from '../listings/TriageControls'

type Best = 'min' | 'max'

interface RowDef {
  label: string
  render: (l: Listing) => React.ReactNode
  value?: (l: Listing) => number | null
  best?: Best
}

const yesNo = (v: boolean | null) => (v == null ? '—' : v ? 'Sì' : 'No')
/** One row of the portal's feature table, by its scraped label. */
const fact = (l: Listing, label: string) => (l.facts ?? []).find((f) => f.label.toLowerCase() === label.toLowerCase())?.value ?? '—'

const ROWS: RowDef[] = [
  { label: 'Canone', render: (l) => <span className="text-lg font-bold">{eur(l.price_eur)}</span>, value: (l) => l.price_eur, best: 'min' },
  { label: 'Superficie', render: (l) => `${num(l.sqm_num)} m²`, value: (l) => l.sqm_num, best: 'max' },
  { label: 'Prezzo al m²', render: (l) => eurSqm(l.price_per_sqm), value: (l) => l.price_per_sqm, best: 'min' },
  // More rooms is not better in itself: the criteria decide (a bilocale hunt). No "migliore" here.
  { label: 'Locali', render: (l) => l.rooms_num ?? '—', value: (l) => l.rooms_num },
  { label: 'Piano', render: (l) => l.floor ?? '—' },
  { label: 'Arredato', render: (l) => yesNo(l.furnished) },
  { label: 'Bagni', render: (l) => l.bathrooms ?? '—' },
  { label: 'Contratto', render: (l) => fact(l, 'Contratto') },
  { label: 'Disponibile da', render: (l) => l.available_from ?? '—' },
  { label: 'Classe energetica', render: (l) => <EnergyChevron value={l.energy_class} /> },
]

function bestIds(rows: Listing[], value: (l: Listing) => number | null, best: Best): Set<number> {
  const vals = rows.map((l) => [l.id, value(l)] as const).filter((x): x is readonly [number, number] => x[1] != null)
  if (vals.length < 2) return new Set()
  const target = best === 'min' ? Math.min(...vals.map((v) => v[1])) : Math.max(...vals.map((v) => v[1]))
  if (vals.every((v) => v[1] === target)) return new Set()
  return new Set(vals.filter((v) => v[1] === target).map((v) => v[0]))
}

function BestMark() {
  return (
    <span className="ml-2 inline-flex items-center gap-1 align-middle text-2xs font-bold tracking-wide text-ink uppercase">
      <span className="h-2.5 w-1.5 bg-ink [clip-path:polygon(100%_0,0_50%,100%_100%)]" aria-hidden />
      migliore
    </span>
  )
}

/**
 * The AI's reason, the heart of the comparison. Narrow phone columns cut it at six lines, with a
 * "Leggi tutto" that opens it in place: a touch screen never shows a tooltip.
 */
function Reason({ text, clamp }: { text: string; clamp: boolean }) {
  const ref = useRef<HTMLParagraphElement>(null)
  const [open, setOpen] = useState(false)
  const [cut, setCut] = useState(false)
  useLayoutEffect(() => {
    const p = ref.current
    if (!p || !clamp || open) return
    const measure = () => setCut(p.scrollHeight > p.clientHeight + 1)
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(p)
    return () => ro.disconnect()
  }, [clamp, open, text])
  return (
    <>
      <p ref={ref} className={cn('mt-1 text-xs leading-relaxed text-ink-2', clamp && !open && 'line-clamp-6')}>
        {text}
      </p>
      {clamp && (cut || open) ? (
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="mt-0.5 inline-flex min-h-8 items-center text-xs font-semibold text-ink underline decoration-hair-strong underline-offset-[3px] hover:decoration-ink"
        >
          {open ? 'Riduci' : 'Leggi tutto'}
        </button>
      ) : null}
    </>
  )
}

export function ComparePage() {
  const [params, setParams] = useSearchParams()
  const stored = useCompare()
  const { data: listings, isLoading } = useListings()
  // Phone: no label column; each row's label runs across the top and the listings share the full width.
  const desk = useMediaQuery('(min-width: 768px)')

  // The URL wins when present (shareable); otherwise the session tray.
  const urlIds = (params.get('ids') ?? '')
    .split(',')
    .map(Number)
    .filter((n) => Number.isFinite(n) && n > 0)
  const ids = urlIds.length ? urlIds.slice(0, 3) : stored
  useEffect(() => {
    if (urlIds.length && urlIds.join() !== stored.join()) compareStore.set(urlIds.slice(0, 3))
  }, [params]) // eslint-disable-line react-hooks/exhaustive-deps

  const rows = ids.map((id) => listings?.find((l) => l.id === id)).filter((l): l is Listing => !!l)
  const remove = (id: number) => {
    const next = ids.filter((x) => x !== id)
    compareStore.set(next)
    setParams(next.length ? { ids: next.join(',') } : {}, { replace: true })
  }

  if (!isLoading && rows.length === 0) {
    return (
      <div className="mx-auto max-w-lg px-6 py-20 text-center">
        <Glasses className="mx-auto w-14 text-ink-3" />
        <p className="mt-3 text-lg font-semibold">Niente da confrontare</p>
        <p className="mt-1 text-sm text-ink-2">
          Apri la scheda di un annuncio e premi <b>Confronta</b>. Puoi mettere fianco a fianco fino a tre annunci: canone,
          metri, prezzo al m² e affinità, con il migliore segnato riga per riga.
        </p>
        <Button asChild className="mt-5">
          <Link to="/">Vai agli annunci</Link>
        </Button>
      </div>
    )
  }

  const cols = desk ? `11rem repeat(${rows.length}, minmax(14rem, 1fr))` : `repeat(${rows.length}, minmax(0, 1fr))`
  // On the phone the row label spans every column above the values; on the desk it is the first column.
  const phoneRowHead = 'col-span-full px-3 pt-2.5 pb-0'
  const cell = cn('min-w-0', desk ? 'border-l border-hair px-4' : 'px-3 [&:nth-child(n+3)]:border-l [&:nth-child(n+3)]:border-hair')
  return (
    <div className="h-full overflow-auto">
      <div className="px-4 py-5 lg:px-8 lg:py-8">
        <div className="flex items-baseline gap-2">
          <h1 className="text-2xl font-bold">Confronto</h1>
          <span className="text-sm text-ink-3">{rows.length} di 3</span>
          {rows.length < 3 ? (
            <Link to="/" className="ml-auto text-sm font-semibold text-ink-2 hover:text-ink hover:underline">
              Aggiungi dagli annunci
            </Link>
          ) : null}
        </div>

        <div className={cn('mt-5 rounded-sm border border-ink bg-sheet', desk && 'min-w-fit')} role="table" aria-label="Confronto annunci">
          <div className="grid border-b border-ink" style={{ gridTemplateColumns: cols }} role="row">
            {desk ? <div role="columnheader" className="p-4" /> : null}
            {rows.map((l, i) => {
              const t = splitTitle(l.title)
              return (
                <div
                  key={l.id}
                  role="columnheader"
                  className={cn('relative min-w-0 p-3', (desk || i > 0) && 'border-l border-hair', !desk && 'p-2.5')}
                >
                  <button
                    type="button"
                    onClick={() => remove(l.id)}
                    className={cn(
                      'absolute z-10 flex size-7 items-center justify-center rounded-sm bg-sheet/90 text-ink-2 hover:text-ink',
                      // A 44px reach around the small mark on touch screens.
                      'after:absolute after:-inset-2',
                      desk ? 'top-4 right-4' : 'top-3.5 right-3.5',
                    )}
                    aria-label={`Togli dal confronto: ${t.headline}`}
                  >
                    <X className="size-4" />
                  </button>
                  <Thumb src={l.thumbnail} size="m-c" className="aspect-[16/10] w-full rounded-[2px]" />
                  <Link
                    to={`/annunci/${l.id}`}
                    className={cn('mt-2.5 block leading-snug font-semibold hover:underline', desk ? 'text-sm' : 'text-xs break-words')}
                  >
                    {t.typology ? <span className="font-normal text-ink-3">{t.typology} · </span> : null}
                    {t.street}
                  </Link>
                  <p className="truncate text-xs text-ink-3" title={t.place || l.city || undefined}>
                    {t.place || l.city}
                  </p>
                  <a
                    href={l.url}
                    target="_blank"
                    rel="noreferrer"
                    aria-label={desk ? undefined : `Apri sul portale: ${t.headline}`}
                    className={cn(
                      'inline-flex items-center gap-1 text-xs font-semibold text-ink-2 hover:text-ink',
                      desk ? 'mt-1' : 'mt-1.5 min-h-8 rounded-sm border border-hair-strong px-2',
                    )}
                  >
                    {desk ? 'Apri sul portale' : 'Portale'} <ExternalLink className="size-3" aria-hidden />
                  </a>
                </div>
              )
            })}
          </div>

          <div className="grid border-b border-hair" style={{ gridTemplateColumns: cols }} role="row">
            <div role="rowheader" className={cn('label-caps text-ink', desk ? 'p-4' : phoneRowHead)}>
              Affinità
            </div>
            {rows.map((l) => {
              const best = bestIds(rows, (x) => (scored(x) ? x.ai_score : null), 'max').has(l.id)
              return (
                <div key={l.id} role="cell" className={cn(cell, desk ? 'py-4' : 'py-2.5')}>
                  <Ladder listing={l} size="sm" className="max-w-52" />
                  <p className="mt-2 text-sm font-semibold">
                    {scored(l) ? verdictLabel(l.ai_verdict) : 'Non valutato'}
                    {best ? <BestMark /> : null}
                  </p>
                  {scored(l) && l.ai_reason ? <Reason text={l.ai_reason} clamp={!desk && rows.length > 1} /> : null}
                </div>
              )
            })}
          </div>

          {ROWS.map((r) => {
            const best = r.value && r.best ? bestIds(rows, r.value, r.best) : new Set<number>()
            return (
              <div key={r.label} className="grid border-b border-hair last:border-b-0" style={{ gridTemplateColumns: cols }} role="row">
                <div role="rowheader" className={cn(desk ? 'px-4 py-2.5 text-sm text-ink-3' : cn('label-caps', phoneRowHead))}>
                  {r.label}
                </div>
                {rows.map((l) => (
                  <div key={l.id} role="cell" className={cn('tnum py-2.5 text-sm', cell, best.has(l.id) && 'bg-[#f1f3ec]')}>
                    {r.render(l)}
                    {best.has(l.id) ? <BestMark /> : null}
                  </div>
                ))}
              </div>
            )
          })}

          <div className="grid border-t border-ink" style={{ gridTemplateColumns: cols }} role="row">
            <div role="rowheader" className={cn('label-caps text-ink', desk ? 'p-4' : phoneRowHead)}>
              Stato
            </div>
            {rows.map((l) => (
              <div key={l.id} role="cell" className={cn(cell, desk ? 'px-3 py-3' : 'py-2.5')}>
                <TriageButtons
                  listing={l}
                  variant="labels"
                  name={listingName(l)}
                  className={cn(
                    '[&_kbd]:hidden [&_button]:px-1 [&_button]:text-xs',
                    // Narrow columns: the three toggles stack, each a full-width 44px row.
                    !desk && 'grid-cols-1 [&>button]:h-11 [&>button]:border-l-0 [&>button+button]:border-t',
                  )}
                />
                {l.triage_note ? <p className="mt-2 text-xs text-ink-2">“{l.triage_note}”</p> : null}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
