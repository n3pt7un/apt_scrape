import { useRef, useSyncExternalStore } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'

interface Ask {
  title: string
  body?: string
  confirmLabel: string
  destructive?: boolean
  resolve: (ok: boolean) => void
  /** What had focus when the question was asked: it gets focus back when the dialog closes. */
  returnTo: HTMLElement | null
}

let current: Ask | null = null
const listeners = new Set<() => void>()
const emit = () => listeners.forEach((l) => l())

/** Ask before a paid or destructive action, in the certificate's own dialog instead of the browser's. */
export function confirmAction(opts: Omit<Ask, 'resolve' | 'returnTo'>): Promise<boolean> {
  current?.resolve(false)
  const focused = document.activeElement
  return new Promise((resolve) => {
    current = { ...opts, resolve, returnTo: focused instanceof HTMLElement && focused !== document.body ? focused : null }
    emit()
  })
}

function settle(ok: boolean) {
  const ask = current
  current = null
  emit()
  ask?.resolve(ok)
}

export function ConfirmHost() {
  const ask = useSyncExternalStore(
    (l) => {
      listeners.add(l)
      return () => listeners.delete(l)
    },
    () => current,
  )
  const cancelRef = useRef<HTMLButtonElement>(null)
  const confirmRef = useRef<HTMLButtonElement>(null)
  // The question that is closing, so focus can go back where it was once the dialog has gone.
  const closing = useRef<Ask | null>(null)
  if (ask) closing.current = ask
  return (
    <Dialog open={!!ask} onOpenChange={(open) => !open && settle(false)}>
      <DialogContent
        showCloseButton={false}
        // Focus is placed once the dialog's focus trap is listening (React autoFocus fires before it,
        // so the trap could not hold it against a popover closing behind). A delete starts on Annulla.
        onOpenAutoFocus={(e) => {
          e.preventDefault()
          ;(current?.destructive ? cancelRef : confirmRef).current?.focus()
        }}
        onCloseAutoFocus={(e) => {
          e.preventDefault()
          const back = closing.current?.returnTo
          closing.current = null
          if (back?.isConnected) back.focus({ preventScroll: true })
        }}
        className="max-w-[calc(100%-2rem)] gap-0 rounded-md border-hair-strong bg-sheet p-0 shadow-[0_6px_24px_-6px_rgb(29_29_27/0.28),0_1px_2px_rgb(29_29_27/0.12)] sm:max-w-md"
      >
        <div className="border-b border-ink px-5 pt-4 pb-3">
          <DialogTitle className="text-lg leading-snug font-semibold text-ink">{ask?.title}</DialogTitle>
        </div>
        <DialogDescription asChild>
          <div className="px-5 py-4 text-sm leading-relaxed text-ink-2">{ask?.body}</div>
        </DialogDescription>
        {/* A held key never answers: Enter auto-repeating from whatever opened the dialog is ignored.
            A delete starts on Annulla; a paid action starts on its own button, one deliberate Enter away. */}
        <div className="flex justify-end gap-2 border-t border-hair px-5 py-3" onKeyDown={(e) => e.repeat && e.preventDefault()}>
          <Button ref={cancelRef} variant="outline" onClick={() => settle(false)}>
            Annulla
          </Button>
          <Button
            ref={confirmRef}
            onClick={() => settle(true)}
            className={ask?.destructive ? 'bg-destructive text-white hover:bg-destructive/90' : undefined}
          >
            {ask?.confirmLabel}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
