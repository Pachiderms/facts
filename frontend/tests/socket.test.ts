import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RoomSocket, parseServerEvent, reconnectDelay, type SocketStatus } from '../src/api/socket'
import type { ServerEvent } from '../src/api/types'

class FakeWebSocket {
  static OPEN = 1
  static instances: FakeWebSocket[] = []
  readyState = 0
  sent: string[] = []
  closedWith: number | null = null
  onopen: (() => void) | null = null
  onmessage: ((e: { data: unknown }) => void) | null = null
  onclose: ((e: { code: number }) => void) | null = null
  constructor(public url: string) {
    FakeWebSocket.instances.push(this)
  }
  send(data: string) {
    this.sent.push(data)
  }
  close(code?: number) {
    this.closedWith = code ?? null
  }
  // aides de test
  open() {
    this.readyState = FakeWebSocket.OPEN
    this.onopen?.()
  }
  receive(data: unknown) {
    this.onmessage?.({ data })
  }
  drop(code: number) {
    this.readyState = 3
    this.onclose?.({ code })
  }
}

describe('parseServerEvent', () => {
  it('décode un événement valide', () => {
    expect(parseServerEvent('{"type":"presence","A":true,"B":false,"spectators":2}')).toMatchObject({ type: 'presence', spectators: 2 })
  })

  it.each([['pas du json'], ['{"type":"inconnu"}'], ['{"sans":"type"}'], ['null'], ['[]'], [42], [new ArrayBuffer(2)]])('ignore la trame invalide %#', (raw) => {
    expect(parseServerEvent(raw)).toBeNull()
  })
})

describe('reconnectDelay', () => {
  it('croît de façon exponentielle puis plafonne', () => {
    const noJitter = () => 0
    expect(reconnectDelay(0, 1006, noJitter)).toBe(1_000)
    expect(reconnectDelay(1, 1006, noJitter)).toBe(2_000)
    expect(reconnectDelay(3, 1006, noJitter)).toBe(8_000)
    expect(reconnectDelay(20, 1006, noJitter)).toBe(30_000)
  })

  it('ajoute au plus 25 % de jitter', () => {
    expect(reconnectDelay(2, 1006, () => 1)).toBe(5_000)
  })

  it('temporise au moins 10 s quand le serveur est saturé (1013)', () => {
    expect(reconnectDelay(0, 1013, () => 0)).toBe(10_000)
  })
})

describe('RoomSocket', () => {
  let events: ServerEvent[]
  let statuses: SocketStatus[]
  let socket: RoomSocket

  beforeEach(() => {
    vi.useFakeTimers()
    FakeWebSocket.instances = []
    vi.stubGlobal('WebSocket', FakeWebSocket)
    vi.spyOn(Math, 'random').mockReturnValue(0)
    events = []
    statuses = []
    socket = new RoomSocket('room-1', { onEvent: (e) => events.push(e), onStatus: (s) => statuses.push(s) })
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  const current = () => FakeWebSocket.instances.at(-1)!

  it('se connecte à l’URL du salon (identifiant encodé)', () => {
    new RoomSocket('a b/c', { onEvent: () => undefined, onStatus: () => undefined }).connect()
    expect(current().url).toMatch(/\/api\/v1\/rooms\/a%20b%2Fc\/ws$/)
  })

  it('passe connecting -> open et transmet les événements valides seulement', () => {
    socket.connect()
    current().open()
    current().receive('{"type":"presence","A":true,"B":true,"spectators":0}')
    current().receive('trame invalide')
    expect(statuses).toEqual(['connecting', 'open'])
    expect(events).toHaveLength(1)
  })

  it('envoie un message au format attendu, et refuse si la connexion n’est pas ouverte', () => {
    socket.connect()
    expect(socket.send('trop tôt')).toBe(false)
    current().open()
    expect(socket.send('Selon l’INSEE…')).toBe(true)
    expect(JSON.parse(current().sent[0]!)).toEqual({ type: 'message', text: 'Selon l’INSEE…' })
  })

  it('se reconnecte après une coupure, avec délai croissant', () => {
    socket.connect()
    current().open()
    current().drop(1006)
    expect(statuses.at(-1)).toBe('reconnecting')
    expect(FakeWebSocket.instances).toHaveLength(1)
    vi.advanceTimersByTime(1_000)
    expect(FakeWebSocket.instances).toHaveLength(2)
    current().drop(1006) // échec sans ouverture : délai suivant doublé
    vi.advanceTimersByTime(1_999)
    expect(FakeWebSocket.instances).toHaveLength(2)
    vi.advanceTimersByTime(1)
    expect(FakeWebSocket.instances).toHaveLength(3)
  })

  it('remet le délai à zéro après une connexion réussie', () => {
    socket.connect()
    current().drop(1006)
    vi.advanceTimersByTime(1_000)
    current().open()
    current().drop(1006)
    vi.advanceTimersByTime(1_000)
    expect(FakeWebSocket.instances).toHaveLength(3)
  })

  it.each([1008, 1009, 1000])('ne se reconnecte pas après le code %i', (code) => {
    socket.connect()
    current().drop(code)
    vi.advanceTimersByTime(60_000)
    expect(FakeWebSocket.instances).toHaveLength(1)
    expect(statuses.at(-1)).toBe('closed')
  })

  it('close() annule toute reconnexion programmée et ferme proprement', () => {
    socket.connect()
    current().open()
    current().drop(1006)
    socket.close()
    vi.advanceTimersByTime(60_000)
    expect(FakeWebSocket.instances).toHaveLength(1)
    expect(statuses.at(-1)).toBe('closed')
  })

  it('close() ferme le socket ouvert avec le code 1000', () => {
    socket.connect()
    current().open()
    const ws = current()
    socket.close()
    expect(ws.closedWith).toBe(1000)
  })

  it('ignore les événements d’un ancien socket après reconnexion', () => {
    socket.connect()
    const old = current()
    old.drop(1006)
    vi.advanceTimersByTime(1_000)
    old.drop(1006) // fermeture tardive de l’ancien : ne doit pas déclencher une 2e reconnexion
    vi.advanceTimersByTime(60_000)
    expect(FakeWebSocket.instances).toHaveLength(2)
  })
})
