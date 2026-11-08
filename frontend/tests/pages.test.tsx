import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CheckResponse, RoomSummary } from '../src/api/types'
import { CheckPage } from '../src/pages/CheckPage'

const hooks = vi.hoisted(() => ({ useRooms: vi.fn(), useRoom: vi.fn(), useRoomLookup: vi.fn() }))
vi.mock('../src/hooks/useRooms', () => ({ useRooms: hooks.useRooms }))
vi.mock('../src/hooks/useRoom', () => ({ useRoom: hooks.useRoom }))
vi.mock('../src/hooks/useRoomLookup', () => ({ useRoomLookup: hooks.useRoomLookup }))

// Importés APRÈS vi.mock (hissé) : ces pages utilisent les hooks simulés.
import App from '../src/App'
import { ArenaPage } from '../src/pages/ArenaPage'
import { RoomPage } from '../src/pages/RoomPage'

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
  visibility: 'public',
  trust_score: null,
  message_count: 0,
  participants: 1,
  max_participants: 2,
  spectators_allowed: true,
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
  denied: null,
  send: vi.fn().mockReturnValue(true),
  dismissNotice: vi.fn(),
  ...over,
})

const found = (over: Partial<RoomSummary> = {}) => ({
  status: 'found',
  lookup: { id: 'room-1', visibility: 'public', requires_code: false, room: room(over) },
})

beforeEach(() => {
  sessionStorage.clear()
  localStorage.clear()
  window.location.hash = ''
  hooks.useRooms.mockReset()
  hooks.useRoom.mockReset()
  hooks.useRoomLookup.mockReset()
  hooks.useRoom.mockReturnValue(roomState())
  hooks.useRoomLookup.mockReturnValue({ status: 'idle' })
})

describe('ArenaPage (liste des salons)', () => {
  it('chargement : message d’attente, aucune connexion temps réel', () => {
    hooks.useRooms.mockReturnValue({ rooms: null, error: null })
    render(<ArenaPage />)
    expect(screen.getByText(/Chargement des salons/)).toBeInTheDocument()
    expect(hooks.useRoom).not.toHaveBeenCalled()
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

  it('chaque salon est un lien vers sa propre page ; score absent « — », présent tel quel', () => {
    hooks.useRooms.mockReturnValue({ rooms: [room(), room({ id: 'room-2', title: 'Électricité', trust_score: 84 })], error: null })
    render(<ArenaPage />)
    expect(screen.getByRole('link', { name: /^(?!Regarder).*SMIC/ })).toHaveAttribute('href', '#/arena/room-1')
    expect(screen.getByRole('link', { name: /^(?!Regarder).*Électricité/ })).toHaveAttribute('href', '#/arena/room-2')
    expect(screen.getByText('Score : —')).toBeInTheDocument()
    expect(screen.getByText('Score : 84')).toBeInTheDocument()
  })

  it('plus de zone « Intervenir » sur la liste : on écrit dans la page d’un salon', () => {
    hooks.useRooms.mockReturnValue({ rooms: [room()], error: null })
    render(<ArenaPage />)
    expect(screen.queryByRole('textbox', { name: 'Votre argument' })).not.toBeInTheDocument()
    expect(screen.queryByText(/Intervenir dans la discussion/)).not.toBeInTheDocument()
    expect(hooks.useRoom).not.toHaveBeenCalled()
  })

  it('la recherche est retardée puis transmise au hook de liste et à la recherche par ID', async () => {
    hooks.useRooms.mockReturnValue({ rooms: [room()], error: null })
    render(<ArenaPage />)
    await userEvent.type(screen.getByRole('searchbox', { name: /Rechercher un salon/ }), 'SMIC')
    await waitFor(() => expect(hooks.useRooms).toHaveBeenLastCalledWith('SMIC'))
    expect(hooks.useRoomLookup).toHaveBeenLastCalledWith('smic')
    expect(hooks.useRooms).not.toHaveBeenCalledWith('S') // pas de requête à chaque frappe
  })

  it('recherche sans résultat : message adapté', async () => {
    hooks.useRooms.mockReturnValue({ rooms: [], error: null })
    render(<ArenaPage />)
    await userEvent.type(screen.getByRole('searchbox'), 'zzz')
    expect(await screen.findByText(/Aucun salon public ne correspond/)).toBeInTheDocument()
  })

  it('limite la recherche à 60 caractères', () => {
    hooks.useRooms.mockReturnValue({ rooms: [], error: null })
    render(<ArenaPage />)
    expect(screen.getByRole('searchbox')).toHaveAttribute('maxlength', '60')
  })

  it('un salon privé trouvé par ID est proposé, sans titre ni contenu', async () => {
    hooks.useRooms.mockReturnValue({ rooms: [], error: null })
    hooks.useRoomLookup.mockReturnValue({ status: 'found', lookup: { id: 'abcd2345', visibility: 'private', requires_code: true, room: null } })
    render(<ArenaPage />)
    expect(screen.getByText('abcd2345')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Rejoindre le salon privé' })).toHaveAttribute('href', '#/arena/abcd2345')
  })

  it('un salon public trouvé par ID n’est pas dupliqué (il est déjà dans la liste)', () => {
    hooks.useRooms.mockReturnValue({ rooms: [room()], error: null })
    hooks.useRoomLookup.mockReturnValue(found())
    render(<ArenaPage />)
    expect(screen.queryByRole('link', { name: 'Rejoindre le salon privé' })).not.toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: /^(?!Regarder).*SMIC/ })).toHaveLength(1)
  })
})

