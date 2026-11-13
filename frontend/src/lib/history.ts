/**
 * « Mes salons » : historique local (ce navigateur uniquement, sans compte).
 * Les données stockées ne sont jamais crues sur parole : chaque entrée est revalidée à la lecture.
 */
import { ROOM_ID_RE } from './route'

const KEY = 'facts.history'
export const HISTORY_MAX = 20

export interface HistoryEntry {
  id: string
  title: string
  visibility: 'public' | 'private'
  /** Code d'un salon privé : gardé sur CET appareil pour revenir sans le redemander. */
  code?: string
  owner: boolean
  pinned: boolean
  /** Dernière visite, en ms depuis l'époque. */
  lastVisit: number
}

const CODE_RE = /^[A-Za-z0-9]{1,16}$/

function parseEntry(raw: unknown): HistoryEntry | null {
  if (typeof raw !== 'object' || raw === null) return null
  const e = raw as Record<string, unknown>
  if (typeof e.id !== 'string' || !ROOM_ID_RE.test(e.id)) return null
  if (typeof e.title !== 'string' || e.title.length === 0) return null
  if (e.visibility !== 'public' && e.visibility !== 'private') return null
  if (typeof e.lastVisit !== 'number' || !Number.isFinite(e.lastVisit)) return null
  const code = typeof e.code === 'string' && CODE_RE.test(e.code) ? e.code : undefined
  return {
    id: e.id,
    title: e.title.slice(0, 120),
    visibility: e.visibility,
    ...(code ? { code } : {}),
    owner: e.owner === true,
    pinned: e.pinned === true,
    lastVisit: e.lastVisit,
  }
}

function sorted(entries: HistoryEntry[]): HistoryEntry[] {
  return [...entries].sort((a, b) => Number(b.pinned) - Number(a.pinned) || b.lastVisit - a.lastVisit)
}

export function loadHistory(): HistoryEntry[] {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(KEY) ?? '[]')
    if (!Array.isArray(raw)) return []
    const seen = new Set<string>()
    const entries: HistoryEntry[] = []
    for (const item of raw) {
      const entry = parseEntry(item)
      if (entry && !seen.has(entry.id)) {
        seen.add(entry.id)
        entries.push(entry)
      }
    }
    return sorted(entries).slice(0, HISTORY_MAX)
  } catch {
    return [] // JSON corrompu ou stockage bloqué : historique vide, jamais d'exception
  }
}

type Listener = (entries: HistoryEntry[], source: 'local' | 'sync') => void
const listeners = new Set<Listener>()

/** Notifie chaque écriture (source « sync » : fusion venue du serveur, à ne pas renvoyer au serveur). */
export function subscribeHistory(listener: Listener): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

function save(entries: HistoryEntry[], source: 'local' | 'sync' = 'local'): HistoryEntry[] {
  // Au-delà de la limite, on retire d'abord les plus anciennes entrées NON épinglées.
  let kept = sorted(entries)
  while (kept.length > HISTORY_MAX) {
    const drop = [...kept].reverse().find((e) => !e.pinned) ?? kept[kept.length - 1]!
    kept = kept.filter((e) => e !== drop)
  }
  try {
    localStorage.setItem(KEY, JSON.stringify(kept))
  } catch {
    /* stockage plein ou bloqué : l'historique de cette session seulement */
  }
  listeners.forEach((l) => l(kept, source))
  return kept
}

/**
 * Fusion avec l'historique du compte. Les codes d'accès restent sur l'appareil (jamais envoyés au serveur).
 * - `union` (première synchronisation de cet appareil) : on garde tout, la visite la plus récente fait foi
 *   pour le titre et l'épingle, « créateur » l'emporte.
 * - sinon le serveur fait foi (une suppression faite ailleurs ne ressuscite pas).
 */
export function mergeHistory(local: HistoryEntry[], remote: HistoryEntry[], union: boolean): HistoryEntry[] {
  const localById = new Map(local.map((e) => [e.id, e]))
  const withCode = (e: HistoryEntry): HistoryEntry => {
    const code = localById.get(e.id)?.code
    return code && e.visibility === 'private' ? { ...e, code } : e
  }
  if (!union) return sorted(remote.map(withCode)).slice(0, HISTORY_MAX)
  const merged = new Map<string, HistoryEntry>()
  for (const e of [...local, ...remote]) {
    const prev = merged.get(e.id)
    if (!prev) {
      merged.set(e.id, e)
      continue
    }
    const newer = e.lastVisit >= prev.lastVisit ? e : prev
    const code = prev.code ?? e.code
    merged.set(e.id, { ...newer, owner: prev.owner || e.owner, ...(code ? { code } : {}) })
  }
  return sorted([...merged.values()].map(withCode)).slice(0, HISTORY_MAX)
}

/** Remplace l'historique local par le résultat d'une synchronisation. */
export function applySynced(entries: HistoryEntry[]): HistoryEntry[] {
  return save(entries, 'sync')
}

type Visit = Pick<HistoryEntry, 'id' | 'title' | 'visibility'> & { code?: string; owner?: boolean }

/** Enregistre (ou rafraîchit) une visite : remonte en tête, garde l'épingle et le statut de créateur. */
export function recordVisit(visit: Visit, now = Date.now()): HistoryEntry[] {
  const entries = loadHistory()
  const previous = entries.find((e) => e.id === visit.id)
  const code = visit.code && CODE_RE.test(visit.code) ? visit.code : previous?.code
  const entry: HistoryEntry = {
    id: visit.id,
    title: visit.title.slice(0, 120),
    visibility: visit.visibility,
    ...(visit.visibility === 'private' && code ? { code } : {}),
    owner: Boolean(visit.owner) || Boolean(previous?.owner),
    pinned: previous?.pinned ?? false,
    lastVisit: now,
  }
  return save([entry, ...entries.filter((e) => e.id !== visit.id)])
}

export function removeEntry(id: string): HistoryEntry[] {
  return save(loadHistory().filter((e) => e.id !== id))
}

export function togglePin(id: string): HistoryEntry[] {
  return save(loadHistory().map((e) => (e.id === id ? { ...e, pinned: !e.pinned } : e)))
}

export function historyCode(id: string): string | undefined {
  return loadHistory().find((e) => e.id === id)?.code
}
