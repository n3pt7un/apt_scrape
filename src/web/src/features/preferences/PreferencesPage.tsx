import { useQueryClient } from '@tanstack/react-query'
import { LoaderCircle, RefreshCw } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/lib/api'
import { relative, usd } from '@/lib/format'
import { keys, useListings, usePreferences } from '@/lib/queries'
import { confirmAction } from '@/components/shell/ConfirmHost'
import { useCostPerListing } from '@/lib/cost'

const SECTIONS = [
  { key: 'MUST HAVE', label: 'Indispensabili', hint: 'Se manca uno di questi, l’affinità crolla.' },
  { key: 'NICE TO HAVE', label: 'Graditi', hint: 'Alzano l’affinità quando ci sono.' },
  { key: 'DEAL BREAKERS', label: 'Esclusioni', hint: 'Bastano da soli a scartare un annuncio.' },
]

function outline(text: string) {
  return SECTIONS.map((s) => {
    const i = text.toUpperCase().indexOf(s.key)
    if (i < 0) return { ...s, count: null as number | null }
    const rest = text.slice(i + s.key.length)
    const next = SECTIONS.map((o) => rest.toUpperCase().indexOf(o.key)).filter((n) => n >= 0)
    const body = rest.slice(0, next.length ? Math.min(...next) : undefined)
    return { ...s, count: body.split('\n').filter((l) => /^\s*[-*•]/.test(l)).length }
  })
}

export function PreferencesPage() {
  const { data, isLoading, error } = usePreferences()
  const { data: listings } = useListings()
  const qc = useQueryClient()
  const [text, setText] = useState('')
  const [saving, setSaving] = useState(false)
  const [rescoring, setRescoring] = useState(false)
  const dirty = data != null && text !== data.content

  useEffect(() => {
    if (data) setText(data.content)
  }, [data])

  const save = async () => {
    setSaving(true)
    try {
      await api.savePreferences(text)
      qc.invalidateQueries({ queryKey: keys.preferences })
      toast.success('Criteri salvati', { description: 'Valgono dalla prossima valutazione.' })
    } catch (e) {
      toast.error('Criteri non salvati', { description: (e as Error).message })
    } finally {
      setSaving(false)
    }
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 's') {
        e.preventDefault()
        if (dirty && !saving) void save()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  // The same estimate every paid action quotes: the last runs' real AI cost per listing sent to the AI.
  const perListing = useCostPerListing()
  const toRescore = useMemo(() => (listings ?? []).filter((l) => l.triage_status !== 'scartato'), [listings])

  const rescoreAll = async () => {
    if (!toRescore.length) return
    const ok = await confirmAction({
      title: `Rivalutare ${toRescore.length} annunci con i criteri attuali?`,
      body: `Milhouse rilegge ogni annuncio: una chiamata all’AI per annuncio${
        perListing ? `, circa ${usd(perListing * toRescore.length)} in tutto` : ''
      }. Gli scartati restano fuori.`,
      confirmLabel: `Rivaluta ${toRescore.length} annunci`,
    })
    if (!ok) return
    setRescoring(true)
    try {
      const r = await api.rescoreMany(toRescore.map((l) => l.id))
      qc.invalidateQueries({ queryKey: keys.listings })
      if (r.errors) toast.warning(`${r.updated - r.errors} rivalutati, ${r.errors} falliti`)
      else toast.success(`${r.updated} annunci rivalutati`)
    } catch (e) {
      toast.error('Rivalutazione non riuscita', { description: (e as Error).message })
    } finally {
      setRescoring(false)
    }
  }

  const parts = outline(text)

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto grid max-w-6xl gap-8 px-4 py-5 lg:grid-cols-[1fr_18rem] lg:px-8 lg:py-8">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold">Criteri di valutazione</h1>
          <p className="mt-0.5 max-w-[62ch] text-sm text-ink-2">
            Milhouse legge questo testo per dare a ogni annuncio la sua affinità. Scrivilo come lo diresti al tuo migliore
            amico che ti aiuta a cercare casa: cosa è indispensabile, cosa è gradito, cosa lo esclude.
          </p>
          {error ? <p className="mt-4 text-sm text-destructive">{(error as Error).message}</p> : null}
          {isLoading ? (
            <Skeleton className="mt-5 h-96 w-full" />
          ) : (
            <div className="mt-5 rounded-sm border border-ink bg-sheet">
              <div className="flex h-10 items-center justify-between border-b border-hair px-4">
                <p className="label-caps text-ink">preferences.txt</p>
                <p className="text-xs text-ink-3">
                  {dirty ? 'Modifiche non salvate' : data?.last_saved ? `Salvato ${relative(data.last_saved)}` : 'Mai salvato'}
                </p>
              </div>
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                spellCheck
                className="block min-h-[28rem] w-full resize-y bg-sheet px-5 py-4 text-[0.9375rem] leading-relaxed text-ink focus:outline-none"
                placeholder={'Cerco un bilocale in affitto a Bologna…\n\nMUST HAVE:\n- Almeno 50 m²\n\nNICE TO HAVE:\n- Balcone\n\nDEAL BREAKERS:\n- Bagno in comune'}
                aria-label="Criteri di valutazione"
              />
              <div className="flex items-center gap-2 border-t border-hair px-4 py-3">
                <Button onClick={save} disabled={!dirty || saving}>
                  {saving ? <LoaderCircle className="size-4 animate-spin" /> : null}
                  Salva criteri
                </Button>
                {dirty ? (
                  <Button variant="ghost" onClick={() => setText(data?.content ?? '')}>
                    Annulla modifiche
                  </Button>
                ) : null}
                <kbd className="ml-auto hidden font-sans text-xs text-ink-3 sm:inline">⌘S per salvare</kbd>
              </div>
            </div>
          )}
        </div>
        <aside className="flex flex-col gap-4 lg:pt-[4.6rem]">
          <div className="rounded-sm border border-hair bg-sheet">
            <p className="label-caps border-b border-hair px-4 py-2.5 text-ink">Struttura</p>
            <ul>
              {parts.map((p) => (
                <li key={p.key} className="border-b border-hair px-4 py-3 last:border-b-0">
                  <p className="flex items-baseline justify-between text-sm font-semibold">
                    {p.label}
                    <span className="tnum text-xs font-normal text-ink-3">
                      {p.count == null ? 'sezione assente' : `${p.count} ${p.count === 1 ? 'voce' : 'voci'}`}
                    </span>
                  </p>
                  <p className="mt-0.5 text-xs text-ink-3">
                    {p.hint} Intestazione: <code className="font-mono text-[0.6875rem]">{p.key}:</code>
                  </p>
                </li>
              ))}
            </ul>
          </div>
          <div className="rounded-sm border border-hair bg-sheet p-4">
            <p className="text-sm font-semibold">Hai cambiato i criteri?</p>
            <p className="mt-0.5 text-xs text-ink-3">
              Gli annunci già trovati tengono la vecchia affinità finché non li rivaluti. Gli scartati sono esclusi.
            </p>
            <Button variant="outline" size="sm" className="mt-3 w-full" onClick={rescoreAll} disabled={rescoring || dirty || !toRescore.length}>
              {rescoring ? <LoaderCircle className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
              {rescoring ? 'Rivaluto…' : `Rivaluta ${toRescore.length} annunci`}
            </Button>
            {dirty ? <p className="mt-1.5 text-xs text-ink-3">Salva prima i criteri.</p> : null}
          </div>
        </aside>
      </div>
    </div>
  )
}
