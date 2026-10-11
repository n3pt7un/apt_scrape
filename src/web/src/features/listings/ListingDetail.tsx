import { useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Columns3, ExternalLink, House, RefreshCw, TriangleAlert } from 'lucide-react'
import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { EnergyChevron } from '@/components/ape/Chevron'
import { Ladder } from '@/components/ape/Ladder'
import { confirmAction } from '@/components/shell/ConfirmHost'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { api } from '@/lib/api'
import { useCostPerListing } from '@/lib/cost'
import { eur, eurSqm, fullDate, imageVariant, num, realPhoto, relative, splitTitle, usd } from '@/lib/format'
import { scored, verdictLabel } from '@/lib/ladder'
import { keys, useListing, usePatchListingCache, useTriage } from '@/lib/queries'
import { toggleCompare, useChat, useCompare } from '@/lib/store'
import type { DetailStatus, ListingDetail as Detail, Listing, ListingFact } from '@/lib/types'
import { MilhouseLoader } from '@/components/milhouse/Glasses'
import { explainAiError } from '@/lib/aiErrors'
import { useElementWidth } from '@/lib/useMediaQuery'
import { cn } from '@/lib/utils'
import { DevelopImg, Thumb } from './ListingTable'
import { TriageButtons } from './TriageControls'

// The chat pulls in the Markdown renderer; load it on first use.
const AiChat = lazy(() => import('./AiChat').then((m) => ({ default: m.AiChat })))

function Field({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={cn('min-w-0 px-3.5 py-3', className)}>
      <p className="label-caps">{label}</p>
      <div className="mt-0.5 whitespace-nowrap">{children}</div>
    </div>
  )
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[9.5rem_1fr] gap-3 border-b border-hair py-2 text-sm last:border-b-0">
      <dt className="text-ink-3">{label}</dt>
      {/* An empty string is a missing fact too (the portal's blank agency field). */}
      <dd className="min-w-0 text-ink">{value == null || value === '' ? <span className="text-ink-3">—</span> : value}</dd>
    </div>
  )
}

const yesNo = (v: boolean | null | undefined) => (v == null ? null : v ? 'Sì' : 'No')

/** The portal's date line ("Annuncio aggiornato il 06/10/2026") as a row: update or publication date. */
function postDateRow(text: string | null): { label: string; value: string | null } {
  if (!text) return { label: 'Pubblicato', value: null }
  const label = /aggiornat/i.test(text) ? 'Aggiornato' : 'Pubblicato'
  const value = text.replace(/^\s*(annuncio\s+)?(pubblicato|inserito|aggiornato)\s+(il\s+)?/i, '').trim()
  return { label, value: value || text }
}

/** Portal facts the certificate already prints elsewhere: the header grid and the title. */
const SHOWN_ELSEWHERE = new Set(['superficie', 'locali', 'tipologia'])

/** Why only the search page's data is on screen, by what happened to the portal's own page. */
const DETAIL_NOTE: Record<Exclude<DetailStatus, 'ok'>, string> = {
  blocked: 'Il portale ha bloccato la lettura della pagina dell’annuncio',
  error: 'La pagina dell’annuncio non si è caricata',
  empty: 'La pagina dell’annuncio è arrivata vuota',
  missing: 'La pagina dell’annuncio non è ancora stata letta',
}

/** A search-card chip ("1 bagno", "Piano R", "No Ascensore") that the portal's feature table already states. */
function chipCovered(chip: string, facts: ListingFact[]): boolean {
  const c = chip.toLowerCase()
  return facts.some((f) => {
    const label = f.label.toLowerCase()
    return c === f.value.toLowerCase() || (label.length >= 4 && c.includes(label.slice(0, -1)))
  })
}

