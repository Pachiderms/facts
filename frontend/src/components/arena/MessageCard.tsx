import { AlertTriangle, CheckCircle2, CircleHelp, CornerUpLeft, ExternalLink, Flag, RefreshCw, XCircle } from 'lucide-react'
import type { RoomMessage } from '../../api/types'
import { badgeTone, formatTime, safeHref } from '../../lib/presentation'

function BadgeIcon({ message }: { message: RoomMessage }) {
  const cls = 'h-3.5 w-3.5'
  if (message.check.status === 'pending') return <RefreshCw className={`${cls} animate-spin`} aria-hidden="true" />
  switch (message.check.badge_type) {
    case 'green':
      return <CheckCircle2 className={cls} aria-hidden="true" />
    case 'amber':
      return <AlertTriangle className={cls} aria-hidden="true" />
    case 'red':
      return <XCircle className={cls} aria-hidden="true" />
    default:
      return <CircleHelp className={cls} aria-hidden="true" />
  }
}

/** `alternate` : débat à deux, les messages se répondent de part et d'autre ; au-delà, tout est aligné. */
export function MessageCard({
  message,
  delta,
  alternate = true,
  mine = false,
  absent = false,
  viewerIsSpectator = false,
  onReport,
  onReply,
  onJumpTo,
  highlighted = false,
}: {
  message: RoomMessage
  delta?: number
  alternate?: boolean
  /** Message du lecteur lui-même (aligné à droite). */
  mine?: boolean
  /** L'auteur n'est plus connecté au salon. */
  absent?: boolean
  /** Le lecteur est spectateur : pas de « moi », on alterne selon le numéro. */
  viewerIsSpectator?: boolean
  /** Fourni uniquement pour les messages des autres : permet de les signaler. */
  onReport?: (messageId: number) => void
  /** Fourni aux intervenants : permet de répondre à ce message. */
  onReply?: (messageId: number) => void
  /** Ramène au message cité. */
  onJumpTo?: (messageId: number) => void
  /** Mise en évidence temporaire après un saut depuis une citation. */
  highlighted?: boolean
}) {
  // Débat à deux : les messages se répondent de part et d'autre. Moi à droite ; un spectateur voit les impairs à gauche.
  const onLeft = viewerIsSpectator ? message.speaker % 2 === 1 : !mine
  const tone = badgeTone(message.check.badge_type)
  const pending = message.check.status === 'pending'

  return (
    <li
      id={`message-${message.id}`}
      className={`space-y-2.5 rounded-xl border bg-white p-4 shadow-sm transition-colors ${highlighted ? 'border-neutral-900 ring-2 ring-neutral-900/20' : 'border-neutral-200'} ${!alternate ? '' : onLeft ? 'mr-6 ml-0' : 'ml-6 mr-0'}`}
    >
      <div className="flex items-center justify-between border-b border-neutral-100 pb-2 text-xs">
        <div className="flex items-center space-x-2">
          <span aria-hidden="true" className="flex h-6 w-6 items-center justify-center rounded-full bg-neutral-200 text-[10px] font-bold text-neutral-800">
            {message.speaker}
          </span>
          <span className="font-bold text-neutral-900">{message.speaker_name}</span>
          {mine && <span className="rounded bg-neutral-100 px-1.5 py-0.5 text-[10px] font-bold text-neutral-600">vous</span>}
          {absent && !mine && <span className="rounded border border-neutral-200 px-1.5 py-0.5 text-[10px] font-semibold text-neutral-400">absent</span>}
        </div>
        <time dateTime={message.timestamp} className="font-mono text-[11px] text-neutral-400">
          {formatTime(message.timestamp)}
        </time>
      </div>

      {message.reply_to && !message.removed && (
        <button
          type="button"
          onClick={() => onJumpTo?.(message.reply_to!.id)}
          aria-label={`Réponse au message du Participant ${message.reply_to.speaker} : ${message.reply_to.preview}`}
          className="flex w-full items-start gap-2 rounded-lg border-l-4 border-neutral-300 bg-neutral-50 px-3 py-2 text-left text-[11px] leading-snug text-neutral-600 hover:bg-neutral-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900"
        >
          <CornerUpLeft className="mt-0.5 h-3 w-3 shrink-0 text-neutral-400" aria-hidden="true" />
          <span className="min-w-0">
            <span className="block font-bold text-neutral-700">Participant {message.reply_to.speaker}</span>
            <span className="block break-words">{message.reply_to.preview}</span>
          </span>
        </button>
      )}

      {message.removed ? (
        <p className="text-sm italic leading-relaxed text-neutral-500">{message.text}</p>
      ) : (
        <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-neutral-800">{message.text}</p>
      )}

      {!message.removed && (onReply || onReport) && (
        <div className="flex justify-end gap-1">
          {onReply && (
            <button
              type="button"
              onClick={() => onReply(message.id)}
              aria-label={`Répondre au message de ${message.speaker_name}`}
              className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold text-neutral-400 hover:bg-neutral-100 hover:text-neutral-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900"
            >
              <CornerUpLeft className="h-3 w-3" aria-hidden="true" /> Répondre
            </button>
          )}
          {onReport && (
            <button
              type="button"
              onClick={() => onReport(message.id)}
              aria-label={`Signaler le message de ${message.speaker_name}`}
              className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold text-neutral-400 hover:bg-neutral-100 hover:text-neutral-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900"
            >
              <Flag className="h-3 w-3" aria-hidden="true" /> Signaler
            </button>
          )}
        </div>
      )}

      <div className={`space-y-1.5 pt-1 ${message.removed ? 'hidden' : ''}`}>
        <div className="flex flex-wrap items-center gap-2">
          <span
            role={pending ? 'status' : undefined}
            className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 font-mono text-[11px] font-bold ${tone.badge}`}
          >
            <BadgeIcon message={message} />
            <span>[{message.check.badge_text}]</span>
          </span>
          {delta ? (
            <span
              className={`rounded px-1.5 py-0.5 font-mono text-[11px] font-bold ${delta > 0 ? 'bg-emerald-50 text-emerald-800' : 'bg-red-50 text-red-800'}`}
              aria-label={`Score du salon ${delta > 0 ? 'en hausse' : 'en baisse'} de ${Math.abs(delta)} points`}
            >
              {delta > 0 ? '+' : '−'}
              {Math.abs(delta)}
            </span>
          ) : null}
        </div>

        {message.check.note && <p className="text-[11px] leading-relaxed text-neutral-600">{message.check.note}</p>}

        {message.check.sources.length > 0 && (
          <ul className="flex flex-wrap gap-x-3 gap-y-1 text-[11px]">
            {message.check.sources.map((s) => {
              const href = safeHref(s.url)
              return (
                <li key={s.url}>
                  {href ? (
                    <a href={href} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-0.5 font-semibold text-neutral-700 hover:underline">
                      {s.domain || s.title} <ExternalLink className="h-2.5 w-2.5" aria-hidden="true" />
                    </a>
                  ) : (
                    <span className="text-neutral-500">{s.domain || s.title}</span>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </li>
  )
}
