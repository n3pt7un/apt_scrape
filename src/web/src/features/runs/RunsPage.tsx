import { useQueries, useQueryClient } from '@tanstack/react-query'
import { Check, Minus, RotateCcw, Trash2, TriangleAlert, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { toast } from 'sonner'
import { RunLauncher } from '@/components/shell/RunLauncher'
import { Button } from '@/components/ui/button'
import { confirmAction } from '@/components/shell/ConfirmHost'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/lib/api'
import { confirmRun, useCostPerListing } from '@/lib/cost'
import { duration, eur, fullDate, num, parseDate, relative, slugLabel, usd } from '@/lib/format'
import { PHASES, readLog, type PhaseState } from '@/lib/phases'
import { isActive, keys, useConfigs, useJob, useJobStats, useJobs, useListings, useOverallStats, useRunConfig } from '@/lib/queries'
import { buildVerbale, notScored } from '@/lib/verbale'
import { VerbaleSheet } from '@/components/milhouse/Verbale'
import { MilhouseLoader } from '@/components/milhouse/Glasses'
import { explainRunError } from '@/lib/runErrors'
import type { Job, JobStatus } from '@/lib/types'
import { useMediaQuery } from '@/lib/useMediaQuery'
import { cn } from '@/lib/utils'
import { useJobStream } from './useJobStream'

export function RunStatus({ status, className }: { status: JobStatus; className?: string }) {
  const map: Record<JobStatus, { label: string; cls: string; style?: React.CSSProperties }> = {
    pending: { label: 'In coda', cls: 'border border-ink text-ink' },
    running: { label: 'In corso', cls: 'bg-ink text-white' },
    done: { label: 'Completata', cls: 'text-white', style: { background: 'var(--r-1)' } },
    failed: { label: 'Fallita', cls: 'text-white', style: { background: 'var(--r-9)' } },
  }
  const s = map[status]
  return (
    <span
      className={cn('chevron inline-flex h-5 items-center gap-1.5 pr-3 pl-1.5 text-2xs font-bold tracking-wide uppercase [--tip:0.45rem]', s.cls, className)}
      style={s.style}
    >
      {status === 'running' ? <span className="size-1.5 animate-pulse rounded-full bg-r-3" /> : null}
      {s.label}
    </span>
  )
}

function elapsed(j: Pick<Job, 'started_at' | 'finished_at'>): number | null {
  const a = parseDate(j.started_at)
  const b = parseDate(j.finished_at) ?? (j.finished_at ? null : new Date())
  return a && b ? (b.getTime() - a.getTime()) / 1000 : null
}

function PhaseStep({ label, state, last, passed }: { label: string; state: PhaseState; last: boolean; passed?: boolean }) {
  return (
    <li
      className={cn(
        'flex items-center gap-2',
        last
          ? 'shrink-0'
          : // on the phone the step in play keeps its name, so it sizes to it instead of running under the next circle
            state === 'active' || state === 'failed'
            ? 'flex-none sm:min-w-0 sm:flex-1'
            : 'min-w-0 flex-1',
      )}
    >
      <span
        className={cn(
          'flex size-6 shrink-0 items-center justify-center rounded-full border text-white transition-colors duration-300',
          state === 'done' && 'border-transparent bg-ink',
          state === 'active' && 'border-ink bg-sheet',
          state === 'todo' && 'border-hair-strong bg-sheet',
          state === 'skipped' && 'border-dashed border-hair-strong bg-sheet text-ink-3',
          state === 'failed' && 'border-transparent bg-[var(--r-9)]',
        )}
      >
        {state === 'done' ? <Check className="size-3.5" strokeWidth={3} /> : null}
        {state === 'active' ? <span className="size-2 animate-pulse rounded-full bg-ink" /> : null}
        {state === 'skipped' ? <Minus className="size-3" /> : null}
        {state === 'failed' ? <X className="size-3.5" strokeWidth={3} /> : null}
      </span>
      <span
        className={cn(
          'shrink-0 text-xs font-semibold whitespace-nowrap',
          state === 'todo' || state === 'skipped' ? 'text-ink-3' : 'text-ink',
          // On the phone only the phase in play keeps its name; the circles carry the rest.
          state !== 'active' && state !== 'failed' && 'sr-only sm:not-sr-only',
        )}
        title={state === 'skipped' ? `${label}: saltata` : state === 'failed' ? `${label}: non riuscita` : label}
      >
        {label}
        {state === 'skipped' ? <span className="sr-only"> (saltata)</span> : null}
        {state === 'failed' ? <span className="sr-only"> (non riuscita)</span> : null}
      </span>
      {!last ? (
        // The rule fills toward the next phase when this one finishes.
        <span className="relative h-px min-w-3 flex-1 bg-hair-strong">
          <span
            className={cn(
              'absolute inset-0 origin-left bg-ink transition-transform duration-500 ease-out-expo',
              state === 'done' || state === 'skipped' || passed ? 'scale-x-100' : 'scale-x-0',
            )}
          />
        </span>
      ) : null}
    </li>
  )
}

function Counter({ label, value }: { label: string; value: number | string | null }) {
  // The real figure, always: a run's outcome is not a place for a count-up.
  return (
    <div className="bg-sheet px-4 py-3">
      <p className="label-caps">{label}</p>
      <p className="tnum mt-0.5 text-2xl font-bold">{value ?? '—'}</p>
    </div>
  )
}

/** The runner stamps log lines in UTC; show them on the reader's clock. */
function localClock(hms: string): string {
  const [h, m, s] = hms.split(':').map(Number)
  const d = new Date()
  d.setUTCHours(h, m, s, 0)
  return d.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function LogView({ log, follow }: { log: string; follow: boolean }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (follow && ref.current) ref.current.scrollTop = ref.current.scrollHeight
  }, [log, follow])
  const lines = log.split('\n').filter(Boolean)
  // Lines already there when the log opened stay put; only lines streamed in afterwards settle in.
  const seen = useRef<number | null>(null)
  if (seen.current == null || lines.length < seen.current) seen.current = lines.length
  return (
    <div ref={ref} className="min-h-0 flex-1 overflow-auto bg-sheet-2 px-4 py-3 font-mono text-[0.75rem] leading-5">
      {lines.length === 0 ? <p className="font-sans text-sm text-ink-3">Il log apparirà qui appena la run comincia.</p> : null}
      {lines.map((l, i) => {
        const m = l.match(/^\[(\d\d:\d\d:\d\d)\]\s?(.*)$/)
        const text = m ? m[2] : l
        const err = text.startsWith('[ERROR]')
        const warn = text.startsWith('[warn]')
        return (
          <div
            key={i}
            className={cn('flex gap-3 whitespace-pre-wrap break-all', i >= seen.current! && 'log-in', err && 'font-semibold text-[var(--r-9)]', warn && 'text-[#9a5b00]')}
          >
            <span className="shrink-0 text-ink-3 select-none">{m ? localClock(m[1]) : ''}</span>
            <span>{text}</span>
          </div>
        )
      })}
    </div>
  )
}

