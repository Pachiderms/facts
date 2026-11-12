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

  const send = useCallback((text: string, replyTo: number | null = null): boolean => socket.current?.send(text, replyTo) ?? false, [])
  const dismissNotice = useCallback(() => dispatch({ type: 'dismiss_notice' }), [])
  const dismissWarning = useCallback(() => dispatch({ type: 'dismiss_warning' }), [])
  const dismissReportNotice = useCallback(() => dispatch({ type: 'dismiss_report_notice' }), [])
  const dismissKickNotice = useCallback(() => dispatch({ type: 'dismiss_kick_notice' }), [])
  const kick = useCallback((target: number): boolean => socket.current?.kick(target) ?? false, [])
  const takeSeat = useCallback((): boolean => socket.current?.takeSeat() ?? false, [])
  const vote = useCallback((approve: boolean): boolean => {
    const ok = socket.current?.vote(approve) ?? false
    if (ok) dispatch({ type: 'voted' })
    return ok
  }, [])
  const report = useCallback((messageId: number): boolean => socket.current?.report(messageId) ?? false, [])

  return { ...state, send, report, kick, vote, takeSeat, dismissNotice, dismissWarning, dismissReportNotice, dismissKickNotice }
}
