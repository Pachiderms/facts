import { useEffect, useState } from 'react'
import { listRooms } from '../api/client'
import type { RoomSummary } from '../api/types'

const REFRESH_MS = 15_000

/** Liste des salons, rafraîchie périodiquement (le score évolue pendant les débats). */
export function useRooms() {
  const [rooms, setRooms] = useState<RoomSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>

    const load = async () => {
      try {
        const data = await listRooms(controller.signal)
        setRooms(data)
        setError(null)
      } catch (e) {
        if (controller.signal.aborted) return
        setError(e instanceof Error ? e.message : 'Impossible de charger les salons.')
      }
      if (!controller.signal.aborted) timer = setTimeout(load, REFRESH_MS)
    }
    void load()

    return () => {
      controller.abort()
      clearTimeout(timer)
    }
  }, [])

  return { rooms, error }
}
