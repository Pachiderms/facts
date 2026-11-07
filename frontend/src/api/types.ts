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
}

export interface CreatedRoom {
  id: string
  visibility: Visibility
  access_code: string | null
}

export type Role = 'A' | 'B' | 'spectator'
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

export interface RoomMessage {
  id: number
  speaker: 'A' | 'B'
  speaker_name: string
  text: string
  /** ISO 8601, UTC. */
  timestamp: string
  check: MessageCheck
}

export interface Presence {
  A: boolean
  B: boolean
  spectators: number
}

/** Événements serveur -> client sur le WebSocket d'un salon. */
export type ServerEvent =
  | { type: 'snapshot'; role: Role; room: RoomSummary; messages: RoomMessage[] }
  | ({ type: 'presence' } & Presence)
  | { type: 'message'; message: RoomMessage; trust_score: number | null }
  | {
      type: 'check_result'
      message_id: number
      check: MessageCheck
      trust_score: number | null
      trust_delta: number
    }
  | { type: 'error'; code: string; detail: string }

/** Limites alignées sur le backend (CheckRequest et ws_max_message_chars). */
export const ASSERTION_MIN = 10
export const ASSERTION_MAX = 500
export const MESSAGE_MAX = 500
export const ROOM_TITLE_MIN = 10
export const ROOM_TITLE_MAX = 120
