import { AlertTriangle, Award, Bot, Check, CheckCircle2, ChevronDown, ChevronUp, ExternalLink, Globe, Scale, Share2 } from 'lucide-react'
import { useState } from 'react'
import type { CheckResponse, View } from '../../api/types'
import { safeHref, verdictTone } from '../../lib/presentation'

function ViewColumn({ view }: { view: View }) {
  return (
    <section className="space-y-4 rounded-xl border border-neutral-200 bg-neutral-50/80 p-5 shadow-sm">
      <h4 className="border-b border-neutral-200 pb-3 text-base font-bold text-neutral-900">{view.title}</h4>
      {view.points.length === 0 ? (
        <p className="text-xs text-neutral-500">Aucun élément étayé par les sources trouvées.</p>
      ) : (
        <ul className="space-y-3">
          {view.points.map((point, i) => (
            <li key={i} className="flex items-start gap-2 rounded-lg border border-neutral-200 bg-white p-3 text-xs leading-relaxed text-neutral-700">
              <span aria-hidden="true" className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-neutral-800" />
              <span>{point}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function shareText(result: CheckResponse, assertion: string): string {
  const sources = result.verified_sources.map((s) => `- ${s.title} (${s.url})`).join('\n')
  return `« ${assertion} »\nVerdict : ${result.verdict} (certitude ${result.confidence_score} %)\n${result.summary}${sources ? `\nSources :\n${sources}` : ''}`
}

export function VerdictPanel({ result, assertion }: { result: CheckResponse; assertion: string }) {
  const [showSources, setShowSources] = useState(false)
  const [copied, setCopied] = useState<'idle' | 'ok' | 'error'>('idle')
  const tone = verdictTone(result.verdict)
  const noSources = result.verified_sources.length === 0

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(shareText(result, assertion))
      setCopied('ok')
    } catch {
      setCopied('error') // presse-papiers indisponible (contexte non sécurisé, permission refusée)
    }
    setTimeout(() => setCopied('idle'), 2500)
  }

  return (
    <article aria-label="Résultat de la vérification" className="overflow-hidden rounded-2xl border border-neutral-200 bg-white shadow-sm">
      <div className="border-b border-neutral-200 bg-neutral-50/60 p-6">
        <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-start">
          <div className="min-w-0">
            <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-2">
              <span className={`rounded-md border px-3 py-1 font-mono text-xs font-bold uppercase tracking-wider ${tone.badge}`}>
                Verdict : {result.verdict}
              </span>
              <span className="flex items-center gap-1 text-xs font-medium text-neutral-500">
                <Award className="h-3.5 w-3.5 text-neutral-700" aria-hidden="true" />
                Indice de certitude : <strong className="text-neutral-900">{result.confidence_score} %</strong>
              </span>
              {result.cached && (
                <span className="rounded bg-neutral-200 px-2 py-0.5 font-mono text-[11px] text-neutral-700">Résultat en cache</span>
              )}
            </div>
            <h2 className="break-words text-xl font-extrabold leading-snug text-neutral-900">{`«\u00A0${assertion}\u00A0»`}</h2>
          </div>

          <div className="flex shrink-0 items-center space-x-2">
            <button
              type="button"
              onClick={() => setShowSources((v) => !v)}
              aria-expanded={showSources}
              aria-controls="sources-drawer"
              className="flex items-center space-x-1.5 rounded-lg border border-neutral-300 bg-white px-3.5 py-2 text-xs font-semibold text-neutral-800 shadow-sm transition hover:bg-neutral-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900"
            >
              <Globe className="h-4 w-4 text-neutral-700" aria-hidden="true" />
              <span>Sources ({result.verified_sources.length})</span>
              {showSources ? <ChevronUp className="ml-1 h-3.5 w-3.5" aria-hidden="true" /> : <ChevronDown className="ml-1 h-3.5 w-3.5" aria-hidden="true" />}
            </button>
            <button
              type="button"
              onClick={copy}
              aria-label="Copier le résultat"
              className="flex items-center space-x-1.5 rounded-lg border border-neutral-300 bg-white p-2 text-neutral-700 transition hover:bg-neutral-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900"
            >
              {copied === 'ok' ? <Check className="h-4 w-4 text-emerald-700" aria-hidden="true" /> : <Share2 className="h-4 w-4" aria-hidden="true" />}
              <span className="sr-only" role="status">
                {copied === 'ok' ? 'Copié' : copied === 'error' ? 'Copie impossible' : ''}
              </span>
            </button>
          </div>
        </div>

        <div className="mt-4 rounded-xl border border-neutral-200 bg-white p-4 text-sm leading-relaxed text-neutral-800 shadow-sm">
          <div className="mb-1 flex items-center gap-1.5 font-mono text-xs font-bold uppercase tracking-wider text-neutral-500">
            <Bot className="h-4 w-4 text-neutral-900" aria-hidden="true" /> Synthèse
          </div>
          {result.summary}
        </div>

        {noSources && (
          <p role="note" className="mt-3 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            Aucune source n’a pu être validée pour cette affirmation : ce verdict est à prendre avec beaucoup de prudence.
          </p>
        )}
      </div>

      {showSources && (
        <div id="sources-drawer" className="space-y-3 border-b border-neutral-200 bg-neutral-100 p-6">
          <h3 className="flex items-center gap-1.5 font-mono text-xs font-bold uppercase tracking-wider text-neutral-600">
            <CheckCircle2 className="h-4 w-4 text-neutral-800" aria-hidden="true" />
            Sources retenues
          </h3>
          {noSources ? (
            <p className="text-xs text-neutral-600">Aucune source.</p>
          ) : (
            <ul className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {result.verified_sources.map((src) => {
                const href = safeHref(src.url)
                return (
                  <li key={src.url} className="flex items-center justify-between gap-3 rounded-xl border border-neutral-200 bg-white p-3.5 shadow-sm">
                    <div className="min-w-0">
                      <div className="break-words text-sm font-bold text-neutral-900">{src.title}</div>
                      <div className="text-xs text-neutral-500">{src.domain}</div>
                    </div>
                    <div className="shrink-0 text-right">
                      <span className="rounded border border-neutral-200 bg-neutral-100 px-2 py-0.5 font-mono text-xs font-bold text-neutral-900">
                        Confiance {src.trust_score}
                      </span>
                      {href && (
                        <a
                          href={href}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="mt-1 flex items-center justify-end gap-0.5 text-[11px] font-semibold text-neutral-600 hover:underline"
                        >
                          Ouvrir <ExternalLink className="h-2.5 w-2.5" aria-hidden="true" />
                        </a>
                      )}
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
          <p className="text-[11px] text-neutral-500">
            Le score de confiance classe le type de source (statistique publique, recherche, presse…) : ce n’est pas une preuve que son contenu est exact.
          </p>
        </div>
      )}

      <div className="space-y-4 p-6">
        <h3 className="flex items-center gap-2 border-b border-neutral-200 pb-3 font-mono text-xs font-bold uppercase tracking-wider text-neutral-500">
          <Scale className="h-4 w-4 text-neutral-800" aria-hidden="true" />
          Confrontation équilibrée des angles d’analyse
        </h3>
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          <ViewColumn view={result.liberal_institutional_view} />
          <ViewColumn view={result.heterodox_social_view} />
        </div>
      </div>
    </article>
  )
}
