import { describe, expect, it } from 'vitest'
import type { MessageCheck, RoomMessage, RoomSummary, ServerEvent } from '../src/api/types'
import { MAX_MESSAGES, initialRoomState, roomReducer, type RoomState } from '../src/state/roomReducer'

const PENDING: MessageCheck = { status: 'pending', badge_type: 'gray', badge_text: 'VÉRIFICATION EN COURS', note: '', sources: [] }
const VERIFIED: MessageCheck = { status: 'verified', badge_type: 'green', badge_text: 'VÉRIFIÉ', note: '', sources: [] }

const msg = (id: number, over: Partial<RoomMessage> = {}): RoomMessage => ({
  id,
  speaker: 1,
  speaker_name: 'Participant 1',
  text: `Message ${id}`,
  timestamp: '2026-11-05T10:00:00+00:00',
  check: PENDING,
  ...over,
})

const room = (over: Partial<RoomSummary> = {}): RoomSummary => ({
  id: 'room-1',
  title: 'Titre',
  category: 'Cat',
  theme_category: 'social',
  visibility: 'public',
  trust_score: null,
  message_count: 0,
  participants: 1,
  max_participants: 2,
  spectators_allowed: true,
  spectators: 0,
  ...over,
})

const apply = (state: RoomState, event: ServerEvent) => roomReducer(state, { type: 'server', event })

describe('roomReducer', () => {
  it('snapshot : rôle, salon, historique et score', () => {
    const s = apply(initialRoomState, { type: 'snapshot', role: 'B', room: room({ trust_score: 62 }), messages: [msg(1)] })
    expect(s).toMatchObject({ role: 'B', trustScore: 62 })
    expect(s.messages).toHaveLength(1)
  })

  it('un nouveau snapshot (reconnexion) remplace l’état sans doublon', () => {
    let s = apply(initialRoomState, { type: 'snapshot', role: 'A', room: room(), messages: [msg(1), msg(2)] })
    s = apply(s, { type: 'message', message: msg(3), trust_score: null })
    s = apply(s, { type: 'snapshot', role: 'A', room: room(), messages: [msg(1), msg(2), msg(3), msg(4)] })
    expect(s.messages.map((m) => m.id)).toEqual([1, 2, 3, 4])
    expect(s.deltas).toEqual({})
  })

  it('message : ajoute et met à jour le score ; ignore un doublon', () => {
    let s = apply(initialRoomState, { type: 'message', message: msg(1), trust_score: 50 })
    s = apply(s, { type: 'message', message: msg(1), trust_score: 99 })
    expect(s.messages).toHaveLength(1)
    expect(s.trustScore).toBe(50)
  })

  it('check_result : met à jour le badge du bon message, le score et la variation', () => {
    let s = apply(initialRoomState, { type: 'message', message: msg(1), trust_score: null })
    s = apply(s, { type: 'message', message: msg(2), trust_score: null })
    s = apply(s, { type: 'check_result', message_id: 2, check: VERIFIED, trust_score: 61, trust_delta: 11 })
    expect(s.messages[0]!.check.status).toBe('pending')
    expect(s.messages[1]!.check.status).toBe('verified')
    expect(s.trustScore).toBe(61)
    expect(s.deltas).toEqual({ 2: 11 })
  })

  it('check_result : une variation nulle n’est pas mémorisée ; un message inconnu est ignoré sans casser', () => {
    let s = apply(initialRoomState, { type: 'message', message: msg(1), trust_score: null })
    s = apply(s, { type: 'check_result', message_id: 1, check: VERIFIED, trust_score: 50, trust_delta: 0 })
    expect(s.deltas).toEqual({})
    s = apply(s, { type: 'check_result', message_id: 999, check: VERIFIED, trust_score: 55, trust_delta: 5 })
    expect(s.messages).toHaveLength(1)
  })

  it('le score peut rester null (aucune vérification) sans devenir 0', () => {
    const s = apply(initialRoomState, { type: 'message', message: msg(1), trust_score: null })
    expect(s.trustScore).toBeNull()
  })

  it('presence : stockée telle quelle', () => {
    const s = apply(initialRoomState, { type: 'presence', present: [1], max_participants: 4, spectators: 3 })
    expect(s.presence).toEqual({ present: [1], max_participants: 4, spectators: 3, scores: {} })
  })

  it('error : affiche le message serveur ; dismiss l’efface ; texte vide -> message par défaut', () => {
    let s = apply(initialRoomState, { type: 'error', code: 'rate_limited', detail: 'Trop de messages, ralentissez.' })
    expect(s.notice).toBe('Trop de messages, ralentissez.')
    s = roomReducer(s, { type: 'dismiss_notice' })
    expect(s.notice).toBeNull()
    s = apply(s, { type: 'error', code: 'x', detail: '' })
    expect(s.notice).toBeTruthy()
  })

  it('borne l’historique affiché', () => {
    let s = initialRoomState
    for (let i = 1; i <= MAX_MESSAGES + 20; i++) s = apply(s, { type: 'message', message: msg(i), trust_score: null })
    expect(s.messages).toHaveLength(MAX_MESSAGES)
    expect(s.messages.at(-1)!.id).toBe(MAX_MESSAGES + 20)
  })

  it('status et reset', () => {
    let s = roomReducer(initialRoomState, { type: 'status', status: 'open' })
    expect(s.status).toBe('open')
    s = apply(s, { type: 'message', message: msg(1), trust_score: 40 })
    expect(roomReducer(s, { type: 'reset' })).toEqual(initialRoomState)
  })
})

