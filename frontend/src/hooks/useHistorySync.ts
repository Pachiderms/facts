import { useEffect } from 'react'
import { ApiError, fetchHistory, pushHistory, type RemoteHistoryEntry } from '../api/client'
import { applySynced, loadHistory, mergeHistory, subscribeHistory, type HistoryEntry } from '../lib/history'
import { getSession } from '../lib/session'

const SYNCED_KEY = 'facts.historySyncedFor'
const PUSH_DELAY_MS = 1000

const toRemote = (e: HistoryEntry): RemoteHistoryEntry => ({
  id: e.id,
  title: e.title,
  visibility: e.visibility,
  owner: e.owner,
  pinned: e.pinned,
  lastVisit: Math.round(e.lastVisit),
})

const fromRemote = (e: RemoteHistoryEntry): HistoryEntry => e

function alreadySynced(userId: string): boolean {
  try {
    return localStorage.getItem(SYNCED_KEY) === userId
  } catch {
    return false
  }
}

function markSynced(userId: string): void {
  try {
    localStorage.setItem(SYNCED_KEY, userId)
  } catch {
    /* sans stockage : fusion complète à chaque chargement, sans conséquence */
  }
}

/**
 * Historique « Mes salons » synchronisé avec le compte. Hors connexion, rien ne change (historique local).
 * Connecté : fusion au chargement, puis envoi (légèrement différé) de chaque modification locale.
 * Une erreur réseau ne perd rien : l'historique local reste la référence de l'appareil.
 */
export function useHistorySync(userId: string | null): void {
  useEffect(() => {
    if (!userId) return
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const controller = new AbortController()

    const push = () => {
      const token = getSession()
      if (!token || !alive) return
      pushHistory(token, loadHistory().map(toRemote), controller.signal).catch(() => undefined)
    }

    const unsubscribe = subscribeHistory((_, source) => {
      if (source === 'sync') return
      clearTimeout(timer)
      timer = setTimeout(push, PUSH_DELAY_MS)
    })

    void (async () => {
      const token = getSession()
      if (!token) return
      try {
        const remote = (await fetchHistory(token, controller.signal)).map(fromRemote)
        if (!alive) return
        const union = !alreadySynced(userId)
        const merged = mergeHistory(loadHistory(), remote, union)
        applySynced(merged)
        markSynced(userId)
        if (union) await pushHistory(token, merged.map(toRemote), controller.signal)
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return // session révoquée : gérée par l'authentification
      }
    })()

    return () => {
      alive = false
      clearTimeout(timer)
      unsubscribe()
      controller.abort()
    }
  }, [userId])
}
