import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { CircleMarker as LeafletCircleMarker, Map as LeafletMap } from 'leaflet'
import { ExternalLink, MapPinned } from 'lucide-react'
import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { CircleMarker, MapContainer, Popup, TileLayer, useMap } from 'react-leaflet'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { ScoreChevron } from '@/components/ape/Chevron'
import { LadderFilter } from '@/components/ape/Ladder'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { eur, num, splitTitle } from '@/lib/format'
import { RUNGS, rungOf, scored } from '@/lib/ladder'
import { keys, useListings } from '@/lib/queries'
import type { Listing } from '@/lib/types'
import { MilhouseLoader } from '@/components/milhouse/Glasses'
import { cn } from '@/lib/utils'
import { useFeed, useFeedFilters } from '../listings/filters'
import { Thumb } from '../listings/ListingTable'

const BOLOGNA: [number, number] = [44.4949, 11.3426]

// Rung colours read once from the stylesheet (Leaflet paths need real colours, not var()); filled on first use.
const rungFill: string[] = []
function rungColour(index: number): string {
  if (!rungFill[index]) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(`--r-${index}`).trim()
    if (!v) return '#888'
    rungFill[index] = v
  }
  return rungFill[index]
}

/** Pin diameter follows the score on a fixed ramp: the best listings are the biggest dots. */
function pinStyle(l: Pick<Listing, 'ai_score' | 'ai_status'>, selected: boolean) {
  if (!scored(l))
    return { radius: 5, color: '#686a64', weight: 1.5, dashArray: '2 2', fillColor: '#d6d8d2', fillOpacity: 0.9 }
  const r = RUNGS[rungOf(l.ai_score)]
  const fill = rungColour(r.index)
  return {
    radius: 5 + (l.ai_score / 100) * 9,
    color: selected ? '#1d1d1b' : '#ffffff',
    weight: selected ? 3 : 1.5,
    fillColor: fill,
    fillOpacity: 0.95,
  }
}

function FitBounds({ points }: { points: [number, number][] }) {
  const map = useMap()
  const done = useRef(false)
  useEffect(() => {
    if (done.current || points.length === 0) return
    done.current = true
    if (points.length === 1) map.setView(points[0], 15)
    else map.fitBounds(points, { padding: [40, 40], maxZoom: 15 })
  }, [points, map])
  return null
}

function GeocodeBar({ missing }: { missing: number }) {
  const qc = useQueryClient()
  const { data: status } = useQuery({
    queryKey: keys.geocode,
    queryFn: api.geocodeStatus,
    refetchInterval: (q) => (q.state.data?.running ? 2000 : false),
  })
  const wasRunning = useRef(false)
  // While geocoding, the feed is refetched to place new pins at most every 10 s or every 10 addresses,
  // not on every 2 s status poll (each refetch reloads every listing).
  const lastRefresh = useRef({ at: 0, done: 0 })
  useEffect(() => {
    if (status?.running) {
      const now = Date.now()
      if (!wasRunning.current) lastRefresh.current = { at: now, done: status.done }
      wasRunning.current = true
      if (now - lastRefresh.current.at >= 10_000 || status.done - lastRefresh.current.done >= 10) {
        lastRefresh.current = { at: now, done: status.done }
        qc.invalidateQueries({ queryKey: keys.listings })
      }
    } else if (wasRunning.current) {
      wasRunning.current = false
      qc.invalidateQueries({ queryKey: keys.listings })
      toast.success('Localizzazione completata', {
        description: status?.failed ? `${status.failed} indirizzi non trovati` : undefined,
      })
    }
  }, [status, qc])

  const start = async (retry = false) => {
    try {
      const s = await api.geocode(retry)
      qc.setQueryData(keys.geocode, s)
    } catch (e) {
      toast.error('Localizzazione non avviata', { description: (e as Error).message })
    }
  }

  if (status?.running) {
    const total = status.pending + status.done + status.failed
    const pct = total ? ((status.done + status.failed) / total) * 100 : 0
    return (
      <div className="border-b border-hair px-4 py-3">
        <MilhouseLoader size="sm" lines={['Milhouse cerca gli indirizzi su OpenStreetMap…', 'Uno al secondo, con pazienza…']} />
        <div className="mt-2 h-1.5 bg-sheet-2">
          <div className="h-full bg-ink transition-[width] duration-500" style={{ width: `${pct}%` }} />
        </div>
        <p className="tnum mt-1 text-xs text-ink-3">
          {status.done} trovati · {status.failed} non trovati · {status.pending} in coda · un indirizzo al secondo
        </p>
      </div>
    )
  }
  if (!missing && !status?.failed) return null
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-hair px-4 py-3">
      <p className="min-w-0 flex-1 text-sm text-ink-2">
        {missing ? (
          <>
            <span className="tnum font-semibold text-ink">{missing}</span> annunci non sono ancora sulla mappa.
          </>
        ) : (
          <>
            <span className="tnum font-semibold text-ink">{status?.failed}</span> indirizzi non trovati.
          </>
        )}
      </p>
      {missing ? (
        <Button size="sm" onClick={() => start(false)}>
          <MapPinned className="size-3.5" /> Localizza
        </Button>
      ) : (
        <Button size="sm" variant="outline" onClick={() => start(true)}>
          Riprova
        </Button>
      )}
    </div>
  )
}

