import type { SocketStatus } from '../api/socket'
import { REPORT_OUTCOMES, isSeat, type MessageCheck, type Presence, type Role, type RoomMessage, type RoomSummary, type ServerEvent } from '../api/types'

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
  /** Accès refusé à l'ouverture : l'interface propose alors l'action adaptée (saisir le code...). */
  denied: DeniedReason | null
  /** Durée d'exclusion restante (secondes) quand `denied === 'banned'`. */
  banRetryAfter: number | null
  /** Avertissement de modération reçu (message refusé) ; effaçable. */
  warning: ModerationWarning | null
  /** Réponse à un signalement, effaçable. */
  reportNotice: string | null
}

export interface ModerationWarning {
  level: 'rephrase' | 'warning' | 'final_warning'
  strikes: number
  maxStrikes: number
  detail: string
}

const REPORT_TEXT: Record<string, string> = {
  removed: 'Merci : le message a été retiré par la modération.',
  kept: 'Merci : le message a été examiné et respecte les règles du salon.',
  unavailable: 'Signalement impossible pour le moment. Réessayez plus tard.',
  duplicate: 'Vous avez déjà signalé ce message.',
  own: 'Vous ne pouvez pas signaler votre propre message.',
  unknown: 'Ce message n’existe plus.',
}

export type DeniedReason = 'invalid_code' | 'too_many_attempts' | 'session_replaced' | 'spectators_not_allowed' | 'room_deleted' | 'banned'
const DENIED_CODES: readonly string[] = ['invalid_code', 'too_many_attempts', 'session_replaced', 'spectators_not_allowed', 'room_deleted', 'banned']

export const initialRoomState: RoomState = {
  status: 'connecting',
  role: null,
  room: null,
  messages: [],
  presence: null,
  trustScore: null,
  deltas: {},
  notice: null,
  denied: null,
  warning: null,
  reportNotice: null,
  banRetryAfter: null,
}

export type RoomAction =
  | { type: 'status'; status: SocketStatus }
  | { type: 'server'; event: ServerEvent }
  | { type: 'dismiss_notice' }
  | { type: 'dismiss_warning' }
  | { type: 'dismiss_report_notice' }
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
    case 'dismiss_warning':
      return { ...state, warning: null }
    case 'dismiss_report_notice':
      return { ...state, reportNotice: null }
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
          return {
            ...state,
            presence: {
              seats: Array.isArray(event.seats) ? event.seats.filter(isSeat) : [],
              max_participants: event.max_participants,
              spectators: event.spectators,
            },
          }
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
        case 'message_removed':
          return {
            ...state,
            messages: state.messages.map((m) =>
              m.id === event.message_id
                ? { ...m, text: event.text, removed: true, check: { ...m.check, status: 'no_claim', badge_type: 'gray', badge_text: 'RETIRÉ', note: '', sources: [] } }
                : m,
            ),
            trustScore: event.trust_score,
            deltas: Object.fromEntries(Object.entries(state.deltas).filter(([id]) => Number(id) !== event.message_id)),
          }
        case 'moderation':
          if (event.level === 'banned') {
            return { ...state, denied: 'banned', banRetryAfter: Number.isFinite(event.retry_after) ? event.retry_after! : null }
          }
          return {
            ...state,
            warning: { level: event.level, strikes: event.strikes, maxStrikes: event.max_strikes, detail: event.detail },
          }
        case 'report_result':
          return { ...state, reportNotice: REPORT_TEXT[REPORT_OUTCOMES.includes(event.outcome) ? event.outcome : 'unavailable'] ?? null }
        case 'error':
          if (DENIED_CODES.includes(event.code)) {
            return {
              ...state,
              denied: event.code as DeniedReason,
              banRetryAfter: event.code === 'banned' && Number.isFinite(event.retry_after) ? event.retry_after! : state.banRetryAfter,
            }
          }
          // `detail` est un message serveur générique en français, sûr à afficher.
          return { ...state, notice: event.detail || 'Une erreur est survenue.' }
      }
    }
  }
}
