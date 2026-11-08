import { ArrowLeft, Lock, UserX, X } from 'lucide-react'
import { useEffect, useRef } from 'react'
import type { SocketStatus } from '../../api/socket'
import { isSeat, type RoomSummary } from '../../api/types'
import { formatDuration } from '../../lib/presentation'
import { useRoom } from '../../hooks/useRoom'
import { recordVisit, removeEntry } from '../../lib/history'
import { forgetCode } from '../../lib/identity'
import { inviteUrl } from '../../lib/route'
import { CopyChip, CopyLinkButton } from '../CopyChip'
import { AccessCodeForm } from './AccessCodeForm'
import { DeleteRoomButton } from './DeleteRoomButton'
import { Composer } from './Composer'
import { MessageCard } from './MessageCard'
import { TrustMeter } from './TrustMeter'

const STATUS_LABEL: Record<SocketStatus, { text: string; dot: string }> = {
  connecting: { text: 'Connexion…', dot: 'bg-neutral-400' },
  open: { text: 'En direct', dot: 'bg-emerald-500 animate-pulse' },
  reconnecting: { text: 'Reconnexion…', dot: 'bg-amber-500 animate-pulse' },
  closed: { text: 'Déconnecté', dot: 'bg-neutral-400' },
}

interface Props {
  roomId: string
  fallback: RoomSummary | undefined
  /** Code d'accès (salon privé) déjà saisi ou mémorisé. */
  code?: string
  onSubmitCode: (code: string) => void
  /** Reprendre la place dans CET onglet (après ouverture dans un autre). */
  onRetake: () => void
  /** Entrer en spectateur sans prendre de siège d'intervenant. */
  spectate?: boolean
}

