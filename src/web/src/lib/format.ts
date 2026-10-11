// Italian skips grouping on four-digit numbers by default; prices read better as 1.100.
const eurFmt = new Intl.NumberFormat('it-IT', { maximumFractionDigits: 0, useGrouping: 'always' })
const dec1 = new Intl.NumberFormat('it-IT', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
const rtf = new Intl.RelativeTimeFormat('it', { numeric: 'auto' })
const timeFmt = new Intl.DateTimeFormat('it-IT', { hour: '2-digit', minute: '2-digit' })
const dayFmt = new Intl.DateTimeFormat('it-IT', { day: 'numeric', month: 'short' })
const fullFmt = new Intl.DateTimeFormat('it-IT', {
  day: 'numeric',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
})

export const eur = (n: number | null | undefined) => (n == null ? '—' : `€ ${eurFmt.format(n)}`)
export const num = (n: number | null | undefined) => (n == null ? '—' : eurFmt.format(n))
export const eurSqm = (n: number | null | undefined) => (n == null ? '—' : `€ ${dec1.format(n)}`)
export const usd = (n: number | null | undefined) =>
  n == null ? '—' : `$ ${new Intl.NumberFormat('it-IT', { maximumFractionDigits: 4 }).format(n)}`

/** Backend datetimes are naive UTC ("2026-10-04T12:25:28"); read them as UTC. */
export function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null
  const hasZone = /[zZ]|[+-]\d\d:?\d\d$/.test(value)
  const d = new Date(hasZone ? value : `${value.replace(' ', 'T')}Z`)
  return Number.isNaN(d.getTime()) ? null : d
}

export function relative(value: string | null | undefined): string {
  const d = parseDate(value)
  if (!d) return '—'
  const diffSec = (d.getTime() - Date.now()) / 1000
  const abs = Math.abs(diffSec)
  if (abs < 45) return diffSec < 0 ? 'adesso' : 'tra poco'
  if (abs < 3600) return rtf.format(Math.round(diffSec / 60), 'minute')
  if (abs < 86400) return rtf.format(Math.round(diffSec / 3600), 'hour')
  if (abs < 86400 * 7) return rtf.format(Math.round(diffSec / 86400), 'day')
  return dayFmt.format(d)
}

export const clock = (value: string | null | undefined) => {
  const d = parseDate(value)
  return d ? timeFmt.format(d) : '—'
}

export const fullDate = (value: string | null | undefined) => {
  const d = parseDate(value)
  return d ? fullFmt.format(d) : '—'
}

export function duration(sec: number | null | undefined): string {
  if (sec == null) return '—'
  if (sec < 60) return `${Math.round(sec)} s`
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  if (m < 60) return s ? `${m} min ${s} s` : `${m} min`
  return `${Math.floor(m / 60)} h ${m % 60} min`
}

const TYPOLOGIES = [
  'Monolocale',
  'Bilocale',
  'Trilocale',
  'Quadrilocale',
  'Pentalocale',
  'Plurilocale',
  'Appartamento',
  'Attico',
  'Mansarda',
  'Loft',
  'Open space',
  'Villa',
  'Villetta',
  'Casa indipendente',
  'Casa semindipendente',
  'Rustico',
]

const STREET_RE =
  /^(via|viale|v\.le|piazza|p\.za|piazzale|piazzetta|corso|strada|stradello|vicolo|vico|largo|borgo|galleria|lungo\w*|contrada|località|loc\.|salita|traversa|circonvallazione|quartiere|frazione)\b/i
// \b cannot close after "²" (not a word character), so sizes are matched on their own.
const DESCRIPTOR_RE = /\d\s*m²|\bmq\b|\b(piano|locali|stato|nuovo|ristrutturat\w*|arredat\w*)\b/i

/**
 * "Bilocale via Nosadella 34, Saragozza, Bologna" → typology, street, place.
 * Portals without an address write "Trilocale ottimo stato, primo piano, Marconi, Bologna":
 * then `isAddress` is false and descriptors are kept out of the place.
 */
export function splitTitle(title: string): {
  typology: string | null
  street: string
  place: string
  isAddress: boolean
  headline: string
} {
  let rest = title.trim()
  let typology: string | null = null
  for (const t of TYPOLOGIES) {
    if (rest.toLowerCase().startsWith(t.toLowerCase() + ' ')) {
      typology = t
      rest = rest.slice(t.length).trim()
      break
    }
  }
  const [first, ...others] = rest.split(',').map((s) => s.trim()).filter(Boolean)
  let street = first || title
  // "via Massarenti, 352, …": the house number comes as its own segment; put it back on the street.
  if (others.length && /^\d+[a-z]?(\/\d+[a-z]?)?$/i.test(others[0])) street = `${street} ${others.shift()}`
  // A size like "43 m²" holds a digit but is not an address.
  const isAddress = STREET_RE.test(street) || (/\d/.test(street) && !DESCRIPTOR_RE.test(street))
  const place = others.filter((p) => !DESCRIPTOR_RE.test(p)).join(', ')
  const headline = isAddress ? street : [typology, street].filter(Boolean).join(' · ')
  return { typology, street, place, isAddress, headline }
}

/** Where the listing is: the portal's zone and city from the title, else the search's city. */
export function zoneOf(t: ReturnType<typeof splitTitle>, l: { city: string }): string {
  return t.place || capitalize(l.city)
}

/**
 * The listing as a screen reader names it on its triage buttons: the street, or, with no address,
 * the typology and the zone ("Bilocale 43 m², Massarenti").
 */
export function listingName(l: { title: string; city: string }): string {
  const t = splitTitle(l.title)
  if (t.isAddress) return t.street
  const head = [t.typology, t.street].filter(Boolean).join(' ')
  return [head, zoneOf(t, l).split(',')[0].trim()].filter(Boolean).join(', ')
}

/** A photo of the flat: not missing, and not the portal's own "no photo" drawing (immo_placeholder.svg). */
export const realPhoto = (url: string | null | undefined): url is string => !!url && !/placeholder/i.test(url)

/** Immobiliare's CDN serves several sizes for the same image id. The portal's placeholder counts as no photo. */
export function imageVariant(url: string | null | undefined, size: 'xs-c' | 'm-c' | 'l-c' | 'xl-c'): string | null {
  if (!realPhoto(url)) return null
  if (url.includes('im-cdn.it/image/')) return url.replace(/\/[a-z-]+\.jpg$/, `/${size}.jpg`)
  return url
}

export const capitalize = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s)

/** "murri-massarenti" → "Murri Massarenti" */
export const slugLabel = (s: string | null | undefined) =>
  (s ?? '')
    .split(/[-_]/)
    .filter(Boolean)
    .map(capitalize)
    .join(' ')
