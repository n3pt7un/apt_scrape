import { animate } from 'motion/react'
import { useLayoutEffect, useRef, useState } from 'react'
import { RUNGS, rungOf, scored, verdictLabel } from '@/lib/ladder'
import { EASE_OUT_EXPO, EASE_TRAVEL, prefersReducedMotion } from '@/lib/motion'
import type { Listing } from '@/lib/types'
import { cn } from '@/lib/utils'

const ROW = { md: 20, sm: 13 }
const GAP = { md: 3, sm: 2 }

/**
 * How the pointer reaches its rung:
 * - print: the certificate is printed (first look, or a first score): bars wipe on, the pointer
 *   drops from the top rung down to where the listing landed.
 * - rescore: same listing, new score: the pointer travels from the old rung, counting.
 * - slide: another listing (j/k): a quick 220ms slide.
 */
type Arrival = { sig: string; mode: 'print' | 'rescore' | 'slide'; from: number | null; fromScore: number | null }

function useArrival(id: number | undefined, ok: boolean, score: number | null): Arrival {
  const sig = `${id ?? ''}|${ok}|${score ?? ''}`
  const last = useRef<{ arrival: Arrival; id: number | undefined; ok: boolean; score: number | null } | null>(null)
  if (last.current?.arrival.sig !== sig) {
    const prev = last.current
    let mode: Arrival['mode'] = 'slide'
    if (ok && (!prev || !prev.ok)) mode = 'print'
    else if (ok && prev && prev.id === id && prev.score !== score) mode = 'rescore'
    last.current = {
      id,
      ok,
      score,
      arrival: { sig, mode, from: prev?.ok && prev.score != null ? rungOf(prev.score) : null, fromScore: prev?.score ?? null },
    }
  }
  return last.current.arrival
}

/**
 * The full APE-style ladder, printed at full strength like the real label.
 * Bars lengthen from best to worst; the black pointer on the right slides to
 * the rung this listing landed on, and a dotted leader ties the two together.
 */
