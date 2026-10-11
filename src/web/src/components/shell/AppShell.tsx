import { useQueryClient } from '@tanstack/react-query'
import { Columns3, FileText, Map, Play, Rows3, SlidersHorizontal, Activity } from 'lucide-react'
import { motion } from 'motion/react'
import { useEffect, useRef } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router'
import { toast } from 'sonner'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { api } from '@/lib/api'
import { duration, parseDate } from '@/lib/format'
import { isActive, keys, useJobs, useListings } from '@/lib/queries'
import { useCompare } from '@/lib/store'
import type { Job } from '@/lib/types'
import { cn } from '@/lib/utils'
import { aiCount, buildVerbale, notScored } from '@/lib/verbale'
import { Glasses } from '@/components/milhouse/Glasses'
import { CommandPalette } from './CommandPalette'
import { ConfirmHost } from './ConfirmHost'
import { RunLauncher } from './RunLauncher'

const NAV = [
  { to: '/', label: 'Annunci', icon: Rows3, end: true, match: ['/', '/annunci'] },
  { to: '/mappa', label: 'Mappa', icon: Map },
  { to: '/confronta', label: 'Confronta', icon: Columns3, compare: true },
  { to: '/ricerche', label: 'Ricerche', icon: SlidersHorizontal },
  { to: '/run', label: 'Run', icon: Activity },
  { to: '/preferenze', label: 'Criteri', icon: FileText },
]

function Mark({ className }: { className?: string }) {
  // Milhouse's glasses, looking at the world through the APE ladder.
  return <Glasses ladder rim="var(--rail-ink)" className={cn('w-7', className)} />
}

function useUnseenCount() {
  const { data } = useListings()
  return data?.filter((l) => !l.seen_at && l.triage_status !== 'scartato').length ?? 0
}

/** A system notification (when allowed and the tab is hidden); clicking it brings the app back on `to`. */
function notify(title: string, body: string, to: string, navigate: (to: string) => void) {
  if (typeof Notification === 'undefined' || Notification.permission !== 'granted' || !document.hidden) return
  try {
    const n = new Notification(title, { body })
    n.onclick = () => {
      window.focus()
      navigate(to)
      n.close()
    }
  } catch {
    /* some browsers only allow notifications from a service worker: the toast still says it */
  }
}

/** Toast (and a system notification when allowed) the moment a run finishes. */
function useRunWatcher(jobs: Job[] | undefined) {
  const prev = useRef<Record<number, string> | null>(null)
  const maxId = useRef(0)
  const qc = useQueryClient()
  const navigate = useNavigate()
  useEffect(() => {
    if (!jobs) return
    // The first snapshot only records what is there: past runs are not news.
    const first = prev.current == null
    for (const j of jobs) {
      const before = prev.current?.[j.id]
      const wasActive = before === 'running' || before === 'pending'
      // A short run can start and finish between two polls: a new id that arrives already finished counts too.
      const missed = !first && before == null && j.id > maxId.current
      if ((wasActive || missed) && !isActive(j)) {
        qc.invalidateQueries({ queryKey: keys.listings })
        // Every cached certificate, the open one included: the run may have re-read or rescored it.
        qc.invalidateQueries({ queryKey: ['listing'] })
        qc.invalidateQueries({ queryKey: keys.job(j.id) })
        qc.invalidateQueries({ queryKey: keys.jobStats(j.id) })
        qc.invalidateQueries({ queryKey: keys.configs })
        qc.invalidateQueries({ queryKey: keys.overall })
        void announce(j)
      }
    }
    prev.current = Object.fromEntries(jobs.map((j) => [j.id, j.status]))
    for (const j of jobs) maxId.current = Math.max(maxId.current, j.id)

    async function announce(j: Job) {
      const name = j.config_name || `Ricerca ${j.config_id}`
      if (j.status !== 'done') {
        toast.error(`Run fallita · ${name}`, {
          description: 'Milhouse ci è rimasto male. Il log dice dove si è fermata.',
          action: { label: 'Apri log', onClick: () => navigate(`/run/${j.id}`) },
        })
        notify(`MilHouse · run n. ${j.id} fallita`, `${name}: il log dice dove si è fermata.`, `/run/${j.id}`, navigate)
        return
      }
      const n = j.listing_count ?? 0
      const examined = n
        ? `${name}: ${n} ${n === 1 ? 'annuncio esaminato' : 'annunci esaminati'}.`
        : `${name}: nessun annuncio stavolta.`
      // Whether the AI scored them is read from the same facts the verbale uses: the full log and the
      // listings as they are now. If either cannot be read, the toast says only what is certain.
      let unscored: { what: string; cause: string | null } | null = null
      if (n) {
        try {
          const [detail, listings] = await Promise.all([
            qc.fetchQuery({ queryKey: keys.job(j.id), queryFn: () => api.job(j.id) }),
            qc.fetchQuery({ queryKey: keys.listings, queryFn: api.listings }),
          ])
          const v = buildVerbale({ ...j, ...detail }, listings, detail.log)
          if (notScored(v)) unscored = { what: aiCount(v.ai), cause: v.ai.cause ? `${v.ai.cause.title}. ${v.ai.cause.fix}` : null }
        } catch {
          /* the verbale will still tell, once the feed loads */
        }
      }
      if (unscored) {
        // The run finished, the scoring did not: a warning that names the cause, not a success.
        const msg = `${examined} Valutazione AI non riuscita (${unscored.what}).`
        toast.warning(`Verbale n. ${j.id} · annunci non valutati`, {
          description: unscored.cause ? `${msg} ${unscored.cause}` : msg,
          duration: 12_000,
          action: { label: 'Leggi', onClick: () => navigate(`/?run=${j.id}`) },
        })
        notify(`MilHouse · verbale n. ${j.id}: annunci non valutati`, msg, `/?run=${j.id}`, navigate)
        return
      }
      // The verdict belongs to the verbale (it knows the scores); the toast only says it is filed.
      const msg = n ? `${examined} Il verbale è in cima agli annunci.` : examined
      toast.success(`Verbale n. ${j.id} di Milhouse`, {
        description: msg,
        action: { label: n ? 'Leggi' : 'Apri', onClick: () => navigate(n ? `/?run=${j.id}` : `/run/${j.id}`) },
      })
      notify(`MilHouse · verbale n. ${j.id}`, msg, n ? `/?run=${j.id}` : `/run/${j.id}`, navigate)
    }
  }, [jobs, qc, navigate])
}

