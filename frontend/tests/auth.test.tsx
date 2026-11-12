import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest'
import { deleteAccount, exportAccount, fetchFeatures, fetchMe, loginWithGoogle, logoutEverywhere, logoutSession, resetFeaturesCache } from '../src/api/client'
import { AccountMenu } from '../src/components/AccountMenu'
import { AuthProvider } from '../src/hooks/useAuth'
import { clearSession, getSession, setSession } from '../src/lib/session'

const TOKEN = 'T'.repeat(43)
const USER = { id: 'u1', email: 'alice@example.com', created_at: '2026-11-13T00:00:00+00:00' }

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const FEATURES_ON = { voice: false, accounts: true, google_client_id: 'cid.apps.googleusercontent.com' }

let fetchMock: MockInstance<typeof fetch>

beforeEach(() => {
  localStorage.clear()
  clearSession()
  resetFeaturesCache()
  fetchMock = vi.spyOn(globalThis, 'fetch')
})
afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

const callsTo = (path: string) => fetchMock.mock.calls.filter(([u]: [RequestInfo | URL, RequestInit?]) => String(u).endsWith(path))
const headersOf = (call: unknown[]) => (call[1] as RequestInit).headers as Record<string, string>

describe('session locale', () => {
  it('garde un jeton valide et refuse tout le reste', () => {
    setSession(TOKEN)
    expect(getSession()).toBe(TOKEN)
    setSession('court')
    expect(getSession()).toBe(TOKEN) // une valeur invalide n'écrase rien
    clearSession()
    expect(getSession()).toBeNull()
  })

  it('ignore et supprime une valeur corrompue dans le stockage', () => {
    localStorage.setItem('facts.session', '<script>alert(1)</script>')
    expect(getSession()).toBeNull()
    expect(localStorage.getItem('facts.session')).toBeNull()
  })

  it('retombe sur la mémoire si le stockage est indisponible', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('bloqué')
    })
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('bloqué')
    })
    setSession(TOKEN)
    expect(getSession()).toBe(TOKEN)
  })
})

describe('client des comptes', () => {
  it('envoie le jeton Google et l’identité anonyme, renvoie la session', async () => {
    fetchMock.mockResolvedValue(json({ session_token: TOKEN, user: USER }))
    const out = await loginWithGoogle('g'.repeat(30))
    expect(out).toEqual({ sessionToken: TOKEN, user: USER })
    const body = JSON.parse((fetchMock.mock.calls[0]![1] as RequestInit).body as string)
    expect(body.credential).toBe('g'.repeat(30))
    expect(body.participant_token).toMatch(/^[A-Za-z0-9_-]{22,64}$/)
  })

  it('rejette une réponse hors contrat (jeton de session mal formé)', async () => {
    fetchMock.mockResolvedValue(json({ session_token: 'x', user: USER }))
    await expect(loginWithGoogle('g'.repeat(30))).rejects.toThrow()
  })

  it('transmet le jeton en en-tête Authorization, jamais dans l’URL', async () => {
    fetchMock.mockResolvedValue(json({ user: USER }))
    await fetchMe(TOKEN)
    const [url, init] = fetchMock.mock.calls[0]!
    expect(String(url)).not.toContain(TOKEN)
    expect(((init as RequestInit).headers as Record<string, string>).Authorization).toBe(`Bearer ${TOKEN}`)
  })

  it('suppression : confirmation explicite dans le corps', async () => {
    fetchMock.mockResolvedValue(json({ deleted: true }))
    await deleteAccount(TOKEN)
    expect(JSON.parse((fetchMock.mock.calls[0]![1] as RequestInit).body as string)).toEqual({ confirm: true })
  })

  it('déconnexion et déconnexion partout appellent les bonnes routes', async () => {
    fetchMock.mockResolvedValue(json({ ok: true }))
    await logoutSession(TOKEN)
    await logoutEverywhere(TOKEN)
    expect(callsTo('/api/v1/auth/logout')).toHaveLength(1)
    expect(callsTo('/api/v1/auth/logout-all')).toHaveLength(1)
  })

  it('export : renvoie un fichier JSON', async () => {
    fetchMock.mockResolvedValue(new Response('{"account":{}}', { status: 200 }))
    const blob = await exportAccount(TOKEN)
    expect(blob.type).toBe('application/json')
  })

  it('fetchFeatures n’active les comptes que si l’identifiant client est fourni', async () => {
    fetchMock.mockResolvedValueOnce(json({ voice: false, accounts: true, google_client_id: null }))
    expect((await fetchFeatures()).accounts).toBe(false)
    fetchMock.mockResolvedValueOnce(json(FEATURES_ON))
    expect(await fetchFeatures()).toMatchObject({ accounts: true, googleClientId: 'cid.apps.googleusercontent.com' })
  })
})

const mount = () =>
  render(
    <AuthProvider>
      <AccountMenu />
    </AuthProvider>,
  )

