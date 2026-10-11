/** Shared motion vocabulary: the certificate's easings and the reduced-motion check for JS-driven animation. */

export const EASE_OUT_EXPO = 'cubic-bezier(0.16, 1, 0.3, 1)'
/** A deliberate travel with a visible start and landing: used when a score changes in place. */
export const EASE_TRAVEL = 'cubic-bezier(0.65, 0, 0.35, 1)'

export function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

// Triage stamps thump in only when the owner just pressed them, not when a feed renders.
const triagedAt = new Map<number, number>()
export const markTriaged = (id: number) => triagedAt.set(id, Date.now())
export const wasJustTriaged = (id: number) => Date.now() - (triagedAt.get(id) ?? 0) < 1200