/**
 * One pin. Memoized, with its style, centre and handlers kept stable, so a feed refetch or a new
 * selection does not make react-leaflet restyle and move every marker on the map.
 */
const PinMarker = memo(function PinMarker({
  l,
  selected,
  onSelect,
  register,
}: {
  l: Listing
  selected: boolean
  onSelect: (id: number) => void
  register: (id: number, m: LeafletCircleMarker | null) => void
}) {
  const t = splitTitle(l.title)
  const style = useMemo(() => pinStyle({ ai_score: l.ai_score, ai_status: l.ai_status }, selected), [l.ai_score, l.ai_status, selected])
  const center = useMemo<[number, number]>(() => [l.lat!, l.lon!], [l.lat, l.lon])
  const handlers = useMemo(() => ({ click: () => onSelect(l.id) }), [l.id, onSelect])
  const ref = useCallback((m: LeafletCircleMarker | null) => register(l.id, m), [l.id, register])
  return (
    <CircleMarker center={center} pathOptions={style} radius={style.radius} ref={ref} eventHandlers={handlers}>
      <Popup>
        <div className="font-sans text-ink">
          <Thumb src={l.thumbnail} size="m-c" className="aspect-[16/9] w-full rounded-t-[3px]" />
          <div className="p-3">
            <div className="flex items-start gap-2">
              <p className="flex-1 text-sm leading-snug font-semibold">{t.headline}</p>
              <ScoreChevron listing={l} size="sm" withTooltip={false} />
            </div>
            <p className="tnum mt-1 text-sm">
              <b>{eur(l.price_eur)}</b> · {num(l.sqm_num)} m² {l.rooms_num ? `· ${l.rooms_num} locali` : ''}
            </p>
            <div className="mt-2.5 flex gap-1.5">
              <Link
                to={`/annunci/${l.id}`}
                className="flex h-7 flex-1 items-center justify-center rounded-sm bg-ink text-xs font-semibold !text-white"
              >
                Apri la scheda
              </Link>
              <a
                href={l.url}
                target="_blank"
                rel="noreferrer"
                className="flex h-7 items-center gap-1 rounded-sm border border-hair-strong px-2 text-xs font-semibold !text-ink"
              >
                Portale <ExternalLink className="size-3" />
              </a>
            </div>
          </div>
        </div>
      </Popup>
    </CircleMarker>
  )
})

