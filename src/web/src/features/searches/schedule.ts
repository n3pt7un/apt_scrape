export const DAYS = [
  { id: 'mon', short: 'Lun', long: 'lunedì' },
  { id: 'tue', short: 'Mar', long: 'martedì' },
  { id: 'wed', short: 'Mer', long: 'mercoledì' },
  { id: 'thu', short: 'Gio', long: 'giovedì' },
  { id: 'fri', short: 'Ven', long: 'venerdì' },
  { id: 'sat', short: 'Sab', long: 'sabato' },
  { id: 'sun', short: 'Dom', long: 'domenica' },
]

/** Schedules are stored as HH:MM in UTC; show them in the browser's zone. */
export function utcToLocal(hhmm: string): string {
  const [h, m] = hhmm.split(':').map(Number)
  const d = new Date()
  d.setUTCHours(h, m, 0, 0)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

export function localToUtc(hhmm: string): string {
  const [h, m] = hhmm.split(':').map(Number)
  const d = new Date()
  d.setHours(h, m, 0, 0)
  return `${String(d.getUTCHours()).padStart(2, '0')}:${String(d.getUTCMinutes()).padStart(2, '0')}`
}

export function scheduleLabel(days: string[], timeUtc: string): string {
  if (!days.length) return 'Solo a mano'
  const names =
    days.length === 7
      ? 'Ogni giorno'
      : DAYS.filter((d) => days.includes(d.id))
          .map((d) => d.short)
          .join(' ')
  return `${names} · ${utcToLocal(timeUtc)}`
}
