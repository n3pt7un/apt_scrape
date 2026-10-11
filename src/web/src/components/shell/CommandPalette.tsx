import { defaultFilter } from 'cmdk'
import { Activity, Columns3, FileText, Map, Play, Plus, Rows3, SlidersHorizontal } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { ScoreChevron } from '@/components/ape/Chevron'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from '@/components/ui/command'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { confirmRun, useCostPerListing } from '@/lib/cost'
import { eur, relative, splitTitle } from '@/lib/format'
import { isActive, useConfigs, useJobs, useListings, useRunConfig } from '@/lib/queries'
import type { SearchConfig } from '@/lib/types'

const PAGES = [
  { to: '/', label: 'Annunci', icon: Rows3 },
  { to: '/mappa', label: 'Mappa', icon: Map },
  { to: '/confronta', label: 'Confronta', icon: Columns3 },
  { to: '/ricerche', label: 'Ricerche', icon: SlidersHorizontal },
  { to: '/run', label: 'Run', icon: Activity },
  { to: '/preferenze', label: 'Criteri di valutazione', icon: FileText },
]

/**
 * A paid run is never one Enter away. Its items only appear when the query asks for them (it starts with
 * "avvia" or "run") or when the list is browsed with an empty query, they rank below every other match,
 * the palette never highlights one on its own, and choosing one still asks for confirmation.
 */
const RUN = 'avvia run '
const isRun = (value: string) => value.startsWith(RUN)
/** A query that names a run ("avvia", "avvia bologna", "run"): it is looking for a search, not a listing. */
const runQuery = (q: string) => {
  const t = q.trim().toLowerCase()
  return t.startsWith('avvia') || t.startsWith('run')
}
const asksForRun = (q: string) => q.trim() === '' || runQuery(q)
const filter = (value: string, search: string, keywords?: string[]) => {
  const score = defaultFilter(value, search, keywords)
  return isRun(value) ? score * 0.001 : score
}
const NAV_KEYS = new Set(['ArrowDown', 'ArrowUp', 'Home', 'End', 'PageDown', 'PageUp'])

export function CommandPalette() {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === 'k' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        setOpen((o) => !o)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="overflow-hidden p-0" showCloseButton={false}>
        <DialogHeader className="sr-only">
          <DialogTitle>Cerca e comanda</DialogTitle>
          <DialogDescription>Annunci, ricerche, sezioni</DialogDescription>
        </DialogHeader>
        {/* Mounted with every opening: no query and no highlight carry over from the last time. */}
        <PaletteBody onClose={() => setOpen(false)} />
      </DialogContent>
    </Dialog>
  )
}

