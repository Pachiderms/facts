import { Lock } from 'lucide-react'
import { useId, useState, type FormEvent } from 'react'

interface Props {
  /** Un code vient d'être refusé. */
  wrong: boolean
  onSubmit: (code: string) => void
}

export function AccessCodeForm({ wrong, onSubmit }: Props) {
  const [code, setCode] = useState('')
  const id = useId()
  const clean = code.trim()

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (clean) onSubmit(clean)
  }

  return (
    <form onSubmit={submit} aria-label="Code d'accès" className="mx-auto max-w-sm space-y-4 rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm">
      <h2 className="flex items-center gap-2 text-sm font-extrabold text-neutral-900">
        <Lock className="h-4 w-4" aria-hidden="true" /> Salon privé
      </h2>
      <p className="text-xs text-neutral-600">Saisissez le code d’accès communiqué par le créateur du salon.</p>
      <div className="space-y-1.5">
        <label htmlFor={id} className="text-xs font-bold text-neutral-800">
          Code d’accès
        </label>
        <input
          id={id}
          type="text"
          value={code}
          maxLength={16}
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          onChange={(e) => setCode(e.target.value)}
          className="w-full rounded-xl border border-neutral-300 bg-neutral-50 px-4 py-2.5 text-center font-mono text-lg tracking-[0.3em] text-neutral-900 uppercase focus:bg-white focus:outline-none focus:ring-2 focus:ring-neutral-900"
        />
      </div>
      {wrong && (
        <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs font-medium text-red-900">
          Code invalide. Vérifiez-le auprès du créateur du salon.
        </p>
      )}
      <button
        type="submit"
        disabled={!clean}
        className="w-full rounded-xl bg-neutral-900 px-5 py-2.5 text-xs font-bold text-white shadow transition hover:bg-neutral-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900 focus-visible:ring-offset-2 disabled:opacity-40"
      >
        Entrer dans le salon
      </button>
    </form>
  )
}