describe('Création d’un salon', () => {
  const fetchMock = vi.fn()
  beforeEach(() => {
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
    hooks.useRooms.mockReturnValue({ rooms: [], error: null })
  })
  afterEach(() => vi.unstubAllGlobals())

  const open = async () => {
    render(<ArenaPage />)
    await userEvent.click(screen.getByRole('button', { name: /Créer un salon/ }))
  }
  const fill = (text = 'Faut-il instaurer un revenu universel ?') =>
    userEvent.type(screen.getByRole('textbox', { name: 'Sujet du débat' }), text)

  it('le formulaire est masqué puis s’ouvre et se referme', async () => {
    render(<ArenaPage />)
    expect(screen.queryByRole('form', { name: 'Créer un salon' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Créer un salon/ }))
    expect(screen.getByRole('form', { name: 'Créer un salon' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Annuler' }))
    expect(screen.queryByRole('form', { name: 'Créer un salon' })).not.toBeInTheDocument()
  })

  it('le bouton reste désactivé sous 10 caractères', async () => {
    await open()
    const submit = screen.getByRole('button', { name: 'Créer le salon' })
    expect(submit).toBeDisabled()
    await fill('Court')
    expect(submit).toBeDisabled()
    await fill(' mais suffisant ?')
    expect(submit).toBeEnabled()
  })

  it('titre limité à 120 caractères ; compteur visible', async () => {
    await open()
    expect(screen.getByRole('textbox', { name: 'Sujet du débat' })).toHaveAttribute('maxlength', '120')
    await fill('Salut les amis')
    expect(screen.getByText(/14\/120/)).toBeInTheDocument()
  })

  it('public par défaut ; propose uniquement les thèmes acceptés par le serveur', async () => {
    await open()
    expect(screen.getByRole('radio', { name: /Public/ })).toBeChecked()
    const options = within(screen.getByRole('combobox', { name: 'Thème' })).getAllByRole('option')
    expect(options.map((o) => (o as HTMLOptionElement).value)).toEqual(['social', 'souverain', 'ecologie', 'techno'])
  })

  it('crée un salon public puis ouvre sa page', async () => {
    fetchMock.mockResolvedValue(json({ id: 'abcd2345', visibility: 'public', access_code: null }, { status: 201 }))
    await open()
    await fill()
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Thème' }), 'ecologie')
    await userEvent.click(screen.getByRole('button', { name: 'Créer le salon' }))
    await waitFor(() => expect(window.location.hash).toBe('#/arena/abcd2345'))
    const body = JSON.parse(fetchMock.mock.calls[0]![1].body)
    expect(body).toMatchObject({ title: 'Faut-il instaurer un revenu universel ?', theme_category: 'ecologie', visibility: 'public' })
    expect(body.participant_token).toMatch(/^[A-Za-z0-9_-]{22,64}$/)
    expect(sessionStorage.getItem('facts.code.abcd2345')).toBeNull()
  })

  it('un salon privé mémorise son code pour le rechargement de l’onglet', async () => {
    fetchMock.mockResolvedValue(json({ id: 'abcd2345', visibility: 'private', access_code: 'k7m2xq' }, { status: 201 }))
    await open()
    await fill()
    await userEvent.click(screen.getByRole('radio', { name: /Privé/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Créer le salon' }))
    await waitFor(() => expect(window.location.hash).toBe('#/arena/abcd2345'))
    expect(JSON.parse(fetchMock.mock.calls[0]![1].body).visibility).toBe('private')
    expect(sessionStorage.getItem('facts.code.abcd2345')).toBe('k7m2xq')
  })

  it('titre sans espaces superflus', async () => {
    fetchMock.mockResolvedValue(json({ id: 'abcd2345', visibility: 'public', access_code: null }, { status: 201 }))
    await open()
    await fill('   Un sujet bien formulé ?   ')
    await userEvent.click(screen.getByRole('button', { name: 'Créer le salon' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    expect(JSON.parse(fetchMock.mock.calls[0]![1].body).title).toBe('Un sujet bien formulé ?')
  })

  it('erreur serveur (limite quotidienne) : alerte, saisie conservée, nouvel essai possible', async () => {
    fetchMock.mockImplementation(async () => json({ detail: 'Limite quotidienne de création de salons atteinte. Revenez demain.' }, { status: 429 }))
    await open()
    await fill()
    await userEvent.click(screen.getByRole('button', { name: 'Créer le salon' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Revenez demain')
    expect(screen.getByRole('textbox', { name: 'Sujet du débat' })).toHaveValue('Faut-il instaurer un revenu universel ?')
    expect(screen.getByRole('button', { name: 'Créer le salon' })).toBeEnabled()
    expect(window.location.hash).toBe('')
  })

  it('serveur injoignable : message clair', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))
    await open()
    await fill()
    await userEvent.click(screen.getByRole('button', { name: 'Créer le salon' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/injoignable/)
  })

  it('un double clic ne crée qu’un seul salon', async () => {
    let release: (r: Response) => void = () => undefined
    fetchMock.mockReturnValue(new Promise<Response>((resolve) => (release = resolve)))
    await open()
    await fill()
    const submit = screen.getByRole('button', { name: 'Créer le salon' })
    await userEvent.dblClick(submit)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: 'Création…' })).toBeDisabled()
    release(json({ id: 'abcd2345', visibility: 'public', access_code: null }, { status: 201 }))
    await waitFor(() => expect(window.location.hash).toBe('#/arena/abcd2345'))
  })
})

describe('RoomPage (une room = une page)', () => {
  it('ouverture : message d’attente, aucune connexion avant de savoir que le salon existe', () => {
    hooks.useRoomLookup.mockReturnValue({ status: 'loading' })
    render(<RoomPage id="room-1" />)
    expect(screen.getByRole('status')).toHaveTextContent(/Ouverture du salon/)
    expect(hooks.useRoom).not.toHaveBeenCalled()
  })

  it('salon introuvable : explique et ramène à la liste, sans connexion', () => {
    hooks.useRoomLookup.mockReturnValue({ status: 'missing' })
    render(<RoomPage id="zzzzzzzz" />)
    expect(screen.getByRole('alert')).toHaveTextContent('Salon introuvable')
    expect(screen.getByRole('link', { name: /Tous les salons/ })).toHaveAttribute('href', '#/arena')
    expect(hooks.useRoom).not.toHaveBeenCalled()
  })

  it('erreur réseau : message du serveur affiché', () => {
    hooks.useRoomLookup.mockReturnValue({ status: 'error', message: 'Serveur injoignable.' })
    render(<RoomPage id="room-1" />)
    expect(screen.getByRole('alert')).toHaveTextContent(/Impossible d’ouvrir le salon.*Serveur injoignable/)
  })

  it('salon public : se connecte sans code, avec lien de retour et ID copiable', () => {
    hooks.useRoomLookup.mockReturnValue(found())
    render(<RoomPage id="room-1" />)
    expect(hooks.useRoom).toHaveBeenLastCalledWith('room-1', undefined, false)
    expect(screen.getByRole('link', { name: /Tous les salons/ })).toHaveAttribute('href', '#/arena')
    expect(screen.getByRole('button', { name: 'Copier id' })).toBeInTheDocument()
    expect(screen.queryByText('Salon privé')).not.toBeInTheDocument()
  })

  it('salon privé : badge, et le code d’accès n’est montré qu’au propriétaire (snapshot)', () => {
    hooks.useRoomLookup.mockReturnValue({ status: 'found', lookup: { id: 'abcd2345', visibility: 'private', requires_code: true, room: null } })
    hooks.useRoom.mockReturnValue(roomState({ room: room({ id: 'abcd2345', visibility: 'private', access_code: 'k7m2xq' }) }))
    const { unmount } = render(<RoomPage id="abcd2345" />)
    expect(screen.getByText('Salon privé')).toBeInTheDocument()
    expect(screen.getByText('k7m2xq')).toBeInTheDocument()
    unmount()
    hooks.useRoom.mockReturnValue(roomState({ room: room({ id: 'abcd2345', visibility: 'private' }) }))
    render(<RoomPage id="abcd2345" />)
    expect(screen.queryByText('k7m2xq')).not.toBeInTheDocument()
  })

  it('réutilise le code mémorisé dans l’onglet (rechargement)', () => {
    sessionStorage.setItem('facts.code.room-1', 'k7m2xq')
    hooks.useRoomLookup.mockReturnValue(found())
    render(<RoomPage id="room-1" />)
    expect(hooks.useRoom).toHaveBeenLastCalledWith('room-1', 'k7m2xq', false)
  })

  it('code requis : formulaire ; la saisie reconnecte avec le code et le mémorise', async () => {
    hooks.useRoomLookup.mockReturnValue({ status: 'found', lookup: { id: 'abcd2345', visibility: 'private', requires_code: true, room: null } })
    hooks.useRoom.mockImplementation((_id: string, code?: string) => roomState(code ? {} : { denied: 'invalid_code' }))
    render(<RoomPage id="abcd2345" />)
    expect(screen.getByRole('heading', { name: /Salon privé/ })).toBeInTheDocument()
    expect(screen.queryByText(/Code invalide/)).not.toBeInTheDocument() // premier passage : pas de reproche
    await userEvent.type(screen.getByLabelText('Code d’accès'), 'k7m2xq{Enter}')
    expect(hooks.useRoom).toHaveBeenLastCalledWith('abcd2345', 'k7m2xq', false)
    expect(sessionStorage.getItem('facts.code.abcd2345')).toBe('k7m2xq')
    expect(screen.queryByRole('form', { name: 'Code d\'accès' })).not.toBeInTheDocument()
  })

  it('code refusé : message d’erreur, et le code erroné n’est pas conservé', async () => {
    sessionStorage.setItem('facts.code.abcd2345', 'faux00')
    hooks.useRoomLookup.mockReturnValue({ status: 'found', lookup: { id: 'abcd2345', visibility: 'private', requires_code: true, room: null } })
    hooks.useRoom.mockReturnValue(roomState({ denied: 'invalid_code' }))
    render(<RoomPage id="abcd2345" />)
    expect(screen.getByRole('alert')).toHaveTextContent('Code invalide')
    await waitFor(() => expect(sessionStorage.getItem('facts.code.abcd2345')).toBeNull())
  })

  it('le formulaire de code refuse une saisie vide', () => {
    hooks.useRoomLookup.mockReturnValue({ status: 'found', lookup: { id: 'abcd2345', visibility: 'private', requires_code: true, room: null } })
    hooks.useRoom.mockReturnValue(roomState({ denied: 'invalid_code' }))
    render(<RoomPage id="abcd2345" />)
    expect(screen.getByRole('button', { name: 'Entrer dans le salon' })).toBeDisabled()
    expect(screen.getByLabelText('Code d’accès')).toHaveAttribute('maxlength', '16')
  })

  it('trop de codes erronés : message d’attente, pas de formulaire', () => {
    hooks.useRoomLookup.mockReturnValue(found())
    hooks.useRoom.mockReturnValue(roomState({ denied: 'too_many_attempts' }))
    render(<RoomPage id="room-1" />)
    expect(screen.getByRole('alert')).toHaveTextContent(/Trop de codes erronés/)
    expect(screen.queryByLabelText('Code d’accès')).not.toBeInTheDocument()
  })

  it('ouvert dans un autre onglet : explique et permet de reprendre la place', async () => {
    hooks.useRoomLookup.mockReturnValue(found())
    hooks.useRoom.mockReturnValue(roomState({ denied: 'session_replaced' }))
    render(<RoomPage id="room-1" />)
    expect(screen.getByRole('alert')).toHaveTextContent(/autre onglet/)
    const calls = hooks.useRoom.mock.calls.length
    hooks.useRoom.mockReturnValue(roomState())
    await userEvent.click(screen.getByRole('button', { name: 'Reprendre ici' }))
    expect(hooks.useRoom.mock.calls.length).toBeGreaterThan(calls) // nouvelle connexion
    expect(screen.queryByRole('button', { name: 'Reprendre ici' })).not.toBeInTheDocument()
  })

  it('affiche le rôle attribué par le serveur, le statut et la présence', () => {
    hooks.useRoomLookup.mockReturnValue(found())
    hooks.useRoom.mockReturnValue(roomState({ role: 'B', presence: { seats: ['A', 'B'], max_participants: 2, spectators: 2 } }))
    render(<RoomPage id="room-1" />)
    expect(screen.getByText('Vous êtes Participant B')).toBeInTheDocument()
    expect(screen.getByText('En direct')).toBeInTheDocument()
    expect(screen.getByText(/Intervenants : 2\/2 \(A, B\) · 2 spectateurs/)).toBeInTheDocument()
  })

  it('la zone de saisie est dans la page du salon (intervenant) et absente pour un spectateur', () => {
    hooks.useRoomLookup.mockReturnValue(found())
    const { unmount } = render(<RoomPage id="room-1" />)
    expect(screen.getByRole('textbox', { name: 'Votre argument' })).toBeInTheDocument()
    unmount()
    hooks.useRoom.mockReturnValue(roomState({ role: 'spectator' }))
    render(<RoomPage id="room-1" />)
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('envoie le message saisi via le hook du salon', async () => {
    const send = vi.fn().mockReturnValue(true)
    hooks.useRoomLookup.mockReturnValue(found())
    hooks.useRoom.mockReturnValue(roomState({ send }))
    render(<RoomPage id="room-1" />)
    await userEvent.type(screen.getByRole('textbox', { name: 'Votre argument' }), 'Selon l’INSEE, 5 %{Enter}')
    expect(send).toHaveBeenCalledWith('Selon l’INSEE, 5 %')
  })

  it('état « reconnexion » visible ; envoi bloqué', async () => {
    hooks.useRoomLookup.mockReturnValue(found())
    hooks.useRoom.mockReturnValue(roomState({ status: 'reconnecting' }))
    render(<RoomPage id="room-1" />)
    expect(screen.getByText('Reconnexion…')).toBeInTheDocument()
    await userEvent.type(screen.getByRole('textbox', { name: 'Votre argument' }), 'Texte')
    expect(screen.getByRole('button', { name: /Envoyer/ })).toBeDisabled()
  })

  it('connexion fermée : explique et propose d’agir', () => {
    hooks.useRoomLookup.mockReturnValue(found())
    hooks.useRoom.mockReturnValue(roomState({ status: 'closed' }))
    render(<RoomPage id="room-1" />)
    expect(screen.getByRole('alert')).toHaveTextContent(/connexion à ce salon est fermée/)
  })

  it('notification serveur (ex. trop de messages) affichée puis fermable', async () => {
    const dismissNotice = vi.fn()
    hooks.useRoomLookup.mockReturnValue(found())
    hooks.useRoom.mockReturnValue(roomState({ notice: 'Trop de messages, ralentissez.', dismissNotice }))
    render(<RoomPage id="room-1" />)
    expect(screen.getByRole('alert')).toHaveTextContent('Trop de messages')
    await userEvent.click(screen.getByRole('button', { name: 'Fermer le message' }))
    expect(dismissNotice).toHaveBeenCalled()
  })

  it('liste vide de messages : invitation adaptée au rôle', () => {
    hooks.useRoomLookup.mockReturnValue(found())
    render(<RoomPage id="room-1" />)
    expect(screen.getByText(/Lancez le débat/)).toBeInTheDocument()
  })

  it('titre du salon : repli sur la recherche tant que le snapshot n’est pas arrivé', () => {
    hooks.useRoomLookup.mockReturnValue(found({ title: 'Titre de la recherche' }))
    hooks.useRoom.mockReturnValue(roomState({ room: null }))
    render(<RoomPage id="room-1" />)
    expect(screen.getByRole('heading', { level: 2, name: 'Titre de la recherche' })).toBeInTheDocument()
  })
})

describe('App (routage)', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ status: 'ok' })))
    hooks.useRooms.mockReturnValue({ rooms: [room()], error: null })
  })
  afterEach(() => vi.unstubAllGlobals())

  it('#/arena : la liste', () => {
    window.location.hash = '#/arena'
    render(<App />)
    expect(screen.getByRole('heading', { level: 1, name: 'Arène de débat' })).toBeInTheDocument()
  })

  it('#/arena/<id> : la page du salon, onglet « Arène » actif', () => {
    window.location.hash = '#/arena/room-1'
    hooks.useRoomLookup.mockReturnValue(found())
    render(<App />)
    expect(screen.getByRole('heading', { level: 2, name: 'SMIC à 1 700 €' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Arène de débat' })).toHaveAttribute('aria-current', 'page')
  })

  it('suit les changements d’adresse sans recharger (lien d’un salon, bouton retour)', async () => {
    window.location.hash = '#/arena'
    hooks.useRoomLookup.mockReturnValue(found())
    render(<App />)
    act(() => {
      window.location.hash = '#/arena/room-1'
    })
    expect(await screen.findByRole('heading', { level: 2, name: 'SMIC à 1 700 €' })).toBeInTheDocument()
    act(() => {
      window.location.hash = '#/arena'
    })
    expect(await screen.findByRole('heading', { level: 1, name: 'Arène de débat' })).toBeInTheDocument()
  })

  it('un identifiant hostile dans l’adresse ramène à la liste', () => {
    window.location.hash = '#/arena/<script>alert(1)</script>'
    render(<App />)
    expect(screen.getByRole('heading', { level: 1, name: 'Arène de débat' })).toBeInTheDocument()
    expect(hooks.useRoom).not.toHaveBeenCalled()
  })

  it('le bouton « Arène de débat » depuis un salon ramène à la liste', async () => {
    window.location.hash = '#/arena/room-1'
    hooks.useRoomLookup.mockReturnValue(found())
    render(<App />)
    await userEvent.click(screen.getByRole('button', { name: 'Arène de débat' }))
    expect(window.location.hash).toBe('#/arena')
  })
})