describe('accès refusé', () => {
  it.each(['invalid_code', 'too_many_attempts', 'session_replaced'] as const)('%s : mémorisé sans notification générique', (code) => {
    const next = apply(initialRoomState, { type: 'error', code, detail: 'x' })
    expect(next.denied).toBe(code)
    expect(next.notice).toBeNull()
  })

  it('les autres erreurs restent des notifications', () => {
    const next = apply(initialRoomState, { type: 'error', code: 'rate_limited', detail: 'Trop de messages.' })
    expect(next.denied).toBeNull()
    expect(next.notice).toBe('Trop de messages.')
  })

  it('reset efface le refus (changement de code ou de salon)', () => {
    const denied = apply(initialRoomState, { type: 'error', code: 'invalid_code', detail: 'x' })
    expect(roomReducer(denied, { type: 'reset' }).denied).toBeNull()
  })

  it('le snapshot d’un propriétaire transmet le code d’accès', () => {
    const next = apply(initialRoomState, { type: 'snapshot', role: 'A', room: room({ visibility: 'private', access_code: 'k7m2xq' }), messages: [] })
    expect(next.room?.access_code).toBe('k7m2xq')
  })
})

describe('modération', () => {
  const base = (): RoomState => roomReducer(initialRoomState, { type: 'server', event: { type: 'snapshot', role: 'A', room: room(), messages: [msg(1, { check: VERIFIED }), msg(2, { speaker: 2 })] } })
  const server = (state: RoomState, event: ServerEvent) => roomReducer(state, { type: 'server', event })

  it('un avertissement s’affiche et peut être fermé', () => {
    const s = server(base(), { type: 'moderation', level: 'warning', strikes: 1, max_strikes: 3, detail: 'Les insultes sont interdites.' })
    expect(s.warning).toEqual({ level: 'warning', strikes: 1, maxStrikes: 3, detail: 'Les insultes sont interdites.' })
    expect(s.denied).toBeNull()
    expect(roomReducer(s, { type: 'dismiss_warning' }).warning).toBeNull()
  })

  it('le dernier avertissement est distingué', () => {
    const s = server(base(), { type: 'moderation', level: 'final_warning', strikes: 2, max_strikes: 3, detail: 'x' })
    expect(s.warning?.level).toBe('final_warning')
  })

  it('l’exclusion bloque l’accès avec la durée restante', () => {
    const s = server(base(), { type: 'moderation', level: 'banned', strikes: 3, max_strikes: 3, detail: 'x', retry_after: 3600 })
    expect(s.denied).toBe('banned')
    expect(s.banRetryAfter).toBe(3600)
  })

  it('refus à l’ouverture pour exclusion (error banned)', () => {
    const s = server(initialRoomState, { type: 'error', code: 'banned', detail: 'x', retry_after: 1200 })
    expect(s.denied).toBe('banned')
    expect(s.banRetryAfter).toBe(1200)
  })

  it('un retry_after invalide est ignoré', () => {
    const s = server(initialRoomState, { type: 'error', code: 'banned', detail: 'x', retry_after: 'abc' as unknown as number })
    expect(s.banRetryAfter).toBeNull()
  })

  it('un message retiré est remplacé, sans badge ni delta, et le score est mis à jour', () => {
    let s = server(base(), { type: 'check_result', message_id: 1, check: VERIFIED, trust_score: 80, trust_delta: 5 })
    s = server(s, { type: 'message_removed', message_id: 1, text: '[Message retiré par la modération]', trust_score: 60, trust_delta: -20 })
    const removed = s.messages.find((m) => m.id === 1)!
    expect(removed).toMatchObject({ removed: true, text: '[Message retiré par la modération]' })
    expect(removed.check).toMatchObject({ status: 'no_claim', sources: [] })
    expect(s.deltas[1]).toBeUndefined()
    expect(s.trustScore).toBe(60)
    expect(s.messages.find((m) => m.id === 2)?.removed).toBeUndefined()
  })

  it.each([
    ['removed', /retiré/],
    ['kept', /respecte les règles/],
    ['unavailable', /impossible/],
    ['duplicate', /déjà signalé/],
    ['own', /propre message/],
  ] as const)('résultat de signalement %s', (outcome, text) => {
    const s = server(base(), { type: 'report_result', message_id: 2, outcome })
    expect(s.reportNotice).toMatch(text)
    expect(roomReducer(s, { type: 'dismiss_report_notice' }).reportNotice).toBeNull()
  })

  it('un résultat de signalement inattendu retombe sur le message neutre', () => {
    const s = server(base(), { type: 'report_result', message_id: 2, outcome: '<script>' as never })
    expect(s.reportNotice).toMatch(/impossible/)
  })
})

