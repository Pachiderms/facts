import type { SocketStatus } from '../api/socket'
import { REPORT_OUTCOMES, type KickVote, type MessageCheck, type Presence, type Role, type RoomMessage, type RoomSummary, type ServerEvent } from '../api/types'

/** Plafond local : le serveur borne déjà l'historique, on borne aussi l'affichage. */
export const MAX_MESSAGES = 500

export interface RoomState {
  status: SocketStatus
  role: Role | null
  /** Mon numéro de participant dans ce salon (null : spectateur ou pas encore connecté). */
  you: number | null
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
  /** Vote d'exclusion en cours. */
  kickVote: KickVote | null
  /** J'ai déjà voté sur le vote en cours (le serveur refuse un second vote). */
  voted: boolean
  /** Issue d'un vote d'exclusion, effaçable. */
  kickNotice: string | null
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

export type DeniedReason =
  | 'invalid_code'
  | 'too_many_attempts'
  | 'session_replaced'
  | 'spectators_not_allowed'
  | 'room_deleted'
  | 'banned'
  | 'kicked'
const DENIED_CODES: readonly string[] = ['invalid_code', 'too_many_attempts', 'session_replaced', 'spectators_not_allowed', 'room_deleted', 'banned', 'kicked']

export const initialRoomState: RoomState = {
  status: 'connecting',
  role: null,
  you: null,
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
  kickVote: null,
  voted: false,
  kickNotice: null,
}

export type RoomAction =
  | { type: 'status'; status: SocketStatus }
  | { type: 'server'; event: ServerEvent }
  | { type: 'dismiss_notice' }
  | { type: 'dismiss_warning' }
  | { type: 'dismiss_report_notice' }
  | { type: 'dismiss_kick_notice' }
  | { type: 'voted' }
  | { type: 'reset' }

function kickText(outcome: string, target: number, you: number | null): string | null {
  const who = target === you ? 'Vous' : `Participant ${target}`
  if (outcome === 'kicked') return `${who} ${target === you ? 'avez été exclu' : 'a été exclu'} du salon.`
  if (outcome === 'kept') return `Le vote n’a pas abouti : ${who === 'Vous' ? 'vous restez' : `${who} reste`} dans le salon.`
  if (outcome === 'cancelled') return 'Le vote d’exclusion a été annulé.'
  return null
}

/** Valide un vote reçu : le serveur n'est pas cru sur parole pour l'affichage (nombres entiers bornés). */
function validVote(raw: unknown): KickVote | null {
  if (typeof raw !== 'object' || raw === null) return null
  const v = raw as Record<string, unknown>
  const ints = ['target', 'score', 'threshold', 'yes', 'no', 'ends_in', 'voters'] as const
  if (!ints.every((k) => Number.isInteger(v[k]) && (v[k] as number) >= 0)) return null
  return { target: v.target, score: v.score, threshold: v.threshold, yes: v.yes, no: v.no, ends_in: v.ends_in, voters: v.voters } as KickVote
}

function cleanScores(raw: unknown): Record<string, number | null> {
  if (typeof raw !== 'object' || raw === null) return {}
  const out: Record<string, number | null> = {}
  for (const [k, v] of Object.entries(raw)) if (/^\d+$/.test(k) && (v === null || (typeof v === 'number' && Number.isFinite(v)))) out[k] = v
  return out
}

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
    case 'dismiss_kick_notice':
      return { ...state, kickNotice: null }
    case 'voted':
      return { ...state, voted: true }
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
            you: Number.isInteger(event.you) ? (event.you as number) : null,
            room: event.room,
            messages: event.messages.slice(-MAX_MESSAGES),
            trustScore: event.room.trust_score,
            deltas: {},
            kickVote: validVote(event.kick_vote),
            voted: false, // le serveur refuse un second vote : au pire, une erreur claire
            presence: state.presence ? { ...state.presence, scores: cleanScores(event.scores) } : state.presence,
          }
        case 'presence':
          return {
            ...state,
            presence: {
              present: Array.isArray(event.present) ? event.present.filter((n): n is number => Number.isInteger(n)) : [],
              max_participants: event.max_participants,
              spectators: event.spectators,
              scores: cleanScores(event.scores),
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
            messages: state.messages.map((m) => {
              if (m.id === event.message_id) {
                return { ...m, text: event.text, removed: true, check: { ...m.check, status: 'no_claim', badge_type: 'gray', badge_text: 'RETIRÉ', note: '', sources: [] } }
              }
              // Les réponses ne doivent plus afficher le propos retiré.
              return m.reply_to?.id === event.message_id ? { ...m, reply_to: { ...m.reply_to, preview: event.text } } : m
            }),
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
        case 'kick_vote': {
          const vote = validVote(event)
          if (vote === null) return state
          return { ...state, kickVote: vote, voted: state.kickVote?.target === vote.target ? state.voted : false }
        }
        case 'kick_result':
          return { ...state, kickVote: null, voted: false, kickNotice: kickText(event.outcome, event.target, state.you) }
        case 'role':
          return {
            ...state,
            role: event.role,
            you: Number.isInteger(event.you) ? (event.you as number) : null,
            kickVote: null,
            voted: false,
          }
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