/** Un salon. Monté avec une `key` : changer de salon ou de code ferme proprement l'ancienne connexion. */
export function RoomView({ roomId, fallback, code, onSubmitCode, onRetake, spectate = false }: Props) {
  const {
    status, role, room, messages, presence, trustScore, deltas, notice, denied, send, dismissNotice,
    warning, reportNotice, banRetryAfter, report, dismissWarning, dismissReportNotice,
  } = useRoom(roomId, code, spectate)
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

  // « Mes salons » : on retient ce salon (et son code, sur cet appareil) dès qu'on y est entré.
  useEffect(() => {
    if (!room) return
    recordVisit({
      id: roomId,
      title: room.title,
      visibility: room.visibility,
      code: room.access_code ?? code,
      owner: room.is_owner === true,
    })
  }, [room, roomId, code])

  // Un code refusé ne doit pas être resservi au prochain rechargement.
  useEffect(() => {
    if (denied === 'invalid_code') forgetCode(roomId)
  }, [denied, roomId])

  if (denied === 'invalid_code') return <AccessCodeForm wrong={Boolean(code)} onSubmit={onSubmitCode} />
  if (denied === 'too_many_attempts') {
    return (
      <p role="alert" className="mx-auto max-w-md rounded-2xl border border-amber-200 bg-amber-50 p-6 text-center text-sm text-amber-900">
        Trop de codes erronés depuis votre connexion. Réessayez dans quelques minutes.
      </p>
    )
  }
  if (denied === 'session_replaced') {
    return (
      <div role="alert" className="mx-auto max-w-md space-y-3 rounded-2xl border border-neutral-200 bg-white p-6 text-center text-sm text-neutral-700 shadow-sm">
        <p>Ce salon est ouvert dans un autre onglet : vous y avez été déconnecté.</p>
        <button
          type="button"
          onClick={onRetake}
          className="rounded-xl bg-neutral-900 px-5 py-2 text-xs font-bold text-white shadow hover:bg-neutral-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900 focus-visible:ring-offset-2"
        >
          Reprendre ici
        </button>
      </div>
    )
  }

  if (denied === 'banned') {
    return (
      <div role="alert" className="mx-auto max-w-md space-y-3 rounded-2xl border border-neutral-200 bg-white p-6 text-center text-sm text-neutral-700 shadow-sm">
        <p className="flex items-center justify-center gap-2 font-bold text-neutral-900">
          <UserX className="h-4 w-4" aria-hidden="true" />
          Exclusion temporaire
        </p>
        <p>
          Vous êtes exclu des salons{banRetryAfter ? ` pendant encore ${formatDuration(banRetryAfter)}` : ' pour un temps'} en raison de messages
          enfreignant les règles (racisme, insultes, menaces).
        </p>
        <a href="#/arena" className="inline-block text-xs font-bold text-neutral-900 underline-offset-2 hover:underline">
          Retour aux salons
        </a>
      </div>
    )
  }

  if (denied === 'spectators_not_allowed' || denied === 'room_deleted') {
    return (
      <div role="alert" className="mx-auto max-w-md space-y-3 rounded-2xl border border-neutral-200 bg-white p-6 text-center text-sm text-neutral-700 shadow-sm">
        <p className="flex items-center justify-center gap-2 font-bold text-neutral-900">
          <UserX className="h-4 w-4" aria-hidden="true" />
          {denied === 'room_deleted' ? 'Salon supprimé' : 'Salon complet'}
        </p>
        <p>
          {denied === 'room_deleted'
            ? 'Ce salon a été supprimé par son créateur.'
            : 'Toutes les places d’intervenant sont prises et ce salon n’admet pas de spectateurs.'}
        </p>
        <a href="#/arena" className="inline-block text-xs font-bold text-neutral-900 underline-offset-2 hover:underline">
          Retour aux salons
        </a>
      </div>
    )
  }

  const live = STATUS_LABEL[status]
  const shareCode = room?.access_code ?? code

  return (
    <div className="space-y-6">
      <a
        href="#/arena"
        className="inline-flex items-center gap-1.5 rounded text-xs font-bold text-neutral-600 hover:text-neutral-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" /> Tous les salons
      </a>

      <section className="space-y-5 rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm">
        <div className="flex flex-col justify-between gap-3 border-b border-neutral-200 pb-4 md:flex-row md:items-center">
          <div className="min-w-0">
            <span className="font-mono text-xs font-bold uppercase tracking-wider text-neutral-500">{info?.category ?? '…'}</span>
            <h2 className="mt-0.5 text-lg font-extrabold text-neutral-900">{info?.title ?? 'Chargement du salon…'}</h2>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {info?.visibility === 'private' && (
                <span className="inline-flex items-center gap-1 rounded-lg border border-neutral-200 bg-neutral-100 px-2 py-1 text-[11px] font-bold text-neutral-700">
                  <Lock className="h-3 w-3" aria-hidden="true" /> Salon privé
                </span>
              )}
              {info?.spectators_allowed === false && (
                <span className="rounded-lg border border-neutral-200 bg-neutral-100 px-2 py-1 text-[11px] font-bold text-neutral-700">Sans spectateurs</span>
              )}
              <CopyChip label="ID" value={roomId} />
              {info?.access_code && <CopyChip label="Code d’accès" value={info.access_code} />}
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <CopyLinkButton url={inviteUrl(roomId, info?.visibility === 'private' ? shareCode : undefined)} />
              {room?.is_owner && (
                <DeleteRoomButton
                  roomId={roomId}
                  onDeleted={() => {
                    removeEntry(roomId)
                    window.location.hash = '#/arena'
                  }}
                />
              )}
            </div>
          </div>
          <div className="flex shrink-0 flex-col items-start gap-1.5 md:items-end">
            <span role="status" className="inline-flex items-center rounded-full border border-neutral-200 bg-neutral-100 px-3 py-1 text-xs font-semibold text-neutral-800">
              <span aria-hidden="true" className={`mr-1.5 h-2 w-2 rounded-full ${live.dot}`} />
              {live.text}
            </span>
            {presence && (
              <span className="text-[11px] text-neutral-500">
                Intervenants : {presence.seats.length}/{presence.max_participants}
                {presence.seats.length > 0 && ` (${presence.seats.join(', ')})`}
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

      {warning && (
        <div role="alert" className="flex items-start justify-between gap-3 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-xs text-amber-900">
          <span>
            <strong className="font-extrabold">
              {warning.level === 'final_warning' ? 'Dernier avertissement' : 'Avertissement'} ({warning.strikes}/{warning.maxStrikes})
            </strong>
            {' · '}
            {warning.detail} Votre message n’a pas été publié.
          </span>
          <button type="button" onClick={dismissWarning} aria-label="Fermer l’avertissement" className="shrink-0 rounded p-0.5 hover:bg-amber-100">
            <X className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </div>
      )}

      {reportNotice && (
        <div role="status" className="flex items-start justify-between gap-3 rounded-xl border border-neutral-200 bg-neutral-50 px-4 py-3 text-xs text-neutral-800">
          <span>{reportNotice}</span>
          <button type="button" onClick={dismissReportNotice} aria-label="Fermer" className="shrink-0 rounded p-0.5 hover:bg-neutral-100">
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
            Aucun message pour l’instant. {isSeat(role) ? 'Lancez le débat !' : 'Le débat va bientôt commencer.'}
          </li>
        ) : (
          messages.map((m) => (
            <MessageCard
              key={m.id}
              message={m}
              delta={deltas[m.id]}
              alternate={(info?.max_participants ?? 2) === 2}
              onReport={m.speaker !== role ? report : undefined}
            />
          ))
        )}
      </ul>

      <Composer role={role} status={status} onSend={send} />
    </div>
  )
}
