import { ArrowLeft } from 'lucide-react'
import { useState } from 'react'
import { RoomView } from '../components/arena/RoomView'
import { useRoomLookup } from '../hooks/useRoomLookup'
import { recallCode, rememberCode } from '../lib/identity'

/** Une room = une page (`#/arena/<id>`). On vérifie d'abord que le salon existe, puis on s'y connecte. */
export function RoomPage({ id }: { id: string }) {
  const lookup = useRoomLookup(id)
  const [code, setCode] = useState<string | undefined>(() => recallCode(id))
  const [attempt, setAttempt] = useState(0)

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
