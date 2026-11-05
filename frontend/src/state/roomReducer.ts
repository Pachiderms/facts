import type { SocketStatus } from '../api/socket'
import type { MessageCheck, Presence, Role, RoomMessage, RoomSummary, ServerEvent } from '../api/types'

/** Plafond local : le serveur borne déjà l'historique, on borne aussi l'affichage. */
export const MAX_MESSAGES = 500

export interface RoomState {
  status: SocketStatus
  role: Role | null
  room: RoomSummary | null
  messages: RoomMessage[]
  presence: Presence | null
  trustScore: number | null
  /** Variation du score provoquée par la vérification de chaque message, par id. */
  deltas: Record<number, number>
  /** Message d'erreur serveur à afficher (rate limit, rôle...), effaçable. */
  notice: string | null
}

export const initialRoomState: RoomState = {
  status: 'connecting',
  role: null,
  room: null,
  messages: [],
  presence: null,
  trustScore: null,
  deltas: {},
  notice: null,
}

export type RoomAction =
  | { type: 'status'; status: SocketStatus }
  | { type: 'server'; event: ServerEvent }
  | { type: 'dismiss_notice' }
  | { type: 'reset' }

function withCheck(messages: RoomMessage[], id: number, check: MessageCheck): RoomMessage[] {
  return messages.map((m) => (m.id === id ? { ...m, check } : m))
}

export function roomReducer(state: RoomState, action: RoomAction): RoomState {
  switch (action.type) {
    case 'reset':
      return initialRoomState
    case 'dismiss_notice':
      return { ...state, notice: null }
    case 'status':
      return { ...state, status: action.status }
    case 'server': {
      const event = action.event
      switch (event.type) {
        case 'snapshot':
          // Après une reconnexion, le snapshot REMPLACE l'état : pas de doublons ni de trous.
          return {
            ...state,
            role: event.role,
            room: event.room,
            messages: event.messages.slice(-MAX_MESSAGES),
            trustScore: event.room.trust_score,
            deltas: {},
          }
        case 'presence':
          return { ...state, presence: { A: event.A, B: event.B, spectators: event.spectators } }
        case 'message': {
          if (state.messages.some((m) => m.id === event.message.id)) return state
          return {
            ...state,
            messages: [...state.messages, event.message].slice(-MAX_MESSAGES),
            trustScore: event.trust_score,
          }
        }
        case 'check_result':
          return {
            ...state,
            messages: withCheck(state.messages, event.message_id, event.check),
            trustScore: event.trust_score,
            deltas: event.trust_delta ? { ...state.deltas, [event.message_id]: event.trust_delta } : state.deltas,
          }
        case 'error':
          // `detail` est un message serveur générique en français, sûr à afficher.
          return { ...state, notice: event.detail || 'Une erreur est survenue.' }
      }
    }
  }
}
