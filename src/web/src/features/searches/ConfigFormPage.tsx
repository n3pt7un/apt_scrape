import { useQuery } from '@tanstack/react-query'
import { Check, ChevronDown, LoaderCircle, Play, TriangleAlert, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { api } from '@/lib/api'
import { eur, slugLabel } from '@/lib/format'
import { useAreas, useConfig, useRunConfig, useSaveConfig, useSites } from '@/lib/queries'
import type { SearchConfigInput } from '@/lib/types'
import { cn } from '@/lib/utils'
import { DAYS, localToUtc, utcToLocal } from './schedule'
import { confirmAction } from '@/components/shell/ConfirmHost'
import { confirmRun, useCostPerListing } from '@/lib/cost'

const FALLBACK_TYPES = ['appartamenti', 'attici', 'case-indipendenti', 'loft', 'ville', 'villette', 'rustici']

const EMPTY: SearchConfigInput = {
  name: '',
  city: '',
  area: null,
  operation: 'affitto',
  property_type: 'appartamenti',
  min_price: null,
  max_price: null,
  min_sqm: null,
  min_rooms: null,
  start_page: 1,
  end_page: 5,
  schedule_days: [],
  schedule_time: '07:00',
  detail_concurrency: 5,
  vpn_rotate_batches: 3,
  auto_analyse: true,
  auto_notion_push: false,
  enabled: true,
  site_id: 'immobiliare',
  request_delay_sec: 2,
  page_delay_sec: 0,
  timeout_sec: null,
}

const inputCls =
  'h-9 w-full rounded-sm border border-hair-strong bg-sheet px-3 text-sm text-ink placeholder:text-ink-3 focus:border-ink focus:outline-none aria-[invalid=true]:border-destructive'

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="grid gap-4 border-t border-ink py-6 first:border-t-0 first:pt-0 md:grid-cols-[12rem_1fr] md:gap-8">
      <div>
        <h2 className="text-base font-bold">{title}</h2>
        {hint ? <p className="mt-0.5 text-sm text-ink-3">{hint}</p> : null}
      </div>
      <div className="grid gap-4">{children}</div>
    </section>
  )
}

function Field({
  label,
  hint,
  error,
  children,
  className,
}: {
  label: string
  hint?: string
  error?: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <label className={cn('block', className)}>
      <span className="text-sm font-semibold">{label}</span>
      <span className="mt-1 block">{children}</span>
      {error ? (
        <span className="mt-1 block text-xs text-destructive">{error}</span>
      ) : hint ? (
        <span className="mt-1 block text-xs text-ink-3">{hint}</span>
      ) : null}
    </label>
  )
}

function NumberInput({
  value,
  onChange,
  suffix,
  invalid,
  ...rest
}: {
  value: number | null
  onChange: (v: number | null) => void
  suffix?: string
  invalid?: boolean
} & Omit<React.InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange'>) {
  return (
    <span className="relative block">
      <input
        type="number"
        inputMode="numeric"
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
        aria-invalid={invalid || undefined}
        className={cn(inputCls, 'tnum', suffix && 'pr-12')}
        {...rest}
      />
      {suffix ? <span className="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-xs text-ink-3">{suffix}</span> : null}
    </span>
  )
}

