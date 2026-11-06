import { act, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CheckResponse, RoomSummary } from '../src/api/types'
import { CheckPage } from '../src/pages/CheckPage'

const hooks = vi.hoisted(() => ({ useRooms: vi.fn(), useRoom: vi.fn() }))
vi.mock('../src/hooks/useRooms', () => ({ useRooms: hooks.useRooms }))
vi.mock('../src/hooks/useRoom', () => ({ useRoom: hooks.useRoom }))

// Importés APRÈS vi.mock (hissé) : ces pages utilisent les hooks simulés.
import { ArenaPage } from '../src/pages/ArenaPage'

const RESULT: CheckResponse = {
  verdict: 'FAUX',
  confidence_score: 92,
  summary: 'Selon l’INSEE, 4,9 %.',
  liberal_institutional_view: { title: 'Vue A', points: ['p1'] },
  heterodox_social_view: { title: 'Vue B', points: ['p2'] },
  verified_sources: [{ title: 'INSEE', url: 'https://insee.fr/x', domain: 'insee.fr', trust_score: 95 }],
  cached: false,
}
const json = (body: unknown, init: ResponseInit = {}) =>
  new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' }, ...init })

describe('CheckPage', () => {
  const fetchMock = vi.fn()
  beforeEach(() => {
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  const field = () => screen.getByRole('textbox', { name: /Affirmation/ })
  const submitBtn = () => screen.getByRole('button', { name: /Vérifier/ })
  const LONG = 'Une affirmation suffisamment longue.'

  it('le bouton reste désactivé sous 10 caractères et le dit', async () => {
    render(<CheckPage />)
    expect(submitBtn()).toBeDisabled()
    await userEvent.type(field(), 'court')
    expect(submitBtn()).toBeDisabled()
    expect(screen.getByText(/10 caractères minimum/)).toBeInTheDocument()
    await userEvent.type(field(), ' mais maintenant assez long')
    expect(submitBtn()).toBeEnabled()
  })

  it('un exemple pré-remplit le champ', async () => {
    render(<CheckPage />)
    await userEvent.click(screen.getByRole('button', { name: 'Retraite à 60 ans' }))
    expect((field() as HTMLTextAreaElement).value).toContain('retraite à 60 ans')
  })

  it('envoie l’affirmation (espaces retirés) avec le filtre actif, puis affiche le verdict', async () => {
    fetchMock.mockResolvedValue(json(RESULT))
    render(<CheckPage />)
    await userEvent.type(field(), `   ${LONG}   `)
    await userEvent.click(submitBtn())
    expect(await screen.findByText(/Verdict : FAUX/)).toBeInTheDocument()
    expect(JSON.parse(fetchMock.mock.calls[0]![1].body)).toEqual({ assertion: LONG, institutional_filter: true })
    expect(screen.getByRole('heading', { level: 2, name: new RegExp(LONG) })).toBeInTheDocument()
  })

  it('le filtre désactivé est transmis au serveur', async () => {
    fetchMock.mockResolvedValue(json(RESULT))
    render(<CheckPage />)
    const toggle = screen.getByRole('button', { name: 'Activé' })
    expect(toggle).toHaveAttribute('aria-pressed', 'true')
    await userEvent.click(toggle)
    expect(screen.getByRole('button', { name: 'Désactivé' })).toHaveAttribute('aria-pressed', 'false')
    await userEvent.type(field(), LONG)
    await userEvent.click(submitBtn())
    await screen.findByText(/Verdict/)
    expect(JSON.parse(fetchMock.mock.calls[0]![1].body).institutional_filter).toBe(false)
  })

  it('Ctrl+Entrée lance la vérification', async () => {
    fetchMock.mockResolvedValue(json(RESULT))
    render(<CheckPage />)
    await userEvent.type(field(), `${LONG}{Control>}{Enter}{/Control}`)
    expect(await screen.findByText(/Verdict : FAUX/)).toBeInTheDocument()
  })

  it('affiche l’erreur du serveur (limite quotidienne) dans une alerte et ne montre pas d’ancien résultat', async () => {
    fetchMock.mockResolvedValue(json({ detail: 'Limite quotidienne de vérifications atteinte. Revenez demain.' }, { status: 429 }))
    render(<CheckPage />)
    await userEvent.type(field(), LONG)
    await userEvent.click(submitBtn())
    expect(await screen.findByRole('alert')).toHaveTextContent('Limite quotidienne')
    expect(screen.queryByText(/Verdict/)).not.toBeInTheDocument()
  })

  it('une erreur après un succès garde le dernier résultat lisible et signale l’erreur', async () => {
    fetchMock.mockResolvedValueOnce(json(RESULT)).mockResolvedValueOnce(json({ detail: 'Service momentanément saturé.' }, { status: 503 }))
    render(<CheckPage />)
    await userEvent.type(field(), LONG)
    await userEvent.click(submitBtn())
    await screen.findByText(/Verdict : FAUX/)
    await userEvent.click(submitBtn())
    expect(await screen.findByRole('alert')).toHaveTextContent('saturé')
  })

  it('pendant la recherche : bouton bloqué, message de chargement, puis message de réveil du serveur', async () => {
    vi.useFakeTimers()
    fetchMock.mockReturnValue(new Promise(() => undefined)) // ne répond jamais
    render(<CheckPage />)
    fireEvent.change(field(), { target: { value: LONG } })
    fireEvent.click(submitBtn())
    expect(screen.getByRole('button', { name: /Recherche en cours/ })).toBeDisabled()
    expect(screen.getByText(/L’agent recherche et analyse/)).toBeInTheDocument()
    expect(screen.queryByText(/Le serveur se réveille/)).not.toBeInTheDocument()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(8_000)
    })
    expect(screen.getByText(/Le serveur se réveille/)).toBeInTheDocument()
  })

  it('une seule requête malgré des clics répétés', async () => {
    fetchMock.mockReturnValue(new Promise(() => undefined))
    render(<CheckPage />)
    await userEvent.type(field(), LONG)
    await userEvent.click(submitBtn())
    await userEvent.click(screen.getByRole('button', { name: /Recherche en cours/ }), { pointerEventsCheck: 0 })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('limite la saisie à 500 caractères', () => {
    render(<CheckPage />)
    expect(field()).toHaveAttribute('maxlength', '500')
  })
})

const room = (over: Partial<RoomSummary> = {}): RoomSummary => ({
  id: 'room-1',
  title: 'SMIC à 1 700 €',
  category: 'Économie & emploi',
  theme_category: 'social',
  trust_score: null,
  message_count: 0,
  participants: 1,
  spectators: 0,
  ...over,
})

const roomState = (over: Record<string, unknown> = {}) => ({
  status: 'open',
  role: 'A',
  room: null,
  messages: [],
  presence: null,
  trustScore: null,
  deltas: {},
  notice: null,
  send: vi.fn().mockReturnValue(true),
  dismissNotice: vi.fn(),
  ...over,
})

describe('ArenaPage', () => {
  beforeEach(() => {
    hooks.useRooms.mockReset()
    hooks.useRoom.mockReset()
    hooks.useRoom.mockReturnValue(roomState())
  })

  it('chargement : message d’attente', () => {
    hooks.useRooms.mockReturnValue({ rooms: null, error: null })
    render(<ArenaPage />)
    expect(screen.getByText(/Chargement des salons/)).toBeInTheDocument()
    expect(screen.getByText(/Connexion au serveur/)).toBeInTheDocument()
    expect(hooks.useRoom).not.toHaveBeenCalled() // aucune connexion WebSocket sans salon
  })

  it('erreur de chargement : alerte avec nouvelle tentative automatique', () => {
    hooks.useRooms.mockReturnValue({ rooms: null, error: 'Serveur injoignable.' })
    render(<ArenaPage />)
    expect(screen.getByRole('alert')).toHaveTextContent(/Serveur injoignable.*Nouvelle tentative/)
  })

  it('aucun salon : le dit', () => {
    hooks.useRooms.mockReturnValue({ rooms: [], error: null })
    render(<ArenaPage />)
    expect(screen.getByText(/Aucun salon ouvert/)).toBeInTheDocument()
  })

  it('ouvre le premier salon par défaut ; score absent affiché « — », présent affiché tel quel', () => {
    hooks.useRooms.mockReturnValue({ rooms: [room(), room({ id: 'room-2', title: 'Électricité', trust_score: 84 })], error: null })
    render(<ArenaPage />)
    expect(hooks.useRoom).toHaveBeenLastCalledWith('room-1')
    expect(screen.getByText('Score : —')).toBeInTheDocument()
    expect(screen.getByText('Score : 84')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /SMIC/ })).toHaveAttribute('aria-pressed', 'true')
  })

  it('changer de salon ouvre une nouvelle connexion pour le salon choisi', async () => {
    hooks.useRooms.mockReturnValue({ rooms: [room(), room({ id: 'room-2', title: 'Électricité' })], error: null })
    render(<ArenaPage />)
    await userEvent.click(screen.getByRole('button', { name: /Électricité/ }))
    expect(hooks.useRoom).toHaveBeenLastCalledWith('room-2')
    expect(screen.getByRole('button', { name: /Électricité/ })).toHaveAttribute('aria-pressed', 'true')
  })

  it('un salon qui disparaît de la liste ramène sur le premier', async () => {
    const both = [room(), room({ id: 'room-2', title: 'Électricité' })]
    hooks.useRooms.mockReturnValue({ rooms: both, error: null })
    const { rerender } = render(<ArenaPage />)
    await userEvent.click(screen.getByRole('button', { name: /Électricité/ }))
    hooks.useRooms.mockReturnValue({ rooms: [both[0]], error: null })
    rerender(<ArenaPage />)
    expect(hooks.useRoom).toHaveBeenLastCalledWith('room-1')
  })

  it('affiche le rôle attribué par le serveur, le statut et la présence', () => {
    hooks.useRooms.mockReturnValue({ rooms: [room()], error: null })
    hooks.useRoom.mockReturnValue(roomState({ role: 'B', presence: { A: true, B: true, spectators: 2 } }))
    render(<ArenaPage />)
    expect(screen.getByText('Vous êtes Participant B')).toBeInTheDocument()
    expect(screen.getByText('En direct')).toBeInTheDocument()
    expect(screen.getByText(/A présent · B présent · 2 spectateurs/)).toBeInTheDocument()
  })

  it('spectateur : pas de zone de saisie', () => {
    hooks.useRooms.mockReturnValue({ rooms: [room()], error: null })
    hooks.useRoom.mockReturnValue(roomState({ role: 'spectator' }))
    render(<ArenaPage />)
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('envoie le message saisi via le hook du salon', async () => {
    const send = vi.fn().mockReturnValue(true)
    hooks.useRooms.mockReturnValue({ rooms: [room()], error: null })
    hooks.useRoom.mockReturnValue(roomState({ send }))
    render(<ArenaPage />)
    await userEvent.type(screen.getByRole('textbox', { name: 'Votre argument' }), 'Selon l’INSEE, 5 %{Enter}')
    expect(send).toHaveBeenCalledWith('Selon l’INSEE, 5 %')
  })

  it('état « reconnexion » visible ; envoi bloqué', async () => {
    hooks.useRooms.mockReturnValue({ rooms: [room()], error: null })
    hooks.useRoom.mockReturnValue(roomState({ status: 'reconnecting' }))
    render(<ArenaPage />)
    expect(screen.getByText('Reconnexion…')).toBeInTheDocument()
    await userEvent.type(screen.getByRole('textbox', { name: 'Votre argument' }), 'Texte')
    expect(screen.getByRole('button', { name: /Envoyer/ })).toBeDisabled()
  })

  it('connexion fermée : explique et propose d’agir', () => {
    hooks.useRooms.mockReturnValue({ rooms: [room()], error: null })
    hooks.useRoom.mockReturnValue(roomState({ status: 'closed' }))
    render(<ArenaPage />)
    expect(screen.getByRole('alert')).toHaveTextContent(/connexion à ce salon est fermée/)
  })

  it('notification serveur (ex. trop de messages) affichée puis fermable', async () => {
    const dismissNotice = vi.fn()
    hooks.useRooms.mockReturnValue({ rooms: [room()], error: null })
    hooks.useRoom.mockReturnValue(roomState({ notice: 'Trop de messages, ralentissez.', dismissNotice }))
    render(<ArenaPage />)
    expect(screen.getByRole('alert')).toHaveTextContent('Trop de messages')
    await userEvent.click(screen.getByRole('button', { name: 'Fermer le message' }))
    expect(dismissNotice).toHaveBeenCalled()
  })

  it('liste vide de messages : invitation adaptée au rôle', () => {
    hooks.useRooms.mockReturnValue({ rooms: [room()], error: null })
    hooks.useRoom.mockReturnValue(roomState({ role: 'A' }))
    render(<ArenaPage />)
    expect(screen.getByText(/Lancez le débat/)).toBeInTheDocument()
  })

  it('titre du salon : repli sur la liste tant que le snapshot n’est pas arrivé', () => {
    hooks.useRooms.mockReturnValue({ rooms: [room({ title: 'Titre de la liste' })], error: null })
    hooks.useRoom.mockReturnValue(roomState({ room: null }))
    render(<ArenaPage />)
    expect(screen.getByRole('heading', { level: 2, name: 'Titre de la liste' })).toBeInTheDocument()
  })
})
