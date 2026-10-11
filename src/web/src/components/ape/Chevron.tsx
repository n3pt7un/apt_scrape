import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { energyIndex, RUNGS, rungOf, scored, verdictLabel } from '@/lib/ladder'
import type { Listing } from '@/lib/types'
import { explainAiError } from '@/lib/aiErrors'
import { cn } from '@/lib/utils'

type ScoreSource = Pick<Listing, 'ai_score' | 'ai_status' | 'ai_verdict' | 'ai_reason'>

const SIZES = {
  sm: 'h-5 min-w-10 pl-1.5 pr-3 text-xs [--tip:0.45rem]',
  md: 'h-6 min-w-12 pl-2 pr-3.5 text-sm [--tip:0.55rem]',
  lg: 'h-9 min-w-18 pl-3 pr-5 text-xl [--tip:0.8rem]',
}

/** The match score as a ladder chevron; N.D. hatching when the AI never scored it. */
export function ScoreChevron({
  listing,
  size = 'md',
  className,
  withTooltip = true,
}: {
  listing: ScoreSource
  size?: keyof typeof SIZES
  className?: string
  withTooltip?: boolean
}) {
  const ok = scored(listing)
  const rung = ok ? RUNGS[rungOf(listing.ai_score!)] : null
  const chip = (
    <span
      className={cn(
        'chevron tnum inline-flex shrink-0 items-center font-bold leading-none',
        SIZES[size],
        !ok && 'hatch text-ink-3',
        className,
      )}
      style={rung ? { background: rung.color, color: rung.ink } : undefined}
      aria-label={ok ? `Affinità ${listing.ai_score} su 100` : 'Non valutato'}
    >
      {ok ? listing.ai_score : 'N.D.'}
    </span>
  )
  if (!withTooltip) return chip
  const tip = ok
    ? verdictLabel(listing.ai_verdict)
    : listing.ai_status === 'error'
      ? explainAiError(listing.ai_reason).title
      : 'Milhouse non l’ha ancora letto'
  return (
    <Tooltip>
      <TooltipTrigger asChild>{chip}</TooltipTrigger>
      <TooltipContent side="left" className="max-w-72">
        <p className="font-semibold">{tip}</p>
        {!ok && listing.ai_status === 'error' ? <p className="mt-0.5 opacity-80">{explainAiError(listing.ai_reason).fix}</p> : null}
      </TooltipContent>
    </Tooltip>
  )
}

/** The listing's real APE class, letter-labelled so it never reads as a score. */
export function EnergyChevron({ value, className }: { value: string | null | undefined; className?: string }) {
  const e = energyIndex(value)
  // Text that is not a class ("In attesa di certificazione") is still worth reading.
  if (!e && value?.trim())
    return (
      <span className={cn('block truncate text-ink-2', className)} title={value}>
        {value}
      </span>
    )
  if (!e) return <span className={cn('text-ink-3', className)}>—</span>
  const r = RUNGS[e.index]
  return (
    <span className={cn('inline-flex items-center gap-1.5', className)}>
      <span
        className="chevron inline-flex h-5 min-w-9 items-center pr-3 pl-1.5 text-xs font-bold [--tip:0.45rem]"
        style={{ background: r.color, color: r.ink }}
      >
        {e.label}
      </span>
      <span className="label-caps">APE</span>
    </span>
  )
}