function PaletteBody({ onClose }: { onClose: () => void }) {
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState('')
  // Whether the owner moved the highlight since the query last changed (keys or pointer).
  const moved = useRef(false)
  const none = useRef(0)
  const navigate = useNavigate()
  const { data: listings } = useListings()
  const { data: configs } = useConfigs()
  const { data: jobs } = useJobs()
  const run = useRunConfig()
  const perListing = useCostPerListing()
  const running = new Set((jobs ?? []).filter(isActive).map((j) => j.config_id))

  const go = (to: string) => {
    onClose()
    navigate(to)
  }

  const launch = async (c: SearchConfig) => {
    onClose()
    const ok = await confirmRun({
      configName: c.name,
      lastRunAt: c.last_job?.started_at,
      perListing,
      expectedListings: c.last_job?.listing_count,
      aiEnabled: c.auto_analyse,
    })
    if (!ok) return
    // The palette has closed (this body unmounted) by the time the owner confirms, and callbacks passed
    // to mutate() only reach a mounted observer: await the run itself, so the toast always comes.
    try {
      const { job_id } = await run.mutateAsync(c.id)
      toast.success(`Run avviata: ${c.name}`, {
        description: 'Segui l’avanzamento in tempo reale.',
        action: { label: 'Segui', onClick: () => navigate(`/run/${job_id}`) },
      })
    } catch (e) {
      toast.error('Run non avviata', { description: (e as Error).message })
    }
  }

  const showRuns = !!configs?.length && asksForRun(search)
  // "avvia…" or "run…" asks for a search: listings would only bury the runs under loose letter
  // matches (a·v·v·i·a fits every "via"), so the Annunci group steps aside.
  const showListings = !!listings?.length && !runQuery(search)

  return (
    <Command
      filter={filter}
      value={selected}
      onValueChange={(v) => {
        // The palette highlights the first match by itself: never when that match would start a run.
        if (isRun(v) && !moved.current) setSelected(`nessuna-${++none.current}`)
        else setSelected(v)
      }}
      onKeyDown={(e) => {
        if (NAV_KEYS.has(e.key) || (e.ctrlKey && 'jknp'.includes(e.key))) moved.current = true
      }}
      className="**:data-[slot=command-input-wrapper]:h-12 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground [&_[cmdk-group]]:px-2 [&_[cmdk-group]:not([hidden])_~[cmdk-group]]:pt-0 [&_[cmdk-input-wrapper]_svg]:h-5 [&_[cmdk-input-wrapper]_svg]:w-5 [&_[cmdk-input]]:h-12 [&_[cmdk-item]]:px-2 [&_[cmdk-item]]:py-3 [&_[cmdk-item]_svg]:h-5 [&_[cmdk-item]_svg]:w-5"
    >
      <CommandInput
        value={search}
        onValueChange={(q) => {
          moved.current = false
          setSearch(q)
        }}
        placeholder="Cerca un annuncio, una via, una ricerca…"
      />
      <CommandList className="max-h-[min(60vh,28rem)]" onPointerMoveCapture={() => (moved.current = true)}>
        <CommandEmpty>Nessun risultato.</CommandEmpty>
        <CommandGroup heading="Vai a">
          {PAGES.map((p) => (
            <CommandItem key={p.to} value={`vai ${p.label}`} onSelect={() => go(p.to)}>
              <p.icon /> {p.label}
            </CommandItem>
          ))}
          <CommandItem value="nuova ricerca crea" onSelect={() => go('/ricerche/nuova')}>
            <Plus /> Nuova ricerca
          </CommandItem>
        </CommandGroup>
        {showListings ? (
          <>
            <CommandSeparator />
            <CommandGroup heading="Annunci">
              {listings!.slice(0, 400).map((l) => {
                const t = splitTitle(l.title)
                return (
                  <CommandItem
                    key={l.id}
                    value={`${l.id} ${l.title} ${l.address ?? ''}`}
                    onSelect={() => go(`/annunci/${l.id}`)}
                    className="gap-3"
                  >
                    <ScoreChevron listing={l} size="sm" withTooltip={false} />
                    <span className="min-w-0 flex-1 truncate">
                      {t.typology ? <span className="text-ink-3">{t.typology} · </span> : null}
                      {t.street}
                    </span>
                    <span className="tnum text-xs text-ink-3">{eur(l.price_eur)}</span>
                  </CommandItem>
                )
              })}
            </CommandGroup>
          </>
        ) : null}
        {showRuns ? (
          <>
            <CommandSeparator />
            {/* Last on purpose: a run reads the portal and pays the AI. */}
            <CommandGroup heading="Avvia run · chiede conferma">
              {configs!.map((c) => {
                const busy = running.has(c.id)
                return (
                  <CommandItem
                    key={c.id}
                    value={`${RUN}${c.id} ${c.name} ${c.city}`}
                    disabled={busy}
                    onSelect={() => void launch(c)}
                  >
                    <Play />
                    <span className="min-w-0 flex-1 truncate">{c.name}</span>
                    <span className="text-xs text-ink-3">
                      {busy ? 'in corso' : c.last_job ? `ultima ${relative(c.last_job.started_at)}` : 'mai avviata'}
                    </span>
                  </CommandItem>
                )
              })}
            </CommandGroup>
          </>
        ) : null}
      </CommandList>
    </Command>
  )
}