function LiveRun({ job, compact }: { job: Job; compact?: boolean }) {
  const started = parseDate(job.started_at)
  const elapsed = started ? (Date.now() - started.getTime()) / 1000 : null
  return (
    <NavLink
      to={`/run/${job.id}`}
      className="group flex flex-col items-center rounded-sm border border-white/15 p-2.5 transition-colors hover:border-white/40 xl:block"
      title="Segui la run"
      aria-label={`Run in corso: ${job.config_name || `ricerca ${job.config_id}`}. Seguila`}
    >
      <span className="flex items-center gap-2">
        <Glasses animate rim="var(--rail-ink)" className="w-6" />
        {!compact && <span className="label-caps hidden text-rail-ink xl:inline">Run in corso</span>}
      </span>
      {!compact && (
        <span className="hidden xl:block">
          <span className="mt-1 block truncate text-sm font-semibold text-rail-ink">{job.config_name}</span>
          <span className="tnum block text-xs text-rail-muted">da {duration(elapsed)}</span>
        </span>
      )}
    </NavLink>
  )
}

export function AppShell() {
  const { data: jobs } = useJobs()
  useRunWatcher(jobs)
  const active = jobs?.find(isActive)
  const compare = useCompare()
  const unseen = useUnseenCount()
  const { pathname } = useLocation()

  const isOn = (item: (typeof NAV)[number]) =>
    item.match ? item.match.some((m) => (m === '/' ? pathname === '/' : pathname.startsWith(m))) : pathname.startsWith(item.to)

  return (
    <div className="flex min-h-dvh flex-col bg-paper md:h-dvh md:flex-row md:overflow-hidden">
      {/* Desktop rail */}
      <aside className="hidden shrink-0 flex-col bg-rail text-rail-ink md:flex md:w-16 xl:w-52">
        <div className="flex h-14 items-center gap-2.5 px-5 xl:px-4">
          <Mark />
          <span className="hidden text-base font-bold tracking-tight xl:inline">MilHouse</span>
        </div>
        <nav className="mt-2 flex flex-col gap-0.5 pr-0 pl-2 xl:pl-3" aria-label="Sezioni">
          {NAV.map((item) => {
            const on = isOn(item)
            const badge = item.compare ? compare.length : item.to === '/' ? unseen : 0
            const link = (
              <NavLink
                key={item.to}
                to={item.compare && compare.length ? `/confronta?ids=${compare.join(',')}` : item.to}
                aria-current={on ? 'page' : undefined}
                // From 768 to 1279px the label is hidden: the link still needs its name (and its count).
                aria-label={
                  !badge
                    ? item.label
                    : item.compare
                      ? `${item.label}, ${badge} ${badge === 1 ? 'annuncio' : 'annunci'}`
                      : `${item.label}, ${badge} da guardare`
                }
                className={cn(
                  'group relative isolate flex h-9 items-center gap-3 pr-4 pl-3 text-sm font-semibold transition-colors',
                  on ? 'text-ink' : 'rounded-l-sm text-rail-muted hover:bg-rail-hover hover:text-rail-ink',
                )}
              >
                {/* The white chevron tab is one object: it travels to the section you open. */}
                {on ? (
                  <motion.span
                    layoutId="rail-tab"
                    className="chevron absolute inset-0 -z-10 bg-sheet [--tip:0.6rem]"
                    transition={{ type: 'tween', duration: 0.24, ease: [0.16, 1, 0.3, 1] }}
                    aria-hidden
                  />
                ) : null}
                <item.icon className="size-4 shrink-0" strokeWidth={2} />
                <span className="hidden xl:inline">{item.label}</span>
                {badge ? (
                  <span
                    className={cn(
                      'tnum ml-auto hidden min-w-5 rounded-sm px-1 text-center text-2xs font-bold xl:inline',
                      on ? 'bg-ink text-white' : 'bg-white/12 text-rail-ink',
                    )}
                  >
                    {badge}
                  </span>
                ) : null}
              </NavLink>
            )
            return (
              <Tooltip key={item.to}>
                <TooltipTrigger asChild>{link}</TooltipTrigger>
                <TooltipContent side="right" className="xl:hidden">
                  {item.label}
                </TooltipContent>
              </Tooltip>
            )
          })}
        </nav>
        <div className="mt-auto flex flex-col gap-2 p-2 xl:p-3">
          {active ? <LiveRun job={active} /> : null}
          <RunLauncher
            side="right"
            align="end"
            trigger={
              <button
                type="button"
                aria-label="Avvia run"
                className="flex h-9 items-center justify-center gap-2 rounded-sm border border-white/25 text-sm font-semibold text-rail-ink transition-colors hover:border-white/60 hover:bg-rail-hover"
              >
                <Play className="size-3.5 fill-current" />
                <span className="hidden xl:inline">Avvia run</span>
              </button>
            }
          />
          <p className="hidden px-1 text-2xs text-rail-muted xl:block">
            <kbd className="font-sans font-semibold text-rail-ink">⌘K</kbd> per cercare e comandare
          </p>
        </div>
      </aside>

      {/* Phone header */}
      <header className="sticky top-0 z-30 flex h-12 items-center gap-2.5 bg-rail px-4 text-rail-ink md:hidden">
        <Mark />
        <span className="text-base font-bold tracking-tight">MilHouse</span>
        {active ? (
          <NavLink to={`/run/${active.id}`} className="ml-2 flex items-center gap-1.5 text-xs text-rail-muted">
            <span className="size-1.5 animate-pulse rounded-full bg-r-3" /> run in corso
          </NavLink>
        ) : null}
        <div className="ml-auto">
          <RunLauncher
            trigger={
              <button
                type="button"
                className="flex h-8 items-center gap-1.5 rounded-sm bg-sheet px-2.5 text-xs font-semibold text-ink"
              >
                <Play className="size-3 fill-current" /> Avvia
              </button>
            }
          />
        </div>
      </header>

      <main className="min-w-0 flex-1 pb-16 md:overflow-hidden md:pb-0">
        <Outlet />
      </main>

      {/* Phone tab bar */}
      <nav
        className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-6 border-t border-black bg-rail pb-[env(safe-area-inset-bottom)] md:hidden"
        aria-label="Sezioni"
      >
        {NAV.map((item) => {
          const on = isOn(item)
          const badge = item.compare ? compare.length : item.to === '/' ? unseen : 0
          return (
            <NavLink
              key={item.to}
              to={item.compare && compare.length ? `/confronta?ids=${compare.join(',')}` : item.to}
              className={cn(
                'relative flex h-14 flex-col items-center justify-center gap-0.5 text-[0.6875rem] font-semibold',
                on ? 'text-rail-ink' : 'text-rail-muted',
              )}
            >
              {on ? (
                <motion.span
                  layoutId="tab-bar"
                  className="absolute top-0 h-0.5 w-8 bg-sheet"
                  transition={{ type: 'tween', duration: 0.24, ease: [0.16, 1, 0.3, 1] }}
                />
              ) : null}
              <item.icon className="size-[1.125rem]" />
              {item.label}
              {badge ? (
                <span className="tnum absolute top-1 left-[calc(50%+0.55rem)] min-w-4 rounded-sm bg-sheet px-0.5 text-center text-2xs leading-4 font-bold text-ink">
                  {badge}
                </span>
              ) : null}
            </NavLink>
          )
        })}
      </nav>
      <CommandPalette />
      <ConfirmHost />
    </div>
  )
}
