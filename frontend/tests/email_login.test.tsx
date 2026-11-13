import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest'
import { fetchFeatures, requestEmailCode, resetFeaturesCache, verifyEmailCode } from '../src/api/client'
import { AccountMenu } from '../src/components/AccountMenu'
import { EmailLoginForm } from '../src/components/EmailLoginForm'
import { AuthProvider } from '../src/hooks/useAuth'
import { clearSession, getSession } from '../src/lib/session'

vi.mock('../src/components/GoogleSignInButton', () => ({ GoogleSignInButton: () => <div data-testid="google-button" /> }))

const TOKEN = 'T'.repeat(43)
const USER = { id: 'u1', email: 'alice@example.com', created_at: '2026-11-13T00:00:00+00:00' }
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const FEATURES_EMAIL = { voice: false, accounts: true, google_client_id: null, email_login: true }
const FEATURES_BOTH = { ...FEATURES_EMAIL, google_client_id: 'cid.apps.googleusercontent.com' }

let fetchMock: MockInstance<typeof fetch>
beforeEach(() => {
  localStorage.clear()
  clearSession()
  resetFeaturesCache()
  fetchMock = vi.spyOn(globalThis, 'fetch')
})
afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

const callsTo = (path: string) => fetchMock.mock.calls.filter(([u]: [RequestInfo | URL, RequestInit?]) => String(u).endsWith(path))
const bodyOf = (call: unknown[]) => JSON.parse((call[1] as RequestInit).body as string) as Record<string, unknown>

/** Serveur simulé : adresse/code attendus, réponses configurables. */
function server(opts: { features?: object; requestStatus?: number; verifyStatus?: number; detail?: string } = {}) {
  fetchMock.mockImplementation(async (input) => {
    const url = String(input)
    if (url.endsWith('/api/v1/features')) return json(opts.features ?? FEATURES_EMAIL)
    if (url.endsWith('/auth/email/request')) return opts.requestStatus && opts.requestStatus !== 202 ? json({ detail: opts.detail ?? 'Erreur' }, opts.requestStatus) : json({ sent: true }, 202)
    if (url.endsWith('/auth/email/verify')) return opts.verifyStatus && opts.verifyStatus !== 200 ? json({ detail: opts.detail ?? 'Code invalide ou expiré.' }, opts.verifyStatus) : json({ session_token: TOKEN, user: USER })
    return json({}, 404)
  })
}

describe('client : connexion par e-mail', () => {
  it('fetchFeatures : les comptes existent avec le seul e-mail (sans identifiant Google)', async () => {
    server()
    const f = await fetchFeatures()
    expect(f).toMatchObject({ accounts: true, googleClientId: null, emailLogin: true })
  })

  it('fetchFeatures : ni Google ni e-mail = pas de comptes', async () => {
    server({ features: { voice: false, accounts: true, google_client_id: null, email_login: false } })
    expect((await fetchFeatures()).accounts).toBe(false)
  })

  it('requestEmailCode : POST de l’adresse, rien d’autre', async () => {
    server()
    await requestEmailCode('alice@example.com')
    const call = callsTo('/auth/email/request')[0]!
    expect((call[1] as RequestInit).method).toBe('POST')
    expect(bodyOf(call)).toEqual({ email: 'alice@example.com' })
  })

  it('requestEmailCode : remonte le message du serveur', async () => {
    server({ requestStatus: 503, detail: 'L’envoi du code est momentanément indisponible. Réessayez plus tard.' })
    await expect(requestEmailCode('a@example.com')).rejects.toThrow(/momentanément indisponible/)
  })

  it('verifyEmailCode : envoie adresse, code et identité anonyme ; valide la réponse', async () => {
    server()
    const r = await verifyEmailCode('alice@example.com', '123456')
    expect(r).toEqual({ sessionToken: TOKEN, user: USER })
    expect(bodyOf(callsTo('/auth/email/verify')[0]!)).toMatchObject({ email: 'alice@example.com', code: '123456', participant_token: expect.any(String) })
  })

  it('verifyEmailCode : réponse hors contrat rejetée', async () => {
    for (const bad of [{}, { session_token: 'court', user: USER }, { session_token: TOKEN, user: { id: 1 } }]) {
      fetchMock.mockResolvedValueOnce(json(bad))
      await expect(verifyEmailCode('a@example.com', '123456')).rejects.toThrow()
    }
  })

  it('verifyEmailCode : refus = message du serveur', async () => {
    server({ verifyStatus: 401 })
    await expect(verifyEmailCode('a@example.com', '000000')).rejects.toThrow('Code invalide ou expiré.')
  })
})

