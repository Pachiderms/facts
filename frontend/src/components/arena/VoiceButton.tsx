import { Loader2, Mic, Square, X } from 'lucide-react'
import { useState } from 'react'
import { useVoiceRecorder } from '../../hooks/useVoiceRecorder'
import { giveVoiceConsent, hasVoiceConsent } from '../../lib/voice'

interface Props {
  disabled?: boolean
  /** Reçoit la transcription : l'appelant la place dans le champ de saisie pour relecture. */
  onText: (text: string) => void
}

/** Bouton micro : enregistrement de 30 s maximum, transcription relue avant envoi, consentement au premier usage. */
export function VoiceButton({ disabled = false, onText }: Props) {
  const { state, secondsLeft, error, start, stop, cancel, clearError } = useVoiceRecorder(onText)
  const [asking, setAsking] = useState(false)

  const begin = () => {
    if (!hasVoiceConsent()) {
      setAsking(true)
      return
    }
    void start()
  }
  const accept = () => {
    giveVoiceConsent()
    setAsking(false)
    void start()
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        {state === 'idle' && (
          <button
            type="button"
            onClick={begin}
            disabled={disabled}
            aria-label="Dicter votre message"
            className="flex items-center gap-1.5 rounded-xl border border-neutral-300 bg-white px-3 py-2 text-xs font-bold text-neutral-800 transition hover:bg-neutral-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900 disabled:opacity-40"
          >
            <Mic className="h-3.5 w-3.5" aria-hidden="true" />
            Dicter
          </button>
        )}
        {state === 'recording' && (
          <>
            <button
              type="button"
              onClick={stop}
              aria-label="Terminer l'enregistrement"
              className="flex items-center gap-1.5 rounded-xl bg-neutral-900 px-3 py-2 text-xs font-bold text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900 focus-visible:ring-offset-2"
            >
              <Square className="h-3.5 w-3.5" aria-hidden="true" />
              Terminer · {secondsLeft} s
            </button>
            <button
              type="button"
              onClick={cancel}
              aria-label="Annuler l'enregistrement"
              className="flex items-center gap-1 rounded-xl border border-neutral-300 px-3 py-2 text-xs font-bold text-neutral-700 hover:bg-neutral-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900"
            >
              <X className="h-3.5 w-3.5" aria-hidden="true" />
              Annuler
            </button>
          </>
        )}
        {state === 'transcribing' && (
          <>
            <span role="status" className="flex items-center gap-1.5 text-xs font-medium text-neutral-600">
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
              Transcription…
            </span>
            <button
              type="button"
              onClick={cancel}
              aria-label="Annuler la transcription"
              className="rounded-xl border border-neutral-300 px-3 py-2 text-xs font-bold text-neutral-700 hover:bg-neutral-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900"
            >
              Annuler
            </button>
          </>
        )}
      </div>

      {asking && (
        <div role="dialog" aria-label="Consentement à la saisie vocale" className="space-y-2 rounded-lg border border-neutral-200 bg-neutral-50 p-3 text-xs text-neutral-700">
          <p>
            Votre voix est envoyée à Groq pour être transcrite en texte. L’enregistrement n’est pas conservé par Facts ; le texte vous est
            proposé pour relecture avant tout envoi.
          </p>
          <div className="flex gap-2">
            <button type="button" onClick={accept} className="rounded-lg bg-neutral-900 px-3 py-1.5 font-bold text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900 focus-visible:ring-offset-2">
              J’accepte
            </button>
            <button type="button" onClick={() => setAsking(false)} className="rounded-lg border border-neutral-300 px-3 py-1.5 font-bold text-neutral-700 hover:bg-neutral-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900">
              Refuser
            </button>
          </div>
        </div>
      )}

      {error && (
        <p role="alert" className="flex items-start justify-between gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs font-medium text-red-900">
          <span>{error}</span>
          <button type="button" onClick={clearError} aria-label="Fermer le message d'erreur" className="font-bold">
            ×
          </button>
        </p>
      )}
    </div>
  )
}