export function MapPage() {
  const { data: listings } = useListings()
  const [filters, setFilters] = useFeedFilters()
  const [showOut, setShowOut] = useState(false)
  const { rows, rungCounts } = useFeed(listings, { ...filters, tab: 'tutti' })
  const [selected, setSelected] = useState<number | null>(null)
  const mapRef = useRef<LeafletMap | null>(null)
  const markers = useRef<Record<number, LeafletCircleMarker | null>>({})
  const register = useCallback((id: number, m: LeafletCircleMarker | null) => {
    markers.current[id] = m
  }, [])

  const visible = useMemo(() => rows.filter((l) => showOut || l.triage_status !== 'scartato'), [rows, showOut])
  const placed = visible.filter((l) => l.lat != null && l.lon != null)
  const missing = (listings ?? []).filter((l) => l.lat == null && l.geocode_status !== 'failed').length
  const points = useMemo(() => placed.map((l) => [l.lat!, l.lon!] as [number, number]), [placed])

  const focus = (l: Listing) => {
    setSelected(l.id)
    if (l.lat == null || !mapRef.current) return
    mapRef.current.flyTo([l.lat, l.lon!], Math.max(mapRef.current.getZoom(), 15), { duration: 0.6 })
    setTimeout(() => markers.current[l.id]?.openPopup(), 650)
  }

  return (
    <div className="flex h-[calc(100dvh-6.5rem)] flex-col-reverse md:h-full lg:flex-row">
      <aside className="flex max-h-[45%] min-h-0 flex-col border-t border-hair bg-sheet lg:max-h-none lg:w-[24rem] lg:border-t-0 lg:border-r">
        <div className="border-b border-hair px-4 py-3">
          <div className="flex items-baseline gap-2">
            <h1 className="text-xl font-bold">Mappa</h1>
            <span className="tnum text-sm text-ink-3">
              {placed.length} su {visible.length}
            </span>
          </div>
          <div className="mt-2.5 flex flex-wrap items-center gap-3">
            <LadderFilter
              minRung={filters.minRung}
              onChange={(r) => setFilters({ minRung: r })}
              includeUnscored={filters.nd}
              onIncludeUnscoredChange={(v) => setFilters({ nd: v })}
              counts={rungCounts}
            />
            <label className="flex items-center gap-1.5 text-xs text-ink-2">
              <input type="checkbox" checked={showOut} onChange={(e) => setShowOut(e.target.checked)} className="accent-ink" />
              Mostra scartati
            </label>
          </div>
        </div>
        <GeocodeBar missing={missing} />
        <ul className="min-h-0 flex-1 overflow-y-auto">
          {visible.map((l) => {
            const t = splitTitle(l.title)
            const on = l.lat != null
            return (
              <li key={l.id}>
                <button
                  type="button"
                  onClick={() => focus(l)}
                  className={cn(
                    'flex w-full items-center gap-3 border-b border-hair px-4 py-2 text-left transition-colors',
                    selected === l.id ? 'bg-[#eef0ea]' : 'hover:bg-sheet-2',
                    !on && 'opacity-60',
                  )}
                >
                  <ScoreChevron listing={l} size="sm" withTooltip={false} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold">{t.headline}</span>
                    <span className="block truncate text-xs text-ink-3">
                      {on ? t.place || l.city : l.geocode_status === 'failed' ? 'Indirizzo non trovato' : 'Non ancora localizzato'}
                    </span>
                  </span>
                  <span className="tnum text-sm font-semibold">{eur(l.price_eur)}</span>
                </button>
              </li>
            )
          })}
        </ul>
      </aside>
      <div className="relative min-h-0 flex-1">
        <MapContainer
          center={BOLOGNA}
          zoom={13}
          className="size-full"
          ref={(m) => {
            mapRef.current = m
          }}
          zoomControl
        >
          <TileLayer
            url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            maxZoom={19}
            className="map-tiles"
          />
          <FitBounds points={points} />
          {[...placed]
            .sort((a, b) => (a.ai_score ?? -1) - (b.ai_score ?? -1))
            .map((l) => (
              <PinMarker key={l.id} l={l} selected={selected === l.id} onSelect={setSelected} register={register} />
            ))}
        </MapContainer>
        {placed.length === 0 ? (
          <div className="pointer-events-none absolute inset-x-0 top-3 z-[500] flex justify-center pr-3 pl-14 sm:top-6 sm:px-4">
            <p className="rounded-sm border border-hair-strong bg-sheet px-4 py-2.5 text-sm shadow-[0_6px_20px_-8px_rgb(29_29_27/0.3)]">
              Nessun annuncio localizzato. Usa <b>Localizza</b> per cercare gli indirizzi su OpenStreetMap.
            </p>
          </div>
        ) : null}
        <div className="pointer-events-none absolute right-3 bottom-6 z-[500] rounded-sm border border-hair-strong bg-sheet/95 px-3 py-2 text-2xs text-ink-2">
          <p className="label-caps mb-1 text-ink">Affinità</p>
          <div className="flex items-end gap-1.5">
            {[90, 70, 50, 30, 10].map((s) => (
              <span key={s} className="flex flex-col items-center gap-0.5">
                <span
                  className="rounded-full border border-white"
                  style={{ width: (5 + (s / 100) * 9) * 2, height: (5 + (s / 100) * 9) * 2, background: RUNGS[rungOf(s)].color }}
                />
                <span className="tnum">{s}</span>
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
