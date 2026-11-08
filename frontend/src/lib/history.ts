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

function save(entries: HistoryEntry[]): HistoryEntry[] {
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
  return kept
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
