import { useEffect, useId, useState } from 'react'
import { cn } from '@/lib/utils'

/**
 * Milhouse's thick round glasses: the product's mark and the AI's face.
 * `ladder` fills the lenses with the APE rungs (the app's mark);
 * `animate` plays the push-up-the-glasses gesture with a glint across the lenses.
 */
export function Glasses({
  className,
  ladder = false,
  animate = false,
  rim = 'currentColor',
}: {
  className?: string
  ladder?: boolean
  animate?: boolean
  rim?: string
}) {
  const id = useId().replace(/:/g, '')
  return (
    <svg
      viewBox="0 0 64 30"
      className={cn('shrink-0 overflow-visible', animate && 'mh-push', className)}
      aria-hidden
    >
      <defs>
        <clipPath id={`l-${id}`}>
          <circle cx="16" cy="16" r="10.5" />
          <circle cx="48" cy="16" r="10.5" />
        </clipPath>
      </defs>
      <g clipPath={`url(#l-${id})`}>
        {ladder ? (
          <>
            <rect x="0" y="0" width="64" height="11" fill="var(--r-0)" />
            <rect x="0" y="11" width="64" height="5" fill="var(--r-3)" />
            <rect x="0" y="16" width="64" height="5" fill="var(--r-5)" />
            <rect x="0" y="21" width="64" height="9" fill="var(--r-9)" />
          </>
        ) : (
          <rect x="0" y="0" width="64" height="30" fill="var(--mh-lens)" />
        )}
        {animate ? <rect className="mh-glint" x="-30" y="-10" width="9" height="50" fill="#fff" opacity="0.85" /> : null}
      </g>
      <g fill="none" stroke={rim} strokeWidth="4.5" strokeLinecap="round">
        <circle cx="16" cy="16" r="10.5" />
        <circle cx="48" cy="16" r="10.5" />
        <path d="M26.5 13.5 Q32 9.5 37.5 13.5" />
        <path d="M5.5 12 L1.5 9.5" />
        <path d="M58.5 12 L62.5 9.5" />
      </g>
    </svg>
  )
}

const DEFAULT_LINES = [
  'Milhouse si sistema gli occhiali…',
  'Milhouse sta leggendo con attenzione…',
  'Milhouse ricontrolla due volte…',
]

/** The loading state: glasses pushed up, and a line that changes while you wait. */
export function MilhouseLoader({
  lines = DEFAULT_LINES,
  className,
  size = 'md',
}: {
  lines?: string[]
  className?: string
  size?: 'sm' | 'md' | 'lg'
}) {
  const [i, setI] = useState(0)
  useEffect(() => {
    if (lines.length < 2) return
    const t = setInterval(() => setI((n) => (n + 1) % lines.length), 1900)
    return () => clearInterval(t)
  }, [lines.length])
  return (
    <div className={cn('flex items-center gap-3', size === 'lg' && 'flex-col gap-4 text-center', className)} role="status" aria-live="polite">
      <Glasses animate className={cn('text-ink', size === 'sm' ? 'w-8' : size === 'md' ? 'w-11' : 'w-24')} />
      <span key={i} className={cn('mh-line text-ink-2', size === 'lg' ? 'text-base' : 'text-sm')}>
        {lines[i % lines.length]}
      </span>
    </div>
  )
}

/** Small avatar used to sign Milhouse's answers. */
export function MilhouseAvatar({ className }: { className?: string }) {
  return (
    <span className={cn('inline-flex size-7 shrink-0 items-center justify-center rounded-full bg-[var(--mh)]', className)} aria-hidden>
      <Glasses className="w-5 text-ink" />
    </span>
  )
}
