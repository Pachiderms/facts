import { ArrowLeft } from 'lucide-react'
import { useEffect, useState } from 'react'
import { RoomView } from '../components/arena/RoomView'
import { useRoomLookup } from '../hooks/useRoomLookup'
import { historyCode, removeEntry } from '../lib/history'
import { recallCode, rememberCode } from '../lib/identity'

/** Une room = une page (`#/arena/<id>`). On vérifie d'abord que le salon existe, puis on s'y connecte. */
export function RoomPage({ id, inviteCode }: { id: string; inviteCode?: string }) {
  const lookup = useRoomLookup(id)
  // Priorité : lien d'invitation, puis code de l'onglet, puis historique de cet appareil.
  const [code, setCode] = useState<string | undefined>(() => inviteCode ?? recallCode(id) ?? historyCode(id))
  const [attempt, setAttempt] = useState(0)

  // Le code d'un lien d'invitation est retiré de la barre d'adresse (historique, captures d'écran).
  useEffect(() => {
    if (!inviteCode) return
    rememberCode(id, inviteCode)
    window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}#/arena/${id}`)
  }, [id, inviteCode])

  // Un salon expiré n'a plus sa place dans l'historique.
  useEffect(() => {
    if (lookup.status === 'missing') removeEntry(id)
  }, [lookup.status, id])

  if (lookup.status === 'idle' || lookup.status === 'loading') {
    return (
      <p role="status" className="py-16 text-center text-sm text-neutral-500">
        Ouverture du salon…
      </p>
    )
  }
  if (lookup.status === 'missing' || lookup.status === 'error') {
    return (
      <div role="alert" className="mx-auto max-w-md space-y-4 rounded-2xl border border-neutral-200 bg-white p-8 text-center shadow-sm">
        <p className="text-sm font-bold text-neutral-900">
          {lookup.status === 'missing' ? 'Salon introuvable' : 'Impossible d’ouvrir le salon'}
        </p>
        <p className="text-xs text-neutral-600">
          {lookup.status === 'missing'
            ? 'Il n’existe pas ou a été supprimé après une période d’inactivité. Vérifiez l’identifiant.'
            : lookup.message}
        </p>
        <a href="#/arena" className="inline-flex items-center gap-1.5 text-xs font-bold text-neutral-900 underline-offset-2 hover:underline">
          <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" /> Tous les salons
        </a>
      </div>
    )
  }

  return (
    <RoomView
      key={`${id}|${code ?? ''}|${attempt}`}
      roomId={id}
      fallback={lookup.lookup.room ?? undefined}
      code={code}
      onSubmitCode={(c) => {
        rememberCode(id, c)
        setCode(c)
      }}
      onRetake={() => setAttempt((n) => n + 1)}
    />
  )
}
