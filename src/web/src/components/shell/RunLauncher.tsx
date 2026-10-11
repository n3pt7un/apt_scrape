import { Play, Plus } from 'lucide-react'
import { useRef, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { confirmRun, useCostPerListing } from '@/lib/cost'
import { relative, slugLabel } from '@/lib/format'
import { isActive, useConfigs, useJobs, useRunConfig } from '@/lib/queries'
import type { SearchConfig } from '@/lib/types'
import { cn } from '@/lib/utils'

/** Pick a search and start it now. Used from the rail, the feed and the runs page. */
export function RunLauncher({
  trigger,
  align = 'end',
  side,
}: {
  trigger?: ReactNode
  align?: 'start' | 'center' | 'end'
  side?: 'top' | 'right' | 'bottom' | 'left'
}) {
  const [open, setOpen] = useState(false)
  const { data: configs, isLoading } = useConfigs()
  const { data: jobs } = useJobs()
  const run = useRunConfig()
  const navigate = useNavigate()
  const perListing = useCostPerListing()

  const runningFor = new Set((jobs ?? []).filter(isActive).map((j) => j.config_id))
  const triggerRef = useRef<HTMLButtonElement>(null)
  // Set when a search was picked: the confirm takes focus, and the closing popover must not take it back.
  const picked = useRef(false)

  // A run reads the portal and pays the AI: picking a search asks first, in the certificate's own dialog.
  const start = async (c: SearchConfig) => {
    picked.current = true
    // Focus rests on the trigger, so the confirm hands it back there when it closes.
    triggerRef.current?.focus({ preventScroll: true })
    setOpen(false)
    const ok = await confirmRun({
      configName: c.name,
      lastRunAt: c.last_job?.started_at,
      perListing,
      expectedListings: c.last_job?.listing_count,
      aiEnabled: c.auto_analyse,
    })
    if (!ok) return
    // Awaited rather than mutate() callbacks: those reach only a mounted launcher, and the owner may
    // have moved on while the confirm was open.
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

  return (
    <Popover
      open={open}
      onOpenChange={(o) => {
        if (o) picked.current = false
        setOpen(o)
      }}
    >
      <PopoverTrigger asChild ref={triggerRef}>
        {trigger ?? (
          <Button size="sm">
            <Play className="size-3.5 fill-current" /> Avvia run
          </Button>
        )}
      </PopoverTrigger>
      <PopoverContent
        align={align}
        side={side}
        className="w-80 p-0"
        // Closed by picking a search, the popover leaves focus with the confirm instead of pulling it
        // back to the trigger behind the modal (where Enter would reopen the launcher).
        onCloseAutoFocus={(e) => {
          if (picked.current) e.preventDefault()
        }}
      >
        <div className="rule-b px-3 py-2.5">
          <p className="text-sm font-semibold">Avvia una ricerca adesso</p>
          <p className="text-xs text-ink-3">Rilegge il portale; l’AI valuta solo gli annunci nuovi, cambiati o senza punteggio.</p>
        </div>
        <ul className="max-h-72 overflow-y-auto py-1">
          {isLoading ? <li className="px-3 py-2 text-sm text-ink-3">Carico le ricerche…</li> : null}
          {configs?.length === 0 ? (
            <li className="px-3 py-3 text-sm text-ink-2">Nessuna ricerca salvata.</li>
          ) : null}
          {configs?.map((c) => {
            const busy = runningFor.has(c.id)
            return (
              <li key={c.id}>
                <button
                  type="button"
                  disabled={busy || run.isPending}
                  onClick={() => void start(c)}
                  className={cn(
                    'group flex w-full items-center gap-3 px-3 py-2 text-left transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60',
                  )}
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold">{c.name}</span>
                    <span className="block truncate text-xs text-ink-3">
                      {slugLabel(c.site_id)} · {c.city}
                      {c.last_job ? ` · ultima ${relative(c.last_job.started_at)}` : ' · mai avviata'}
                    </span>
                  </span>
                  {busy ? (
                    <span className="label-caps text-ink-2">In corso</span>
                  ) : (
                    <Play className="size-3.5 text-ink-3 transition-colors group-hover:text-ink" />
                  )}
                </button>
              </li>
            )
          })}
        </ul>
        <div className="border-t border-hair p-1">
          <button
            type="button"
            onClick={() => {
              setOpen(false)
              navigate('/ricerche/nuova')
            }}
            className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm text-ink-2 hover:bg-accent hover:text-ink"
          >
            <Plus className="size-3.5" /> Nuova ricerca
          </button>
        </div>
      </PopoverContent>
    </Popover>
  )
}
