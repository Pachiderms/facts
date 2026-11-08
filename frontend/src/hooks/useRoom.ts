import { useCallback, useEffect, useReducer, useRef } from 'react'
import { RoomSocket } from '../api/socket'
import { initialRoomState, roomReducer } from '../state/roomReducer'

/** Connexion temps réel à un salon. Se connecte au montage, se ferme au démontage. */
export function useRoom(roomId: string, code?: string, spectate = false) {
  const [state, dispatch] = useReducer(roomReducer, initialRoomState)
  const socket = useRef<RoomSocket | null>(null)

  useEffect(() => {
    dispatch({ type: 'reset' })
    const s = new RoomSocket(roomId, {
      onEvent: (event) => dispatch({ type: 'server', event }),
      onStatus: (status) => dispatch({ type: 'status', status }),
    }, { code, spectate })
    socket.current = s
    s.connect()
    return () => {
      s.close()
      socket.current = null
    }
  }, [roomId, code, spectate])

  const send = useCallback((text: string): boolean => socket.current?.send(text) ?? false, [])
  const dismissNotice = useCallback(() => dispatch({ type: 'dismiss_notice' }), [])

  return { ...state, send, dismissNotice }
}
