import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest'
import { fetchBilling, startCheckout } from '../src/api/client'
import { clearSession, setSession } from '../src/lib/session'

const auth = vi.hoisted(() => ({ value: {} as Record<string, unknown> }))
vi.mock('../src/hooks/useAuth', () => ({ useAuth: () => auth.value }))
vi.mock('../src/components/GoogleSignInButton', () => ({ GoogleSignInButton: () => <div data-testid="google-button" /> }))

import { Footer, Header } from '../src/components/Layout'
import { PricingPage } from '../src/pages/PricingPage'

const TOKEN = 'T'.repeat(43)
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const billing = (over = {}) => ({ enabled: true, price_label: '5 € / mois', plan: 'free', status: null, current_period_end: null, portal_url: null, ...over })
const ANON = { enabled: true, googleClientId: 'cid', user: null, signIn: vi.fn() }
const USER = { ...ANON, user: { id: 'u1', email: 'a@example.com', created_at: '2026-01-01' } }

let fetchMock: MockInstance<typeof fetch>
beforeEach(() => {
  localStorage.clear()
  clearSession()
  auth.value = ANON
  fetchMock = vi.spyOn(globalThis, 'fetch')
})
afterEach(() => vi.restoreAllMocks())

describe('fetchBilling', () => {
  it('lit l’état et envoie la session seulement si elle existe', async () => {
    fetchMock.mockImplementation(async () => json(billing({ plan: 'pro', status: 'active', current_period_end: '2026-12-01T00:00:00+00:00' })))
    const b = await fetchBilling()
    expect(b).toMatchObject({ enabled: true, priceLabel: '5 € / mois', plan: 'pro', status: 'active', currentPeriodEnd: '2026-12-01T00:00:00+00:00' })
    expect((fetchMock.mock.calls[0]![1] as RequestInit).headers).not.toHaveProperty('Authorization')
    setSession(TOKEN)
    await fetchBilling()
    expect((fetchMock.mock.calls[1]![1] as RequestInit).headers).toMatchObject({ Authorization: `Bearer ${TOKEN}` })
  })

  it('ne retient un lien de gestion que s’il est en https, et borne le libellé du prix', async () => {
    for (const bad of ['http://x.example/p', 'javascript:alert(1)', '//x.example', 42, null]) {
      fetchMock.mockResolvedValueOnce(json(billing({ portal_url: bad })))
      expect((await fetchBilling()).portalUrl).toBeNull()
    }
    fetchMock.mockResolvedValueOnce(json(billing({ portal_url: 'https://pay.example/portal', price_label: 'x'.repeat(200) })))
    const b = await fetchBilling()
    expect(b.portalUrl).toBe('https://pay.example/portal')
    expect(b.priceLabel).toHaveLength(60)
  })

  it('rejette une réponse hors contrat', async () => {
    for (const bad of [{}, billing({ enabled: 'oui' }), billing({ plan: 'vip' }), billing({ plan: undefined }), null]) {
      fetchMock.mockResolvedValueOnce(json(bad))
      await expect(fetchBilling()).rejects.toThrow()
    }
  })
})

describe('startCheckout', () => {
  it('POST avec la session et renvoie l’adresse https', async () => {
    setSession(TOKEN)
    fetchMock.mockResolvedValueOnce(json({ url: 'https://shop.example/checkout/abc?x=1' }))
    expect(await startCheckout()).toBe('https://shop.example/checkout/abc?x=1')
    const init = fetchMock.mock.calls[0]![1] as RequestInit
    expect(init.method).toBe('POST')
    expect(init.headers).toMatchObject({ Authorization: `Bearer ${TOKEN}` })
  })

  it.each(['http://shop.example/c', 'javascript:alert(1)', 'data:text/html,x', '//shop.example', '', 5, null])('refuse l’adresse %j (jamais de redirection non https)', async (url) => {
    fetchMock.mockResolvedValueOnce(json({ url }))
    await expect(startCheckout()).rejects.toThrow()
  })

  it('remonte le message du serveur', async () => {
    fetchMock.mockResolvedValueOnce(json({ detail: 'Le paiement n’est pas encore disponible.' }, 503))
    await expect(startCheckout()).rejects.toThrow(/pas encore disponible/)
  })
})

