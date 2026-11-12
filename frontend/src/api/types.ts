/** Contrats de l'API backend (voir backend/app/core/schemas.py et backend/app/services/rooms.py). */

export type Verdict = 'VRAI' | 'FAUX' | 'À NUANCER' | 'NON VÉRIFIABLE'

export interface View {
  title: string
  points: string[]
}

export interface Source {
  title: string
  url: string
  domain: string
  trust_score: number
}

export interface CheckResponse {
  verdict: Verdict
  confidence_score: number
  summary: string
  liberal_institutional_view: View
  heterodox_social_view: View
  verified_sources: Source[]
  cached: boolean
}

export interface RoomSummary {
  id: string
  title: string
  category: string
  theme_category: string
  visibility: 'public' | 'private'
  max_participants: number
  spectators_allowed: boolean
  /** Score individuel (en dessous) à partir duquel le créateur peut proposer une exclusion. */
  kick_threshold?: number
  /** Dans le snapshot : vrai pour le créateur du salon (il peut le supprimer s'il est vide). */
  is_owner?: boolean
  /** Présent uniquement dans le snapshot envoyé au PROPRIÉTAIRE d'un salon privé. */
  access_code?: string
  /** `null` tant qu'aucun message vérifiable n'a été évalué. */
  trust_score: number | null
  message_count: number
  participants: number
  spectators: number
}

export type Visibility = 'public' | 'private'

/** Résultat d'une recherche par ID : un salon privé ne révèle ni titre ni contenu. */
export interface RoomLookup {
  id: string
  visibility: Visibility
  requires_code: boolean
  room: RoomSummary | null
}

export interface CreateRoomInput {
  title: string
  theme_category: string
  visibility: Visibility
  max_participants: number
  spectators_allowed: boolean
  kick_threshold?: number
}

export interface CreatedRoom {
  id: string
  visibility: Visibility
  access_code: string | null
}

export const SEAT_LETTERS = ['A', 'B', 'C', 'D', 'E', 'F'] as const
export type Seat = (typeof SEAT_LETTERS)[number]
export type Role = Seat | 'spectator'
export const isSeat = (value: unknown): value is Seat => SEAT_LETTERS.includes(value as Seat)
export const PARTICIPANTS_MIN = 2
export const PARTICIPANTS_MAX = 6
export const KICK_THRESHOLDS = [20, 25, 30, 35, 40] as const
export const KICK_THRESHOLD_DEFAULT = 30
export type BadgeType = 'green' | 'amber' | 'red' | 'gray'
export type CheckStatus =
  | 'pending'
  | 'verified'
  | 'nuanced'
  | 'false'
  | 'unsourced'
  | 'unchecked'
  | 'no_claim'

export interface MessageCheck {
  status: CheckStatus
  badge_type: BadgeType
  badge_text: string
  note: string
  sources: { title: string; url: string; domain: string }[]
}

/** Citation d'un message précédent. L'aperçu est fourni par le SERVEUR (jamais par l'auteur de la réponse). */
export interface ReplyRef {
  id: number
  speaker: number
  preview: string
}

export interface RoomMessage {
  id: number
  /** Numéro stable de l'auteur dans ce salon (« Participant N »), jamais réattribué. */
  speaker: number
  speaker_name: string
  text: string
  /** ISO 8601, UTC. */
  timestamp: string
  check: MessageCheck
  /** Retiré par la modération : le texte d'origine n'est plus fourni. */
  removed?: boolean
  /** Message auquel celui-ci répond, s'il y en a un. */
  reply_to?: ReplyRef | null
}

export interface Presence {
  /** Numéros des participants actuellement connectés. */
  present: number[]
  max_participants: number
  spectators: number
  /** Score individuel (0-100) des connectés, par numéro ; `null` tant qu'il y a moins de 3 messages vérifiés. */
  scores?: Record<string, number | null>
}

/** Vote d'exclusion en cours (les identités des votants ne sont jamais transmises). */
export interface KickVote {
  target: number
  score: number
  threshold: number
  yes: number
  no: number
  /** Secondes restantes au moment de l'envoi. */
  ends_in: number
  /** Nombre de spectateurs pouvant voter. */
  voters: number
}

export type KickOutcome = 'kicked' | 'kept' | 'cancelled'

/** Événements serveur -> client sur le WebSocket d'un salon. */
export type ServerEvent =
  | {
      type: 'snapshot'
      role: Role
      you?: number | null
      room: RoomSummary
      messages: RoomMessage[]
      kick_vote?: (Omit<KickVote, never> & { type?: 'kick_vote' }) | null
      scores?: Record<string, number | null>
    }
  | ({ type: 'presence' } & Presence)
  | { type: 'message'; message: RoomMessage; trust_score: number | null }
  | {
      type: 'check_result'
      message_id: number
      check: MessageCheck
      trust_score: number | null
      trust_delta: number
    }
  | { type: 'error'; code: string; detail: string; retry_after?: number }
  | {
      type: 'moderation'
      level: 'rephrase' | 'warning' | 'final_warning' | 'banned'
      strikes: number
      max_strikes: number
      detail: string
      retry_after?: number
    }
  | { type: 'message_removed'; message_id: number; text: string; trust_score: number | null; trust_delta: number }
  | { type: 'report_result'; message_id: number; outcome: ReportOutcome }
  | ({ type: 'kick_vote' } & KickVote)
  | { type: 'kick_result'; target: number; outcome: KickOutcome }
  | { type: 'role'; role: Role; you: number | null }

export type ReportOutcome = 'removed' | 'kept' | 'unavailable' | 'duplicate' | 'own' | 'unknown'
export const REPORT_OUTCOMES: readonly ReportOutcome[] = ['removed', 'kept', 'unavailable', 'duplicate', 'own', 'unknown']

/** Limites alignées sur le backend (CheckRequest et ws_max_message_chars). */
export const ASSERTION_MIN = 10
export const ASSERTION_MAX = 500
export const MESSAGE_MAX = 500
export const ROOM_TITLE_MIN = 10
export const ROOM_TITLE_MAX = 120