describe('menu de compte', () => {
  it('n’affiche rien (et ne touche à aucun compte) quand le serveur ne propose pas de comptes', async () => {
    fetchMock.mockResolvedValue(json({ voice: false, accounts: false, google_client_id: null }))
    const { container } = mount()
    await waitFor(() => expect(callsTo('/api/v1/features')).toHaveLength(1))
    expect(container).toBeEmptyDOMElement()
    expect(callsTo('/api/v1/auth/me')).toHaveLength(0)
  })

  it('ne contacte pas /me avec une ancienne session quand les comptes sont désactivés', async () => {
    setSession(TOKEN)
    fetchMock.mockResolvedValue(json({ voice: false, accounts: false, google_client_id: null }))
    mount()
    await waitFor(() => expect(callsTo('/api/v1/features')).toHaveLength(1))
    await act(async () => {})
    expect(callsTo('/api/v1/auth/me')).toHaveLength(0)
  })

  it('n’affiche rien si l’API est injoignable', async () => {
    fetchMock.mockRejectedValue(new Error('réseau'))
    const { container } = mount()
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })

  it('reconnaît une session existante et affiche l’adresse e-mail', async () => {
    setSession(TOKEN)
    fetchMock.mockImplementation(async (u: RequestInfo | URL) => (String(u).endsWith('/features') ? json(FEATURES_ON) : json({ user: USER })))
    mount()
    expect(await screen.findByRole('button', { name: /mon compte/i })).toHaveTextContent('alice@example.com')
    expect(headersOf(callsTo('/api/v1/auth/me')[0]!).Authorization).toBe(`Bearer ${TOKEN}`)
  })

  it('une session expirée (401) est effacée et la connexion est reproposée', async () => {
    setSession(TOKEN)
    vi.stubGlobal('google', undefined)
    fetchMock.mockImplementation(async (u: RequestInfo | URL) => (String(u).endsWith('/features') ? json(FEATURES_ON) : json({ detail: 'Session expirée ou invalide.' }, 401)))
    mount()
    await waitFor(() => expect(getSession()).toBeNull())
    expect(screen.queryByRole('button', { name: /mon compte/i })).toBeNull()
  })

  it('une panne réseau sur /me garde la session (pas de déconnexion injustifiée)', async () => {
    setSession(TOKEN)
    fetchMock.mockImplementation(async (u: RequestInfo | URL) => {
      if (String(u).endsWith('/features')) return json(FEATURES_ON)
      throw new Error('réseau')
    })
    mount()
    await waitFor(() => expect(callsTo('/api/v1/auth/me').length).toBeGreaterThan(0))
    await act(async () => {})
    expect(getSession()).toBe(TOKEN)
  })

  async function signedIn() {
    setSession(TOKEN)
    fetchMock.mockImplementation(async (u: RequestInfo | URL) => {
      const url = String(u)
      if (url.endsWith('/features')) return json(FEATURES_ON)
      if (url.endsWith('/auth/me')) return json({ user: USER })
      if (url.endsWith('/auth/export')) return new Response('{"account":{}}', { status: 200 })
      return json({ ok: true, deleted: true, revoked: 1 })
    })
    const user = userEvent.setup()
    mount()
    await user.click(await screen.findByRole('button', { name: /mon compte/i }))
    return user
  }

  it('se déconnecter efface la session locale et prévient le serveur', async () => {
    const user = await signedIn()
    await user.click(screen.getByRole('menuitem', { name: /^se déconnecter$/i }))
    await waitFor(() => expect(getSession()).toBeNull())
    expect(callsTo('/api/v1/auth/logout')).toHaveLength(1)
    expect(screen.queryByRole('button', { name: /mon compte/i })).toBeNull()
  })

  it('se déconnecter même si le serveur est injoignable', async () => {
    const user = await signedIn()
    fetchMock.mockRejectedValue(new Error('réseau'))
    await user.click(screen.getByRole('menuitem', { name: /^se déconnecter$/i }))
    await waitFor(() => expect(getSession()).toBeNull())
  })

  it('la suppression demande une confirmation avant d’appeler le serveur', async () => {
    const user = await signedIn()
    await user.click(screen.getByRole('menuitem', { name: /supprimer mon compte/i }))
    expect(callsTo('/api/v1/auth/delete')).toHaveLength(0)
    expect(screen.getByText(/irréversible/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /annuler/i }))
    expect(callsTo('/api/v1/auth/delete')).toHaveLength(0)
    await user.click(screen.getByRole('menuitem', { name: /supprimer mon compte/i }))
    await user.click(screen.getByRole('button', { name: /supprimer définitivement/i }))
    await waitFor(() => expect(callsTo('/api/v1/auth/delete')).toHaveLength(1))
    await waitFor(() => expect(getSession()).toBeNull())
  })

  it('télécharger mes données déclenche un téléchargement JSON', async () => {
    const user = await signedIn()
    const create = vi.fn(() => 'blob:x')
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: create, revokeObjectURL: vi.fn() }))
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    await user.click(screen.getByRole('menuitem', { name: /télécharger mes données/i }))
    await waitFor(() => expect(click).toHaveBeenCalled())
    expect(create).toHaveBeenCalled()
  })

  it('Échap referme le menu', async () => {
    const user = await signedIn()
    expect(screen.getByRole('menu')).toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('le menu n’affiche jamais le jeton de session', async () => {
    await signedIn()
    expect(document.body.innerHTML).not.toContain(TOKEN)
  })
})