function AreaPicker({ site, value, onChange }: { site: string; value: string[]; onChange: (v: string[]) => void }) {
  const { data: areas, isLoading } = useAreas(site)
  const [open, setOpen] = useState(false)
  const toggle = (a: string) => onChange(value.includes(a) ? value.filter((x) => x !== a) : [...value, a])
  if (!isLoading && !areas?.length) {
    return (
      <input
        className={inputCls}
        value={value.join(', ')}
        onChange={(e) => onChange(e.target.value.split(',').map((s) => s.trim()).filter(Boolean))}
        placeholder="es. murri-massarenti, san-vitale"
      />
    )
  }
  return (
    <div className="grid gap-2">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button type="button" className={cn(inputCls, 'flex items-center justify-between text-left')}>
            <span className={value.length ? 'text-ink' : 'text-ink-3'}>
              {value.length ? `${value.length} zone selezionate` : 'Tutta la città'}
            </span>
            <ChevronDown className="size-4 text-ink-3" />
          </button>
        </PopoverTrigger>
        <PopoverContent className="w-[var(--radix-popover-trigger-width)] p-0" align="start">
          <Command>
            <CommandInput placeholder="Cerca una zona…" />
            <CommandList>
              <CommandEmpty>Nessuna zona.</CommandEmpty>
              <CommandGroup>
                {areas?.map((a) => (
                  <CommandItem key={a} value={a} onSelect={() => toggle(a)}>
                    <span className={cn('flex size-4 items-center justify-center rounded-[2px] border border-hair-strong', value.includes(a) && 'border-ink bg-ink text-white')}>
                      {value.includes(a) ? <Check className="size-3 text-white" /> : null}
                    </span>
                    {slugLabel(a)}
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
      {value.length ? (
        <ul className="flex flex-wrap gap-1.5">
          {value.map((a) => (
            <li key={a} className="flex h-7 items-center gap-1 rounded-sm bg-ink pr-1 pl-2 text-xs font-semibold text-white">
              {slugLabel(a)}
              <button type="button" onClick={() => toggle(a)} aria-label={`Togli ${a}`} className="rounded-[2px] p-0.5 hover:bg-white/20">
                <X className="size-3" />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

function summarySentence(form: SearchConfigInput): string {
  const f = { ...form, min_price: form.min_price || null }
  const types = f.property_type.split(',').filter(Boolean).join(', ') || 'immobili'
  const where = slugLabel(f.city) || '(città da scegliere)'
  const zones = (f.area ?? '').split(',').filter(Boolean)
  const parts = [`${slugLabel(types)} in ${f.operation} a ${where}`]
  if (zones.length) parts.push(`zone ${zones.map(slugLabel).join(', ')}`)
  if (f.min_price != null || f.max_price != null)
    parts.push(
      f.min_price != null && f.max_price != null
        ? `da ${eur(f.min_price)} a ${eur(f.max_price)}`
        : f.max_price != null
          ? `fino a ${eur(f.max_price)}`
          : `da ${eur(f.min_price)}`,
    )
  if (f.min_sqm != null) parts.push(`almeno ${f.min_sqm} m²`)
  if (f.min_rooms != null) parts.push(`almeno ${f.min_rooms} locali`)
  return parts.join(', ') + '.'
}

export function ConfigFormPage() {
  const { id } = useParams()
  const [params] = useSearchParams()
  const editId = id ? Number(id) : null
  const copyFrom = params.get('da') ? Number(params.get('da')) : null
  const { data: existing, isLoading } = useConfig(editId ?? copyFrom)
  const { data: sites } = useSites()
  const save = useSaveConfig()
  const run = useRunConfig()
  const perListing = useCostPerListing()
  const navigate = useNavigate()
  const [form, setForm] = useState<SearchConfigInput>(EMPTY)
  const [touched, setTouched] = useState(false)

  useEffect(() => {
    if (!existing) return
    const { id: _id, created_at: _c, next_run_at: _n, last_job: _l, listing_count: _lc, ...rest } = existing
    void _id, _c, _n, _l, _lc
    setForm(copyFrom && !editId ? { ...rest, name: `${rest.name} (copia)` } : rest)
  }, [existing, copyFrom, editId])

  const { data: siteConfig } = useQuery({
    queryKey: ['site-config', form.site_id],
    queryFn: () => api.siteConfig(form.site_id),
    staleTime: 5 * 60_000,
  })
  const types: string[] = useMemo(() => {
    const map = siteConfig?.property_type_map
    return map && typeof map === 'object' ? Object.keys(map) : FALLBACK_TYPES
  }, [siteConfig])

  const set = <K extends keyof SearchConfigInput>(k: K, v: SearchConfigInput[K]) => setForm((f) => ({ ...f, [k]: v }))
  const areas = (form.area ?? '').split(',').map((s) => s.trim()).filter(Boolean)
  const selectedTypes = form.property_type.split(',').map((s) => s.trim()).filter(Boolean)

  const errors: Partial<Record<keyof SearchConfigInput, string>> = {}
  if (!form.name.trim()) errors.name = 'Dai un nome alla ricerca.'
  if (!form.city.trim()) errors.city = 'Indica la città, es. bologna.'
  if (form.min_price != null && form.max_price != null && form.min_price > form.max_price)
    errors.max_price = 'Il massimo è sotto il minimo.'
  if (form.end_page < form.start_page) errors.end_page = 'L’ultima pagina viene prima della prima.'
  if (!selectedTypes.length) errors.property_type = 'Scegli almeno una tipologia.'
  const valid = Object.keys(errors).length === 0

  const submit = async (andRun: boolean) => {
    setTouched(true)
    if (!valid) {
      toast.error('Controlla i campi evidenziati')
      return
    }
    // Asked before saving, so Annulla leaves both the search and the portal untouched.
    if (andRun) {
      const last = editId ? existing?.last_job : null
      const ok = await confirmRun({
        configName: form.name.trim(),
        lastRunAt: last?.started_at,
        perListing,
        expectedListings: last?.listing_count,
        aiEnabled: form.auto_analyse,
      })
      if (!ok) return
    }
    const body = { ...form, name: form.name.trim(), city: form.city.trim().toLowerCase(), area: areas.length ? areas.join(',') : null }
    save.mutate(
      { id: editId, body },
      {
        onSuccess: (cfg) => {
          toast.success(editId ? 'Ricerca aggiornata' : 'Ricerca creata')
          if (andRun) {
            run.mutate(cfg.id, {
              onSuccess: ({ job_id }) => navigate(`/run/${job_id}`),
              onError: (e) => toast.error('Run non avviata', { description: (e as Error).message }),
            })
          } else navigate('/ricerche')
        },
        onError: (e) => toast.error('Ricerca non salvata', { description: (e as Error).message }),
      },
    )
  }

  const err = (k: keyof SearchConfigInput) => (touched ? errors[k] : undefined)
  const busy = save.isPending || run.isPending

  if ((editId || copyFrom) && isLoading) {
    return <div className="p-8 text-sm text-ink-3">Carico la ricerca…</div>
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto grid max-w-6xl gap-8 px-4 py-5 lg:grid-cols-[1fr_20rem] lg:px-8 lg:py-8">
        <div className="min-w-0">
          <p className="text-sm text-ink-3">
            <Link to="/ricerche" className="hover:text-ink hover:underline">
              Ricerche
            </Link>{' '}
            / {editId ? 'Modifica' : 'Nuova'}
          </p>
          <h1 className="mt-1 text-2xl font-bold">{editId ? form.name || 'Modifica ricerca' : 'Nuova ricerca'}</h1>

          <form
            className="mt-6 rounded-sm border border-hair bg-sheet px-5 py-6 md:px-7"
            onSubmit={(e) => {
              e.preventDefault()
              void submit(false)
            }}
          >
            <Section title="Dove" hint="Portale, città e zone da leggere.">
              <Field label="Nome" error={err('name')}>
                <input className={inputCls} value={form.name} onChange={(e) => set('name', e.target.value)} placeholder="es. Bologna · bilocali Cirenaica" aria-invalid={!!err('name')} />
              </Field>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Portale">
                  <Select value={form.site_id} onValueChange={(v) => setForm((f) => ({ ...f, site_id: v, area: null }))}>
                    <SelectTrigger className="h-9 w-full rounded-sm border-hair-strong bg-sheet">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {(sites ?? [form.site_id]).map((s) => (
                        <SelectItem key={s} value={s}>
                          {slugLabel(s)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
                <Field label="Città" hint="Come compare nell’indirizzo del portale." error={err('city')}>
                  <input className={inputCls} value={form.city} onChange={(e) => set('city', e.target.value)} placeholder="bologna" aria-invalid={!!err('city')} />
                </Field>
              </div>
              <Field label="Zone" hint="Nessuna zona = tutta la città.">
                <AreaPicker site={form.site_id} value={areas} onChange={(v) => set('area', v.join(','))} />
              </Field>
            </Section>

            <Section title="Cosa" hint="Contratto e tipologia.">
              <div className="grid grid-cols-2 rounded-sm border border-hair-strong sm:w-64" role="radiogroup" aria-label="Contratto">
                {['affitto', 'vendita'].map((op) => (
                  <button
                    key={op}
                    type="button"
                    role="radio"
                    aria-checked={form.operation === op}
                    onClick={() => set('operation', op)}
                    className={cn('h-9 text-sm font-semibold capitalize first:border-r first:border-hair-strong', form.operation === op ? 'bg-ink text-white' : 'text-ink-2 hover:bg-accent')}
                  >
                    {op}
                  </button>
                ))}
              </div>
              <div>
                <p className="text-sm font-semibold">Tipologie</p>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {types.map((t) => {
                    const on = selectedTypes.includes(t)
                    return (
                      <button
                        key={t}
                        type="button"
                        aria-pressed={on}
                        onClick={() => set('property_type', (on ? selectedTypes.filter((x) => x !== t) : [...selectedTypes, t]).join(','))}
                        className={cn('h-8 rounded-sm border px-3 text-sm transition-colors', on ? 'border-ink bg-ink text-white' : 'border-hair-strong text-ink-2 hover:border-ink hover:text-ink')}
                      >
                        {slugLabel(t)}
                      </button>
                    )
                  })}
                </div>
                {err('property_type') ? <p className="mt-1 text-xs text-destructive">{err('property_type')}</p> : null}
              </div>
            </Section>

            <Section title="Filtri" hint="Applicati dal portale prima di scaricare.">
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Prezzo minimo">
                  <NumberInput value={form.min_price} onChange={(v) => set('min_price', v)} suffix="€" min={0} step={50} />
                </Field>
                <Field label="Prezzo massimo" error={err('max_price')}>
                  <NumberInput value={form.max_price} onChange={(v) => set('max_price', v)} suffix="€" min={0} step={50} invalid={!!err('max_price')} />
                </Field>
                <Field label="Superficie minima">
                  <NumberInput value={form.min_sqm} onChange={(v) => set('min_sqm', v)} suffix="m²" min={0} step={5} />
                </Field>
                <Field label="Locali minimi">
                  <NumberInput value={form.min_rooms} onChange={(v) => set('min_rooms', v)} min={1} max={10} />
                </Field>
              </div>
            </Section>

            <Section title="Quando" hint="Giorni e ora in cui partire da sola.">
              <div>
                <p className="text-sm font-semibold">Giorni</p>
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {DAYS.map((d) => {
                    const on = form.schedule_days.includes(d.id)
                    return (
                      <button
                        key={d.id}
                        type="button"
                        aria-pressed={on}
                        aria-label={d.long}
                        onClick={() => set('schedule_days', on ? form.schedule_days.filter((x) => x !== d.id) : [...form.schedule_days, d.id])}
                        className={cn('h-9 w-12 rounded-sm border text-sm font-semibold transition-colors', on ? 'border-ink bg-ink text-white' : 'border-hair-strong text-ink-2 hover:border-ink')}
                      >
                        {d.short}
                      </button>
                    )
                  })}
                </div>
                {form.enabled && form.schedule_days.length === 0 ? (
                  <p className="mt-1.5 flex items-center gap-1.5 text-xs font-semibold text-ink" role="status">
                    <TriangleAlert className="size-3.5 shrink-0" />
                    Pianificazione attiva ma nessun giorno scelto: non partirà da sola.
                  </p>
                ) : (
                  <p className="mt-1 text-xs text-ink-3">Nessun giorno: parte solo quando la avvii tu.</p>
                )}
              </div>
              <Field label="Ora" hint={`Nel tuo fuso. Salvata come ${form.schedule_time} UTC.`} className="sm:w-48">
                <input type="time" className={cn(inputCls, 'tnum')} value={utcToLocal(form.schedule_time)} onChange={(e) => e.target.value && set('schedule_time', localToUtc(e.target.value))} />
              </Field>
              <label className="flex items-center justify-between gap-4 rounded-sm border border-hair px-3 py-2.5">
                <span>
                  <span className="block text-sm font-semibold">Pianificazione attiva</span>
                  <span className="block text-xs text-ink-3">Spegnila per tenere la ricerca senza farla partire.</span>
                </span>
                <Switch checked={form.enabled} onCheckedChange={(v) => set('enabled', v)} />
              </label>
            </Section>

            <Section title="Dopo lo scraping" hint="Cosa fare con gli annunci trovati.">
              <label className="flex items-center justify-between gap-4 rounded-sm border border-hair px-3 py-2.5">
                <span>
                  <span className="block text-sm font-semibold">Valuta con l’AI</span>
                  <span className="block text-xs text-ink-3">Ogni annuncio riceve un’affinità 0–100 sui tuoi criteri.</span>
                </span>
                <Switch checked={form.auto_analyse} onCheckedChange={(v) => set('auto_analyse', v)} />
              </label>
              <label className="flex items-center justify-between gap-4 rounded-sm border border-hair px-3 py-2.5">
                <span>
                  <span className="block text-sm font-semibold">Invia a Notion</span>
                  <span className="block text-xs text-ink-3">Salta gli annunci già presenti nel database.</span>
                </span>
                <Switch checked={form.auto_notion_push} onCheckedChange={(v) => set('auto_notion_push', v)} />
              </label>
            </Section>

            <Section title="Raccolta" hint="Quante pagine e a che ritmo. I valori prudenti evitano i blocchi.">
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Dalla pagina">
                  <NumberInput value={form.start_page} onChange={(v) => set('start_page', v ?? 1)} min={1} />
                </Field>
                <Field label="Alla pagina" error={err('end_page')}>
                  <NumberInput value={form.end_page} onChange={(v) => set('end_page', v ?? 1)} min={1} invalid={!!err('end_page')} />
                </Field>
                <Field label="Dettagli in parallelo" hint="Pagine di dettaglio aperte insieme.">
                  <NumberInput value={form.detail_concurrency} onChange={(v) => set('detail_concurrency', v ?? 1)} min={1} max={20} />
                </Field>
                <Field label="Cambio VPN ogni" hint="Blocchi di dettagli prima di ruotare il proxy.">
                  <NumberInput value={form.vpn_rotate_batches} onChange={(v) => set('vpn_rotate_batches', v ?? 1)} min={1} suffix="blocchi" />
                </Field>
                <Field label="Pausa tra richieste" hint="Tra l’apertura di due pagine, di ricerca o di dettaglio.">
                  <NumberInput value={form.request_delay_sec} onChange={(v) => set('request_delay_sec', v ?? 0)} min={0} step={0.5} suffix="s" />
                </Field>
                <Field label="Pausa tra pagine">
                  <NumberInput value={form.page_delay_sec} onChange={(v) => set('page_delay_sec', v ?? 0)} min={0} step={0.5} suffix="s" />
                </Field>
              </div>
            </Section>
            <button type="submit" className="hidden" />
          </form>
        </div>

        <aside className="lg:sticky lg:top-8 lg:self-start">
          <div className="rounded-sm border border-ink bg-sheet">
            <p className="label-caps border-b border-hair px-4 py-2.5 text-ink">Riepilogo</p>
            <p className="px-4 py-4 text-base leading-relaxed">{summarySentence(form)}</p>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 border-t border-hair px-4 py-3 text-sm">
              <dt className="text-ink-3">Portale</dt>
              <dd className="text-right font-semibold">{slugLabel(form.site_id)}</dd>
              <dt className="text-ink-3">Parte</dt>
              <dd className="text-right font-semibold">
                {form.schedule_days.length && form.enabled
                  ? `${DAYS.filter((d) => form.schedule_days.includes(d.id)).map((d) => d.short).join(' ')} · ${utcToLocal(form.schedule_time)}`
                  : 'Solo a mano'}
              </dd>
              <dt className="text-ink-3">Pagine</dt>
              <dd className="tnum text-right font-semibold">
                {form.start_page}–{form.end_page}
              </dd>
              <dt className="text-ink-3">AI · Notion</dt>
              <dd className="text-right font-semibold">
                {form.auto_analyse ? 'Sì' : 'No'} · {form.auto_notion_push ? 'Sì' : 'No'}
              </dd>
            </dl>
            <div className="flex flex-col gap-2 border-t border-hair p-4">
              <Button onClick={() => void submit(true)} disabled={busy}>
                {busy ? <LoaderCircle className="size-4 animate-spin" /> : <Play className="size-3.5 fill-current" />}
                Salva e avvia
              </Button>
              <Button variant="outline" onClick={() => void submit(false)} disabled={busy}>
                Salva
              </Button>
              <Button variant="ghost" asChild>
                <Link to="/ricerche">Annulla</Link>
              </Button>
            </div>
          </div>
          {editId ? (
            <button
              type="button"
              className="mt-3 w-full text-center text-xs text-ink-3 hover:text-destructive"
              onClick={async () => {
                const ok = await confirmAction({
                  title: 'Eliminare questa ricerca?',
                  body: 'Non partirà più, né a mano né pianificata. Gli annunci che ha già trovato restano nel feed.',
                  confirmLabel: 'Elimina ricerca',
                  destructive: true,
                })
                if (!ok) return
                await api.deleteConfig(editId)
                toast.success('Ricerca eliminata')
                navigate('/ricerche')
              }}
            >
              Elimina ricerca
            </button>
          ) : null}
        </aside>
      </div>
    </div>
  )
}
