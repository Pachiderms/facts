import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../src/api/client'
import type { RoomSummary } from '../src/api/types'

const api = vi.hoisted(() => ({ createRoom: vi.fn(), deleteRoom: vi.fn(), roomsStatus: vi.fn(), reformulateTitle: vi.fn() }))
vi.mock('../src/api/client', async (orig) => ({ ...(await orig<typeof import('../src/api/client')>()), ...api }))

import { CreateRoomForm } from '../src/components/arena/CreateRoomForm'
import { DeleteRoomButton } from '../src/components/arena/DeleteRoomButton'
import { MyRooms } from '../src/components/arena/MyRooms'
import { RoomList } from '../src/components/arena/RoomList'
import { loadHistory, recordVisit } from '../src/lib/history'

const room = (i: number, theme = 'social'): RoomSummary => ({
  id: `room${i}aaa`,
  title: `Salon numéro ${i}`,
  category: 'Cat',
  theme_category: theme,
  visibility: 'public',
  trust_score: null,
  message_count: 0,
  participants: 1,
  max_participants: 4,
  spectators_allowed: true,
  spectators: 0,
})

beforeEach(() => {
  api.createRoom.mockReset()
  api.deleteRoom.mockReset()
  api.roomsStatus.mockReset()
  api.reformulateTitle.mockReset()
  localStorage.clear()
  window.location.hash = ''
})

describe('CreateRoomForm : places et spectateurs', () => {
  it('2 intervenants et spectateurs autorisés par défaut ; les choix partent au serveur et le salon entre dans l’historique', async () => {
    api.createRoom.mockResolvedValue({ id: 'abcd2345', visibility: 'public', access_code: null })
    render(<CreateRoomForm onCancel={vi.fn()} />)
    await userEvent.type(screen.getByLabelText(/Sujet du débat/i), 'Faut-il un revenu universel ?')
    expect(screen.getByLabelText('Intervenants maximum')).toHaveValue('2')
    await userEvent.selectOptions(screen.getByLabelText('Intervenants maximum'), '5')
    await userEvent.click(screen.getByLabelText(/Autoriser les spectateurs/))
    await userEvent.click(screen.getByRole('button', { name: /Créer le salon/ }))
    await waitFor(() => expect(api.createRoom).toHaveBeenCalled())
    expect(api.createRoom.mock.calls[0]![0]).toMatchObject({ max_participants: 5, spectators_allowed: false })
    expect(loadHistory()[0]).toMatchObject({ id: 'abcd2345', owner: true })
  })

  it('propose uniquement 2 à 6 intervenants', () => {
    render(<CreateRoomForm onCancel={vi.fn()} />)
    const values = Array.from((screen.getByLabelText('Intervenants maximum') as HTMLSelectElement).options).map((o) => o.value)
    expect(values).toEqual(['2', '3', '4', '5', '6'])
  })
})

