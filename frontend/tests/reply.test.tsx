import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { MessageCheck, RoomMessage } from '../src/api/types'
import { Composer } from '../src/components/arena/Composer'
import { MessageCard } from '../src/components/arena/MessageCard'
import { quotePreview } from '../src/lib/presentation'
import { initialRoomState, roomReducer } from '../src/state/roomReducer'

const CHECK: MessageCheck = { status: 'no_claim', badge_type: 'gray', badge_text: 'ARGUMENT', note: '', sources: [] }
const msg = (over: Partial<RoomMessage> = {}): RoomMessage => ({
  id: 2, speaker: 2, speaker_name: 'Participant 2', text: 'Non, c’est faux.', timestamp: '2026-11-12T10:00:00+00:00', check: CHECK, ...over,
})
const reply = { id: 1, speaker: 1, preview: 'La Suède n’a jamais confiné sa population.' }

describe('MessageCard : répondre', () => {
  it('propose « Répondre » seulement quand le lecteur peut intervenir', async () => {
    const onReply = vi.fn()
    const { rerender } = render(<ul><MessageCard message={msg()} onReply={onReply} /></ul>)
    await userEvent.click(screen.getByRole('button', { name: 'Répondre au message de Participant 2' }))
    expect(onReply).toHaveBeenCalledWith(2)
    rerender(<ul><MessageCard message={msg()} /></ul>) // spectateur : pas de prop
    expect(screen.queryByRole('button', { name: /Répondre au message/ })).not.toBeInTheDocument()
  })

  it('pas de « Répondre » sur un message retiré', () => {
    render(<ul><MessageCard message={msg({ removed: true, text: '[Message retiré par la modération]' })} onReply={vi.fn()} /></ul>)
    expect(screen.queryByRole('button', { name: /Répondre au message/ })).not.toBeInTheDocument()
  })

  it('affiche la citation, et un clic ramène au message d’origine', async () => {
    const onJumpTo = vi.fn()
    render(<ul><MessageCard message={msg({ reply_to: reply })} onJumpTo={onJumpTo} /></ul>)
    const quote = screen.getByRole('button', { name: /Réponse au message du Participant 1/ })
    expect(quote).toHaveTextContent('La Suède n’a jamais confiné sa population.')
    await userEvent.click(quote)
    expect(onJumpTo).toHaveBeenCalledWith(1)
  })

  it('l’aperçu est affiché comme du texte, jamais interprété comme du HTML', () => {
    render(<ul><MessageCard message={msg({ reply_to: { ...reply, preview: '<img src=x onerror=alert(1)>' } })} /></ul>)
    expect(document.querySelector('img')).toBeNull()
    expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeInTheDocument()
  })

  it('porte une ancre et peut être mis en évidence', () => {
    render(<ul><MessageCard message={msg()} highlighted /></ul>)
    const li = document.getElementById('message-2')!
    expect(li.className).toContain('ring-2')
  })
})

describe('Composer : réponse', () => {
  it('affiche la citation, envoie avec l’identifiant puis la ferme', async () => {
    const onSend = vi.fn().mockReturnValue(true)
    const onCancelReply = vi.fn()
    render(<Composer role="A" status="open" onSend={onSend} replyTo={reply} onCancelReply={onCancelReply} />)
    expect(screen.getByText('Réponse à Participant 1')).toBeInTheDocument()
    await userEvent.type(screen.getByRole('textbox'), 'Faux, ils ont limité les contacts.{Enter}')
    expect(onSend).toHaveBeenCalledWith('Faux, ils ont limité les contacts.', 1)
    expect(onCancelReply).toHaveBeenCalledTimes(1)
  })

  it('si l’envoi échoue, la réponse reste en place avec le texte', async () => {
    const onSend = vi.fn().mockReturnValue(false)
    const onCancelReply = vi.fn()
    render(<Composer role="A" status="open" onSend={onSend} replyTo={reply} onCancelReply={onCancelReply} />)
    await userEvent.type(screen.getByRole('textbox'), 'Un argument{Enter}')
    expect(onCancelReply).not.toHaveBeenCalled()
    expect(screen.getByRole('textbox')).toHaveValue('Un argument')
  })

  it('la croix et Échap annulent la réponse', async () => {
    const onCancelReply = vi.fn()
    render(<Composer role="A" status="open" onSend={vi.fn()} replyTo={reply} onCancelReply={onCancelReply} />)
    await userEvent.click(screen.getByRole('button', { name: 'Annuler la réponse' }))
    await userEvent.type(screen.getByRole('textbox'), '{Escape}')
    expect(onCancelReply).toHaveBeenCalledTimes(2)
  })

  it('sans réponse en cours, aucun bloc de citation et replyTo vaut null', async () => {
    const onSend = vi.fn().mockReturnValue(true)
    render(<Composer role="A" status="open" onSend={onSend} />)
    expect(screen.queryByText(/Réponse à/)).not.toBeInTheDocument()
    await userEvent.type(screen.getByRole('textbox'), 'Un argument{Enter}')
    expect(onSend).toHaveBeenCalledWith('Un argument', null)
  })
})

describe('quotePreview', () => {
  it('aplatit les espaces et coupe proprement', () => {
    expect(quotePreview('  a \n\n b ')).toBe('a b')
    const out = quotePreview('mot '.repeat(100))
    expect(out.length).toBeLessThanOrEqual(120)
    expect(out.endsWith('…')).toBe(true)
  })
})

describe('roomReducer : propos retiré', () => {
  it('les réponses à un message retiré n’affichent plus son texte', () => {
    const original = msg({ id: 1, speaker: 1, text: 'Un propos injurieux' })
    const answer = msg({ id: 2, reply_to: { id: 1, speaker: 1, preview: 'Un propos injurieux' } })
    const state = { ...initialRoomState, messages: [original, answer] }
    const next = roomReducer(state, { type: 'server', event: { type: 'message_removed', message_id: 1, text: '[Message retiré par la modération]', trust_score: null, trust_delta: 0 } } as never)
    expect(next.messages[1]!.reply_to!.preview).toBe('[Message retiré par la modération]')
    expect(JSON.stringify(next)).not.toContain('injurieux')
  })
})
