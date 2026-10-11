import { X } from 'lucide-react'
import { useLayoutEffect, useState } from 'react'
import { ScoreChevron } from '@/components/ape/Chevron'
import { MilhouseAvatar } from '@/components/milhouse/Glasses'
import { parseDate, relative, splitTitle } from '@/lib/format'
import type { Listing } from '@/lib/types'
import { aiCount, firstStamp, foundKnown, notScored, type Verbale } from '@/lib/verbale'
import { cn } from '@/lib/utils'

const stampDate = (iso: string | null) =>
  (parseDate(iso) ?? new Date()).toLocaleDateString('it-IT', { day: '2-digit', month: 'short', year: 'numeric' }).toUpperCase()

/**
 * The rubber stamp at the corner of the verbale, in the run outcome's ladder colour. A run that finished
 * without scoring its listings is not "seen": it gets the N.D. hatch, never a ladder colour.
 */
export function VerbaleStamp({ v, finishedAt, className }: { v: Verbale; finishedAt: string | null; className?: string }) {
  // Decided in an effect, not during render: StrictMode renders twice, and the first look must win.
  const [thump, setThump] = useState(false)
  useLayoutEffect(() => {
    if (firstStamp(v.number)) setThump(true)
  }, [v.number])
  const failed = v.outcome === 'failed'
  const unscored = notScored(v)
  return (
    <span
      className={cn(
        'pointer-events-none inline-flex flex-col items-center rounded-[3px] border-2 border-current px-2.5 py-1 leading-none uppercase outline outline-1 outline-offset-2 outline-current select-none [rotate:-6deg]',
        unscored && 'hatch',
        thump && 'stamp-in',
        className,
      )}
      style={{ color: failed ? 'var(--r-9)' : unscored ? 'var(--ink-2)' : 'var(--r-1)' }}
      aria-hidden
    >
      <span className={cn('font-bold', unscored ? 'text-sm tracking-[0.12em]' : 'text-base tracking-[0.2em]')}>
        {failed ? 'Interrotta' : unscored ? 'Non valutati' : 'Visto'}
      </span>
      <span className="tnum mt-1 text-2xs leading-none font-semibold tracking-[0.1em]">
        {stampDate(finishedAt)} · N.{v.number}
      </span>
    </span>
  )
}

function BestLine({ best, onOpen }: { best: Listing; onOpen?: (id: number) => void }) {
  const t = splitTitle(best.title)
  const name = t.isAddress ? t.street : t.headline
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      {onOpen ? (
        <button
          type="button"
          onClick={() => onOpen(best.id)}
          className="min-w-0 truncate font-semibold text-ink underline decoration-hair-strong underline-offset-[3px] hover:decoration-ink"
        >
          {name}
        </button>
      ) : (
        <span className="min-w-0 truncate font-semibold">{name}</span>
      )}
      <ScoreChevron listing={best} size="sm" withTooltip={false} />
    </span>
  )
}

/** The full verbale at the head of a finished run: Milhouse's report, signed and stamped. */
export function VerbaleSheet({
  v,
  finishedAt,
  onOpenBest,
  className,
}: {
  v: Verbale
  finishedAt: string | null
  onOpenBest?: (id: number) => void
  className?: string
}) {
  return (
    <section className={cn('relative border-b border-hair bg-sheet px-5 py-4', className)} aria-label={`Verbale numero ${v.number}`}>
      <div className="flex items-start gap-3 pr-[9.5rem]">
        <MilhouseAvatar />
        <div className="min-w-0">
          <p className="text-xs font-bold text-mh-ink">
            Verbale n. {v.number} <span className="font-semibold">· F.to Milhouse</span>
          </p>
          <p className="mt-1 max-w-[60ch] text-[0.9375rem] leading-snug text-ink">{v.line}</p>
        </div>
      </div>
      <dl className="mt-3 max-w-[30rem] text-sm sm:ml-10">
        {/* A run that stopped early has no count to file: the outcome row says why. */}
        {v.outcome === 'done' || v.examined ? (
        <div className="grid grid-cols-[7.5rem_1fr] sm:grid-cols-[9.5rem_1fr] items-center gap-3 border-t border-hair py-1.5">
          <dt className="text-ink-3">Annunci esaminati</dt>
          <dd className="tnum font-semibold">
            {v.examined}
            {v.examined && v.exact ? <span className="font-normal text-ink-2"> · {foundKnown(v)}</span> : null}
          </dd>
        </div>
        ) : null}
        {v.outcome === 'done' && v.ai.outcome !== 'ok' ? (
          // The AI's failure, summarised once: the count and the cause most of the failures share.
          <div className="grid grid-cols-[7.5rem_1fr] sm:grid-cols-[9.5rem_1fr] items-baseline gap-3 border-t border-hair py-1.5">
            <dt className="text-ink-3">Valutazione AI</dt>
            <dd className="min-w-0">
              <span className="tnum font-semibold">{aiCount(v.ai)}</span>
              {v.ai.cause ? <span className="text-ink"> · {v.ai.cause.title}</span> : null}
              {v.ai.cause ? <span className="mt-0.5 block text-xs leading-snug text-ink-2">{v.ai.cause.fix}</span> : null}
            </dd>
          </div>
        ) : null}
        {v.best ? (
          <div className="grid grid-cols-[7.5rem_1fr] sm:grid-cols-[9.5rem_1fr] items-center gap-3 border-t border-hair py-1.5">
            <dt className="text-ink-3">{v.moved ? 'Il migliore qui' : 'Il migliore'}</dt>
            <dd className="min-w-0">
              <BestLine best={v.best} onOpen={onOpenBest} />
            </dd>
          </div>
        ) : null}
        {/* "nessuno da 60 in su" is only a fact when at least one listing of the run has a score */}
        {v.attributed && v.best ? (
          <div className="grid grid-cols-[7.5rem_1fr] sm:grid-cols-[9.5rem_1fr] items-center gap-3 border-t border-hair py-1.5">
            <dt className="text-ink-3">{v.moved ? 'Da 60 in su, qui' : 'Da 60 in su'}</dt>
            <dd className="tnum font-semibold">{v.above60 ? v.above60 : <span className="font-normal text-ink-2">nessuno</span>}</dd>
          </div>
        ) : null}
        {v.failure ? (
          <div className="grid grid-cols-[7.5rem_1fr] sm:grid-cols-[9.5rem_1fr] items-center gap-3 border-t border-hair py-1.5">
            <dt className="text-ink-3">Esito</dt>
            <dd className="font-semibold">{v.failure}</dd>
          </div>
        ) : null}
      </dl>
      <VerbaleStamp v={v} finishedAt={finishedAt} className="absolute top-4 right-5" />
    </section>
  )
}

