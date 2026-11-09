import { Globe, Lock, Sparkles } from 'lucide-react'
import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { ApiError, createRoom, reformulateTitle, type Reformulation } from '../../api/client'
import { KICK_THRESHOLDS, KICK_THRESHOLD_DEFAULT, PARTICIPANTS_MAX, PARTICIPANTS_MIN, ROOM_TITLE_MAX, ROOM_TITLE_MIN, type Visibility } from '../../api/types'
import { recordVisit } from '../../lib/history'
import { rememberCode } from '../../lib/identity'
import { CREATABLE_THEMES, themeBadge } from '../../lib/presentation'
import { roomHref } from '../../lib/route'

export function CreateRoomForm({ onCancel }: { onCancel: () => void }) {
  const [title, setTitle] = useState('')
  const [theme, setTheme] = useState<string>(CREATABLE_THEMES[0])
  const [visibility, setVisibility] = useState<Visibility>('public')
  const [maxParticipants, setMaxParticipants] = useState(PARTICIPANTS_MIN)
  const [spectators, setSpectators] = useState(true)
  const [kickThreshold, setKickThreshold] = useState<number>(KICK_THRESHOLD_DEFAULT)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inFlight = useRef(false)
  // Reformulation par l'IA : proposition à accepter ou ignorer, jamais appliquée automatiquement.
  const [suggestion, setSuggestion] = useState<Reformulation | null>(null)
  const [suggesting, setSuggesting] = useState(false)
  const [suggestError, setSuggestError] = useState<string | null>(null)
  const suggestAbort = useRef<AbortController | null>(null)
  useEffect(() => () => suggestAbort.current?.abort(), [])
  const ids = { title: useId(), theme: useId(), seats: useId(), kick: useId() }

  const trimmed = title.trim()
  const tooShort = trimmed.length < ROOM_TITLE_MIN
  // Sujet refusé par l'IA (hors débat, illégal...) : création bloquée tant que le titre n'est pas modifié.
  const [refusedTitle, setRefusedTitle] = useState<string | null>(null)
  const refused = refusedTitle !== null && refusedTitle === trimmed
  const canSubmit = !tooShort && !busy && !refused

  const editTitle = (value: string) => {
    setTitle(value)
    setSuggestion(null) // une proposition ne vaut que pour le texte sur lequel elle a été demandée
    setSuggestError(null)
  }

  const suggest = async () => {
    if (suggesting || trimmed.length < 3) return
    suggestAbort.current?.abort()
    const controller = new AbortController()
    suggestAbort.current = controller
    setSuggesting(true)
    setSuggestError(null)
    setSuggestion(null)
    try {
      const result = await reformulateTitle(trimmed, controller.signal)
      if (!controller.signal.aborted) setSuggestion(result)
    } catch (err) {
      if (!controller.signal.aborted) {
        if (err instanceof ApiError && err.status === 422) setRefusedTitle(trimmed)
        setSuggestError(err instanceof Error ? err.message : 'Reformulation impossible. Réessayez.')
      }
    } finally {
      if (!controller.signal.aborted) setSuggesting(false)
    }
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!canSubmit || inFlight.current) return // un double clic ne crée pas deux salons
    inFlight.current = true
    setBusy(true)
    setError(null)
    try {
      const created = await createRoom({
        title: trimmed,
        theme_category: theme,
        visibility,
        max_participants: maxParticipants,
        spectators_allowed: spectators,
        kick_threshold: kickThreshold,
      })
      // Dès la création, le salon entre dans « Mes salons » : on le retrouve même si on quitte la page.
      recordVisit({ id: created.id, title: trimmed, visibility: created.visibility, code: created.access_code ?? undefined, owner: true })
      // Le propriétaire entre sans code (le serveur le reconnaît) ; on garde le code pour un rechargement.
      if (created.access_code) rememberCode(created.id, created.access_code)
      window.location.hash = roomHref(created.id)
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) setRefusedTitle(trimmed) // le serveur a refusé ce sujet
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
          onChange={(e) => editTitle(e.target.value)}
          placeholder="Ex. : Faut-il instaurer un revenu universel en France ?"
          className="w-full rounded-xl border border-neutral-300 bg-neutral-50 px-4 py-2.5 text-sm text-neutral-900 placeholder-neutral-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-neutral-900"
        />
        <p className={`text-[11px] ${tooShort && trimmed.length > 0 ? 'text-amber-700' : 'text-neutral-500'}`}>
          {trimmed.length}/{ROOM_TITLE_MAX} · formulez une question neutre, au moins {ROOM_TITLE_MIN} caractères
        </p>
        <button
          type="button"
          onClick={suggest}
          disabled={suggesting || trimmed.length < 3}
          className="inline-flex items-center gap-1.5 rounded-lg border border-neutral-300 bg-white px-3 py-1.5 text-[11px] font-bold text-neutral-800 hover:border-neutral-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Sparkles className="h-3 w-3" aria-hidden="true" />
          {suggesting ? 'Reformulation…' : 'Proposer une reformulation'}
        </button>
        {suggestError && (
          <p role="alert" className="rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-2 text-xs font-medium text-neutral-800">
            {suggestError}
          </p>
        )}
        {suggestion && (
          <div role="status" aria-label="Proposition de reformulation" className="space-y-2 rounded-xl border border-neutral-200 bg-neutral-50 p-3">
            <p className="text-[11px] font-bold uppercase tracking-wide text-neutral-500">Proposition de l’IA</p>
            <p className="text-sm font-bold text-neutral-900">{suggestion.title}</p>
            <p className="text-[11px] text-neutral-600">
              Thème : <span className="font-bold">{themeBadge(suggestion.theme_category).name}</span>
            </p>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => {
                  setTitle(suggestion.title)
                  setTheme(suggestion.theme_category)
                  setSuggestion(null)
                }}
                className="rounded-lg bg-neutral-900 px-3 py-1.5 text-[11px] font-bold text-white hover:bg-neutral-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900 focus-visible:ring-offset-1"
              >
                Utiliser cette question
              </button>
              <button
                type="button"
                onClick={() => setSuggestion(null)}
                className="rounded-lg border border-neutral-300 bg-white px-3 py-1.5 text-[11px] font-bold text-neutral-700 hover:border-neutral-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900"
              >
                Garder mon titre
              </button>
            </div>
          </div>
        )}
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

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <label htmlFor={ids.seats} className="text-xs font-bold text-neutral-800">
            Intervenants maximum
          </label>
          <select
            id={ids.seats}
            value={maxParticipants}
            onChange={(e) => setMaxParticipants(Number(e.target.value))}
            className="w-full rounded-xl border border-neutral-300 bg-neutral-50 px-3 py-2.5 text-sm text-neutral-900 focus:bg-white focus:outline-none focus:ring-2 focus:ring-neutral-900"
          >
            {Array.from({ length: PARTICIPANTS_MAX - PARTICIPANTS_MIN + 1 }, (_, i) => PARTICIPANTS_MIN + i).map((n) => (
              <option key={n} value={n}>
                {n} intervenants
              </option>
            ))}
          </select>
        </div>
        <label className="flex cursor-pointer items-start gap-3 self-end rounded-xl border border-neutral-200 p-3 text-xs hover:border-neutral-300">
          <input type="checkbox" checked={spectators} onChange={(e) => setSpectators(e.target.checked)} className="mt-0.5 accent-neutral-900" />
          <span>
            <span className="block font-bold text-neutral-900">Autoriser les spectateurs</span>
            <span className="text-neutral-500">Jusqu’à 20 personnes qui suivent sans intervenir.</span>
          </span>
        </label>
      </div>

      <div className="space-y-1.5">
        <label htmlFor={ids.kick} className="text-xs font-bold text-neutral-800">
          Seuil d’exclusion d’un participant
        </label>
        <select
          id={ids.kick}
          value={kickThreshold}
          onChange={(e) => setKickThreshold(Number(e.target.value))}
          className="w-full rounded-xl border border-neutral-300 bg-neutral-50 px-3 py-2.5 text-sm text-neutral-900 focus:bg-white focus:outline-none focus:ring-2 focus:ring-neutral-900"
        >
          {KICK_THRESHOLDS.map((n) => (
            <option key={n} value={n}>
              {n} %{n === KICK_THRESHOLD_DEFAULT ? ' (par défaut)' : ''}
            </option>
          ))}
        </select>
        <p className="text-[11px] text-neutral-500">
          Sous ce score de fiabilité individuel (3 messages vérifiés minimum), vous pouvez proposer d’exclure un participant ; les spectateurs votent.
        </p>
      </div>

      {error && (
        <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs font-medium text-red-900">
          {error}
        </p>
      )}

      {refused && !error && !suggestError && (
        <p role="status" className="text-[11px] font-medium text-neutral-600">
          Ce sujet a été refusé : modifiez le titre pour pouvoir créer le salon.
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
