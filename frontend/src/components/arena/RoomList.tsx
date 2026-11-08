import { RefreshCw, Users } from 'lucide-react'
import { useState } from 'react'
import type { RoomSummary } from '../../api/types'
import { formatScore, themeBadge, trustTone } from '../../lib/presentation'
import { roomHref } from '../../lib/route'

interface Props {
  rooms: RoomSummary[] | null
  error: string | null
  /** Recherche en cours : adapte le message « aucun résultat ». */
  searching: boolean
}

const PAGE_SIZE = 9

export function RoomList({ rooms, error, searching }: Props) {
  const [theme, setTheme] = useState<string>('all')
  const [shown, setShown] = useState(PAGE_SIZE)

  // Filtres proposés : uniquement les thèmes réellement présents dans la liste.
  const themes = [...new Set((rooms ?? []).map((r) => r.theme_category))]
  const activeTheme = themes.includes(theme) ? theme : 'all'
  const filtered = (rooms ?? []).filter((r) => activeTheme === 'all' || r.theme_category === activeTheme)
  const visible = filtered.slice(0, shown)

  return (
    <section aria-label="Salons de débat" className="space-y-3">
      {themes.length > 1 && (
        <div role="group" aria-label="Filtrer par thème" className="flex flex-wrap gap-2">
          {['all', ...themes].map((t) => (
            <button
              key={t}
              type="button"
              aria-pressed={activeTheme === t}
              onClick={() => {
                setTheme(t)
                setShown(PAGE_SIZE)
              }}
              className={`rounded-full border px-3 py-1 text-[11px] font-bold focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900 ${
                activeTheme === t ? 'border-neutral-900 bg-neutral-900 text-white' : 'border-neutral-200 bg-white text-neutral-700 hover:border-neutral-400'
              }`}
            >
              {t === 'all' ? 'Tous' : themeBadge(t).name}
            </button>
          ))}
        </div>
      )}

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
      {rooms?.length === 0 && (
        <p className="rounded-2xl border border-dashed border-neutral-300 bg-white p-8 text-center text-sm text-neutral-500">
          {searching ? 'Aucun salon public ne correspond à cette recherche.' : 'Aucun salon ouvert pour le moment.'}
        </p>
      )}

      <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {visible.map((room) => (
          <li key={room.id}>
            <RoomCard room={room} />
          </li>
        ))}
      </ul>

      {filtered.length > shown && (
        <div className="text-center">
          <button
            type="button"
            onClick={() => setShown((n) => n + PAGE_SIZE)}
            className="rounded-xl border border-neutral-300 bg-white px-5 py-2 text-xs font-bold text-neutral-800 hover:border-neutral-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900"
          >
            Voir plus ({filtered.length - shown})
          </button>
        </div>
      )}
    </section>
  )
}

/** Carte blanche : seul le badge de thème est coloré. Un lien, donc ouvrable dans un nouvel onglet. */
function RoomCard({ room }: { room: RoomSummary }) {
  const badge = themeBadge(room.theme_category)
  const tone = trustTone(room.trust_score)
  return (
    <a
      href={roomHref(room.id)}
      className="block h-full rounded-xl border border-neutral-200 bg-white p-4 shadow-sm transition-all hover:border-neutral-400 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900"
    >
      <span className={`mb-2 inline-block rounded border px-2 py-0.5 text-[10px] font-bold ${badge.badge}`}>{badge.name}</span>
      <span className="line-clamp-3 block text-sm font-bold leading-snug text-neutral-900">{room.title}</span>
      <span className="mt-4 flex items-center justify-between border-t border-neutral-100 pt-2 text-[11px] text-neutral-500">
        <span className="flex items-center gap-1 font-medium text-neutral-600">
          <Users className="h-3 w-3 text-neutral-400" aria-hidden="true" />
          {room.participants}/{room.max_participants} intervenants
          {room.spectators > 0 && ` · ${room.spectators} spect.`}
        </span>
        <span className={`rounded px-1.5 py-0.5 font-mono font-bold ${tone.badge}`}>Score : {formatScore(room.trust_score)}</span>
      </span>
    </a>
  )
}
