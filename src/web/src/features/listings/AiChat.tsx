import { ArrowUp, Check, ChevronRight, Copy, MessagesSquare, ReceiptText, RotateCcw, ShieldCheck, Siren, Square } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { ScoreChevron } from '@/components/ape/Chevron'
import { Glasses, MilhouseAvatar, MilhouseLoader } from '@/components/milhouse/Glasses'
import { ChatContainerContent, ChatContainerRoot, ChatContainerScrollAnchor } from '@/components/ui/chat-container'
import { Markdown } from '@/components/ui/markdown'
import { PromptInput, PromptInputActions, PromptInputTextarea } from '@/components/ui/prompt-input'
import { ScrollButton } from '@/components/ui/scroll-button'
import { streamChatEvents } from '@/lib/api'
import { eur, splitTitle } from '@/lib/format'
import { setChat, useChat } from '@/lib/store'
import type { ChatMessage, Listing } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Thumb } from './ListingTable'

const STARTERS = [
  { icon: ShieldCheck, title: 'I miei requisiti', prompt: 'Rispetta i miei requisiti indispensabili?' },
  { icon: ReceiptText, title: 'Il costo vero', prompt: 'Quanto costa davvero al mese, spese incluse?' },
  { icon: MessagesSquare, title: 'Domande per l’agenzia', prompt: 'Cosa chiedo all’agenzia prima della visita?' },
  { icon: Siren, title: 'Segnali d’allarme', prompt: 'Ci sono segnali d’allarme in questo annuncio?' },
]

const READING_LINES = [
  'Milhouse si sistema gli occhiali…',
  'Rilegge l’annuncio riga per riga…',
  'Lo confronta con i tuoi criteri…',
]

// The model is told not to use emoji; this keeps them out even when it slips.
const EMOJI = /[\p{Extended_Pictographic}\u{FE0F}\u{20E3}]/gu
const clean = (text: string) => text.replace(EMOJI, '')

const secs = (ms: number | null | undefined) =>
  ms == null ? '' : ms < 1000 ? 'meno di un secondo' : `${(ms / 1000).toLocaleString('it-IT', { maximumFractionDigits: 1 })} s`

const controllers = new Map<number, AbortController>()

/**
 * Glasses that push up once (on mount, when `once`) and then rest; they loop only while Milhouse works.
 * The first loop's end is the cue to stop, so the gesture always finishes back in place.
 */
function PushingGlasses({ className, once = false, working = false }: { className?: string; once?: boolean; working?: boolean }) {
  const [first, setFirst] = useState(once)
  return (
    <span className="contents" onAnimationIteration={() => setFirst(false)}>
      <Glasses animate={working || first} className={className} />
    </span>
  )
}

/** The reasoning, Claude-style: a folded line while Milhouse thinks; open it to read along. */
function ThinkingBlock({ m }: { m: ChatMessage }) {
  const live = m.stage === 'thinking'
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (live && ref.current) ref.current.scrollTop = ref.current.scrollHeight
  }, [m.thinking, live])
  if (!m.thinking && !live) return null
  const expanded = open
  return (
    <div className="mb-3">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={expanded}
        className="group inline-flex items-center gap-2 text-sm text-mh-ink transition-colors hover:text-ink"
      >
        <Glasses animate={live} className="w-6 text-mh-ink" />
        <span className={cn(live && 'mh-shimmer')}>
          {live ? 'Milhouse ci pensa su…' : `Ci ha pensato ${secs(m.thinkingMs)}`}
        </span>
        <ChevronRight className={cn('size-3.5 transition-transform duration-200', open && 'rotate-90')} />
      </button>
      {expanded && m.thinking ? (
        <div
          ref={ref}
          className={cn(
            'mt-2 overflow-y-auto border-l-2 border-[var(--mh)] py-1 pr-2 pl-3 text-[0.8125rem] leading-relaxed whitespace-pre-wrap text-mh-ink',
            live ? 'max-h-32' : 'max-h-80',
          )}
        >
          {m.thinking}
        </div>
      ) : null}
    </div>
  )
}

