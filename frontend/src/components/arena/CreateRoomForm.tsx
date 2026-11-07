import { Globe, Lock } from 'lucide-react'
import { useId, useRef, useState, type FormEvent } from 'react'
import { createRoom } from '../../api/client'
import { ROOM_TITLE_MAX, ROOM_TITLE_MIN, type Visibility } from '../../api/types'
import { rememberCode } from '../../lib/identity'
import { CREATABLE_THEMES, themeBadge } from '../../lib/presentation'
import { roomHref } from '../../lib/route'

export function CreateRoomForm({ onCancel }: { onCancel: () => void }) {
  const [title, setTitle] = useState('')
  const [theme, setTheme] = useState<string>(CREATABLE_THEMES[0])
  const [visibility, setVisibility] = useState<Visibility>('public')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inFlight = useRef(false)
  const ids = { title: useId(), theme: useId() }

  const trimmed = title.trim()
  const tooShort = trimmed.length < ROOM_TITLE_MIN
  const canSubmit = !tooShort && !busy

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!canSubmit || inFlight.current) return // un double clic ne crée pas deux salons
    inFlight.current = true
    setBusy(true)
    setError(null)
    try {
      const created = await createRoom({ title: trimmed, theme_category: theme, visibility })
      // Le propriétaire entre sans code (le serveur le reconnaît) ; on garde le code pour un rechargement.
      if (created.access_code) rememberCode(created.id, created.access_code)
      window.location.hash = roomHref(created.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Création impossible. Réessayez.')
      inFlight.current = false
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} aria-label="Créer un salon" className="space-y-4 rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm">
      <h2 className="text-sm font-extrabold text-neutral-900">Créer un salon de débat</h2>

      <div className="space-y-1.5">
        <label htmlFor={ids.title} className="text-xs font-bold text-neutral-800">
          Sujet du débat
        </label>
        <input
          id={ids.title}
          type="text"
          value={title}
          maxLength={ROOM_TITLE_MAX}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Ex. : Faut-il instaurer un revenu universel en France ?"
          className="w-full rounded-xl border border-neutral-300 bg-neutral-50 px-4 py-2.5 text-sm text-neutral-900 placeholder-neutral-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-neutral-900"
        />
        <p className={`text-[11px] ${tooShort && trimmed.length > 0 ? 'text-amber-700' : 'text-neutral-500'}`}>
          {trimmed.length}/{ROOM_TITLE_MAX} · formulez une question neutre, au moins {ROOM_TITLE_MIN} caractères
        </p>
      </div>

      <div className="space-y-1.5">
        <label htmlFor={ids.theme} className="text-xs font-bold text-neutral-800">
          Thème
        </label>
        <select
          id={ids.theme}
          value={theme}
          onChange={(e) => setTheme(e.target.value)}
          className="w-full rounded-xl border border-neutral-300 bg-neutral-50 px-3 py-2.5 text-sm text-neutral-900 focus:bg-white focus:outline-none focus:ring-2 focus:ring-neutral-900"
        >
          {CREATABLE_THEMES.map((t) => (
            <option key={t} value={t}>
              {themeBadge(t).name}
            </option>
          ))}
        </select>
      </div>

      <fieldset className="space-y-2">
        <legend className="text-xs font-bold text-neutral-800">Visibilité</legend>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {(
            [
              ['public', Globe, 'Public', 'Visible dans la liste et la recherche.'],
              ['private', Lock, 'Privé', 'Accessible uniquement avec un code à partager.'],
            ] as const
          ).map(([value, Icon, label, help]) => (
            <label
              key={value}
              className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3 text-xs ${
                visibility === value ? 'border-neutral-900 ring-1 ring-neutral-900' : 'border-neutral-200 hover:border-neutral-300'
              }`}
            >
              <input
                type="radio"
                name="visibility"
                value={value}
                checked={visibility === value}
                onChange={() => setVisibility(value)}
                className="mt-0.5 accent-neutral-900"
              />
              <span>
                <span className="flex items-center gap-1.5 font-bold text-neutral-900">
                  <Icon className="h-3.5 w-3.5" aria-hidden="true" /> {label}
                </span>
                <span className="text-neutral-500">{help}</span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      {error && (
        <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs font-medium text-red-900">
          {error}
        </p>
      )}

      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-xl px-4 py-2 text-xs font-bold text-neutral-600 hover:text-neutral-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900"
        >
          Annuler
        </button>
        <button
          type="submit"
          disabled={!canSubmit}
          className="rounded-xl bg-neutral-900 px-5 py-2 text-xs font-bold text-white shadow transition hover:bg-neutral-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900 focus-visible:ring-offset-2 disabled:opacity-40"
        >
          {busy ? 'Création…' : 'Créer le salon'}
        </button>
      </div>
    </form>
  )
}
