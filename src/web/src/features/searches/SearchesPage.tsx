import { useQueryClient } from '@tanstack/react-query'
import { MoreHorizontal, Pencil, Play, Plus, Trash2 } from 'lucide-react'
import { Link, useNavigate } from 'react-router'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { api } from '@/lib/api'
import { confirmRun, useCostPerListing } from '@/lib/cost'
import { eur, relative, slugLabel } from '@/lib/format'
import { isActive, keys, useConfigs, useJobs, useRunConfig } from '@/lib/queries'
import type { SearchConfig } from '@/lib/types'
import { RunStatus } from '../runs/RunsPage'
import { scheduleLabel } from './schedule'
import { confirmAction } from '@/components/shell/ConfirmHost'

export function filtersLabel(cfg: SearchConfig): string {
  const c = { ...cfg, min_price: cfg.min_price || null }
  const parts: string[] = []
  if (c.min_price != null || c.max_price != null) {
    parts.push(
      c.min_price != null && c.max_price != null
        ? `${eur(c.min_price)}–${eur(c.max_price).replace('€ ', '')}`
        : c.max_price != null
          ? `fino a ${eur(c.max_price)}`
          : `da ${eur(c.min_price)}`,
    )
  }
  if (c.min_sqm != null) parts.push(`≥ ${c.min_sqm} m²`)
  if (c.min_rooms != null) parts.push(`≥ ${c.min_rooms} locali`)
  return parts.join(' · ') || 'Nessun filtro'
}

export function whereLabel(c: SearchConfig): string {
  const areas = (c.area ?? '')
    .split(',')
    .map((a) => a.trim())
    .filter(Boolean)
  const city = slugLabel(c.city)
  if (!areas.length) return city
  return `${city}: ${areas.slice(0, 3).map(slugLabel).join(', ')}${areas.length > 3 ? ` +${areas.length - 3}` : ''}`
}

