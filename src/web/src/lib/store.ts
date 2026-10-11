import { useSyncExternalStore } from 'react'
import type { ChatMessage } from './types'

/** Minimal external store: module state that survives route changes, not reloads. */
function createStore<T>(initial: T) {
  let state = initial
  const listeners = new Set<() => void>()
  return {
    get: () => state,
    set: (next: T | ((prev: T) => T)) => {
      state = typeof next === 'function' ? (next as (p: T) => T)(state) : next
      listeners.forEach((l) => l())
    },
    subscribe: (l: () => void) => {
      listeners.add(l)
      return () => listeners.delete(l)
    },
  }
}

// ── Compare tray: up to three listings, kept for the session ────────────────
const COMPARE_KEY = 'confronta'
const readCompare = (): number[] => {
  try {
    const v = JSON.parse(sessionStorage.getItem(COMPARE_KEY) ?? '[]')
    return Array.isArray(v) ? v.filter((n) => typeof n === 'number').slice(0, 3) : []
  } catch {
    return []
  }
}
export const MAX_COMPARE = 3
export const compareStore = createStore<number[]>(readCompare())
compareStore.subscribe(() => {
  try {
    sessionStorage.setItem(COMPARE_KEY, JSON.stringify(compareStore.get()))
  } catch {
    /* storage unavailable: the tray still works for this page view */
  }
})
export const useCompare = () => useSyncExternalStore(compareStore.subscribe, compareStore.get)
export function toggleCompare(id: number): 'added' | 'removed' | 'full' {
  const cur = compareStore.get()
  if (cur.includes(id)) {
    compareStore.set(cur.filter((x) => x !== id))
    return 'removed'
  }
  if (cur.length >= MAX_COMPARE) return 'full'
  compareStore.set([...cur, id])
  return 'added'
}

// ── Ephemeral AI chats, one thread per listing ──────────────────────────────
export const chatStore = createStore<Record<number, ChatMessage[]>>({})
export const useChat = (listingId: number) =>
  useSyncExternalStore(chatStore.subscribe, () => chatStore.get()[listingId] ?? EMPTY)
const EMPTY: ChatMessage[] = []
export function setChat(listingId: number, update: (prev: ChatMessage[]) => ChatMessage[]) {
  chatStore.set((all) => ({ ...all, [listingId]: update(all[listingId] ?? []) }))
}