describe('DeleteRoomButton', () => {
  it('demande confirmation avant de supprimer', async () => {
    api.deleteRoom.mockResolvedValue(undefined)
    const onDeleted = vi.fn()
    render(<DeleteRoomButton roomId="abcd2345" onDeleted={onDeleted} />)
    await userEvent.click(screen.getByRole('button', { name: /Supprimer le salon/ }))
    expect(api.deleteRoom).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Confirmer' }))
    await waitFor(() => expect(onDeleted).toHaveBeenCalled())
    expect(api.deleteRoom).toHaveBeenCalledWith('abcd2345')
  })

  it('annuler ne supprime rien', async () => {
    render(<DeleteRoomButton roomId="abcd2345" onDeleted={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: /Supprimer le salon/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Annuler' }))
    expect(api.deleteRoom).not.toHaveBeenCalled()
  })

  it('affiche le refus du serveur (salon non vide) sans supprimer', async () => {
    api.deleteRoom.mockRejectedValue(new Error('Des participants sont encore connectés.'))
    const onDeleted = vi.fn()
    render(<DeleteRoomButton roomId="abcd2345" onDeleted={onDeleted} />)
    await userEvent.click(screen.getByRole('button', { name: /Supprimer le salon/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Confirmer' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('encore connectés')
    expect(onDeleted).not.toHaveBeenCalled()
  })
})

describe('MyRooms', () => {
  it('ne s’affiche pas sans historique', () => {
    const { container } = render(<MyRooms />)
    expect(container).toBeEmptyDOMElement()
  })

  it('liste les salons visités, marque « Expiré » ceux disparus du serveur, et permet de retirer', async () => {
    recordVisit({ id: 'aaaa2222', title: 'Salon vivant', visibility: 'public' }, 2)
    recordVisit({ id: 'bbbb2222', title: 'Salon mort', visibility: 'private', code: 'k7m2xq' }, 1)
    api.roomsStatus.mockResolvedValue(['aaaa2222'])
    render(<MyRooms />)
    expect(screen.getByText('Salon mort')).toBeInTheDocument()
    expect(await screen.findByText('Expiré')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Retirer Salon mort/ }))
    expect(screen.queryByText('Salon mort')).not.toBeInTheDocument()
    expect(loadHistory().map((e) => e.id)).toEqual(['aaaa2222'])
  })

  it('serveur injoignable : aucun faux « Expiré »', async () => {
    recordVisit({ id: 'aaaa2222', title: 'Salon vivant', visibility: 'public' })
    api.roomsStatus.mockRejectedValue(new Error('réseau'))
    render(<MyRooms />)
    await waitFor(() => expect(api.roomsStatus).toHaveBeenCalled())
    expect(screen.queryByText('Expiré')).not.toBeInTheDocument()
  })

  it('le bouton supprimer n’apparaît que pour le créateur', async () => {
    recordVisit({ id: 'aaaa2222', title: 'Le mien', visibility: 'public', owner: true }, 2)
    recordVisit({ id: 'bbbb2222', title: 'Pas le mien', visibility: 'public' }, 1)
    api.roomsStatus.mockResolvedValue(['aaaa2222', 'bbbb2222'])
    render(<MyRooms />)
    await waitFor(() => expect(api.roomsStatus).toHaveBeenCalled())
    expect(screen.getAllByRole('button', { name: 'Supprimer le salon' })).toHaveLength(1)
  })
})

describe('RoomList : filtre par thème et « Voir plus »', () => {
  it('affiche 9 salons puis le reste au clic', async () => {
    const rooms = Array.from({ length: 12 }, (_, i) => room(i))
    render(<RoomList rooms={rooms} error={null} searching={false} />)
    expect(screen.getAllByRole('link')).toHaveLength(9)
    await userEvent.click(screen.getByRole('button', { name: /Voir plus \(3\)/ }))
    expect(screen.getAllByRole('link')).toHaveLength(12)
    expect(screen.queryByRole('button', { name: /Voir plus/ })).not.toBeInTheDocument()
  })

  it('filtre par thème, uniquement sur les thèmes présents', async () => {
    const rooms = [room(1, 'social'), room(2, 'techno'), room(3, 'techno')]
    render(<RoomList rooms={rooms} error={null} searching={false} />)
    expect(screen.queryByRole('button', { name: 'Écologie' })).not.toBeInTheDocument()
    const group = screen.getByRole('group', { name: 'Filtrer par thème' })
    const buttons = Array.from(group.querySelectorAll('button'))
    expect(buttons).toHaveLength(3) // Tous + 2 thèmes
    await userEvent.click(buttons[2]!)
    expect(screen.getAllByRole('link').length).toBeLessThan(3)
  })

  it('affiche la capacité du salon', () => {
    render(<RoomList rooms={[room(1)]} error={null} searching={false} />)
    expect(screen.getByText(/1\/4 intervenants/)).toBeInTheDocument()
  })
})

describe('CreateRoomForm : reformulation par l’IA', () => {
  const SUGGESTION = { title: 'Faut-il augmenter le SMIC à 1 700 € net ?', theme_category: 'souverain' }
  const type = (text: string) => userEvent.type(screen.getByLabelText(/Sujet du débat/i), text)

  it('le bouton est inactif tant que le sujet est vide', () => {
    render(<CreateRoomForm onCancel={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Proposer une reformulation' })).toBeDisabled()
  })

  it('affiche la proposition sans rien modifier ; « Utiliser » remplace le titre et le thème', async () => {
    api.reformulateTitle.mockResolvedValue(SUGGESTION)
    render(<CreateRoomForm onCancel={vi.fn()} />)
    await type('smic 1700 il faut')
    await userEvent.click(screen.getByRole('button', { name: 'Proposer une reformulation' }))
    expect(await screen.findByText(SUGGESTION.title)).toBeInTheDocument()
    expect(screen.getByLabelText(/Sujet du débat/i)).toHaveValue('smic 1700 il faut') // pas appliquée d'office
    await userEvent.click(screen.getByRole('button', { name: 'Utiliser cette question' }))
    expect(screen.getByLabelText(/Sujet du débat/i)).toHaveValue(SUGGESTION.title)
    expect(screen.getByLabelText('Thème')).toHaveValue('souverain')
    expect(screen.queryByRole('status', { name: 'Proposition de reformulation' })).not.toBeInTheDocument()
  })

  it('« Garder mon titre » ferme la proposition et conserve la saisie', async () => {
    api.reformulateTitle.mockResolvedValue(SUGGESTION)
    render(<CreateRoomForm onCancel={vi.fn()} />)
    await type('smic 1700 il faut')
    await userEvent.click(screen.getByRole('button', { name: 'Proposer une reformulation' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Garder mon titre' }))
    expect(screen.getByLabelText(/Sujet du débat/i)).toHaveValue('smic 1700 il faut')
    expect(screen.queryByText(SUGGESTION.title)).not.toBeInTheDocument()
  })

  it('un refus de l’IA est expliqué à l’utilisateur', async () => {
    api.reformulateTitle.mockRejectedValue(new Error('Ce sujet cible des personnes ou incite à la haine.'))
    render(<CreateRoomForm onCancel={vi.fn()} />)
    await type('sujet refusé')
    await userEvent.click(screen.getByRole('button', { name: 'Proposer une reformulation' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('incite à la haine')
  })

  it('modifier le titre efface une proposition devenue obsolète', async () => {
    api.reformulateTitle.mockResolvedValue(SUGGESTION)
    render(<CreateRoomForm onCancel={vi.fn()} />)
    await type('smic 1700')
    await userEvent.click(screen.getByRole('button', { name: 'Proposer une reformulation' }))
    await screen.findByText(SUGGESTION.title)
    await type(' !')
    expect(screen.queryByText(SUGGESTION.title)).not.toBeInTheDocument()
  })

  it('un seul appel à la fois (double clic)', async () => {
    let resolve!: (v: unknown) => void
    api.reformulateTitle.mockReturnValue(new Promise((r) => (resolve = r)))
    render(<CreateRoomForm onCancel={vi.fn()} />)
    await type('smic 1700')
    const btn = screen.getByRole('button', { name: 'Proposer une reformulation' })
    await userEvent.click(btn)
    await userEvent.click(screen.getByRole('button', { name: 'Reformulation…' }), { pointerEventsCheck: 0 })
    expect(api.reformulateTitle).toHaveBeenCalledTimes(1)
    resolve(SUGGESTION)
  })

  it('le texte proposé est affiché comme du texte, jamais interprété comme du HTML', async () => {
    api.reformulateTitle.mockResolvedValue({ title: 'Faut-il <img src=x onerror=alert(1)> réformer la fiscalité ?', theme_category: 'social' })
    const { container } = render(<CreateRoomForm onCancel={vi.fn()} />)
    await type('fiscalité')
    await userEvent.click(screen.getByRole('button', { name: 'Proposer une reformulation' }))
    await screen.findByText(/réformer la fiscalité/)
    expect(container.querySelector('img')).toBeNull()
  })
})

describe('CreateRoomForm : sujet refusé par l’IA', () => {
  const type = (text: string) => userEvent.type(screen.getByLabelText(/Sujet du débat/i), text)
  const submit = () => screen.getByRole('button', { name: /Créer le salon/ })

  it('la création est désactivée tant que le titre refusé n’est pas modifié', async () => {
    api.reformulateTitle.mockRejectedValue(new ApiError(422, 'Le sujet ne constitue pas un débat pertinent.'))
    render(<CreateRoomForm onCancel={vi.fn()} />)
    await type('azerty qsdfgh wxcvbn')
    expect(submit()).toBeEnabled()
    await userEvent.click(screen.getByRole('button', { name: 'Proposer une reformulation' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('débat pertinent')
    expect(submit()).toBeDisabled()
    await type(' ?')
    expect(submit()).toBeEnabled() // titre modifié : nouvelle chance
  })

  it('un refus du serveur à la création bloque aussi ce titre', async () => {
    api.createRoom.mockRejectedValue(new ApiError(422, 'Le sujet ne constitue pas un débat pertinent.'))
    render(<CreateRoomForm onCancel={vi.fn()} />)
    await type('azerty qsdfgh wxcvbn')
    await userEvent.click(submit())
    expect(await screen.findByRole('alert')).toHaveTextContent('débat pertinent')
    expect(submit()).toBeDisabled()
  })

  it('une panne réseau ou un 429 ne bloque pas la création', async () => {
    api.reformulateTitle.mockRejectedValue(new ApiError(429, 'Limite quotidienne atteinte.'))
    render(<CreateRoomForm onCancel={vi.fn()} />)
    await type('Faut-il réformer la fiscalité ?')
    await userEvent.click(screen.getByRole('button', { name: 'Proposer une reformulation' }))
    await screen.findByRole('alert')
    expect(submit()).toBeEnabled()
  })
})
