import { MessageSquare, Send } from 'lucide-react'
import { useId, useState, type FormEvent, type KeyboardEvent } from 'react'
import type { SocketStatus } from '../../api/socket'
import { MESSAGE_MAX, type Role } from '../../api/types'
import { composeHint } from '../../lib/presentation'

interface Props {
  role: Role | null
  status: SocketStatus
  onSend: (text: string) => boolean
}

const HINT_STYLES = {
  warning: 'bg-amber-50 text-amber-900 border-amber-200',
  success: 'bg-emerald-50 text-emerald-900 border-emerald-200',
  info: 'bg-neutral-100 text-neutral-700 border-neutral-200',
} as const

export function Composer({ role, status, onSend }: Props) {
  const [text, setText] = useState('')
  const [failed, setFailed] = useState(false)
  const fieldId = useId()

  const isSpeaker = role !== null && role !== 'spectator'
  const connected = status === 'open'
  const trimmed = text.trim()
  const canSend = isSpeaker && connected && trimmed.length > 0
  const hint = isSpeaker ? composeHint(text) : null

  const send = (e?: FormEvent) => {
    e?.preventDefault()
    if (!canSend) return
    if (onSend(trimmed)) {
      setText('')
      setFailed(false)
    } else {
      setFailed(true) // connexion perdue entre-temps : on garde le texte saisi
    }
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  return (
    <section aria-label="Intervenir dans la discussion" className="space-y-3 rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between text-xs font-bold text-neutral-800">
        <span className="flex items-center gap-2">
          <MessageSquare className="h-4 w-4 text-neutral-700" aria-hidden="true" />
          Intervenir dans la discussion
        </span>
        <span className="rounded-lg border border-neutral-200 bg-neutral-100 px-2.5 py-1 text-[11px] font-bold text-neutral-700">
          {role === null ? 'Connexion…' : isSpeaker ? `Vous êtes Participant ${role}` : 'Spectateur'}
        </span>
      </div>

      {role === 'spectator' ? (
        <p className="rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-2.5 text-xs text-neutral-600">
          Toutes les places d’intervenant sont prises : vous suivez le débat en spectateur. Revenez plus tard ou choisissez un autre salon.
        </p>
      ) : (
        <form onSubmit={send} className="space-y-3">
          <label htmlFor={fieldId} className="sr-only">
            Votre argument
          </label>
          <textarea
            id={fieldId}
            rows={2}
            value={text}
            maxLength={MESSAGE_MAX}
            disabled={!isSpeaker}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Saisissez votre argument… (ex. : Selon l'INSEE, l'inflation s'élève à…)"
            className="w-full resize-none rounded-xl border border-neutral-300 bg-neutral-50 px-4 py-2.5 text-sm text-neutral-900 placeholder-neutral-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-neutral-900 disabled:opacity-60"
          />

          {hint && (
            <p className={`rounded-lg border px-3 py-2 text-xs font-medium ${HINT_STYLES[hint.kind]}`}>{hint.text}</p>
          )}
          {failed && (
            <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs font-medium text-red-900">
              Message non envoyé : la connexion au salon est interrompue. Votre texte est conservé.
            </p>
          )}

          <div className="flex items-center justify-between">
            <span className="font-mono text-[11px] text-neutral-400">
              {trimmed.length}/{MESSAGE_MAX}
              <span className="ml-3 hidden font-sans sm:inline">Entrée pour envoyer · Maj+Entrée pour un retour à la ligne</span>
            </span>
            <button
              type="submit"
              disabled={!canSend}
              className="flex items-center space-x-2 rounded-xl bg-neutral-900 px-5 py-2 text-xs font-bold text-white shadow transition hover:bg-neutral-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900 focus-visible:ring-offset-2 disabled:opacity-40"
            >
              <span>Envoyer</span>
              <Send className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          </div>
        </form>
      )}
    </section>
  )
}
