import { RefreshCw, Scale, Users } from 'lucide-react'
import type { RoomSummary } from '../../api/types'
import { formatScore, themeBadge, trustTone } from '../../lib/presentation'

interface Props {
  rooms: RoomSummary[] | null
  error: string | null
  selectedId: string | null
  onSelect: (id: string) => void
}

export function RoomList({ rooms, error, selectedId, onSelect }: Props) {
  return (
    <aside className="space-y-4">
      <section className="rounded-2xl border border-neutral-200 bg-white p-4 shadow-sm" aria-label="Salons de débat">
        <h2 className="mb-3 font-mono text-xs font-bold uppercase tracking-wider text-neutral-500">Salons de débat</h2>

        {rooms === null && !error && (
          <p className="flex items-center gap-2 text-xs text-neutral-500" role="status">
            <RefreshCw className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> Chargement des salons…
          </p>
        )}
        {error && rooms === null && (
          <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-900">
            {error} Nouvelle tentative automatique…
          </p>
        )}

        <ul className="space-y-2.5">
          {rooms?.map((room) => {
            const selected = room.id === selectedId
            const badge = themeBadge(room.theme_category)
            const tone = trustTone(room.trust_score)
            return (
              <li key={room.id}>
                {/* Carte blanche : seul le badge de thème est coloré. */}
                <button
                  type="button"
                  onClick={() => onSelect(room.id)}
                  aria-pressed={selected}
                  className={`w-full rounded-xl border bg-white p-3.5 text-left transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900 ${
                    selected ? 'border-neutral-900 shadow-md ring-2 ring-neutral-900' : 'border-neutral-200 hover:border-neutral-300'
                  }`}
                >
                  <span className={`mb-2 inline-block rounded border px-2 py-0.5 text-[10px] font-bold ${badge.badge}`}>{badge.name}</span>
                  <span className="line-clamp-2 block text-xs font-bold leading-snug text-neutral-900">{room.title}</span>
                  <span className="mt-3 flex items-center justify-between border-t border-neutral-100 pt-2 text-[11px] text-neutral-500">
                    <span className="flex items-center gap-1 font-medium text-neutral-600">
                      <Users className="h-3 w-3 text-neutral-400" aria-hidden="true" />
                      {room.participants}/2 intervenants
                    </span>
                    <span className={`rounded px-1.5 py-0.5 font-mono font-bold ${tone.badge}`}>Score : {formatScore(room.trust_score)}</span>
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      </section>

      <section className="space-y-2 rounded-2xl border border-neutral-200 bg-white p-4 text-xs shadow-sm">
        <h3 className="flex items-center gap-1.5 font-bold text-neutral-900">
          <Scale className="h-3.5 w-3.5 text-neutral-700" aria-hidden="true" /> Neutralité factuelle
        </h3>
        <p className="text-[11px] leading-relaxed text-neutral-500">
          Le score évalue <strong>uniquement la rigueur factuelle</strong> des chiffres et des faits partagés. Les participants sont anonymes et
          sans étiquette politique.
        </p>
      </section>
    </aside>
  )
}