describe('modération : reformulation (vulgarité)', () => {
  it('« rephrase » s’affiche comme invitation à reformuler, sans compter d’avertissement', () => {
    const s = roomReducer(initialRoomState, {
      type: 'server',
      event: { type: 'moderation', level: 'rephrase', strikes: 1, max_strikes: 3, detail: 'Message non publié : merci de le reformuler sans vulgarité.' },
    })
    expect(s.warning?.level).toBe('rephrase')
    expect(s.denied).toBeNull()
  })
})

describe('numéros stables', () => {
  const server = (state: RoomState, event: ServerEvent) => roomReducer(state, { type: 'server', event })

  it('le snapshot donne mon numéro ; un spectateur n’en a pas', () => {
    expect(server(initialRoomState, { type: 'snapshot', role: 'A', you: 2, room: room(), messages: [] }).you).toBe(2)
    expect(server(initialRoomState, { type: 'snapshot', role: 'spectator', you: null, room: room(), messages: [] }).you).toBeNull()
  })

  it('une valeur inattendue pour « you » est ignorée', () => {
    const s = server(initialRoomState, { type: 'snapshot', role: 'A', you: '2' as never, room: room(), messages: [] })
    expect(s.you).toBeNull()
  })

  it('la présence ne garde que des numéros entiers', () => {
    const s = server(initialRoomState, { type: 'presence', present: [1, 'x', 3.5, 3] as never, max_participants: 4, spectators: 0 })
    expect(s.presence?.present).toEqual([1, 3])
    expect(server(initialRoomState, { type: 'presence', present: 'abc' as never, max_participants: 4, spectators: 0 }).presence?.present).toEqual([])
  })

  it('après une reconnexion, mon numéro reste celui du snapshot même si mon siège a changé', () => {
    let s = server(initialRoomState, { type: 'snapshot', role: 'B', you: 2, room: room(), messages: [msg(1, { speaker: 2 })] })
    s = server(s, { type: 'snapshot', role: 'A', you: 2, room: room(), messages: [msg(1, { speaker: 2 })] })
    expect(s).toMatchObject({ role: 'A', you: 2 })
  })
})

describe('roomReducer : exclusion', () => {
  const VOTE = { type: 'kick_vote' as const, target: 2, score: 20, threshold: 30, yes: 1, no: 0, ends_in: 45, voters: 3 }

  it('kick_vote : affiche le vote', () => {
    expect(apply(initialRoomState, VOTE).kickVote).toMatchObject({ target: 2, yes: 1, voters: 3 })
  })

  it('kick_vote invalide (types douteux) : ignoré', () => {
    const bad = { ...VOTE, score: '20' } as unknown as ServerEvent
    expect(apply(initialRoomState, bad).kickVote).toBeNull()
    const neg = { ...VOTE, yes: -1 } as ServerEvent
    expect(apply(initialRoomState, neg).kickVote).toBeNull()
  })

  it('un nouveau vote sur la même cible garde « j’ai voté »', () => {
    const voted = roomReducer(apply(initialRoomState, VOTE), { type: 'voted' })
    expect(apply(voted, { ...VOTE, yes: 2 }).voted).toBe(true)
  })

  it('kick_result : efface le vote et affiche l’issue', () => {
    const s = apply(apply(initialRoomState, VOTE), { type: 'kick_result', target: 2, outcome: 'kicked' })
    expect(s.kickVote).toBeNull()
    expect(s.kickNotice).toContain('exclu')
  })

  it('kick_result sur soi-même : « Vous avez été exclu »', () => {
    const base = { ...initialRoomState, you: 2 }
    expect(apply(base, { type: 'kick_result', target: 2, outcome: 'kicked' }).kickNotice).toContain('Vous avez été exclu')
  })

  it('role : prise de siège met à jour rôle et numéro', () => {
    const s = apply({ ...initialRoomState, role: 'spectator', you: null }, { type: 'role', role: 'B', you: 2 })
    expect(s).toMatchObject({ role: 'B', you: 2 })
  })

  it('error kicked : accès refusé', () => {
    expect(apply(initialRoomState, { type: 'error', code: 'kicked', detail: 'x' }).denied).toBe('kicked')
  })

  it('presence : scores nettoyés (clés numériques, valeurs number|null)', () => {
    const ev = { type: 'presence', present: [1], max_participants: 2, spectators: 0, scores: { '1': 25, x: 3, '2': 'a' } } as unknown as ServerEvent
    expect(apply(initialRoomState, ev).presence?.scores).toEqual({ '1': 25 })
  })
})
