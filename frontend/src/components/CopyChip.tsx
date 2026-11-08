import { Check, Copy, Link2 } from 'lucide-react'
import { useState } from 'react'

/** Valeur courte à partager (ID, code) avec un bouton « copier » qui survit à un presse-papiers indisponible. */
export function CopyChip({ label, value }: { label: string; value: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle')

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value)
      setState('copied')
    } catch {
      setState('failed')
    }
    setTimeout(() => setState('idle'), 2000)
  }

  return (
    <span className="inline-flex items-center gap-1.5 rounded-lg border border-neutral-200 bg-neutral-50 py-1 pl-2.5 pr-1 text-[11px] text-neutral-600">
      {label}
      <span className="font-mono font-bold text-neutral-900">{value}</span>
      <button
        type="button"
        onClick={copy}
        aria-label={`Copier ${label.toLowerCase()}`}
        className="rounded p-1 text-neutral-500 hover:bg-neutral-200 hover:text-neutral-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900"
      >
        {state === 'copied' ? <Check className="h-3 w-3" aria-hidden="true" /> : <Copy className="h-3 w-3" aria-hidden="true" />}
      </button>
      <span role="status" className="sr-only">
        {state === 'copied' ? 'Copié' : state === 'failed' ? 'Copie impossible' : ''}
      </span>
      {state === 'failed' && <span className="pr-1 text-amber-700">Copie impossible</span>}
    </span>
  )
}

/** Copie un lien d'invitation (le lien d'un salon privé contient son code : à partager avec soin). */
export function CopyLinkButton({ url }: { url: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle')

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url)
      setState('copied')
    } catch {
      setState('failed')
    }
    setTimeout(() => setState('idle'), 2000)
  }

  return (
    <button
      type="button"
      onClick={copy}
      className="inline-flex items-center gap-1.5 rounded-lg border border-neutral-200 bg-white px-2.5 py-1 text-[11px] font-bold text-neutral-700 hover:border-neutral-400 hover:text-neutral-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900"
    >
      {state === 'copied' ? <Check className="h-3 w-3" aria-hidden="true" /> : <Link2 className="h-3 w-3" aria-hidden="true" />}
      {state === 'copied' ? 'Lien copié' : state === 'failed' ? 'Copie impossible' : 'Copier le lien d’invitation'}
    </button>
  )
}
