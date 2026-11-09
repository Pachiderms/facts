import { getParticipantToken } from '../lib/identity'
import { wsBase } from './client'
import type { ServerEvent } from './types'

export type SocketStatus = 'connecting' | 'open' | 'reconnecting' | 'closed'

/**
 * 1008 : salon inconnu, code refusé ou origine refusée ; 4000 : même identité connectée dans un autre
 * onglet (cette connexion a cédé sa place). Réessayer ne changerait rien, voire se disputerait la place.
 */
const NO_RETRY_CODES = new Set([1000, 1008, 1009, 4000]) // 1008 couvre aussi l'exclusion (« banned »)
const BASE_DELAY_MS = 1_000
const MAX_DELAY_MS = 30_000
/** 1013 : « réessayez plus tard » (salon ou IP saturés) : on temporise davantage. */
const BUSY_MIN_DELAY_MS = 10_000

const EVENT_TYPES = new Set(['snapshot', 'presence', 'message', 'check_result', 'error', 'moderation', 'message_removed', 'report_result', 'kick_vote', 'kick_result', 'role'])

/** Décode un événement serveur ; retourne `null` si la trame est invalide (ignorée). */
export function parseServerEvent(raw: unknown): ServerEvent | null {
  if (typeof raw !== 'string') return null
  try {
    const data: unknown = JSON.parse(raw)
    if (typeof data === 'object' && data !== null && EVENT_TYPES.has((data as { type?: string }).type ?? '')) {
      return data as ServerEvent
    }
  } catch {
    /* JSON invalide */
  }
  return null
}

export function reconnectDelay(attempt: number, closeCode: number | null, random: () => number = Math.random): number {
  const exponential = Math.min(MAX_DELAY_MS, BASE_DELAY_MS * 2 ** attempt)
  const jitter = exponential * 0.25 * random() // évite que tous les clients se reconnectent ensemble
  const delay = exponential + jitter
  return closeCode === 1013 ? Math.max(delay, BUSY_MIN_DELAY_MS) : delay
}

interface Handlers {
  onEvent: (event: ServerEvent) => void
  onStatus: (status: SocketStatus) => void
}

export interface SocketOptions {
  /** Jeton d'identité ; par défaut celui du navigateur. */
  token?: string
  /** Code d'accès d'un salon privé. */
  code?: string
  /** Entrer en spectateur même s'il reste des sièges d'intervenant. */
  spectate?: boolean
}

/** Connexion WebSocket d'un salon, avec reconnexion automatique (backoff exponentiel + jitter). */
export class RoomSocket {
  private ws: WebSocket | null = null
  private attempt = 0
  private timer: ReturnType<typeof setTimeout> | null = null
  private stopped = false

  constructor(
    private readonly roomId: string,
    private readonly handlers: Handlers,
    private readonly options: SocketOptions = {},
  ) {}

  connect(): void {
    this.stopped = false
    this.open()
  }

  private open(): void {
    this.handlers.onStatus(this.attempt === 0 ? 'connecting' : 'reconnecting')
    const ws = new WebSocket(`${wsBase()}/api/v1/rooms/${encodeURIComponent(this.roomId)}/ws`)
    this.ws = ws
    ws.onopen = () => {
      // Premier message obligatoire : identité et, pour un salon privé, code d'accès.
      const { code, spectate } = this.options
      ws.send(
        JSON.stringify({
          type: 'hello',
          token: this.options.token ?? getParticipantToken(),
          ...(code ? { code } : {}),
          ...(spectate ? { spectate: true } : {}),
        }),
      )
      this.attempt = 0
      this.handlers.onStatus('open')
    }
    ws.onmessage = (e: MessageEvent) => {
      const event = parseServerEvent(e.data)
      if (event) this.handlers.onEvent(event)
    }
    ws.onclose = (e: CloseEvent) => {
      if (this.ws !== ws) return
      this.ws = null
      if (this.stopped || NO_RETRY_CODES.has(e.code)) {
        this.handlers.onStatus('closed')
        return
      }
      this.handlers.onStatus('reconnecting')
      this.timer = setTimeout(() => this.open(), reconnectDelay(this.attempt++, e.code))
    }
  }

  /** Envoie un message ; retourne `false` si la connexion n'est pas ouverte. */
  send(text: string): boolean {
    if (this.ws?.readyState !== WebSocket.OPEN) return false
    this.ws.send(JSON.stringify({ type: 'message', text }))
    return true
  }

  /** Signale le message d'un autre participant : un second avis (filtre + IA) décide, jamais le signaleur seul. */
  report(messageId: number): boolean {
    if (this.ws?.readyState !== WebSocket.OPEN) return false
    this.ws.send(JSON.stringify({ type: 'report', message_id: messageId }))
    return true
  }

  /** Créateur : propose d'exclure un participant (le serveur vérifie score, seuil et droits). */
  kick(target: number): boolean {
    return this.sendJson({ type: 'kick', target })
  }

  /** Spectateur : vote pour (`true`) ou contre l'exclusion en cours. Un seul vote par personne. */
  vote(approve: boolean): boolean {
    return this.sendJson({ type: 'vote', approve })
  }

  /** Spectateur : prend une place d'intervenant libre (premier arrivé, premier servi). */
  takeSeat(): boolean {
    return this.sendJson({ type: 'take_seat' })
  }

  private sendJson(payload: object): boolean {
    if (this.ws?.readyState !== WebSocket.OPEN) return false
    this.ws.send(JSON.stringify(payload))
    return true
  }

  close(): void {
    this.stopped = true
    if (this.timer) clearTimeout(this.timer)
    const ws = this.ws
    this.ws = null
    ws?.close(1000)
    this.handlers.onStatus('closed')
  }
}
