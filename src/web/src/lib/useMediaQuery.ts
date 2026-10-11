import { useCallback, useLayoutEffect, useMemo, useState, useSyncExternalStore } from 'react'

export function useMediaQuery(query: string): boolean {
  // Stable per query: a new subscribe function on every render would make React re-subscribe each time.
  const mql = useMemo(() => window.matchMedia(query), [query])
  const subscribe = useCallback(
    (cb: () => void) => {
      mql.addEventListener('change', cb)
      return () => mql.removeEventListener('change', cb)
    },
    [mql],
  )
  const getSnapshot = useCallback(() => mql.matches, [mql])
  return useSyncExternalStore(subscribe, getSnapshot)
}

/** Width of an element, kept current: lets a pane lay itself out by its own size, not the window's. */
export function useElementWidth(ref: React.RefObject<HTMLElement | null>): number {
  const [width, setWidth] = useState(0)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    setWidth(el.getBoundingClientRect().width)
    const ro = new ResizeObserver(([entry]) => setWidth(entry.borderBoxSize[0]?.inlineSize ?? el.getBoundingClientRect().width))
    ro.observe(el)
    return () => ro.disconnect()
  }, [ref])
  return width
}