function AssistantMessage({ m, last, onRetry }: { m: ChatMessage; last: boolean; onRetry: () => void }) {
  const [copied, setCopied] = useState(false)
  const streaming = m.stage === 'writing'
  const waiting = m.stage === 'reading'
  return (
    <div className="group/msg flex gap-3">
      <MilhouseAvatar className="mt-0.5" />
      <div className="min-w-0 flex-1">
        <p className="mb-1 text-xs font-bold text-mh-ink">Milhouse</p>
        <ThinkingBlock m={m} />
        {waiting ? <MilhouseLoader size="sm" lines={READING_LINES} className="py-1" /> : null}
        {m.error ? (
          <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2.5 text-sm">
            <p className="font-semibold text-destructive">Milhouse non è riuscito a rispondere</p>
            <p className="mt-0.5 text-ink-2">{m.content}</p>
            {last ? (
              <button
                type="button"
                onClick={onRetry}
                className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-ink underline underline-offset-2"
              >
                <RotateCcw className="size-3" /> Riprova
              </button>
            ) : null}
          </div>
        ) : m.content ? (
          <Markdown className={cn('md text-[0.9375rem] leading-relaxed text-ink', streaming && 'md-streaming')}>
            {clean(m.content)}
          </Markdown>
        ) : null}
        {m.stage === 'done' && !m.error ? (
          <div className="mt-2 flex items-center gap-1 text-xs text-ink-3 opacity-0 transition-opacity group-hover/msg:opacity-100 focus-within:opacity-100 [@media(hover:none)]:opacity-100">
            <button
              type="button"
              onClick={() => {
                void navigator.clipboard?.writeText(clean(m.content))
                setCopied(true)
                setTimeout(() => setCopied(false), 1500)
              }}
              className="inline-flex h-7 items-center gap-1 rounded-sm px-1.5 hover:bg-accent hover:text-ink"
            >
              {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
              {copied ? 'Copiata' : 'Copia'}
            </button>
            {last ? (
              <button
                type="button"
                onClick={onRetry}
                className="inline-flex h-7 items-center gap-1 rounded-sm px-1.5 hover:bg-accent hover:text-ink"
              >
                <RotateCcw className="size-3.5" /> Rigenera
              </button>
            ) : null}
            {m.elapsedMs ? <span className="tnum ml-1">risposto in {secs(m.elapsedMs)}</span> : null}
          </div>
        ) : null}
      </div>
    </div>
  )
}

/** Ephemeral Q&A about one listing, streamed as events: it lives until the page reloads. */
export function AiChat({ listing, className }: { listing: Listing; className?: string }) {
  const listingId = listing.id
  const messages = useChat(listingId)
  const [input, setInput] = useState('')
  const [deep, setDeep] = useState(false)
  const [, force] = useState(0)
  const streaming = controllers.has(listingId)
  const t = splitTitle(listing.title)

  const patchLast = (fn: (m: ChatMessage) => ChatMessage) =>
    setChat(listingId, (prev) => {
      const next = [...prev]
      next[next.length - 1] = fn(next[next.length - 1])
      return next
    })

  const ask = async (text: string, deepAsk = deep) => {
    const q = text.trim()
    if (!q || controllers.has(listingId)) return
    setInput('')
    const history: ChatMessage[] = [
      ...messages.filter((m) => !m.error && m.content),
      { role: 'user', content: q, deep: deepAsk },
    ]
    setChat(listingId, () => [...history, { role: 'assistant', content: '', stage: 'reading' }])
    const ctrl = new AbortController()
    controllers.set(listingId, ctrl)
    force((n) => n + 1)
    try {
      await streamChatEvents(listingId, history, { deep: deepAsk, signal: ctrl.signal }, (e) => {
        if (e.type === 'status') patchLast((m) => ({ ...m, stage: e.stage }))
        else if (e.type === 'thinking') patchLast((m) => ({ ...m, thinking: (m.thinking ?? '') + e.delta }))
        else if (e.type === 'text') patchLast((m) => ({ ...m, stage: 'writing', content: m.content + e.delta }))
        else if (e.type === 'done')
          patchLast((m) => ({ ...m, stage: 'done', elapsedMs: e.elapsed_ms, thinkingMs: e.thinking_ms }))
        else patchLast((m) => ({ ...m, stage: 'done', error: true, content: e.message }))
      })
    } catch (e) {
      if ((e as Error).name === 'AbortError')
        patchLast((m) => ({ ...m, stage: 'done', content: m.content || 'Risposta interrotta.' }))
      else patchLast((m) => ({ ...m, stage: 'done', error: true, content: (e as Error).message }))
    } finally {
      controllers.delete(listingId)
      force((n) => n + 1)
    }
  }

  const retry = () => {
    const lastUser = [...messages].reverse().find((m) => m.role === 'user')
    if (!lastUser) return
    setChat(listingId, (prev) => prev.slice(0, -2))
    void ask(lastUser.content, !!lastUser.deep)
  }

  // What Milhouse is reading: the listing, pinned like an attachment
  const pinned = (
    <div className="flex max-w-full items-center gap-3 self-start rounded-md border border-hair bg-sheet-2 py-1.5 pr-3 pl-1.5">
      <Thumb src={listing.thumbnail} className="h-9 w-12 shrink-0 rounded-[3px]" />
      <div className="min-w-0">
        <p className="truncate text-sm font-semibold" title={t.headline}>
          {t.headline}
        </p>
        <p className="tnum truncate text-xs text-ink-3">
          {eur(listing.price_eur)} · {listing.sqm_num ?? '—'} m² · {listing.source ?? 'portale'}
        </p>
      </div>
      <ScoreChevron listing={listing} size="sm" withTooltip={false} />
    </div>
  )

  return (
    <div className={cn('flex min-h-0 flex-col bg-sheet', className)}>
      {messages.length === 0 ? (
        // No stick-to-bottom before the first question: an empty chat reads from the top, pinned listing first.
        <div className="min-h-0 flex-1 overflow-y-auto [scrollbar-gutter:stable_both-edges]">
          <div className="mx-auto flex w-full max-w-[46rem] flex-col gap-6 px-5 pt-5 pb-8">
            {pinned}
            <div className="flex flex-col items-center pt-4 text-center">
              {/* Milhouse at the counter: his glasses on his own blue, pushed up once as he greets you. */}
              <span className="flex size-24 items-center justify-center rounded-full bg-[var(--mh)]">
                <PushingGlasses once className="w-16 text-ink" />
              </span>
              <h3 className="mt-5 text-2xl font-bold">Ciao, sono Milhouse.</h3>
              <p className="mt-1.5 max-w-[44ch] text-[0.9375rem] text-ink-2">
                Ho letto questo annuncio e i tuoi criteri, due volte. Se un dato non c’è non me lo invento: te lo
                dico e ti suggerisco cosa chiedere.
              </p>
              <div className="mt-6 w-full max-w-[34rem] text-left">
                <p className="label-caps border-b border-ink pb-1.5 text-mh-ink">Domande allo sportello</p>
                <ul>
                  {STARTERS.map((s) => (
                    <li key={s.title}>
                      <button
                        type="button"
                        onClick={() => ask(s.prompt)}
                        className="group flex w-full items-center gap-3 border-b border-hair px-1 py-2.5 text-left transition-colors hover:bg-[var(--mh-lens)] focus-visible:bg-[var(--mh-lens)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ink"
                      >
                        <s.icon className="size-4 shrink-0 text-ink-3 transition-colors group-hover:text-mh-ink" />
                        <span className="min-w-0 flex-1">
                          <span className="block text-sm font-semibold">{s.prompt}</span>
                        </span>
                        <span
                          className="chevron h-4 w-3 shrink-0 bg-hair-strong transition-colors [--tip:0.4rem] group-hover:bg-mh-ink group-focus-visible:bg-mh-ink"
                          aria-hidden
                        />
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        </div>
      ) : (
        <ChatContainerRoot className="relative min-h-0 flex-1">
          <ChatContainerContent className="mx-auto w-full max-w-[46rem] gap-6 px-5 pt-5 pb-8">
            {pinned}

            {messages.map((m, i) =>
              m.role === 'user' ? (
                <div key={i} className="ml-auto flex max-w-[85%] flex-col items-end gap-1">
                  <div className="rounded-md border border-hair bg-sheet-2 px-3.5 py-2 text-[0.9375rem] text-ink">
                    {m.content}
                  </div>
                  {m.deep ? (
                    <span className="inline-flex items-center gap-1 text-2xs font-semibold text-mh-ink">
                      <Glasses className="w-4" /> Pensaci bene
                    </span>
                  ) : null}
                </div>
              ) : (
                <AssistantMessage key={i} m={m} last={i === messages.length - 1} onRetry={retry} />
              ),
            )}
            <ChatContainerScrollAnchor />
          </ChatContainerContent>
          <div className="pointer-events-none absolute inset-x-0 bottom-2 flex justify-center">
            <ScrollButton
              aria-label="Vai all’ultima risposta"
              className="pointer-events-auto size-9 rounded-md border-hair-strong bg-sheet shadow-[0_6px_24px_-6px_rgb(29_29_27/0.28),0_1px_2px_rgb(29_29_27/0.12)]"
            />
          </div>
        </ChatContainerRoot>
      )}

      <div className="border-t border-hair bg-sheet px-3 pt-3 pb-2">
        <div className="mx-auto w-full max-w-[46rem]">
          <PromptInput
            value={input}
            onValueChange={setInput}
            isLoading={streaming}
            onSubmit={() => ask(input)}
            className={cn(
              'rounded-lg border bg-sheet p-2 shadow-[0_6px_20px_-12px_rgb(29_29_27/0.35)] transition-colors',
              deep ? 'border-[var(--mh)] focus-within:border-mh-ink' : 'border-hair-strong focus-within:border-ink',
            )}
          >
            <PromptInputTextarea
              placeholder={deep ? 'Milhouse ci penserà bene. Cosa vuoi sapere?' : 'Chiedi a Milhouse…'}
              className="min-h-[2.75rem] px-1.5 text-[0.9375rem] text-ink placeholder:text-ink-3"
            />
            <PromptInputActions className="items-center justify-between gap-2 pt-1">
              <button
                type="button"
                aria-pressed={deep}
                onClick={() => setDeep((d) => !d)}
                title="Più ragionamento per questa domanda: risposte più lente ma più accurate"
                className={cn(
                  'inline-flex h-8 items-center gap-1.5 rounded-sm border px-2.5 text-xs font-semibold transition-colors',
                  deep
                    ? 'border-[var(--mh)] bg-[var(--mh-lens)] text-mh-ink'
                    : 'border-hair-strong text-ink-3 hover:border-ink hover:text-ink',
                )}
              >
                <PushingGlasses key={String(deep)} once={deep} working={deep && streaming} className="w-5" /> Pensaci bene
              </button>
              {streaming ? (
                <button
                  type="button"
                  onClick={() => controllers.get(listingId)?.abort()}
                  aria-label="Ferma la risposta"
                  className="flex size-8 items-center justify-center rounded-sm bg-ink text-white hover:bg-ink/85"
                >
                  <Square className="size-3 fill-current" />
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => ask(input)}
                  disabled={!input.trim()}
                  aria-label="Invia domanda"
                  className="flex size-8 items-center justify-center rounded-sm bg-ink text-white transition-opacity hover:bg-ink/85 disabled:opacity-20"
                >
                  <ArrowUp className="size-4" />
                </button>
              )}
            </PromptInputActions>
          </PromptInput>
          <p className="mt-1.5 text-center text-2xs text-ink-3">
            Milhouse può sbagliare. Verifica sempre sul portale prima di chiamare.
          </p>
        </div>
      </div>
    </div>
  )
}