function AreaBars({ stats }: { stats: Record<string, number> }) {
  const entries = Object.entries(stats).sort((a, b) => b[1] - a[1])
  const max = Math.max(1, ...entries.map((e) => e[1]))
  if (!entries.length) return null
  return (
    <div>
      <p className="label-caps mb-2">Annunci per zona</p>
      <ul className="flex flex-col gap-1.5">
        {entries.map(([area, n]) => (
          <li key={area} className="grid grid-cols-[9rem_1fr_2.5rem] items-center gap-3 text-sm">
            <span className="truncate text-ink-2">{area ? slugLabel(area) : 'Tutta la città'}</span>
            <span className="h-2.5 bg-sheet-2">
              <span className="block h-full bg-ink" style={{ width: `${(n / max) * 100}%` }} />
            </span>
            <span className="tnum text-right font-semibold">{n}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function JobPanel({ job, onDeleted }: { job: Job; onDeleted: () => void }) {
  const stream = useJobStream(job)
  // The jobs list carries no logs: the full log comes from the job record (refetched when the run ends).
  const { data: detail, isError: detailFailed } = useJob(job.id)
  const status = stream.status ?? job.status
  const log = stream.log || detail?.log || ''
  const reading = useMemo(() => readLog(log, status), [log, status])
  const finished = status === 'done' || status === 'failed'
  const { data: stats } = useJobStats(job.id, finished)
  const [follow, setFollow] = useState(true)
  const qc = useQueryClient()
  const [, tick] = useState(0)
  useEffect(() => {
    if (finished) return
    const t = setInterval(() => tick((n) => n + 1), 1000)
    return () => clearInterval(t)
  }, [finished])

  const run = useRunConfig()
  const navigate = useNavigate()
  const { data: listings, dataUpdatedAt: listingsAt, isError: listingsFailed } = useListings()
  // The verbale is filed only once its inputs cover the finished run: the job record is terminal
  // (not just the stream's last event) and the listings were fetched after the run ended.
  const finishedAt = parseDate(job.finished_at)?.getTime() ?? null
  // The verbale reads the full log (a failed run's error line, the AI step's own tally or crash), so it
  // waits for it: the streamed log of a run watched to its end, or a copy of the record fetched after
  // the run ended (one fetched while it ran holds half a log). Filed early, the stamp could thump
  // "Visto" and then turn into "Non valutati" when the log lands.
  const logReady = !!stream.log || (detail != null && !isActive(detail)) || detailFailed
  const verbaleReady =
    finished && !isActive(job) && finishedAt != null && listings != null && !listingsFailed && listingsAt >= finishedAt && logReady
  const verbale = useMemo(
    () => (verbaleReady ? buildVerbale({ ...job, status }, listings, log) : null),
    [verbaleReady, job, status, log, listings],
  )
  // The log alone cannot see a run whose listings all came back N.D.: the verbale (log + listings) can.
  const phases = useMemo(
    () => (verbale && notScored(verbale) && reading.phases.ai === 'done' ? { ...reading.phases, ai: 'failed' as const } : reading.phases),
    [verbale, reading.phases],
  )

  // A failed run that a later run of the same search has since completed needs no retry: point there.
  const { data: jobs } = useJobs()
  const { data: configs } = useConfigs()
  const supersededBy =
    status === 'failed'
      ? (jobs ?? []).find((j) => j.config_id === job.config_id && j.id > job.id && j.status === 'done') ?? null
      : null
  const runningNow = (jobs ?? []).find((j) => j.config_id === job.config_id && j.id !== job.id && isActive(j)) ?? null
  const perListing = useCostPerListing()
  const retry = async () => {
    const cfg = configs?.find((c) => c.id === job.config_id)
    const ok = await confirmRun({
      configName: job.config_name || cfg?.name || `Ricerca ${job.config_id}`,
      lastRunAt: cfg?.last_job?.started_at ?? job.started_at,
      perListing,
      expectedListings: cfg?.last_job?.listing_count,
      aiEnabled: cfg?.auto_analyse,
    })
    if (!ok) return
    run.mutate(job.config_id, {
      onSuccess: ({ job_id }) => {
        toast.success('Run riavviata')
        navigate(`/run/${job_id}`)
      },
      onError: (e) => toast.error('Run non avviata', { description: (e as Error).message }),
    })
  }

  const remove = async () => {
    const ok = await confirmAction({
      title: `Eliminare la run #${job.id}?`,
      body: 'Sparisce il log di questa run. Gli annunci che ha trovato restano nel feed.',
      confirmLabel: 'Elimina run',
      destructive: true,
    })
    if (!ok) return
    try {
      await api.deleteJob(job.id)
      qc.invalidateQueries({ queryKey: keys.jobs })
      onDeleted()
      toast.success(`Run #${job.id} eliminata`)
    } catch (e) {
      toast.error('Eliminazione non riuscita', { description: (e as Error).message })
    }
  }

  const live = !finished
  return (
    <div className="flex h-full min-h-0 flex-col bg-sheet">
      <header className="border-b border-hair px-5 py-4">
        <div className="flex flex-wrap items-center gap-2.5">
          <h2 className="text-xl font-bold">{job.config_name || `Ricerca ${job.config_id}`}</h2>
          <RunStatus status={status} />
          <div className="ml-auto flex items-center gap-1">
            {status === 'done' && verbale?.attributed ? (
              <Button asChild variant="outline" size="sm">
                <Link to={`/?run=${job.id}`}>
                  {verbale.attributed === 1 ? 'Vedi l’annuncio di questa run' : `Vedi i ${verbale.attributed} annunci di questa run`}
                </Link>
              </Button>
            ) : (
              <Button asChild variant="ghost" size="sm">
                <Link to={`/?ricerca=${job.config_id}`}>Annunci della ricerca</Link>
              </Button>
            )}
            {finished ? (
              <Button variant="ghost" size="icon" onClick={remove} aria-label="Elimina run" className="size-8 text-ink-3 hover:text-destructive">
                <Trash2 className="size-4" />
              </Button>
            ) : null}
          </div>
        </div>
        <p className="tnum mt-1 text-sm text-ink-3">
          Run #{job.id} · {job.triggered_by === 'manual' ? 'avviata a mano' : 'pianificata'} · {fullDate(job.started_at)} ·{' '}
          {live ? 'da ' : 'durata '}
          {duration(elapsed(job))}
        </p>
        <ol className="mt-4 flex items-center gap-2" aria-label="Fasi della run">
          {PHASES.map((p, i) => (
            <PhaseStep
              key={p.id}
              label={p.label}
              state={phases[p.id]}
              last={i === PHASES.length - 1}
              // a done run went past a phase that failed: the rule to the next one still fills
              passed={status === 'done'}
            />
          ))}
        </ol>
      </header>

      {verbale ? (
        <VerbaleSheet v={verbale} finishedAt={job.finished_at} onOpenBest={(id) => navigate(`/annunci/${id}`)} />
      ) : finished ? (
        <MilhouseLoader size="sm" className="border-b border-hair px-5 py-4" lines={['Milhouse sta compilando il verbale…']} />
      ) : null}

      {reading.error || status === 'failed' ? (
        <div className="flex flex-wrap items-start gap-x-2.5 gap-y-2 border-b border-hair bg-[color-mix(in_srgb,var(--r-9)_7%,white)] px-5 py-3 text-sm">
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-[var(--r-9)]" />
          <div className="min-w-0 flex-1 basis-[calc(100%-1.625rem)] sm:basis-0">
            <p className="font-semibold text-ink">La run si è fermata · {explainRunError(reading.error).title}</p>
            <p className="mt-0.5 max-w-[68ch] text-ink-2">{explainRunError(reading.error).fix}</p>
            {reading.error ? (
              <details className="mt-1.5 text-xs text-ink-3">
                <summary className="cursor-pointer select-none hover:text-ink">Dettagli tecnici</summary>
                <p className="mt-1 font-mono text-[0.6875rem] break-all">{reading.error}</p>
              </details>
            ) : null}
          </div>
          {/* on the phone the action takes its own row under the explanation, which keeps its width */}
          {!finished ? null : supersededBy ? (
            <Link
              to={`/run/${supersededBy.id}`}
              className="ml-6.5 inline-flex shrink-0 items-center gap-2 rounded-sm border border-hair-strong bg-sheet py-1 pr-1.5 pl-2.5 text-xs font-semibold text-ink transition-colors hover:border-ink sm:ml-0"
            >
              Superata dalla run #{supersededBy.id}
              <RunStatus status="done" />
            </Link>
          ) : runningNow ? (
            <Link
              to={`/run/${runningNow.id}`}
              className="ml-6.5 inline-flex shrink-0 items-center gap-2 rounded-sm border border-hair-strong bg-sheet py-1 pr-1.5 pl-2.5 text-xs font-semibold text-ink transition-colors hover:border-ink sm:ml-0"
            >
              Run #{runningNow.id}
              <RunStatus status={runningNow.status} />
            </Link>
          ) : (
            <Button size="sm" onClick={() => void retry()} disabled={run.isPending} className="ml-6.5 shrink-0 sm:ml-0">
              <RotateCcw className="size-3.5" /> Riprova
            </Button>
          )}
        </div>
      ) : null}

      <div className="grid grid-cols-2 gap-px border-b border-hair bg-hair sm:grid-cols-4">
        <Counter label="Pagine lette" value={reading.pagesFetched} />
        <Counter label="Annunci trovati" value={stats?.scraped_count ?? reading.found} />
        <Counter label="Unici" value={stats?.listing_count ?? reading.unique} />
        <Counter
          label={finished ? 'Costo AI' : 'Da arricchire'}
          value={finished ? usd(stats?.ai_cost_usd ?? job.ai_cost_usd) : reading.enriching}
        />
      </div>

      {finished && stats ? (
        <div className="grid gap-6 border-b border-hair px-5 py-4 sm:grid-cols-[1fr_auto]">
          <AreaBars stats={stats.area_stats} />
          <dl className="grid min-w-44 grid-cols-[auto_1fr] content-start gap-x-4 gap-y-1 text-sm">
            <dt className="text-ink-3">Duplicati rimossi</dt>
            <dd className="tnum text-right font-semibold">{stats.dupes_removed ?? '—'}</dd>
            <dt className="text-ink-3">Canone medio</dt>
            <dd className="tnum text-right font-semibold">{eur(stats.avg_price_eur)}</dd>
            <dt className="text-ink-3">Token AI</dt>
            <dd className="tnum text-right font-semibold">{num(stats.ai_tokens_used)}</dd>
          </dl>
        </div>
      ) : null}

      <div className="flex h-9 items-center justify-between border-b border-hair px-5">
        <p className="label-caps">
          Log {live ? (stream.connected ? '· in diretta' : '· in attesa') : ''}
          {reading.warnings.length ? ` · ${reading.warnings.length} ${reading.warnings.length === 1 ? 'avviso' : 'avvisi'}` : ''}
        </p>
        {live ? (
          <label className="flex items-center gap-1.5 text-xs text-ink-2">
            <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} className="accent-ink" />
            Segui la coda
          </label>
        ) : null}
      </div>
      <LogView log={log} follow={follow} />
    </div>
  )
}

function OverallStrip() {
  const { data } = useOverallStats()
  if (!data) return null
  const items: [string, string][] = [
    ['Run completate', String(data.total_runs)],
    ['Annunci unici', String(data.total_listings)],
    ['Duplicati rimossi', String(data.total_dupes_removed)],
    ['Canone medio', eur(data.avg_price_eur)],
    ['Costo AI totale', usd(data.total_ai_cost_usd)],
    ['Tempo di raccolta', duration(data.total_duration_sec)],
  ]
  return (
    <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
      {items.map(([k, v]) => (
        <div key={k} className="flex items-baseline gap-1.5">
          <dt className="text-ink-3">{k}</dt>
          <dd className="tnum font-semibold">{v}</dd>
        </div>
      ))}
    </dl>
  )
}

export function RunsPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { data: jobs, isLoading, error } = useJobs()
  const desktop = useMediaQuery('(min-width: 1024px)')
  const selectedId = id ? Number(id) : null
  const selected = jobs?.find((j) => j.id === selectedId)
  // Completed runs whose listings came back without a score: "completata" alone would read as all well.
  const { data: listings } = useListings()
  // The jobs list carries no logs. A run with listings but no AI count on record may be one whose AI
  // step crashed (its listings then stay unscored, not in error): only its log can tell, so fetch it.
  const needLog = useMemo(
    () => (jobs ?? []).filter((j) => j.status === 'done' && (j.listing_count ?? 0) > 0 && j.ai_scored_count == null),
    [jobs],
  )
  const details = useQueries({
    queries: needLog.map((j) => ({
      queryKey: keys.job(j.id),
      queryFn: () => api.job(j.id),
      // a finished run's log no longer changes; a copy fetched while it ran is refetched
      staleTime: (q: { state: { data?: Job } }) => (q.state.data && !isActive(q.state.data) ? Infinity : 0),
    })),
  })
  const logsKey = details.map((d) => (d.data && !isActive(d.data) ? d.dataUpdatedAt : 0)).join()
  const unscored = useMemo(() => {
    const logs = new Map<number, string | undefined>()
    needLog.forEach((j, i) => {
      const d = details[i]?.data
      logs.set(j.id, d && !isActive(d) ? (d.log ?? undefined) : undefined)
    })
    return new Set(
      (jobs ?? [])
        .filter((j) => j.status === 'done' && listings && notScored(buildVerbale(j, listings, logs.get(j.id))))
        .map((j) => j.id),
    )
  }, [jobs, listings, needLog, logsKey]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (desktop && selectedId == null && jobs?.length) navigate(`/run/${jobs[0].id}`, { replace: true })
  }, [desktop, selectedId, jobs, navigate])

  if (!desktop && selected) {
    return (
      <div className="flex h-[calc(100dvh-6.5rem)] flex-col md:h-full">
        <button type="button" onClick={() => navigate('/run')} className="border-b border-hair bg-sheet px-4 py-2 text-left text-sm font-semibold">
          ← Tutte le run
        </button>
        <JobPanel job={selected} onDeleted={() => navigate('/run')} />
      </div>
    )
  }

  const list = (
    <section className="flex min-h-0 flex-col bg-sheet md:h-full lg:border-r lg:border-hair">
      <div className="border-b border-hair px-4 py-3 lg:px-5">
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-bold">Run</h1>
          <div className="ml-auto">
            <RunLauncher />
          </div>
        </div>
        <div className="mt-2">
          <OverallStrip />
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {error ? <p className="p-5 text-sm text-destructive">{(error as Error).message}</p> : null}
        {isLoading ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : null}
        {jobs?.length === 0 ? (
          <div className="px-6 py-16 text-center">
            <p className="font-semibold">Nessuna run ancora</p>
            <p className="mt-1 text-sm text-ink-2">Avvia una ricerca: qui vedrai l’avanzamento in diretta e il log.</p>
          </div>
        ) : null}
        <ul>
          {jobs?.map((j) => {
            const sel = j.id === selectedId
            return (
              <li key={j.id}>
                <Link
                  to={`/run/${j.id}`}
                  className={cn(
                    'relative grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-0.5 border-b border-hair px-4 py-2.5 transition-colors lg:px-5',
                    sel ? 'bg-[#eef0ea]' : 'hover:bg-sheet-2',
                  )}
                >
                  <span className="truncate text-sm font-semibold">{j.config_name || `Ricerca ${j.config_id}`}</span>
                  <RunStatus status={j.status} />
                  <span className="tnum truncate text-xs text-ink-3">
                    #{j.id} · {relative(j.started_at)} · {isActive(j) ? 'in corso' : duration(elapsed(j))}
                  </span>
                  <span className="tnum text-right text-xs text-ink-2">
                    {j.listing_count != null ? `${j.listing_count} annunci` : '—'}
                    {unscored.has(j.id) ? <span className="font-semibold text-ink"> · non valutati</span> : null}
                  </span>
                  {sel ? (
                    <span className="absolute top-1/2 right-0 hidden h-4 w-2 -translate-y-1/2 bg-ink [clip-path:polygon(0_0,100%_50%,0_100%)] lg:block" />
                  ) : null}
                </Link>
              </li>
            )
          })}
        </ul>
      </div>
    </section>
  )

  if (!desktop) return list

  return (
    <div className="grid h-full grid-cols-[minmax(20rem,26rem)_1fr]">
      {list}
      <div className="min-h-0">
        {selected ? (
          <JobPanel key={selected.id} job={selected} onDeleted={() => navigate('/run')} />
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-ink-3">Seleziona una run.</div>
        )}
      </div>
    </div>
  )
}