function renderForm(onDone = vi.fn()) {
  render(
    <AuthProvider>
      <EmailLoginForm onDone={onDone} />
    </AuthProvider>,
  )
  return onDone
}

describe('EmailLoginForm', () => {
  it('adresse invalide : message immédiat, aucune requête d’envoi', async () => {
    server()
    renderForm()
    await userEvent.type(screen.getByLabelText('Votre adresse e-mail'), 'pas-un-mail')
    await userEvent.click(screen.getByRole('button', { name: 'Recevoir un code' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Adresse e-mail invalide.')
    expect(callsTo('/auth/email/request')).toHaveLength(0)
  })

  it('bouton inactif tant que l’adresse est vide', () => {
    server()
    renderForm()
    expect(screen.getByRole('button', { name: 'Recevoir un code' })).toBeDisabled()
  })

  it('parcours complet : adresse → code → session ouverte', async () => {
    server()
    const onDone = renderForm()
    await userEvent.type(screen.getByLabelText('Votre adresse e-mail'), '  Alice@Example.COM ')
    await userEvent.click(screen.getByRole('button', { name: 'Recevoir un code' }))
    expect(await screen.findByText('alice@example.com')).toBeInTheDocument() // adresse normalisée
    expect(bodyOf(callsTo('/auth/email/request')[0]!)).toEqual({ email: 'alice@example.com' })
    const code = screen.getByLabelText(/Code reçu à/)
    expect(code).toHaveAttribute('autocomplete', 'one-time-code')
    expect(screen.getByRole('button', { name: 'Se connecter' })).toBeDisabled()
    await userEvent.type(code, '123456')
    await userEvent.click(screen.getByRole('button', { name: 'Se connecter' }))
    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1))
    expect(getSession()).toBe(TOKEN)
  })

  it('le champ code n’accepte que des chiffres, 6 au plus', async () => {
    server()
    renderForm()
    await userEvent.type(screen.getByLabelText('Votre adresse e-mail'), 'a@example.com')
    await userEvent.click(screen.getByRole('button', { name: 'Recevoir un code' }))
    const code = await screen.findByLabelText(/Code reçu à/)
    await userEvent.type(code, '12a-34 5678')
    expect(code).toHaveValue('123456')
  })

  it('mauvais code : message du serveur, champ vidé, pas de session', async () => {
    server({ verifyStatus: 401 })
    const onDone = renderForm()
    await userEvent.type(screen.getByLabelText('Votre adresse e-mail'), 'a@example.com')
    await userEvent.click(screen.getByRole('button', { name: 'Recevoir un code' }))
    await userEvent.type(await screen.findByLabelText(/Code reçu à/), '000000')
    await userEvent.click(screen.getByRole('button', { name: 'Se connecter' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Code invalide ou expiré.')
    expect(screen.getByLabelText(/Code reçu à/)).toHaveValue('')
    expect(onDone).not.toHaveBeenCalled()
    expect(getSession()).toBeNull()
  })

  it('échec d’envoi : message affiché, on reste sur l’étape adresse', async () => {
    server({ requestStatus: 503, detail: 'Envoi momentanément indisponible.' })
    renderForm()
    await userEvent.type(screen.getByLabelText('Votre adresse e-mail'), 'a@example.com')
    await userEvent.click(screen.getByRole('button', { name: 'Recevoir un code' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Envoi momentanément indisponible.')
    expect(screen.getByLabelText('Votre adresse e-mail')).toBeInTheDocument()
  })

  it('« Changer d’adresse » revient à la saisie', async () => {
    server()
    renderForm()
    await userEvent.type(screen.getByLabelText('Votre adresse e-mail'), 'a@example.com')
    await userEvent.click(screen.getByRole('button', { name: 'Recevoir un code' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Changer d’adresse' }))
    expect(screen.getByLabelText('Votre adresse e-mail')).toBeInTheDocument()
  })

  it('« Renvoyer le code » : inactif pendant 30 s, puis redemande un code', async () => {
    server()
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const user = userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTime(ms) })
    renderForm()
    await user.type(screen.getByLabelText('Votre adresse e-mail'), 'a@example.com')
    await user.click(screen.getByRole('button', { name: 'Recevoir un code' }))
    const resend = await screen.findByRole('button', { name: /Renvoyer le code \(30 s\)/ })
    expect(resend).toBeDisabled()
    for (let i = 0; i < 29; i++) await act(async () => void vi.advanceTimersByTime(1000))
    expect(screen.getByRole('button', { name: /Renvoyer le code \(1 s\)/ })).toBeDisabled()
    await act(async () => void vi.advanceTimersByTime(1000))
    const ready = await screen.findByRole('button', { name: 'Renvoyer le code' })
    expect(ready).toBeEnabled()
    await user.click(ready)
    await waitFor(() => expect(callsTo('/auth/email/request')).toHaveLength(2))
  })

  it('double soumission : une seule demande en vol', async () => {
    let release: (r: Response) => void = () => {}
    fetchMock.mockImplementation((input) => {
      const url = String(input)
      if (url.endsWith('/features')) return Promise.resolve(json(FEATURES_EMAIL))
      return new Promise<Response>((resolve) => (release = resolve))
    })
    renderForm()
    await userEvent.type(screen.getByLabelText('Votre adresse e-mail'), 'a@example.com{Enter}{Enter}')
    expect(callsTo('/auth/email/request')).toHaveLength(1)
    release(json({ sent: true }, 202))
    await screen.findByLabelText(/Code reçu à/)
  })
})

describe('AccountMenu : connexion par e-mail', () => {
  const renderMenu = () =>
    render(
      <AuthProvider>
        <AccountMenu />
      </AuthProvider>,
    )

  it('e-mail seul : bouton « Se connecter par e-mail », pas de bouton Google', async () => {
    server()
    renderMenu()
    expect(await screen.findByRole('button', { name: /Se connecter par e-mail/ })).toBeInTheDocument()
    expect(screen.queryByTestId('google-button')).not.toBeInTheDocument()
  })

  it('Google + e-mail : les deux options', async () => {
    server({ features: FEATURES_BOTH })
    renderMenu()
    expect(await screen.findByTestId('google-button')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Se connecter par e-mail/ })).toBeInTheDocument()
  })

  it('Google seul : pas de bouton e-mail', async () => {
    server({ features: { voice: false, accounts: true, google_client_id: 'cid.apps.googleusercontent.com', email_login: false } })
    renderMenu()
    expect(await screen.findByTestId('google-button')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Se connecter par e-mail/ })).not.toBeInTheDocument()
  })

  it('ouvre le formulaire, Échap le ferme, et la connexion remplace le bouton par le compte', async () => {
    server()
    renderMenu()
    const toggle = await screen.findByRole('button', { name: /Se connecter par e-mail/ })
    await userEvent.click(toggle)
    expect(screen.getByRole('form', { name: 'Connexion par e-mail' })).toBeInTheDocument()
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('form', { name: 'Connexion par e-mail' })).not.toBeInTheDocument()
    await userEvent.click(toggle)
    await userEvent.type(screen.getByLabelText('Votre adresse e-mail'), 'alice@example.com')
    await userEvent.click(screen.getByRole('button', { name: 'Recevoir un code' }))
    await userEvent.type(await screen.findByLabelText(/Code reçu à/), '123456')
    await userEvent.click(screen.getByRole('button', { name: 'Se connecter' }))
    expect(await screen.findByRole('button', { name: 'Mon compte' })).toBeInTheDocument()
    expect(screen.queryByRole('form', { name: 'Connexion par e-mail' })).not.toBeInTheDocument()
  })
})