describe('PricingPage', () => {
  const show = async (b = billing()) => {
    fetchMock.mockImplementation(async () => json(b))
    render(<PricingPage />)
  }

  it('paiement fermé : « Bientôt disponible », bouton inactif, aucun prix affiché', async () => {
    await show(billing({ enabled: false, price_label: '' }))
    const btn = await screen.findByRole('button', { name: 'Bientôt disponible' })
    expect(btn).toBeDisabled()
    expect(screen.queryByText('5 € / mois')).not.toBeInTheDocument()
    expect(screen.getByText('Bientôt')).toBeInTheDocument()
  })

  it('offre gratuite toujours présentée', async () => {
    await show(billing({ enabled: false }))
    expect(screen.getByRole('region', { name: 'Offre gratuite' })).toHaveTextContent('0 €')
  })

  it('serveur injoignable : message, pas de bouton d’achat', async () => {
    fetchMock.mockRejectedValue(new Error('réseau'))
    render(<PricingPage />)
    expect(await screen.findByText('Offre momentanément indisponible.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Passer à Pro' })).not.toBeInTheDocument()
  })

  it('ouvert + non connecté : invite à se connecter (pas de paiement sans compte)', async () => {
    await show()
    expect(await screen.findByText(/Connectez-vous pour vous abonner/)).toBeInTheDocument()
    expect(screen.getByTestId('google-button')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Passer à Pro' })).not.toBeInTheDocument()
    expect(screen.getByText('5 € / mois')).toBeInTheDocument()
  })

  it('ouvert + connexion indisponible : le dit', async () => {
    auth.value = { ...ANON, enabled: false, googleClientId: null }
    await show()
    expect(await screen.findByText(/connexion est momentanément indisponible/)).toBeInTheDocument()
  })

  it('connecté : « Passer à Pro » demande le lien puis redirige vers lui', async () => {
    auth.value = USER
    const assign = vi.fn()
    vi.stubGlobal('location', { ...window.location, assign })
    try {
      fetchMock.mockImplementation(async (input) => (String(input).includes('/checkout') ? json({ url: 'https://shop.example/pay' }) : json(billing())))
      render(<PricingPage />)
      await userEvent.click(await screen.findByRole('button', { name: 'Passer à Pro' }))
      await waitFor(() => expect(assign).toHaveBeenCalledWith('https://shop.example/pay'))
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('double clic : une seule demande de paiement à la fois', async () => {
    auth.value = USER
    const assign = vi.fn()
    vi.stubGlobal('location', { ...window.location, assign })
    let release: (r: Response) => void = () => {}
    let checkoutCalls = 0
    try {
      fetchMock.mockImplementation((input) => {
        if (!String(input).includes('/checkout')) return Promise.resolve(json(billing()))
        checkoutCalls += 1
        return new Promise<Response>((resolve) => (release = resolve))
      })
      render(<PricingPage />)
      const btn = await screen.findByRole('button', { name: 'Passer à Pro' })
      await userEvent.dblClick(btn)
      expect(checkoutCalls).toBe(1)
      release(json({ url: 'https://shop.example/pay' }))
      await waitFor(() => expect(assign).toHaveBeenCalledTimes(1))
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('connecté : erreur de paiement affichée, bouton réutilisable, aucune redirection', async () => {
    auth.value = USER
    const assign = vi.fn()
    vi.stubGlobal('location', { ...window.location, assign })
    try {
      fetchMock.mockImplementation(async (input) =>
        String(input).includes('/checkout') ? json({ detail: 'Paiement indisponible.' }, 503) : json(billing()),
      )
      render(<PricingPage />)
      await userEvent.click(await screen.findByRole('button', { name: 'Passer à Pro' }))
      expect(await screen.findByRole('alert')).toHaveTextContent('Paiement indisponible.')
      expect(assign).not.toHaveBeenCalled()
      expect(screen.getByRole('button', { name: 'Passer à Pro' })).toBeEnabled()
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('un lien de paiement non https renvoyé par le serveur n’ouvre rien', async () => {
    auth.value = USER
    const assign = vi.fn()
    vi.stubGlobal('location', { ...window.location, assign })
    try {
      fetchMock.mockImplementation(async (input) => (String(input).includes('/checkout') ? json({ url: 'javascript:alert(1)' }) : json(billing())))
      render(<PricingPage />)
      await userEvent.click(await screen.findByRole('button', { name: 'Passer à Pro' }))
      expect(await screen.findByRole('alert')).toBeInTheDocument()
      expect(assign).not.toHaveBeenCalled()
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('abonné : statut, fin de période et lien de gestion sûr', async () => {
    auth.value = USER
    await show(billing({ plan: 'pro', status: 'active', current_period_end: '2026-12-15T10:00:00+00:00', portal_url: 'https://pay.example/portal' }))
    expect(await screen.findByText('Vous êtes abonné Pro.')).toBeInTheDocument()
    expect(screen.getByText(/Période en cours jusqu’au 15 décembre 2026/)).toBeInTheDocument()
    const link = screen.getByRole('link', { name: 'Gérer mon abonnement' })
    expect(link).toHaveAttribute('href', 'https://pay.example/portal')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    expect(link).toHaveAttribute('target', '_blank')
    expect(screen.queryByRole('button', { name: 'Passer à Pro' })).not.toBeInTheDocument()
  })

  it('abonnement résilié : « Accès jusqu’au »', async () => {
    auth.value = USER
    await show(billing({ plan: 'pro', status: 'cancelled', current_period_end: '2026-12-15T10:00:00+00:00' }))
    expect(await screen.findByText(/Accès jusqu’au 15 décembre 2026/)).toBeInTheDocument()
  })

  it('renvoie vers les CGU et la confidentialité', async () => {
    await show(billing({ enabled: false }))
    expect(screen.getByRole('link', { name: 'conditions générales' })).toHaveAttribute('href', '#/cgu')
    expect(screen.getByRole('link', { name: 'politique de confidentialité' })).toHaveAttribute('href', '#/confidentialite')
  })
})

describe('navigation', () => {
  it('le pied de page donne accès aux tarifs et aux documents légaux', () => {
    render(<Footer />)
    const links = Object.fromEntries(screen.getAllByRole('link').map((a) => [a.textContent, a.getAttribute('href')]))
    expect(links).toEqual({ Tarifs: '#/tarifs', 'Mentions légales': '#/mentions-legales', Confidentialité: '#/confidentialite', CGU: '#/cgu' })
  })

  it('sur Tarifs ou une page légale, aucun onglet n’est marqué actif', () => {
    render(<Header page={null} onNavigate={() => {}} />)
    expect(document.querySelector('[aria-current="page"]')).toBeNull()
  })
})