/** The last verbale, pinned above the feed until archived: what the run found, in one breath. */
export function VerbaleStrip({
  v,
  finishedAt,
  onOpenBest,
  onShowRun,
  onOpenLog,
  onArchive,
}: {
  v: Verbale
  finishedAt: string | null
  onOpenBest: (id: number) => void
  onShowRun?: () => void
  onOpenLog: () => void
  onArchive?: () => void
}) {
  const unscored = notScored(v)
  const showRun = onShowRun && v.outcome === 'done' && v.attributed ? onShowRun : null
  const showLabel = `Vedi ${v.attributed === 1 ? 'l’annuncio' : `i ${v.attributed}`}`
  return (
    <aside
      className="flex items-start gap-3 border-b border-hair bg-[var(--mh-lens)] px-4 py-2.5 lg:px-5"
      aria-label={`Verbale numero ${v.number} di Milhouse`}
    >
      <MilhouseAvatar className="mt-0.5" />
      <div className="min-w-0 flex-1 text-sm leading-snug">
        <p>
          <span className="font-bold text-mh-ink">Verbale n. {v.number}</span>
          <span className="text-ink-3"> · {relative(finishedAt)}</span>
          <span className="text-mh-ink"> — {v.line}</span>
        </p>
        <p className="tnum mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-ink-2">
          {v.outcome === 'failed' ? (
            <span>
              <span className="font-semibold text-ink">{v.failure}.</span>{' '}
              <button type="button" onClick={onOpenLog} className="font-semibold text-ink underline underline-offset-[3px]">
                Apri il verbale completo
              </button>
            </span>
          ) : (
            <>
              <span>
                {v.examined} {v.examined === 1 ? 'annuncio' : 'annunci'}
                {v.examined && v.exact ? `${v.found && v.known ? ':' : ','} ${foundKnown(v)}` : ''}.
                {v.fresh ? ` ${v.fresh} da guardare.` : ''}
              </span>
              {unscored ? (
                // Why the scores are missing, once for the whole run, and where the remedy is.
                <span>
                  <span className="font-semibold text-ink">
                    {aiCount(v.ai).replace(/^./, (c) => c.toUpperCase())}
                    {v.ai.cause ? `: ${v.ai.cause.title}` : ''}.
                  </span>{' '}
                  <button type="button" onClick={onOpenLog} className="font-semibold text-ink underline underline-offset-[3px]">
                    Il rimedio
                  </button>
                </span>
              ) : null}
              {v.best ? (
                <span className="inline-flex min-w-0 items-center gap-1.5">
                  Il migliore: <BestLine best={v.best} onOpen={onOpenBest} />
                </span>
              ) : null}
            </>
          )}
        </p>
        {showRun ? (
          // On the phone this is the strip's primary action, so it gets its own row and a thumb-sized target.
          <button
            type="button"
            onClick={showRun}
            className="mt-2 inline-flex h-9 items-center rounded-sm border border-mh-ink/40 bg-sheet px-3 text-sm font-semibold text-ink transition-colors hover:border-ink sm:hidden"
          >
            {showLabel}
          </button>
        ) : null}
      </div>
      {showRun ? (
        <button
          type="button"
          onClick={showRun}
          className="hidden h-8 shrink-0 items-center rounded-sm border border-mh-ink/40 bg-sheet px-2.5 text-xs font-semibold text-ink transition-colors hover:border-ink sm:inline-flex"
        >
          {showLabel}
        </button>
      ) : null}
      {onArchive ? (
        <button
          type="button"
          onClick={onArchive}
          className="flex size-8 shrink-0 items-center justify-center rounded-sm text-ink-3 transition-colors hover:bg-sheet hover:text-ink"
          aria-label="Archivia il verbale"
          title="Archivia il verbale"
        >
          <X className="size-4" />
        </button>
      ) : null}
    </aside>
  )
}