function Gallery({ detail }: { detail: Detail }) {
  const photos = (detail.raw.detail?.photos ?? []).filter(realPhoto)
  const [i, setI] = useState(0)
  // The portal's raw "r.jpg" variant is refused by its CDN: always ask for a sized one.
  const main = imageVariant(photos[i], 'xl-c') ?? imageVariant(detail.thumbnail, 'l-c')
  if (!main)
    return (
      <div className="flex aspect-[16/9] flex-col items-center justify-center gap-1.5 bg-sheet-2 text-sm text-ink-3">
        <House className="size-6" aria-hidden />
        Nessuna foto
      </div>
    )
  return (
    <div>
      <div className="bg-sheet-2">
        <DevelopImg key={main} src={main} className="aspect-[16/9] w-full object-cover [&>svg]:size-6" />
      </div>
      {photos.length > 1 ? (
        <div className="flex gap-1 overflow-x-auto px-4 pt-2">
          {photos.map((p, idx) => (
            <button
              key={p}
              type="button"
              onClick={() => setI(idx)}
              className={cn('h-12 w-16 shrink-0 overflow-hidden rounded-[2px] ring-offset-1', idx === i && 'ring-2 ring-ink')}
            >
              <DevelopImg key={p} src={imageVariant(p, 'xs-c') ?? p} alt={`Foto ${idx + 1}`} loading="lazy" className="size-full bg-sheet-2 object-cover" />
            </button>
          ))}
        </div>
      ) : null}
    </div>
  )
}

function NoteField({ listing }: { listing: Listing }) {
  const [value, setValue] = useState(listing.triage_note ?? '')
  const triage = useTriage()
  useEffect(() => setValue(listing.triage_note ?? ''), [listing.id, listing.triage_note])
  const save = () => {
    const next = value.trim() || null
    if (next === (listing.triage_note ?? null)) return
    triage.mutate({ id: listing.id, note: next })
  }
  return (
    <label className="block">
      <span className="label-caps">La tua nota</span>
      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onBlur={save}
        rows={2}
        placeholder="Es. chiamato martedì, visita sabato ore 11"
        className="mt-1 block w-full resize-y rounded-sm border border-hair-strong bg-sheet px-3 py-2 text-sm text-ink placeholder:text-ink-3 focus:border-ink focus:outline-none"
      />
    </label>
  )
}

/** Each rescore is one paid AI call: say so, with the real average cost when the runs have recorded it. */
function confirmRescore(detail: Listing, perListing: number | null): Promise<boolean> {
  const ok = scored(detail)
  const cost = perListing ? `, circa ${usd(perListing)} (la media per annuncio delle ultime run)` : ''
  return confirmAction({
    title: ok ? 'Rivalutare questo annuncio?' : detail.ai_status === 'error' ? 'Riprovare la valutazione?' : 'Valutare questo annuncio?',
    body: ok
      ? `Milhouse lo rilegge con i criteri attuali: una chiamata all’AI${cost}. L’affinità di adesso, ${detail.ai_score}, viene sostituita dalla nuova.`
      : `Milhouse lo legge con i criteri attuali e gli dà un posto sulla scala: una chiamata all’AI${cost}.`,
    confirmLabel: ok ? 'Rivaluta' : 'Valuta adesso',
  })
}

