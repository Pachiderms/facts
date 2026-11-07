import { Plus, Search } from 'lucide-react'
import { useId, useState } from 'react'
import { CreateRoomForm } from '../components/arena/CreateRoomForm'
import { RoomList } from '../components/arena/RoomList'
import { useDebounced } from '../hooks/useDebounced'
import { useRoomLookup } from '../hooks/useRoomLookup'
import { useRooms } from '../hooks/useRooms'
import { roomHref } from '../lib/route'

/** Liste des salons, recherche (nom ou ID) et création. On débat dans la page d'un salon. */
export function ArenaPage() {
  const [query, setQuery] = useState('')
  const [creating, setCreating] = useState(false)
  const search = useDebounced(query.trim(), 300)
  const { rooms, error } = useRooms(search)
  const lookup = useRoomLookup(search.toLowerCase())
  const searchId = useId()

  // Un salon public trouvé par ID apparaît déjà dans la liste ; un salon privé, jamais : on l'affiche ici.
  const privateMatch = lookup.status === 'found' && lookup.lookup.requires_code ? lookup.lookup : null

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-xl font-extrabold text-neutral-900">Arène de débat</h1>
          <p className="mt-1 max-w-2xl text-xs leading-relaxed text-neutral-500">
            Rejoignez un salon pour débattre : chaque chiffre avancé est vérifié en direct et alimente un score de fiabilité factuelle. Les
            participants sont anonymes et sans étiquette politique.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setCreating((v) => !v)}
          aria-expanded={creating}
          className="flex shrink-0 items-center justify-center gap-2 rounded-xl bg-neutral-900 px-4 py-2.5 text-xs font-bold text-white shadow transition hover:bg-neutral-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900 focus-visible:ring-offset-2"
        >
          <Plus className="h-4 w-4" aria-hidden="true" /> Créer un salon
        </button>
      </div>

      {creating && <CreateRoomForm onCancel={() => setCreating(false)} />}

      <div className="relative">
        <label htmlFor={searchId} className="sr-only">
          Rechercher un salon par nom ou par identifiant
        </label>
        <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-neutral-400" aria-hidden="true" />
        <input
          id={searchId}
          type="search"
          value={query}
          maxLength={60}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Rechercher par nom ou par ID…"
          className="w-full rounded-xl border border-neutral-300 bg-white py-2.5 pl-11 pr-4 text-sm text-neutral-900 placeholder-neutral-400 focus:outline-none focus:ring-2 focus:ring-neutral-900"
        />
      </div>

      {privateMatch && (
        <section aria-label="Salon privé trouvé" className="space-y-2">
          <p className="text-xs text-neutral-600">
            Le salon <span className="font-mono font-bold text-neutral-900">{privateMatch.id}</span> est privé : le code d’accès vous sera demandé.
          </p>
          <a
            href={roomHref(privateMatch.id)}
            className="inline-block rounded-xl border border-neutral-900 bg-white px-4 py-2 text-xs font-bold text-neutral-900 hover:bg-neutral-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900"
          >
            Rejoindre le salon privé
          </a>
        </section>
      )}

      <RoomList rooms={rooms} error={error} searching={search !== ''} />

      <section className="max-w-xl space-y-2 rounded-2xl border border-neutral-200 bg-white p-4 text-xs shadow-sm">
        <h2 className="font-bold text-neutral-900">Neutralité factuelle</h2>
        <p className="text-[11px] leading-relaxed text-neutral-500">
          Le score évalue <strong>uniquement la rigueur factuelle</strong> des chiffres et des faits partagés, pas les opinions.
        </p>
      </section>
    </div>
  )
}