export function SearchesPage() {
  const { data: configs, isLoading, error } = useConfigs()
  const { data: jobs } = useJobs()
  const run = useRunConfig()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const running = new Set((jobs ?? []).filter(isActive).map((j) => j.config_id))
  const perListing = useCostPerListing()

  const toggle = async (c: SearchConfig) => {
    try {
      await api.toggleConfig(c.id)
      qc.invalidateQueries({ queryKey: keys.configs })
    } catch (e) {
      toast.error('Modifica non salvata', { description: (e as Error).message })
    }
  }
  const remove = async (c: SearchConfig) => {
    const ok = await confirmAction({
      title: `Eliminare la ricerca “${c.name}”?`,
      body: 'Non partirà più, né a mano né pianificata. Gli annunci che ha già trovato restano nel feed.',
      confirmLabel: 'Elimina ricerca',
      destructive: true,
    })
    if (!ok) return
    try {
      await api.deleteConfig(c.id)
      qc.invalidateQueries({ queryKey: keys.configs })
      toast.success('Ricerca eliminata')
    } catch (e) {
      toast.error('Eliminazione non riuscita', { description: (e as Error).message })
    }
  }
  const start = async (c: SearchConfig) => {
    const ok = await confirmRun({
      configName: c.name,
      lastRunAt: c.last_job?.started_at,
      perListing,
      expectedListings: c.last_job?.listing_count,
      aiEnabled: c.auto_analyse,
    })
    if (!ok) return
    run.mutate(c.id, {
      onSuccess: ({ job_id }) => {
        toast.success(`Run avviata: ${c.name}`)
        navigate(`/run/${job_id}`)
      },
      onError: (e) => toast.error('Run non avviata', { description: (e as Error).message }),
    })
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl px-4 py-5 lg:px-8 lg:py-8">
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <h1 className="text-2xl font-bold">Ricerche</h1>
            <p className="mt-0.5 text-sm text-ink-2">Dove cercare, con quali filtri e quando. Ogni ricerca produce run e annunci.</p>
          </div>
          <Button asChild className="ml-auto">
            <Link to="/ricerche/nuova">
              <Plus className="size-4" /> Nuova ricerca
            </Link>
          </Button>
        </div>

        <div className="mt-6 overflow-hidden rounded-sm border border-hair bg-sheet">
          {error ? <p className="p-5 text-sm text-destructive">{(error as Error).message}</p> : null}
          {isLoading ? (
            <div className="space-y-2 p-4">
              <Skeleton className="h-14 w-full" />
              <Skeleton className="h-14 w-full" />
            </div>
          ) : null}
          {configs?.length === 0 ? (
            <div className="px-6 py-16 text-center">
              <p className="text-lg font-semibold">Nessuna ricerca</p>
              <p className="mx-auto mt-1 max-w-md text-sm text-ink-2">
                Una ricerca dice al sistema quale portale leggere, in quale città e zone, con quali filtri e in quali
                giorni. Creane una per iniziare a ricevere annunci.
              </p>
              <Button asChild className="mt-5">
                <Link to="/ricerche/nuova">
                  <Plus className="size-4" /> Crea la prima ricerca
                </Link>
              </Button>
            </div>
          ) : null}
          {configs?.length ? (
            <table className="w-full border-separate border-spacing-0 text-sm">
              <thead className="hidden md:table-header-group">
                <tr>
                  {['Ricerca', 'Filtri', 'Pianificazione', 'Ultima run', 'Annunci', 'Attiva', ''].map((h, i) => (
                    <th
                      key={i}
                      className={`label-caps h-9 border-b border-ink/80 px-4 text-left font-semibold ${i === 4 ? 'text-right' : ''}`}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {configs.map((c) => (
                  <tr key={c.id} className="group flex flex-col gap-1 border-b border-hair px-4 py-3 md:table-row md:p-0">
                    <td className="md:rule-b md:px-4 md:py-3">
                      <Link to={`/ricerche/${c.id}`} className="font-semibold hover:underline">
                        {c.name}
                      </Link>
                      <p className="text-xs text-ink-3">
                        {slugLabel(c.site_id)} · {c.operation} · {c.property_type.split(',').join(', ')} · {whereLabel(c)}
                      </p>
                    </td>
                    <td className="tnum text-ink-2 md:rule-b md:px-4">{filtersLabel(c)}</td>
                    <td className="md:rule-b md:px-4">
                      <p className="tnum text-ink-2">{scheduleLabel(c.schedule_days, c.schedule_time)}</p>
                      {c.enabled && c.next_run_at ? (
                        <p className="text-xs whitespace-nowrap text-ink-3">prossima {relative(c.next_run_at)}</p>
                      ) : null}
                    </td>
                    <td className="md:rule-b md:px-4">
                      {running.has(c.id) ? (
                        <RunStatus status="running" />
                      ) : c.last_job ? (
                        <Link to={`/run/${c.last_job.id}`} className="flex items-center gap-2">
                          <RunStatus status={c.last_job.status} />
                          <span className="text-xs whitespace-nowrap text-ink-3">{relative(c.last_job.started_at)}</span>
                        </Link>
                      ) : (
                        <span className="text-xs text-ink-3">Mai avviata</span>
                      )}
                    </td>
                    <td className="tnum md:rule-b md:px-4 md:text-right">
                      <Link to={`/?ricerca=${c.id}`} className="font-semibold hover:underline">
                        {c.listing_count ?? 0}
                        <span className="font-normal text-ink-3 md:hidden"> annunci</span>
                      </Link>
                    </td>
                    <td className="md:rule-b md:px-4">
                      <label className="flex items-center gap-2">
                        <Switch checked={c.enabled} onCheckedChange={() => toggle(c)} aria-label={`Pianificazione attiva: ${c.name}`} />
                        <span className="text-xs text-ink-3 md:hidden">{c.enabled ? 'Attiva' : 'In pausa'}</span>
                      </label>
                    </td>
                    <td className="md:rule-b md:px-3">
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={running.has(c.id) || run.isPending}
                          onClick={() => void start(c)}
                        >
                          <Play className="size-3 fill-current" /> Avvia
                        </Button>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button variant="ghost" size="icon" className="size-8" aria-label="Altre azioni">
                              <MoreHorizontal className="size-4" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem onSelect={() => navigate(`/ricerche/${c.id}`)}>
                              <Pencil /> Modifica
                            </DropdownMenuItem>
                            <DropdownMenuItem onSelect={() => navigate(`/ricerche/nuova?da=${c.id}`)}>
                              <Plus /> Duplica
                            </DropdownMenuItem>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem variant="destructive" onSelect={() => remove(c)}>
                              <Trash2 /> Elimina
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </div>
        <p className="mt-3 text-xs text-ink-3">
          Gli orari sono mostrati nel tuo fuso; il server li salva in UTC.
        </p>
      </div>
    </div>
  )
}
