import { Trash2 } from 'lucide-react'
import { useRef, useState } from 'react'
import { deleteRoom } from '../../api/client'

interface Props {
  roomId: string
  onDeleted: () => void
  /** `compact` : icône seule (liste « Mes salons »). */
  compact?: boolean
}

/** Suppression en deux temps (pas de clic accidentel). Le serveur refuse si d'autres personnes sont connectées. */
export function DeleteRoomButton({ roomId, onDeleted, compact = false }: Props) {
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inFlight = useRef(false)

  const confirm = async () => {
    if (inFlight.current) return
    inFlight.current = true
    setBusy(true)
    setError(null)
    try {
      await deleteRoom(roomId)
      onDeleted()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Suppression impossible.')
      setConfirming(false)
      inFlight.current = false
      setBusy(false)
    }
  }

  if (!confirming) {
    return (
      <span className="inline-flex flex-col items-start gap-1">
        <button
          type="button"
          onClick={() => {
            setError(null)
            setConfirming(true)
          }}
          aria-label={compact ? 'Supprimer le salon' : undefined}
          className="inline-flex items-center gap-1.5 rounded-lg border border-neutral-200 bg-white px-2.5 py-1 text-[11px] font-bold text-neutral-700 hover:border-red-300 hover:text-red-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900"
        >
          <Trash2 className="h-3 w-3" aria-hidden="true" />
          {!compact && 'Supprimer le salon'}
        </button>
        {error && (
          <span role="alert" className="max-w-xs text-[11px] font-medium text-red-800">
            {error}
          </span>
        )}
      </span>
    )
  }

  return (
    <span role="group" aria-label="Confirmer la suppression" className="inline-flex items-center gap-1.5 text-[11px]">
      <span className="font-medium text-neutral-700">Supprimer définitivement ?</span>
      <button
        type="button"
        onClick={confirm}
        disabled={busy}
        className="rounded-lg bg-red-700 px-2.5 py-1 font-bold text-white hover:bg-red-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900 disabled:opacity-50"
      >
        {busy ? 'Suppression…' : 'Confirmer'}
      </button>
      <button
        type="button"
        onClick={() => setConfirming(false)}
        disabled={busy}
        className="rounded-lg px-2 py-1 font-bold text-neutral-600 hover:text-neutral-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900"
      >
        Annuler
      </button>
    </span>
  )
}
