import { AlertTriangle, Building2, Globe, RefreshCw, Sparkles } from 'lucide-react'
import { useId, useState, type FormEvent, type KeyboardEvent } from 'react'
import { ASSERTION_MAX, ASSERTION_MIN } from '../api/types'
import { VerdictPanel } from '../components/check/VerdictPanel'
import { UsageNote } from '../components/check/UsageNote'
import { useCheck } from '../hooks/useCheck'

const EXAMPLES = [
  { label: 'SMIC net à 1 700 €', text: "La mesure de LFI d'augmenter le SMIC net à 1 700 € est dangereuse pour l'économie française." },
  { label: 'Nucléaire vs renouvelables', text: 'Le développement du nucléaire bloque le financement des énergies renouvelables en France.' },
  { label: 'Retraite à 60 ans', text: "Le retour à la retraite à 60 ans provoquerait la faillite immédiate du système d'assurance vieillesse." },
]

export function CheckPage() {
  const [text, setText] = useState('')
  const [institutional, setInstitutional] = useState(true)
  const { loading, slow, error, result, assertion, submit } = useCheck()
  const fieldId = useId()

  const trimmed = text.trim()
  const valid = trimmed.length >= ASSERTION_MIN && trimmed.length <= ASSERTION_MAX

  const onSubmit = (e?: FormEvent) => {
    e?.preventDefault()
    if (valid && !loading) void submit(trimmed, institutional)
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) onSubmit()
  }

  return (
    <div className="space-y-6">
      <section className="relative overflow-hidden rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm">
        <div className="absolute inset-x-0 top-0 h-1 bg-neutral-900" aria-hidden="true" />

        <div className="mb-5 flex flex-col justify-between gap-4 md:flex-row md:items-center">
          <div>
            <h1 className="flex items-center gap-2 text-xl font-bold text-neutral-900">
              <Sparkles className="h-5 w-5 text-neutral-700" aria-hidden="true" />
              Vérificateur d’affirmations politiques
            </h1>
            <p className="mt-1 text-xs text-neutral-500">
              Soumettez une déclaration. L’agent interroge le web et confronte les analyses de façon neutre et sourcée.
            </p>
            <UsageNote refreshKey={result ?? error} />
          </div>

          <div className="flex items-center space-x-2 rounded-xl border border-neutral-200 bg-neutral-50 px-3 py-1.5 text-xs">
            <Building2 className="h-3.5 w-3.5 text-neutral-600" aria-hidden="true" />
            <span className="font-medium text-neutral-700">Sources officielles en priorité :</span>
            <button
              type="button"
              aria-pressed={institutional}
              onClick={() => setInstitutional((v) => !v)}
              title="Classe en premier les sources institutionnelles et de recherche (INSEE, Trésor, OFCE…)"
              className={`rounded-lg px-2.5 py-1 font-bold transition focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900 ${
                institutional ? 'bg-neutral-900 text-white shadow-sm' : 'bg-neutral-200 text-neutral-700'
              }`}
            >
              {institutional ? 'Activé' : 'Désactivé'}
            </button>
          </div>
        </div>

        <form onSubmit={onSubmit} className="space-y-2">
          <label htmlFor={fieldId} className="sr-only">
            Affirmation à vérifier
          </label>
          <textarea
            id={fieldId}
            rows={3}
            value={text}
            maxLength={ASSERTION_MAX}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Entrez une affirmation (ex. : « La hausse du SMIC à 1 700 € est dangereuse pour l'économie »)"
            className="w-full rounded-xl border border-neutral-300 bg-neutral-50 px-4 py-3 text-sm leading-relaxed text-neutral-900 placeholder-neutral-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-neutral-900"
          />
          <div className="flex items-center justify-between gap-3">
            <span className={`font-mono text-[11px] ${trimmed.length > 0 && trimmed.length < ASSERTION_MIN ? 'text-amber-700' : 'text-neutral-400'}`}>
              {trimmed.length}/{ASSERTION_MAX}
              {trimmed.length > 0 && trimmed.length < ASSERTION_MIN && ` · ${ASSERTION_MIN} caractères minimum`}
            </span>
            <button
              type="submit"
              disabled={!valid || loading}
              className="flex items-center space-x-2 rounded-lg bg-neutral-900 px-4 py-2 text-xs font-semibold text-white shadow transition hover:bg-neutral-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900 focus-visible:ring-offset-2 disabled:opacity-50"
            >
              {loading ? (
                <>
                  <RefreshCw className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                  <span>Recherche en cours…</span>
                </>
              ) : (
                <>
                  <Globe className="h-3.5 w-3.5" aria-hidden="true" />
                  <span>Vérifier</span>
                </>
              )}
            </button>
          </div>
        </form>

        <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-neutral-100 pt-3 text-xs">
          <span className="font-medium text-neutral-500">Essayer avec :</span>
          {EXAMPLES.map((ex) => (
            <button
              key={ex.label}
              type="button"
              onClick={() => setText(ex.text)}
              className="rounded-full border border-neutral-200 bg-neutral-100 px-3 py-1 font-medium text-neutral-800 transition hover:bg-neutral-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900"
            >
              {ex.label}
            </button>
          ))}
        </div>
      </section>

      <div aria-live="polite">
        {error && !loading && (
          <div role="alert" className="flex items-start gap-3 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-900">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <p>{error}</p>
          </div>
        )}

        {loading && (
          <div className="space-y-3 rounded-2xl border border-neutral-200 bg-white p-12 text-center shadow-sm">
            <div className="inline-flex rounded-full bg-neutral-100 p-4 text-neutral-800">
              <RefreshCw className="h-8 w-8 animate-spin" aria-hidden="true" />
            </div>
            <h2 className="text-base font-bold text-neutral-900">L’agent recherche et analyse les sources…</h2>
            <p className="mx-auto max-w-md text-xs text-neutral-500">
              {slow
                ? 'Le serveur se réveille, cela peut prendre jusqu’à une minute la première fois.'
                : institutional
                  ? 'Consultation prioritaire des publications institutionnelles et de recherche.'
                  : 'Consultation des sources du web, tous types confondus.'}
            </p>
          </div>
        )}

        {result && assertion && !loading && <VerdictPanel result={result} assertion={assertion} />}
      </div>
    </div>
  )
}
