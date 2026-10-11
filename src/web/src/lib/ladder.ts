import type { Listing } from './types'

/** Ten rungs, best first, like the APE label's A4 → G. */
export const RUNGS = Array.from({ length: 10 }, (_, i) => {
  const floor = 90 - i * 10
  return {
    index: i,
    floor,
    label: i === 0 ? '90–100' : `${floor}–${floor + 9}`,
    color: `var(--r-${i})`,
    // White labels only where they clear 4.5:1; ink elsewhere.
    ink: i <= 1 || i === 9 ? '#ffffff' : 'var(--ink)',
  }
})

export const ENERGY_CLASSES = ['A4', 'A3', 'A2', 'A1', 'B', 'C', 'D', 'E', 'F', 'G'] as const

export function rungOf(score: number): number {
  return Math.min(9, Math.max(0, 9 - Math.floor(score / 10)))
}

/** A listing only sits on the ladder when the AI actually scored it. */
export function scored(l: Pick<Listing, 'ai_score' | 'ai_status'>): l is { ai_score: number; ai_status: 'ok' } {
  return l.ai_status === 'ok' && l.ai_score != null
}

/** Parse "B", "A3", "A", "Classe A+", "classe energetica: g" into a ladder index. */
export function energyIndex(raw: string | null | undefined): { index: number; label: string } | null {
  if (!raw) return null
  // Not \b: a "+" is not a word character, so "A+" never ended a \b match.
  const m = raw.toUpperCase().match(/(?:^|[^A-Z0-9])(A[1-4]|A\+{1,4}|[A-G])(?![A-Z0-9+])/)
  if (!m) return null
  const v = m[1]
  if (/^A[1-4]$/.test(v)) return { index: 4 - Number(v[1]), label: v }
  if (v.startsWith('A+')) return { index: Math.max(0, 3 - (v.length - 1)), label: v }
  // The old single "A" class sits on the A1 rung.
  if (v === 'A') return { index: 3, label: v }
  const idx = ENERGY_CLASSES.indexOf(v as (typeof ENERGY_CLASSES)[number])
  return idx >= 0 ? { index: idx, label: v } : null
}

const VERDICTS: Record<string, string> = {
  'strong match': 'Corrispondenza forte',
  'excellent match': 'Corrispondenza eccellente',
  'good match': 'Buona corrispondenza',
  'potential': 'Da valutare',
  'weak match': 'Corrispondenza debole',
  'poor match': 'Poco adatto',
  'skip': 'Da scartare',
  'error': 'Valutazione fallita',
}

export function verdictLabel(v: string | null | undefined): string | null {
  if (!v) return null
  return VERDICTS[v.trim().toLowerCase()] ?? v
}