function ScoreSection({ detail }: { detail: Listing }) {
  const qc = useQueryClient()
  const patch = usePatchListingCache()
  const perListing = useCostPerListing()
  const [busy, setBusy] = useState(false)
  const sectionRef = useRef<HTMLElement>(null)
  const width = useElementWidth(sectionRef)
  // Ladder beside the verdict when the pane is wide; otherwise the full ladder stacked above it.
  // Only a pane narrower than any phone falls back to the compact ladder (0 = not measured yet).
  const beside = width >= 560
  const compact = width > 0 && width < 260
  const ok = scored(detail)
  const rescore = async () => {
    if (!(await confirmRescore(detail, perListing))) return
    setBusy(true)
    try {
      const updated = await api.rescore(detail.id)
      patch(updated)
      qc.invalidateQueries({ queryKey: keys.listing(detail.id) })
      if (updated.ai_status === 'ok') toast.success(`Nuova valutazione: ${updated.ai_score}`)
      else toast.error('Valutazione ancora fallita', { description: updated.ai_reason ?? undefined })
    } catch (e) {
      toast.error('Rivalutazione non riuscita', { description: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }
  return (
    <section ref={sectionRef} className={cn('grid gap-4 px-5 py-5', beside && 'grid-cols-[minmax(0,15rem)_1fr] gap-5')}>
      <Ladder listing={detail} size={compact ? 'sm' : 'md'} className={beside ? 'max-w-72' : 'w-full max-w-[22rem]'} />
      <div className="min-w-0">
        {ok ? (
          <>
            <h3 className="text-lg leading-tight font-bold sm:text-xl">{verdictLabel(detail.ai_verdict)}</h3>
            {detail.ai_reason ? <p className="mt-2 text-[0.9375rem] leading-relaxed text-ink-2">{detail.ai_reason}</p> : null}
            {detail.ai_notes ? (
              <p className="mt-3 border-t border-hair pt-3 text-sm leading-relaxed text-ink-2">
                <span className="font-semibold text-ink">Da sapere: </span>
                {detail.ai_notes}
              </p>
            ) : null}
          </>
        ) : (
          <>
            <h3 className="text-lg leading-tight font-bold sm:text-xl">
              {detail.ai_status === 'error' ? 'Valutazione fallita' : 'Non ancora valutato'}
            </h3>
            {detail.ai_status === 'error' ? (
              <>
                <p className="mt-2 text-sm leading-relaxed text-ink-2">
                  <span className="font-semibold text-ink">{explainAiError(detail.ai_reason).title}.</span>{' '}
                  {explainAiError(detail.ai_reason).fix}
                </p>
                {detail.ai_reason ? (
                  <details className="mt-2 text-xs text-ink-3">
                    <summary className="cursor-pointer select-none hover:text-ink">Dettagli tecnici</summary>
                    <p className="mt-1 font-mono text-[0.6875rem] break-all">{detail.ai_reason}</p>
                  </details>
                ) : null}
              </>
            ) : (
              <p className="mt-2 text-sm leading-relaxed text-ink-2">
                Milhouse non l’ha ancora letto: premi Valuta adesso per dargli un posto sulla scala.
              </p>
            )}
          </>
        )}
        {busy ? (
          <MilhouseLoader size="sm" className="mt-3" lines={['Milhouse rilegge l’annuncio…', 'Cerca il gradino giusto…']} />
        ) : null}
        <button
          type="button"
          onClick={rescore}
          disabled={busy}
          className={cn(
            'mt-3 inline-flex h-8 items-center gap-1.5 rounded-sm border border-hair-strong px-2.5 text-xs font-semibold text-ink-2 transition-colors hover:border-ink hover:text-ink disabled:opacity-60',
            busy && 'hidden',
          )}
        >
          <RefreshCw className="size-3.5" />
          {ok ? 'Rivaluta' : 'Valuta adesso'}
        </button>
      </div>
    </section>
  )
}

function DetailSkeleton() {
  return (
    <div className="flex flex-col gap-4 p-5">
      <Skeleton className="aspect-[16/9] w-full" />
      <Skeleton className="h-6 w-3/4" />
      <Skeleton className="h-4 w-1/2" />
      <Skeleton className="h-20 w-full" />
      <Skeleton className="h-40 w-full" />
    </div>
  )
}

export function ListingDetail({
  id,
  summary,
  onClose,
  mobile = false,
}: {
  id: number
  summary?: Listing
  onClose: () => void
  mobile?: boolean
}) {
  const { data, isLoading, error } = useListing(id)
  const compare = useCompare()
  const chat = useChat(id)
  const [tab, setTab] = useState('scheda')
  const scrollRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 0 })
  }, [id])
  // The summary in the feed cache is fresher for triage; the detail query adds raw fields.
  const d: Detail | undefined = data ? { ...data, ...(summary ?? {}) } : undefined
  const head = d ?? summary

  if (error && !head) {
    return (
      <div className="p-6 text-sm">
        <p className="font-semibold">Milhouse ha cercato ovunque, ma questo annuncio non c’è.</p>
        <p className="text-ink-3">{(error as Error).message}</p>
      </div>
    )
  }
  if (!head) return <DetailSkeleton />
  const t = splitTitle(head.title)
  const inCompare = compare.includes(id)
  const raw = d?.raw
  const detailDescription = raw?.detail_description || raw?.detail?.description
  // Without the portal's page, the search card's excerpt is the description there is.
  const description = detailDescription || head.description_snippet
  const costs = { ...(raw?.detail_costs ?? {}), ...(raw?.detail?.costs ?? {}) }
  // The summary's agency is cleaned of scraped UI labels ("Mostra Telefono"); raw is the fallback.
  const agency = head.agency || raw?.detail_agency || raw?.detail?.agency || null
  const postDate = postDateRow(head.post_date)
  const detailStatus = head.detail_status ?? 'ok'
  const bathrooms = head.bathrooms ?? raw?.bathrooms ?? null
  const facts = head.facts ?? []
  // A fact is listed unless a fixed row above already carries its value.
  const fixed: Record<string, unknown> = {
    piano: head.floor,
    arredato: head.furnished,
    bagni: bathrooms,
    'classe energetica': head.energy_class,
  }
  const extraFacts = facts.filter((f) => {
    const key = f.label.trim().toLowerCase()
    return !SHOWN_ELSEWHERE.has(key) && fixed[key] == null
  })
  const chips = head.features.filter((f) => !chipCovered(f, facts))
  const seenAgain = head.last_job_id != null && head.last_job_id !== head.job_id
  // Rows saved before runs kept their first-found run carry the last run that saw them instead
  const foundVerb = head.first_seen_exact === false ? 'visto' : 'trovato'
  const sourceLine = `${head.source ?? 'Portale'} · ${head.config_name || 'ricerca'} · ${foundVerb} ${relative(head.first_seen_at ?? head.scraped_at)}`

  return (
    <article className="flex h-full min-h-0 flex-col bg-sheet" aria-label={head.title}>
      <header className={cn('flex h-12 shrink-0 items-center gap-1 border-b border-hair px-2', !mobile && 'pl-3')}>
        {/* Desktop always shows a certificate beside the feed (the best match opens on its own), so only the phone closes it. */}
        {mobile ? (
          <button
            type="button"
            onClick={onClose}
            className="flex size-8 items-center justify-center rounded-sm text-ink-2 hover:bg-accent hover:text-ink"
            aria-label="Torna agli annunci"
          >
            <ArrowLeft className="size-4" />
          </button>
        ) : null}
        <p className="min-w-0 flex-1 truncate px-1 text-xs text-ink-3" title={sourceLine}>
          {sourceLine}
        </p>
        <button
          type="button"
          onClick={() => {
            const r = toggleCompare(id)
            if (r === 'full') toast('Confronti già 3 annunci', { description: 'Togline uno per aggiungerne un altro.' })
          }}
          aria-pressed={inCompare}
          className={cn(
            'inline-flex h-8 items-center gap-1.5 rounded-sm px-2.5 text-xs font-semibold transition-colors',
            inCompare ? 'bg-ink text-white' : 'text-ink-2 hover:bg-accent hover:text-ink',
          )}
        >
          <Columns3 className="size-3.5" /> {inCompare ? 'In confronto' : 'Confronta'}
        </button>
        {/* The phone's foot bar carries "Portale" on the Scheda; up here it shrinks to an icon so the source line fits. */}
        <a
          href={head.url}
          target="_blank"
          rel="noreferrer"
          aria-label={mobile ? 'Apri sul portale' : undefined}
          className={cn(
            'inline-flex h-8 items-center gap-1.5 rounded-sm bg-ink text-xs font-semibold text-white hover:bg-ink/85',
            mobile ? 'w-8 justify-center' : 'px-3',
          )}
        >
          {mobile ? null : 'Apri sul portale'} <ExternalLink className="size-3.5" />
        </a>
      </header>

      <Tabs value={tab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col gap-0">
        <TabsList className="h-10 w-full shrink-0 justify-start gap-4 rounded-none border-b border-hair bg-sheet px-5 py-0">
          <TabsTrigger
            value="scheda"
            className="h-full flex-none rounded-none border-0 border-b-2 border-transparent px-0 text-sm font-semibold text-ink-3 shadow-none data-[state=active]:border-ink data-[state=active]:text-ink data-[state=active]:shadow-none"
          >
            Scheda
          </TabsTrigger>
          <TabsTrigger
            value="ai"
            className="h-full flex-none rounded-none border-0 border-b-2 border-transparent px-0 text-sm font-semibold text-ink-3 shadow-none data-[state=active]:border-ink data-[state=active]:text-ink data-[state=active]:shadow-none"
          >
            Chiedi a Milhouse
            {chat.length ? <span className="tnum ml-1.5 rounded-sm bg-ink px-1 text-2xs text-white">{Math.ceil(chat.length / 2)}</span> : null}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="scheda" ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
          {d ? <Gallery key={id} detail={d} /> : <Thumb src={head.thumbnail} size="l-c" className="aspect-[16/9] w-full" />}

          <div className="px-5 pt-4">
            <h2 className="text-xl font-bold text-balance">
              {t.typology ? <span className="font-semibold text-ink-3">{t.typology} </span> : null}
              {t.street}
            </h2>
            <p className="mt-0.5 text-sm text-ink-3">{head.address && head.address !== head.title ? head.address : t.place || head.city}</p>
          </div>

          <div className="mx-5 mt-4 grid grid-cols-2 gap-px border-y border-ink bg-hair sm:grid-cols-4 [&>*]:bg-sheet">
            <Field label="Canone al mese">
              <span className="tnum text-2xl font-bold">{eur(head.price_eur)}</span>
            </Field>
            <Field label="Superficie">
              <span className="tnum text-2xl font-bold">{num(head.sqm_num)}</span>
              <span className="text-xs text-ink-3"> m²</span>
            </Field>
            <Field label="Locali">
              <span className="tnum text-2xl font-bold">{head.rooms_num ?? '—'}</span>
            </Field>
            <Field label="Prezzo al m²">
              <span className="tnum text-2xl font-bold">{eurSqm(head.price_per_sqm)}</span>
            </Field>
          </div>

          <ScoreSection detail={head} />

          <section className="mx-5 flex flex-col gap-3 border-t border-hair py-5">
            {!mobile ? <TriageButtons listing={head} variant="labels" /> : null}
            <NoteField listing={head} />
          </section>

          <section className="mx-5 border-t border-hair py-5">
            <h3 className="label-caps mb-1 text-ink">Dati dell’annuncio</h3>
            {detailStatus !== 'ok' ? (
              <p className="mb-1.5 flex items-start gap-1.5 text-xs leading-snug text-ink-2" title={head.detail_error ?? undefined}>
                <TriangleAlert className="mt-px size-3.5 shrink-0 text-ink-3" aria-hidden />
                <span>
                  {DETAIL_NOTE[detailStatus]}: qui ci sono solo i dati della pagina di ricerca. La prossima run che lo ritrova
                  riprova a leggerla.
                </span>
              </p>
            ) : null}
            <dl>
              <Row label="Classe energetica" value={<EnergyChevron value={head.energy_class} />} />
              <Row label="Piano" value={head.floor} />
              <Row label="Arredato" value={yesNo(head.furnished)} />
              <Row label="Disponibile da" value={head.available_from} />
              <Row label="Bagni" value={bathrooms} />
              <Row label="Agenzia" value={agency} />
              <Row label={postDate.label} value={postDate.value} />
              <Row
                label={foundVerb === 'visto' ? 'Visto il' : 'Trovato il'}
                value={`${fullDate(head.first_seen_at ?? head.scraped_at)} · run #${head.job_id}`}
              />
              {seenAgain ? <Row label="Rivisto il" value={`${fullDate(head.last_seen_at)} · run #${head.last_job_id}`} /> : null}
            </dl>
            {chips.length ? (
              <ul className="mt-3 flex flex-wrap gap-1.5">
                {chips.map((f) => (
                  <li key={f} className="rounded-sm border border-hair-strong px-2 py-0.5 text-xs text-ink-2">
                    {f}
                  </li>
                ))}
              </ul>
            ) : null}
          </section>

          {extraFacts.length ? (
            <section className="mx-5 border-t border-hair py-5">
              <h3 className="label-caps mb-1 text-ink">Caratteristiche dal portale</h3>
              <dl>
                {extraFacts.map((f, i) => (
                  <Row key={`${f.label}:${i}`} label={f.label} value={f.value} />
                ))}
              </dl>
            </section>
          ) : null}

          {Object.keys(costs).length ? (
            <section className="mx-5 border-t border-hair py-5">
              <h3 className="label-caps mb-1 text-ink">Costi</h3>
              <dl>
                {Object.entries(costs).map(([k, v]) => (
                  <Row key={k} label={k} value={v} />
                ))}
              </dl>
            </section>
          ) : null}

          {description ? (
            <section className="mx-5 border-t border-hair py-5">
              <h3 className="label-caps mb-2 text-ink">Descrizione</h3>
              <p className="max-w-[68ch] text-[0.9375rem] leading-relaxed whitespace-pre-line text-ink-2">{description}</p>
              {!detailDescription ? (
                <p className="mt-2 text-xs text-ink-3">
                  {detailStatus === 'ok'
                    ? 'Estratto dalla pagina di ricerca: la pagina dell’annuncio non riporta una descrizione.'
                    : 'Estratto dalla pagina di ricerca: la pagina dell’annuncio non è stata letta.'}
                </p>
              ) : null}
            </section>
          ) : null}
          <div className="h-8" />
        </TabsContent>

        <TabsContent value="ai" className="flex min-h-0 flex-1 flex-col">
          <Suspense fallback={<MilhouseLoader className="p-5" lines={['Milhouse arriva…']} />}>
            <AiChat listing={head} className="flex-1" />
          </Suspense>
        </TabsContent>
      </Tabs>
      {mobile && tab === 'scheda' ? (
        // Phone: the verdict and the portal are a thumb's reach away, not two screens below the photo. Four 44px cells.
        <footer className="grid shrink-0 grid-cols-4 border-t border-hair bg-sheet p-2">
          <TriageButtons
            listing={head}
            variant="labels"
            className="col-span-3 rounded-r-none [&>button]:h-11 [&>button]:flex-col [&>button]:gap-0.5 [&>button]:text-xs"
          />
          <a
            href={head.url}
            target="_blank"
            rel="noreferrer"
            aria-label="Apri sul portale"
            className="flex h-[2.875rem] flex-col items-center justify-center gap-0.5 rounded-r-sm border border-l-0 border-hair-strong text-xs font-semibold text-ink-2 transition-colors hover:bg-accent hover:text-ink"
          >
            <ExternalLink className="size-3.5" aria-hidden />
            Portale
          </a>
        </footer>
      ) : null}
      {isLoading && !data ? <span className="sr-only">Carico i dettagli…</span> : null}
    </article>
  )
}