export function Ladder({
  listing,
  size = 'md',
  className,
}: {
  listing: Pick<Listing, 'ai_score' | 'ai_status' | 'ai_verdict'> & { id?: number }
  size?: 'md' | 'sm'
  className?: string
}) {
  const ok = scored(listing)
  const rung = ok ? rungOf(listing.ai_score!) : null
  const row = ROW[size]
  const gap = GAP[size]
  const sm = size === 'sm'
  const arrival = useArrival(listing.id, ok, ok ? listing.ai_score : null)
  const pointerRef = useRef<HTMLSpanElement>(null)
  const [counting, setCounting] = useState<number | null>(null)

  // Timings for this arrival; the leader draws in as the pointer lands.
  const still = typeof window !== 'undefined' && prefersReducedMotion()
  const travel =
    arrival.mode === 'print' ? 340 + (rung ?? 0) * 42 : arrival.mode === 'rescore' ? 760 : 220
  const delay = arrival.mode === 'print' ? 170 : 0
  const landAt = still ? 0 : delay + travel * (arrival.mode === 'slide' ? 0.5 : 0.9)

  useLayoutEffect(() => {
    const el = pointerRef.current
    if (!el || rung == null || still || arrival.mode === 'slide') return
    const step = row + gap
    const to = `translateY(${rung * step}px)`
    if (arrival.mode === 'print') {
      const a = el.animate(
        [
          { transform: 'translateY(0px)', opacity: 0 },
          { transform: 'translateY(0px)', opacity: 1, offset: 0.12 },
          { transform: to, opacity: 1 },
        ],
        { duration: travel, delay, easing: EASE_OUT_EXPO, fill: 'backwards' },
      )
      return () => a.cancel()
    }
    // rescore: travel from the old rung and count the old score into the new one
    const fromRung = arrival.from ?? 0
    const a = el.animate([{ transform: `translateY(${fromRung * step}px)` }, { transform: to }], {
      duration: travel,
      easing: EASE_TRAVEL,
    })
    const from = arrival.fromScore ?? listing.ai_score!
    const c = animate(from, listing.ai_score!, {
      duration: travel / 1000,
      ease: [0.65, 0, 0.35, 1],
      onUpdate: (v) => setCounting(Math.round(v)),
      onComplete: () => setCounting(null),
    })
    return () => {
      a.cancel()
      c.stop()
      setCounting(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [arrival.sig])

  return (
    <div
      className={cn('relative grid', sm ? 'grid-cols-[1fr_2.75rem]' : 'grid-cols-[1fr_4.25rem]', className)}
      role="img"
      aria-label={
        ok
          ? `Affinità con i tuoi criteri: ${listing.ai_score} su 100, ${verdictLabel(listing.ai_verdict) ?? ''}`
          : 'Affinità non valutata'
      }
    >
      <ol className="flex flex-col" style={{ gap }}>
        {RUNGS.map((r) => {
          const here = r.index === rung
          return (
            <li
              key={r.index}
              className={cn('flex items-center', arrival.mode === 'print' && ok && 'ape-print')}
              style={{ height: row, animationDelay: `${r.index * 24}ms` }}
            >
              <span
                className={cn(
                  'chevron tnum flex h-full shrink-0 items-center',
                  // The compact rows still print their floors at the 11px label floor.
                  sm ? 'pl-1 text-2xs leading-none [--tip:0.35rem]' : 'pl-2 text-2xs [--tip:0.6rem]',
                  here ? 'font-bold' : 'font-semibold',
                  !ok && 'hatch text-ink-2',
                )}
                style={{
                  // The compact ladder starts its best rung wider so its floor label clears the tip in narrow columns.
                  width: sm ? `${48 + r.index * (52 / 9)}%` : `${38 + r.index * (62 / 9)}%`,
                  ...(ok ? { background: r.color, color: r.ink } : {}),
                }}
              >
                {sm ? r.floor : r.label}
              </span>
              {here ? (
                <span
                  key={arrival.sig}
                  className="ape-leader mx-1 h-0 flex-1 border-t border-dotted border-ink"
                  style={{ animationDelay: `${landAt}ms` }}
                  aria-hidden
                />
              ) : null}
            </li>
          )
        })}
      </ol>
      <div className="relative">
        {ok ? (
          <span
            ref={pointerRef}
            className={cn(
              'chevron-left tnum absolute inset-x-0 flex items-center justify-end bg-ink font-bold text-white',
              arrival.mode === 'slide' && 'transition-transform duration-[220ms] ease-out-expo',
              sm ? 'pr-1.5 text-xs [--tip:0.4rem]' : 'pr-2.5 text-base [--tip:0.7rem]',
            )}
            style={{
              height: row + (sm ? 2 : 6),
              top: sm ? -1 : -3,
              transform: `translateY(${rung! * (row + gap)}px)`,
            }}
          >
            {counting ?? listing.ai_score}
          </span>
        ) : (
          <span
            className={cn(
              'absolute inset-x-0 top-0 flex items-center justify-center border border-dashed border-ink-3 bg-sheet font-bold text-ink-2',
              sm ? 'h-4 text-2xs leading-none' : 'h-7 text-xs',
            )}
          >
            N.D.
          </span>
        )}
      </div>
    </div>
  )
}

/**
 * The same ladder as a filter: a chain of chevrons; pick the lowest rung you still want.
 * `fill`: below 768px the chain stretches across its row, so each rung is as wide a target as the
 * phone allows (the chevron is the target: its clip-path is also its hit area).
 */
export function LadderFilter({
  minRung,
  onChange,
  includeUnscored,
  onIncludeUnscoredChange,
  counts,
  fill = false,
}: {
  minRung: number | null
  onChange: (rung: number | null) => void
  includeUnscored: boolean
  onIncludeUnscoredChange: (v: boolean) => void
  counts: number[]
  fill?: boolean
}) {
  // Rungs switch on/off in a quick cascade spreading from the one you picked,
  // so "this rung and everything better" reads as one gesture.
  const anchor = useRef(minRung)
  if (minRung != null) anchor.current = minRung
  return (
    <div className={cn('flex items-center', fill && 'max-md:w-full')} role="group" aria-label="Affinità minima">
      {RUNGS.map((r) => {
        const on = minRung == null || r.index <= minRung
        return (
          <button
            key={r.index}
            type="button"
            aria-pressed={minRung != null && r.index <= minRung}
            aria-label={`Affinità da ${r.floor} in su, ${counts[r.index] ?? 0} annunci in questa fascia`}
            title={`Da ${r.floor} in su · ${counts[r.index] ?? 0} annunci in questa fascia`}
            onClick={() => onChange(minRung === r.index ? null : r.index)}
            className={cn(
              'tnum relative -mr-[5px] flex h-9 w-[1.875rem] shrink-0 items-center justify-center pl-1.5 text-[0.6875rem] font-bold transition-[background-color,color] duration-150 [--tip:6px] md:h-7',
              fill && 'max-md:w-auto max-md:grow max-md:basis-[1.875rem]',
              '[clip-path:polygon(0_0,calc(100%-var(--tip))_0,100%_50%,calc(100%-var(--tip))_100%,0_100%,var(--tip)_50%)] first:[clip-path:polygon(0_0,calc(100%-var(--tip))_0,100%_50%,calc(100%-var(--tip))_100%,0_100%)] first:pl-0',
              // The clip-path cuts an outline away: focus is drawn inside the chevron instead.
              'focus-visible:outline-none focus-visible:[box-shadow:inset_0_0_0_2px_var(--sheet),inset_0_0_0_4px_var(--ink)]',
            )}
            style={{
              transitionDelay: `${Math.abs(r.index - (anchor.current ?? r.index)) * 16}ms`,
              zIndex: 20 - r.index,
              background: on ? r.color : `color-mix(in srgb, ${r.color} 22%, var(--sheet))`,
              color: on ? r.ink : 'var(--ink-2)',
            }}
          >
            {r.floor}
          </button>
        )
      })}
      <button
        type="button"
        aria-pressed={includeUnscored}
        title="Includi gli annunci non valutati dall’AI"
        aria-label="Includi gli annunci non valutati dall’AI"
        onClick={() => onIncludeUnscoredChange(!includeUnscored)}
        className={cn(
          'ml-3 flex h-9 shrink-0 items-center rounded-sm border px-1.5 text-[0.6875rem] font-bold transition-colors md:h-7',
          fill && 'max-md:min-w-9 max-md:justify-center',
          includeUnscored ? 'hatch border-ink-3 text-ink' : 'border-dashed border-hair-strong bg-sheet text-ink-3 line-through',
        )}
      >
        N.D.
      </button>
    </div>
  )
}
