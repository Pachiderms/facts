import { TrendingUp } from 'lucide-react'
import { formatScore, trustTone } from '../../lib/presentation'
import { scaleCaption, TrustScale } from './TrustScale'

export function TrustMeter({ score }: { score: number | null }) {
  const tone = trustTone(score)
  return (
    <section aria-label="Score de fiabilité factuelle" className="space-y-2.5 rounded-xl border border-neutral-200 bg-neutral-50 p-4">
      <div className="flex items-center justify-between text-xs">
        <h3 className="flex items-center gap-1.5 font-mono font-bold uppercase tracking-wider text-neutral-900">
          <TrendingUp className="h-4 w-4 text-neutral-700" aria-hidden="true" />
          Score de fiabilité factuelle
        </h3>
        <span className={`whitespace-nowrap pl-2 font-mono text-sm font-bold ${score === null ? 'text-neutral-900' : tone.text}`}>
          {score === null ? '—' : `${formatScore(score)} / 100`}
        </span>
      </div>

      <div className="flex items-center gap-3">
        <TrustScale score={score} />
        <div className="min-w-0 flex-1">
          <div
            role="progressbar"
            aria-label="Score de fiabilité factuelle du débat"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={score ?? undefined}
            aria-valuetext={score === null ? 'Pas encore de donnée' : `${score} sur 100`}
            className="h-3 w-full overflow-hidden rounded-full bg-neutral-200 p-0.5"
          >
            <div className={`h-full rounded-full transition-all duration-500 ${tone.bar}`} style={{ width: `${score ?? 0}%` }} />
          </div>
          <p className={`mt-1.5 text-[11px] font-semibold ${tone.text}`}>{scaleCaption(score)}</p>
        </div>
      </div>

      <div className="flex justify-between text-[11px] font-medium text-neutral-500">
        <span>0 (non étayé)</span>
        <span className="text-center">{score === null ? 'Aucun message vérifié pour l’instant' : 'Calculé sur les messages vérifiés'}</span>
        <span>100 (vérifié)</span>
      </div>
    </section>
  )
}
