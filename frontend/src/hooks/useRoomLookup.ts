import { useEffect, useState } from 'react'
import { ApiError, lookupRoom } from '../api/client'
import type { RoomLookup } from '../api/types'
import { ROOM_ID_RE } from '../lib/route'

export type LookupState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'found'; lookup: RoomLookup }
  | { status: 'missing' }
  | { status: 'error'; message: string }

/** Cherche un salon par ID (une fois). `id` vide ou invalide : rien n'est demandé au serveur. */
export function useRoomLookup(id: string): LookupState {
  const wanted = ROOM_ID_RE.test(id) ? id : ''
  const [state, setState] = useState<LookupState>({ status: wanted ? 'loading' : 'idle' })

  useEffect(() => {
    if (!wanted) {
      setState({ status: 'idle' })
      return
    }
    const controller = new AbortController()
    setState({ status: 'loading' })
    lookupRoom(wanted, controller.signal)
      .then((lookup) => {
        if (!controller.signal.aborted) setState({ status: 'found', lookup }) // ignore une réponse devenue périmée
      })
      .catch((e: unknown) => {
        if (controller.signal.aborted) return
        if (e instanceof ApiError && e.status === 404) setState({ status: 'missing' })
        else setState({ status: 'error', message: e instanceof Error ? e.message : 'Recherche impossible.' })
      })
    return () => controller.abort()
  }, [wanted])

  return state
}
