import { Eye, Lock, Pin, PinOff, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { roomsStatus } from '../../api/client'
import { loadHistory, removeEntry, togglePin, type HistoryEntry } from '../../lib/history'
import { timeAgo } from '../../lib/presentation'
import { roomHref } from '../../lib/route'
import { DeleteRoomButton } from './DeleteRoomButton'

/** Historique local : retrouver un salon quitté (surtout un salon privé, jamais listé). */
export function MyRooms() {
  const [entries, setEntries] = useState<HistoryEntry[]>(() => loadHistory())
  // `null` tant que le serveur n'a pas répondu : on n'affiche alors aucun « Expiré » (pas de faux négatif).
  const [existing, setExisting] = useState<Set<string> | null>(null)
  const idsKey = entries.map((e) => e.id).join(',')

  useEffect(() => {
    if (!idsKey) return
    const controller = new AbortController()
    roomsStatus(idsKey.split(','), controller.signal)
      .then((ids) => setExisting(new Set(ids)))
      .catch(() => undefined) // statut inconnu : on laisse tout cliquable
    return () => controller.abort()
  }, [idsKey])

  if (entries.length === 0) return null

  return (
    <section aria-label="Mes salons" className="space-y-3">
      <h2 className="text-sm font-extrabold text-neutral-900">
        Mes salons <span className="font-mono text-xs font-bold text-neutral-400">{entries.length}</span>
      </h2>
      <ul className="divide-y divide-neutral-100 rounded-2xl border border-neutral-200 bg-white shadow-sm">
        {entries.map((entry) => {
          const expired = existing !== null && !existing.has(entry.id)
          return (
            <li key={entry.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3">
              <div className="min-w-0 flex-1">
                <a
                  href={roomHref(entry.id)}
                  className={`flex items-center gap-1.5 text-sm font-bold hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900 ${
                    expired ? 'text-neutral-400' : 'text-neutral-900'
                  }`}
                >
                  {entry.visibility === 'private' && <Lock className="h-3 w-3 shrink-0" aria-label="Salon privé" />}
                  <span className="truncate">{entry.title}</span>
                </a>
                <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-neutral-500">
                  <span className="font-mono">{entry.id}</span>
                  <span>·</span>
                  <span>{timeAgo(entry.lastVisit)}</span>
                  {entry.owner && <span className="rounded border border-neutral-200 bg-neutral-100 px-1.5 py-0.5 font-bold text-neutral-700">Créateur</span>}
                  {expired && <span className="rounded border border-neutral-300 bg-neutral-100 px-1.5 py-0.5 font-bold text-neutral-600">Expiré</span>}
                </p>
              </div>

              <div className="flex items-center gap-1.5">
                {!expired && (
                  // Entrer en spectateur, sans prendre de siège ; le code d'un salon privé vient de l'historique.
                  <a
                    href={roomHref(entry.id, true)}
                    aria-label={`Regarder ${entry.title} en spectateur`}
                    title="Regarder en spectateur"
                    className="rounded-lg border border-neutral-200 p-1.5 text-neutral-600 hover:border-neutral-400 hover:text-neutral-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900"
                  >
                    <Eye className="h-3.5 w-3.5" aria-hidden="true" />
                  </a>
                )}
                {entry.owner && !expired && <DeleteRoomButton roomId={entry.id} compact onDeleted={() => setEntries(removeEntry(entry.id))} />}
                <button
                  type="button"
                  onClick={() => setEntries(togglePin(entry.id))}
                  aria-pressed={entry.pinned}
                  aria-label={entry.pinned ? `Désépingler ${entry.title}` : `Épingler ${entry.title}`}
                  className="rounded-lg border border-neutral-200 p-1.5 text-neutral-600 hover:border-neutral-400 hover:text-neutral-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900"
                >
                  {entry.pinned ? <PinOff className="h-3.5 w-3.5" aria-hidden="true" /> : <Pin className="h-3.5 w-3.5" aria-hidden="true" />}
                </button>
                <button
                  type="button"
                  onClick={() => setEntries(removeEntry(entry.id))}
                  aria-label={`Retirer ${entry.title} de l’historique`}
                  className="rounded-lg border border-neutral-200 p-1.5 text-neutral-600 hover:border-neutral-400 hover:text-neutral-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900"
                >
                  <X className="h-3.5 w-3.5" aria-hidden="true" />
                </button>
              </div>
            </li>
          )
        })}
      </ul>
      <p className="text-[11px] text-neutral-500">Historique enregistré sur cet appareil uniquement. Un salon vide depuis 30 minutes est supprimé.</p>
    </section>
  )
}
