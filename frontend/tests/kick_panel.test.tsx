import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { KickVote, Presence } from '../src/api/types'
import { KickPanel } from '../src/components/arena/KickPanel'

const presence = (over: Partial<Presence> = {}): Presence => ({
  present: [1, 2],
  max_participants: 2,
  spectators: 1,
  scores: { '1': 80, '2': 20 },
  ...over,
})
const VOTE: KickVote = { target: 2, score: 20, threshold: 30, yes: 1, no: 0, ends_in: 45, voters: 2 }

function setup(over: Partial<React.ComponentProps<typeof KickPanel>> = {}) {
  const fns = { onKick: vi.fn(), onVote: vi.fn(), onTakeSeat: vi.fn() }
  const props: React.ComponentProps<typeof KickPanel> = {
    isOwner: false, you: 1, spectator: false, presence: presence(), threshold: 30, vote: null, voted: false, ...fns, ...over,
  }
  render(<KickPanel {...props} />)
  return fns
}

describe('KickPanel', () => {
  it('rien à afficher sans score, sans vote et sans place libre', () => {
    const { container } = render(
      <KickPanel isOwner={false} you={1} spectator={false} presence={presence({ scores: { '1': null, '2': null } })} threshold={30} vote={null} voted={false} onKick={vi.fn()} onVote={vi.fn()} onTakeSeat={vi.fn()} />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('le créateur peut proposer d’exclure seulement un participant sous le seuil, jamais lui-même', async () => {
    const { onKick } = setup({ isOwner: true })
    const buttons = screen.getAllByRole('button', { name: /Proposer l’exclusion/ })
    expect(buttons).toHaveLength(1)
    await userEvent.click(buttons[0]!)
    expect(onKick).toHaveBeenCalledWith(2)
  })

  it('un participant non créateur ne voit aucun bouton d’exclusion', () => {
    setup({ isOwner: false })
    expect(screen.queryByRole('button', { name: /Proposer l’exclusion/ })).not.toBeInTheDocument()
  })

  it('pas de bouton d’exclusion si le score est au-dessus du seuil', () => {
    setup({ isOwner: true, presence: presence({ scores: { '1': 80, '2': 55 } }) })
    expect(screen.queryByRole('button', { name: /Proposer l’exclusion/ })).not.toBeInTheDocument()
  })

  it('un spectateur vote une seule fois (boutons désactivés ensuite)', async () => {
    const { onVote } = setup({ spectator: true, you: null, vote: VOTE })
    await userEvent.click(screen.getByRole('button', { name: /Garder/ }))
    expect(onVote).toHaveBeenCalledWith(false)
  })

  it('après avoir voté, les boutons sont désactivés', () => {
    setup({ spectator: true, you: null, vote: VOTE, voted: true })
    expect(screen.getByRole('button', { name: /Exclure/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Garder/ })).toBeDisabled()
  })

  it('un intervenant voit le vote mais ne peut pas voter', () => {
    setup({ spectator: false, vote: VOTE })
    expect(screen.getByText(/Vote d’exclusion/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Garder/ })).not.toBeInTheDocument()
  })

  it('un spectateur voit « Prendre la place » quand un siège est libre', async () => {
    const { onTakeSeat } = setup({ spectator: true, you: null, presence: presence({ present: [1], scores: {} }) })
    await userEvent.click(screen.getByRole('button', { name: /Prendre la place/ }))
    expect(onTakeSeat).toHaveBeenCalledTimes(1)
  })

  it('pas de « Prendre la place » si le salon est complet ou pour un intervenant', () => {
    setup({ spectator: true, you: null })
    expect(screen.queryByRole('button', { name: /Prendre la place/ })).not.toBeInTheDocument()
  })
})
