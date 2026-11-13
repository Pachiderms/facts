import { render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest'
import { createRoom, deleteRoom, resetFeaturesCache } from '../src/api/client'
import { RoomSocket } from '../src/api/socket'
import { useHistorySync } from '../src/hooks/useHistorySync'
import { loadHistory, mergeHistory, recordVisit, type HistoryEntry } from '../src/lib/history'
import { clearSession, setSession } from '../src/lib/session'

const TOKEN = 'T'.repeat(43)
const e = (id: string, extra: Partial<HistoryEntry> = {}): HistoryEntry => ({
  id, title: `Salon ${id}`, visibility: 'public', owner: false, pinned: false, lastVisit: 1, ...extra,
})
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

describe('mergeHistory', () => {
  it('union : garde tout, la visite la plus récente fait foi, « créateur » l’emporte', () => {
    const local = [e('aaaa2222', { title: 'ancien', lastVisit: 1, owner: true }), e('bbbb2222')]
    const remote = [e('aaaa2222', { title: 'récent', lastVisit: 5, pinned: true }), e('cccc2222')]
    const out = mergeHistory(local, remote, true)
    expect(out.map((x) => x.id).sort()).toEqual(['aaaa2222', 'bbbb2222', 'cccc2222'])
    const a = out.find((x) => x.id === 'aaaa2222')!
    expect(a).toMatchObject({ title: 'récent', pinned: true, owner: true, lastVisit: 5 })
  })

  it('le code d’un salon privé reste celui de l’appareil, même si le serveur fait foi', () => {
    const local = [e('aaaa2222', { visibility: 'private', code: 'k7m2xq' })]
    const remote = [e('aaaa2222', { visibility: 'private', lastVisit: 9 })]
    expect(mergeHistory(local, remote, false)[0]!.code).toBe('k7m2xq')
    expect(mergeHistory(local, remote, true)[0]!.code).toBe('k7m2xq')
  })

  it('hors première synchronisation, le serveur fait foi : une suppression ailleurs ne ressuscite pas', () => {
    expect(mergeHistory([e('aaaa2222'), e('bbbb2222')], [e('bbbb2222')], false).map((x) => x.id)).toEqual(['bbbb2222'])
  })

  it('respecte la limite de 20 entrées', () => {
    const many = Array.from({ length: 30 }, (_, i) => e(`room-${i}`, { lastVisit: i }))
    expect(mergeHistory(many, [], true)).toHaveLength(20)
  })

  it('un code reçu du serveur n’est jamais conservé (le serveur n’en envoie pas)', () => {
    const remote = [e('aaaa2222', { visibility: 'public' })]
    expect(mergeHistory([], remote, false)[0]!.code).toBeUndefined()
  })
})

let fetchMock: MockInstance<typeof fetch>
beforeEach(() => {
  localStorage.clear()
  clearSession()
  resetFeaturesCache()
  fetchMock = vi.spyOn(globalThis, 'fetch')
})
afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
})

function Probe({ userId }: { userId: string | null }) {
  useHistorySync(userId)
  return null
}

const pushes = () => fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === 'POST')

