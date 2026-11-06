import { X } from 'lucide-react'
import { useEffect, useRef } from 'react'
import type { SocketStatus } from '../../api/socket'
import type { RoomSummary } from '../../api/types'
import { useRoom } from '../../hooks/useRoom'
import { Composer } from './Composer'
import { MessageCard } from './MessageCard'
import { TrustMeter } from './TrustMeter'

const STATUS_LABEL: Record<SocketStatus, { text: string; dot: string }> = {
  connecting: { text: 'Connexion…', dot: 'bg-neutral-400' },
  open: { text: 'En direct', dot: 'bg-emerald-500 animate-pulse' },
  reconnecting: { text: 'Reconnexion…', dot: 'bg-amber-500 animate-pulse' },
  closed: { text: 'Déconnecté', dot: 'bg-neutral-400' },
}

/** Un salon. Monté avec `key={roomId}` : changer de salon ferme proprement l'ancienne connexion. */
export function RoomView({ roomId, fallback }: { roomId: string; fallback: RoomSummary | undefined }) {
  const { status, role, room, messages, presence, trustScore, deltas, notice, send, dismissNotice } = useRoom(roomId)
  const info = room ?? fallback
  const listRef = useRef<HTMLUListElement>(null)
  const stickToBottom = useRef(true)

  // Ne ramène en bas que si l'utilisateur y était déjà : on ne l'arrache pas à sa lecture.
  const onScroll = () => {
    const el = listRef.current
    if (el) stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
  }
  useEffect(() => {
    const el = listRef.current
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight
  }, [messages])

  const live = STATUS_LABEL[status]

  return (
    <div className="space-y-6">
      <section className="space-y-5 rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm">
        <div className="flex flex-col justify-between gap-3 border-b border-neutral-200 pb-4 md:flex-row md:items-center">
          <div className="min-w-0">
            <span className="font-mono text-xs font-bold uppercase tracking-wider text-neutral-500">{info?.category ?? '…'}</span>
            <h2 className="mt-0.5 text-lg font-extrabold text-neutral-900">{info?.title ?? 'Chargement du salon…'}</h2>
          </div>
          <div className="flex shrink-0 flex-col items-start gap-1.5 md:items-end">
            <span role="status" className="inline-flex items-center rounded-full border border-neutral-200 bg-neutral-100 px-3 py-1 text-xs font-semibold text-neutral-800">
              <span aria-hidden="true" className={`mr-1.5 h-2 w-2 rounded-full ${live.dot}`} />
              {live.text}
            </span>
            {presence && (
              <span className="text-[11px] text-neutral-500">
                Intervenants : A {presence.A ? 'présent' : 'absent'} · B {presence.B ? 'présent' : 'absent'}
                {presence.spectators > 0 && ` · ${presence.spectators} spectateur${presence.spectators > 1 ? 's' : ''}`}
              </span>
            )}
          </div>
        </div>

        <TrustMeter score={trustScore} />
      </section>

      {notice && (
        <div role="alert" className="flex items-start justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900">
          <span>{notice}</span>
          <button type="button" onClick={dismissNotice} aria-label="Fermer le message" className="shrink-0 rounded p-0.5 hover:bg-amber-100">
            <X className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </div>
      )}

      {status === 'closed' && (
        <p role="alert" className="rounded-xl border border-neutral-200 bg-neutral-50 px-4 py-3 text-xs text-neutral-700">
          La connexion à ce salon est fermée (salon indisponible ou accès refusé). Choisissez un autre salon ou rechargez la page.
        </p>
      )}

      <ul
        ref={listRef}
        onScroll={onScroll}
        role="log"
        aria-live="polite"
        aria-label="Messages du débat"
        className="max-h-[60vh] min-h-[12rem] space-y-4 overflow-y-auto rounded-2xl border border-neutral-200 bg-neutral-50 p-3 sm:p-4"
      >
        {messages.length === 0 ? (
          <li className="rounded-xl border border-dashed border-neutral-300 bg-white p-8 text-center text-xs text-neutral-500">
            Aucun message pour l’instant. {role === 'A' || role === 'B' ? 'Lancez le débat !' : 'Le débat va bientôt commencer.'}
          </li>
        ) : (
          messages.map((m) => <MessageCard key={m.id} message={m} delta={deltas[m.id]} />)
        )}
      </ul>

      <Composer role={role} status={status} onSend={send} />
    </div>
  )
}
