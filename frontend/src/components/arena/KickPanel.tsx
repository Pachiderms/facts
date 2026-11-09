import { Armchair, Gavel, ThumbsDown, ThumbsUp } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { KickVote, Presence } from '../../api/types'

interface Props {
  isOwner: boolean
  you: number | null
  spectator: boolean
  presence: Presence | null
  threshold: number
  vote: KickVote | null
  voted: boolean
  onKick: (target: number) => void
  onVote: (approve: boolean) => void
  onTakeSeat: () => void
}

/** Secondes restantes, décomptées localement à partir de la valeur envoyée par le serveur. */
function useCountdown(initial: number | undefined): number {
  const [left, setLeft] = useState(initial ?? 0)
  useEffect(() => {
    setLeft(initial ?? 0)
    if (!initial) return
    const t = setInterval(() => setLeft((n) => Math.max(0, n - 1)), 1000)
    return () => clearInterval(t)
  }, [initial])
  return left
}

/** Scores individuels, exclusion (créateur), vote (spectateurs) et prise de place libérée. */
export function KickPanel({ isOwner, you, spectator, presence, threshold, vote, voted, onKick, onVote, onTakeSeat }: Props) {
  const left = useCountdown(vote?.ends_in)
  const scores = presence?.scores ?? {}
  const present = presence?.present ?? []
  const seatFree = presence !== null && present.length < presence.max_participants
  const showScores = present.some((n) => typeof scores[String(n)] === 'number')

  if (!vote && !showScores && !(spectator && seatFree)) return null

  return (
    <section aria-label="Scores et exclusion" className="space-y-3 rounded-2xl border border-neutral-200 bg-white p-4 text-xs shadow-sm">
      {spectator && seatFree && !vote && (
        <div className="flex items-center justify-between gap-3">
          <span className="text-neutral-700">Une place d’intervenant est libre.</span>
          <button
            type="button"
            onClick={onTakeSeat}
            className="inline-flex items-center gap-1.5 rounded-xl bg-neutral-900 px-4 py-2 text-xs font-bold text-white hover:bg-neutral-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900 focus-visible:ring-offset-2"
          >
            <Armchair className="h-3.5 w-3.5" aria-hidden="true" /> Prendre la place
          </button>
        </div>
      )}

      {showScores && (
        <ul aria-label="Scores individuels" className="flex flex-wrap gap-2">
          {present.map((n) => {
            const score = scores[String(n)]
            const low = typeof score === 'number' && score < threshold
            const canKick = isOwner && n !== you && low && !vote
            return (
              <li key={n} className="flex items-center gap-2 rounded-lg border border-neutral-200 bg-neutral-50 px-2.5 py-1.5">
                <span className="font-bold text-neutral-900">
                  Participant {n}
                  {n === you ? ' (vous)' : ''}
                </span>
                <span className="text-neutral-600">{typeof score === 'number' ? `${score} %` : 'pas encore noté'}</span>
                {canKick && (
                  <button
                    type="button"
                    onClick={() => onKick(n)}
                    aria-label={`Proposer l’exclusion du participant ${n}`}
                    className="inline-flex items-center gap-1 rounded-md border border-neutral-300 bg-white px-2 py-0.5 font-bold text-neutral-800 hover:bg-neutral-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900"
                  >
                    <Gavel className="h-3 w-3" aria-hidden="true" /> Exclure
                  </button>
                )}
              </li>
            )
          })}
        </ul>
      )}

      {vote && (
        <div role="status" className="space-y-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-amber-900">
          <p>
            <strong className="font-extrabold">Vote d’exclusion</strong> · Participant {vote.target} (score {vote.score} %, seuil {vote.threshold} %).
            {' '}Pour : {vote.yes} · Contre : {vote.no} · {left} s restantes
          </p>
          {spectator && !isOwner && (
            <div className="flex gap-2">
              <button
                type="button"
                disabled={voted}
                onClick={() => onVote(true)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-amber-300 bg-white px-3 py-1.5 font-bold hover:bg-amber-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900 disabled:opacity-40"
              >
                <ThumbsUp className="h-3.5 w-3.5" aria-hidden="true" /> Exclure
              </button>
              <button
                type="button"
                disabled={voted}
                onClick={() => onVote(false)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-amber-300 bg-white px-3 py-1.5 font-bold hover:bg-amber-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900 disabled:opacity-40"
              >
                <ThumbsDown className="h-3.5 w-3.5" aria-hidden="true" /> Garder
              </button>
              {voted && <span className="self-center">Vote enregistré.</span>}
            </div>
          )}
        </div>
      )}
    </section>
  )
}