describe('useHistorySync', () => {
  it('ne fait rien sans compte', async () => {
    render(<Probe userId={null} />)
    recordVisit({ id: 'aaaa2222', title: 'Salon', visibility: 'public' })
    await new Promise((r) => setTimeout(r, 1200))
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('première connexion : fusionne le local et le serveur puis renvoie le résultat', async () => {
    setSession(TOKEN)
    recordVisit({ id: 'aaaa2222', title: 'Local', visibility: 'public' }, 1)
    fetchMock.mockImplementation(async (_u, init) =>
      (init as RequestInit | undefined)?.method === 'POST'
        ? json({ entries: [] })
        : json({ entries: [{ ...e('bbbb2222', { lastVisit: 7 }) }] }),
    )
    render(<Probe userId="u1" />)
    await waitFor(() => expect(loadHistory().map((x) => x.id).sort()).toEqual(['aaaa2222', 'bbbb2222']))
    await waitFor(() => expect(pushes()).toHaveLength(1))
    const sent = JSON.parse((pushes()[0]![1] as RequestInit).body as string).entries as { id: string; code?: string }[]
    expect(sent.map((x) => x.id).sort()).toEqual(['aaaa2222', 'bbbb2222'])
    expect((pushes()[0]![1] as RequestInit).headers).toMatchObject({ Authorization: `Bearer ${TOKEN}` })
  })

  it('n’envoie jamais le code d’accès au serveur', async () => {
    setSession(TOKEN)
    recordVisit({ id: 'aaaa2222', title: 'Privé', visibility: 'private', code: 'k7m2xq', owner: true }, 1)
    fetchMock.mockImplementation(async () => json({ entries: [] }))
    render(<Probe userId="u1" />)
    await waitFor(() => expect(pushes()).toHaveLength(1))
    expect((pushes()[0]![1] as RequestInit).body as string).not.toContain('k7m2xq')
    expect(loadHistory()[0]!.code).toBe('k7m2xq')
  })

  it('ensuite, chaque modification locale est envoyée (en différé, une seule fois)', async () => {
    setSession(TOKEN)
    localStorage.setItem('facts.historySyncedFor', 'u1')
    fetchMock.mockImplementation(async () => json({ entries: [] }))
    render(<Probe userId="u1" />)
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1)) // lecture seule : déjà synchronisé
    recordVisit({ id: 'aaaa2222', title: 'A', visibility: 'public' })
    recordVisit({ id: 'bbbb2222', title: 'B', visibility: 'public' })
    await waitFor(() => expect(pushes()).toHaveLength(1), { timeout: 3000 })
  })

  it('une fusion venue du serveur n’est pas renvoyée au serveur (pas d’écho)', async () => {
    setSession(TOKEN)
    localStorage.setItem('facts.historySyncedFor', 'u1')
    fetchMock.mockImplementation(async () => json({ entries: [e('bbbb2222', { lastVisit: 7 })] }))
    render(<Probe userId="u1" />)
    await waitFor(() => expect(loadHistory().map((x) => x.id)).toEqual(['bbbb2222']))
    await new Promise((r) => setTimeout(r, 1400))
    expect(pushes()).toHaveLength(0)
  })

  it('une erreur réseau ne perd rien : l’historique local reste intact', async () => {
    setSession(TOKEN)
    recordVisit({ id: 'aaaa2222', title: 'Local', visibility: 'public' }, 1)
    fetchMock.mockRejectedValue(new TypeError('réseau'))
    render(<Probe userId="u1" />)
    await new Promise((r) => setTimeout(r, 100))
    expect(loadHistory().map((x) => x.id)).toEqual(['aaaa2222'])
  })
})

describe('identité de compte côté client', () => {
  it('création et suppression de salon portent la session quand elle existe, pas sinon', async () => {
    fetchMock.mockImplementation(async () => json({ id: 'room-x', visibility: 'public', access_code: null }))
    const input = { title: 'Un titre de salon assez long', theme_category: 'social', visibility: 'public', max_participants: 2, spectators_allowed: true, kick_threshold: 30 } as never
    await createRoom(input)
    expect((fetchMock.mock.calls[0]![1] as RequestInit).headers).not.toHaveProperty('Authorization')
    setSession(TOKEN)
    await createRoom(input)
    expect((fetchMock.mock.calls[1]![1] as RequestInit).headers).toMatchObject({ Authorization: `Bearer ${TOKEN}` })
    fetchMock.mockImplementation(async () => new Response(null, { status: 204 }))
    await deleteRoom('room-x')
    expect((fetchMock.mock.calls[2]![1] as RequestInit).headers).toMatchObject({ Authorization: `Bearer ${TOKEN}` })
  })

  it('le « hello » WebSocket contient la session seulement si elle existe', () => {
    const sent: string[] = []
    class FakeWS {
      static OPEN = 1
      readyState = 1
      onopen: (() => void) | null = null
      onmessage = null
      onclose = null
      onerror = null
      send = (d: string) => void sent.push(d)
      close() {}
      constructor() {
        queueMicrotask(() => this.onopen?.())
      }
    }
    vi.stubGlobal('WebSocket', FakeWS)
    return (async () => {
      new RoomSocket('room-1', { onEvent: () => undefined, onStatus: () => undefined }, { token: 'abcdefghijklmnopqrstuvwxyz012345' }).connect()
      await Promise.resolve()
      await Promise.resolve()
      expect(JSON.parse(sent[0]!)).not.toHaveProperty('session')
      setSession(TOKEN)
      new RoomSocket('room-1', { onEvent: () => undefined, onStatus: () => undefined }, { token: 'abcdefghijklmnopqrstuvwxyz012345' }).connect()
      await Promise.resolve()
      await Promise.resolve()
      expect(JSON.parse(sent[1]!).session).toBe(TOKEN)
      vi.unstubAllGlobals()
    })()
  })
})
