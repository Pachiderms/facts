import { AlertTriangle, CheckCircle2, CircleHelp, ExternalLink, RefreshCw, XCircle } from 'lucide-react'
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
export function MessageCard({ message, delta, alternate = true }: { message: RoomMessage; delta?: number; alternate?: boolean }) {
  const isA = message.speaker === 'A'
  const tone = badgeTone(message.check.badge_type)
  const pending = message.check.status === 'pending'

  return (
    <li className={`space-y-2.5 rounded-xl border border-neutral-200 bg-white p-4 shadow-sm ${!alternate ? '' : isA ? 'mr-6 ml-0' : 'ml-6 mr-0'}`}>
      <div className="flex items-center justify-between border-b border-neutral-100 pb-2 text-xs">
        <div className="flex items-center space-x-2">
          <span aria-hidden="true" className="flex h-6 w-6 items-center justify-center rounded-full bg-neutral-200 text-[10px] font-bold text-neutral-800">
            {message.speaker}
          </span>
          <span className="font-bold text-neutral-900">{message.speaker_name}</span>
        </div>
        <time dateTime={message.timestamp} className="font-mono text-[11px] text-neutral-400">
          {formatTime(message.timestamp)}
        </time>
      </div>

      <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-neutral-800">{message.text}</p>

      <div className="space-y-1.5 pt-1">
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
