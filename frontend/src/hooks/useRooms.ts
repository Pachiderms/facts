import { useEffect, useState } from 'react'
import { listRooms } from '../api/client'
import type { RoomSummary } from '../api/types'

const REFRESH_MS = 15_000
const MAX_BACKOFF_MS = 120_000

/** Liste des salons, rafraîchie périodiquement (le score évolue pendant les débats). */
export function useRooms() {
  const [rooms, setRooms] = useState<RoomSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    let failures = 0

    const load = async () => {
      try {
        const data = await listRooms(controller.signal)
        setRooms(data)
        setError(null)
        failures = 0
      } catch (e) {
        if (controller.signal.aborted) return
        failures += 1
        setError(e instanceof Error ? e.message : 'Impossible de charger les salons.')
      }
      // Délai croissant après une erreur (ex. 429) : on n'insiste pas auprès d'un serveur qui refuse.
      const delay = Math.min(REFRESH_MS * 2 ** failures, MAX_BACKOFF_MS)
      if (!controller.signal.aborted) timer = setTimeout(tick, failures ? delay : REFRESH_MS)
    }
    // Onglet caché : on suspend le rafraîchissement, on reprend au retour.
    const tick = () => {
      if (document.hidden) {
        timer = setTimeout(tick, REFRESH_MS)
        return
      }
      void load()
    }
    void load()

    return () => {
      controller.abort()
      clearTimeout(timer)
    }
  }, [])

  return { rooms, error }
}
