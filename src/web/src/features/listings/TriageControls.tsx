import { useState } from 'react'
import { Ban, Phone, Star } from 'lucide-react'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { wasJustTriaged } from '@/lib/motion'
import { useTriage } from '@/lib/queries'
import type { Listing, TriageStatus } from '@/lib/types'
import { cn } from '@/lib/utils'

export const TRIAGE: { id: TriageStatus; label: string; icon: typeof Star; key: string }[] = [
  { id: 'preferito', label: 'Preferito', icon: Star, key: 'p' },
  { id: 'contattato', label: 'Contattato', icon: Phone, key: 'c' },
  { id: 'scartato', label: 'Scartato', icon: Ban, key: 'x' },
]

/**
 * Three toggles; pressing the active one clears it. `name` (the listing's street or zone) goes into
 * every button's accessible name, so a screen reader hears "Preferito: via Mincio 6" and not the
 * same three words on every row.
 */
export function TriageButtons({
  listing,
  variant = 'icons',
  name,
  tabbable = true,
  className,
}: {
  listing: Pick<Listing, 'id' | 'triage_status'>
  variant?: 'icons' | 'labels'
  name?: string
  /** False takes the toggles out of the tab order (feed rows other than the open one). */
  tabbable?: boolean
  className?: string
}) {
  const triage = useTriage()
  const set = (s: TriageStatus) =>
    triage.mutate({ id: listing.id, status: listing.triage_status === s ? null : s })
  const label = (t: (typeof TRIAGE)[number]) => (name ? `${t.label}: ${name}` : undefined)
  const group = name ? `Stato di ${name}` : 'Stato'

  if (variant === 'labels') {
    return (
      <div className={cn('grid grid-cols-3 rounded-sm border border-hair-strong', className)} role="group" aria-label={group}>
        {TRIAGE.map((t) => {
          const on = listing.triage_status === t.id
          return (
            <button
              key={t.id}
              type="button"
              aria-pressed={on}
              aria-label={label(t)}
              tabIndex={tabbable ? undefined : -1}
              onClick={() => set(t.id)}
              className={cn(
                'flex h-9 items-center justify-center gap-1.5 border-l border-hair-strong text-sm font-semibold transition-colors first:border-l-0',
                on ? 'bg-ink text-white' : 'text-ink-2 hover:bg-accent hover:text-ink',
              )}
            >
              <t.icon
                key={String(on)}
                className={cn('size-3.5', on && t.id === 'preferito' && 'fill-current', on && wasJustTriaged(listing.id) && 'icon-pop')}
              />
              {t.label}
              <kbd className={cn('ml-0.5 hidden font-sans text-2xs font-semibold opacity-50 lg:inline')}>{t.key.toUpperCase()}</kbd>
            </button>
          )
        })}
      </div>
    )
  }

  return (
    <div className={cn('flex items-center', className)} role="group" aria-label={group}>
      {TRIAGE.map((t) => {
        const on = listing.triage_status === t.id
        return (
          <Tooltip key={t.id}>
            <TooltipTrigger asChild>
              <button
                type="button"
                aria-pressed={on}
                aria-label={label(t) ?? t.label}
                tabIndex={tabbable ? undefined : -1}
                onClick={(e) => {
                  e.stopPropagation()
                  set(t.id)
                }}
                className={cn(
                  'flex size-7 items-center justify-center rounded-sm transition-colors',
                  on ? 'text-ink' : 'text-ink-3 hover:bg-accent hover:text-ink',
                )}
              >
                <t.icon
                  key={String(on)}
                  className={cn('size-3.5', on && t.id === 'preferito' && 'fill-current', on && wasJustTriaged(listing.id) && 'icon-pop')}
                  strokeWidth={on ? 2.5 : 2}
                />
              </button>
            </TooltipTrigger>
            <TooltipContent>
              {t.label} <kbd className="ml-1 opacity-60">{t.key.toUpperCase()}</kbd>
            </TooltipContent>
          </Tooltip>
        )
      })}
    </div>
  )
}

export function TriageStamp({ id, status }: { id?: number; status: TriageStatus | null }) {
  if (!status) return null
  // Keyed by status so a new stamp is a new imprint.
  return <Stamp key={status} id={id} status={status} />
}

function Stamp({ id, status }: { id?: number; status: TriageStatus }) {
  const [fresh] = useState(() => id != null && wasJustTriaged(id))
  const t = TRIAGE.find((x) => x.id === status)!
  return (
    <span
      className={cn(
        'inline-flex h-4 items-center gap-1 rounded-[2px] px-1 text-2xs leading-4 font-bold tracking-[0.05em] uppercase',
        status === 'scartato' ? 'border border-ink-3 text-ink-3' : 'bg-ink text-white',
        fresh && 'stamp-in',
      )}
    >
      <t.icon className={cn('size-2.5', status === 'preferito' && 'fill-current')} strokeWidth={2.5} />
      {t.label}
    </span>
  )
}
