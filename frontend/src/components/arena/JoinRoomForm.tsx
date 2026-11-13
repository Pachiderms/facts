import { LogIn } from 'lucide-react'
import { useId, useState, type FormEvent } from 'react'
import { rememberCode } from '../../lib/identity'
import { parseJoinInput, roomHref } from '../../lib/route'

/** Rejoindre un salon par son identifiant (ou un lien d'invitation collé) et, si besoin, son code d'accès. */
export function JoinRoomForm({ onCancel }: { onCancel: () => void }) {
  const [room, setRoom] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const ids = { room: useId(), code: useId() }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const target = parseJoinInput(room, code)
    if (!target) {
      setError(code.trim() && !/^[A-Za-z0-9]{1,16}$/.test(code.trim()) ? 'Code invalide : lettres et chiffres uniquement.' : 'Identifiant de salon invalide.')
      return
    }
    // Le code reste dans l'onglet (comme pour un lien d'invitation) ; la page du salon le présente au serveur.
    if (target.code) rememberCode(target.id, target.code)
    window.location.hash = roomHref(target.id)
  }

  const field =
    'w-full rounded-xl border border-neutral-300 bg-neutral-50 px-4 py-2.5 text-sm text-neutral-900 placeholder-neutral-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-neutral-900'

  return (
    <form onSubmit={submit} aria-label="Rejoindre un salon" className="max-w-xl space-y-4 rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm">
      <h2 className="flex items-center gap-2 text-sm font-extrabold text-neutral-900">
        <LogIn className="h-4 w-4" aria-hidden="true" /> Rejoindre un salon
      </h2>
      <div className="space-y-1.5">
        <label htmlFor={ids.room} className="text-xs font-bold text-neutral-800">
          Identifiant du salon ou lien d’invitation
        </label>
        <input
          id={ids.room}
          type="text"
          value={room}
          maxLength={300}
          autoComplete="off"
          spellCheck={false}
          placeholder="ex. revenu-universel-ab12"
          onChange={(e) => {
            setRoom(e.target.value)
            setError(null)
          }}
          className={field}
        />
      </div>
      <div className="space-y-1.5">
        <label htmlFor={ids.code} className="text-xs font-bold text-neutral-800">
          Code d’accès <span className="font-medium text-neutral-500">(salons privés)</span>
        </label>
        <input
          id={ids.code}
          type="text"
          value={code}
          maxLength={16}
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          onChange={(e) => {
            setCode(e.target.value)
            setError(null)
          }}
          className={`${field} font-mono uppercase tracking-[0.2em]`}
        />
      </div>
      {error && (
        <p role="alert" className="text-xs font-medium text-red-700">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={!room.trim()}
          className="rounded-xl bg-neutral-900 px-4 py-2.5 text-xs font-bold text-white transition hover:bg-neutral-800 disabled:cursor-not-allowed disabled:bg-neutral-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900 focus-visible:ring-offset-2"
        >
          Rejoindre
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-xl border border-neutral-300 bg-white px-4 py-2.5 text-xs font-bold text-neutral-700 hover:bg-neutral-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900"
        >
          Annuler
        </button>
      </div>
    </form>
  )
}
