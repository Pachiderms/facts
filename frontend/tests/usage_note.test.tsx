import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest'
import { checkAssertion, fetchUsage } from '../src/api/client'
import { UsageNote } from '../src/components/check/UsageNote'
import { getParticipantToken } from '../src/lib/identity'
import { clearSession, setSession } from '../src/lib/session'

const TOKEN = 'T'.repeat(43)
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const usage = (over = {}) => ({
  plan: 'anonymous',
  checks: { used: 5, limit: 30, remaining: 25 },
  debate: { used: 10, limit: 40, remaining: 30 },
  degraded: false,
  ...over,
})

let fetchMock: MockInstance<typeof fetch>
beforeEach(() => {
  localStorage.clear()
  clearSession()
  fetchMock = vi.spyOn(globalThis, 'fetch')
})
afterEach(() => vi.restoreAllMocks())

describe('fetchUsage', () => {
  it('lit le quota et envoie la session seulement si elle existe', async () => {
    fetchMock.mockImplementation(async () => json(usage()))
    expect((await fetchUsage()).checks.remaining).toBe(25)
    expect((fetchMock.mock.calls[0]![1] as RequestInit).headers).not.toHaveProperty('Authorization')
    setSession(TOKEN)
    await fetchUsage()
    expect((fetchMock.mock.calls[1]![1] as RequestInit).headers).toMatchObject({ Authorization: `Bearer ${TOKEN}` })
  })

  it('envoie le jeton du navigateur, connecté ou non : le quota suit la personne', async () => {
    fetchMock.mockImplementation(async (input) => (String(input).endsWith('/usage') ? json(usage()) : json({})))
    const token = getParticipantToken()
    expect(token).toMatch(/^[A-Za-z0-9_-]{22,64}$/)
    await fetchUsage()
    setSession(TOKEN)
    await fetchUsage()
    for (const call of fetchMock.mock.calls) expect((call[1] as RequestInit).headers).toMatchObject({ 'X-Participant-Token': token })
  })

  it('accepte le plan Pro', async () => {
    fetchMock.mockResolvedValueOnce(json(usage({ plan: 'pro' })))
    expect((await fetchUsage()).plan).toBe('pro')
  })

  it('rejette une réponse hors contrat', async () => {
    for (const bad of [{}, usage({ plan: 'vip' }), usage({ degraded: 'non' }), usage({ checks: { used: 'x', limit: 1, remaining: 1 } }), usage({ debate: undefined }), usage({ debate: { used: 1 } })]) {
      fetchMock.mockResolvedValueOnce(json(bad))
      await expect(fetchUsage()).rejects.toThrow()
    }
  })

  it('la vérification d’une affirmation porte la session (quota du compte)', async () => {
    setSession(TOKEN)
    fetchMock.mockResolvedValue(json({}, 500))
    await checkAssertion('x'.repeat(30), true).catch(() => undefined)
    expect((fetchMock.mock.calls[0]![1] as RequestInit).headers).toMatchObject({ Authorization: `Bearer ${TOKEN}` })
  })
})

describe('UsageNote', () => {
  it('affiche le quota restant, au pluriel correct', async () => {
    fetchMock.mockResolvedValue(json(usage()))
    render(<UsageNote refreshKey={0} />)
    expect(await screen.findByText(/25 vérifications restantes aujourd’hui sur 30/)).toBeTruthy()
    fetchMock.mockResolvedValue(json(usage({ checks: { used: 29, limit: 30, remaining: 1 } })))
    render(<UsageNote refreshKey={1} />)
    expect(await screen.findByText(/1 vérification restante aujourd’hui/)).toBeTruthy()
  })

  it('budget du débat : texte dédié, messages toujours publiés au-delà', async () => {
    fetchMock.mockImplementation(async () => json(usage()))
    render(<UsageNote kind="debate" refreshKey={0} />)
    expect(await screen.findByText(/30 messages vérifiés possibles aujourd’hui sur 40/)).toBeTruthy()
    expect(screen.getByText(/restent publiés sans vérification/)).toBeTruthy()
  })

  it('limite atteinte et service dégradé', async () => {
    fetchMock.mockResolvedValue(json(usage({ checks: { used: 30, limit: 30, remaining: 0 }, degraded: true })))
    render(<UsageNote refreshKey={0} />)
    expect(await screen.findByText(/Limite du jour atteinte/)).toBeTruthy()
    expect(screen.getByText(/très sollicité/)).toBeTruthy()
  })

  it('n’affiche rien si le serveur ne répond pas (pas de faux chiffre)', async () => {
    fetchMock.mockRejectedValue(new TypeError('réseau'))
    const { container } = render(<UsageNote refreshKey={0} />)
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    expect(container.textContent).toBe('')
  })
})

describe('checkAssertion : suivi du quota par navigateur', () => {
  it('envoie le jeton du navigateur avec la session, et garde le même d’un appel à l’autre', async () => {
    fetchMock.mockImplementation(async () => json({}, 500))
    await checkAssertion('Le SMIC a augmenté.', true).catch(() => undefined)
    setSession(TOKEN)
    await checkAssertion('Le SMIC a augmenté.', true).catch(() => undefined)
    const [first, second] = fetchMock.mock.calls.map((c) => (c[1] as RequestInit).headers as Record<string, string>)
    expect(first).not.toHaveProperty('Authorization')
    expect(second).toMatchObject({ Authorization: `Bearer ${TOKEN}` })
    expect(first!['X-Participant-Token']).toBe(second!['X-Participant-Token'])
    expect(first!['X-Participant-Token']).toBe(getParticipantToken())
  })
})
