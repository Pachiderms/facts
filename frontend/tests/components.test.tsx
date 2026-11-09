import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { CheckResponse, MessageCheck, RoomMessage } from '../src/api/types'
import { Composer } from '../src/components/arena/Composer'
import { MessageCard } from '../src/components/arena/MessageCard'
import { TrustMeter } from '../src/components/arena/TrustMeter'
import { VerdictPanel } from '../src/components/check/VerdictPanel'

const RESULT: CheckResponse = {
  verdict: 'À NUANCER',
  confidence_score: 85,
  summary: 'Une synthèse neutre.',
  liberal_institutional_view: { title: 'Vue institutionnelle', points: ['Risque A', 'Risque B'] },
  heterodox_social_view: { title: 'Vue sociale', points: ['Levier A'] },
  verified_sources: [{ title: 'INSEE', url: 'https://www.insee.fr/x', domain: 'insee.fr', trust_score: 95 }],
  cached: false,
}

describe('VerdictPanel', () => {
  it("entoure l'affirmation de guillemets français avec espaces insécables (pas de séquence échappée littérale)", () => {
    render(<VerdictPanel result={RESULT} assertion="Mon affirmation" />)
    const h2 = screen.getByRole('heading', { level: 2 })
    expect(h2.textContent).toBe('«\u00A0Mon affirmation\u00A0»')
  })

  it('affiche verdict, certitude, synthèse et les deux colonnes', () => {
    render(<VerdictPanel result={RESULT} assertion="Mon affirmation" />)
    expect(screen.getByText(/Verdict : À NUANCER/)).toBeInTheDocument()
    expect(screen.getByText('85 %')).toBeInTheDocument()
    expect(screen.getByText('Une synthèse neutre.')).toBeInTheDocument()
    expect(screen.getByText('Vue institutionnelle')).toBeInTheDocument()
    expect(screen.getByText('Risque B')).toBeInTheDocument()
    expect(screen.getByText('Levier A')).toBeInTheDocument()
  })

  it('indique un résultat en cache', () => {
    render(<VerdictPanel result={{ ...RESULT, cached: true }} assertion="x" />)
    expect(screen.getByText('Résultat en cache')).toBeInTheDocument()
  })

  it('le tiroir de sources s’ouvre et propose un lien sûr (noopener, nouvel onglet)', async () => {
    render(<VerdictPanel result={RESULT} assertion="x" />)
    expect(screen.queryByText('Sources retenues')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Sources \(1\)/ }))
    const link = screen.getByRole('link', { name: /Ouvrir/ })
    expect(link).toHaveAttribute('href', 'https://www.insee.fr/x')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('n’affiche JAMAIS un lien javascript: ou data: venu des données', async () => {
    const hostile = {
      ...RESULT,
      verified_sources: [
        { title: 'Piège 1', url: 'javascript:alert(1)', domain: 'evil.example', trust_score: 90 },
        { title: 'Piège 2', url: 'data:text/html,<script>alert(1)</script>', domain: 'evil2.example', trust_score: 90 },
      ],
    }
    render(<VerdictPanel result={hostile} assertion="x" />)
    await userEvent.click(screen.getByRole('button', { name: /Sources \(2\)/ }))
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    expect(screen.getByText('Piège 1')).toBeInTheDocument() // le titre reste lisible, sans lien
  })

  it('affiche le HTML hostile comme du texte, sans l’interpréter', () => {
    const hostile = { ...RESULT, summary: '<img src=x onerror=alert(1)> <script>alert(2)</script>' }
    const { container } = render(<VerdictPanel result={hostile} assertion={'<b>gras</b>'} />)
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('b')).toBeNull()
    expect(screen.getByText(/onerror=alert\(1\)/)).toBeInTheDocument()
  })

  it('avertit quand aucune source n’a été validée', () => {
    render(<VerdictPanel result={{ ...RESULT, verified_sources: [] }} assertion="x" />)
    expect(screen.getByRole('note')).toHaveTextContent(/Aucune source/)
  })

  it('une colonne vide l’indique plutôt que de rester blanche', () => {
    render(<VerdictPanel result={{ ...RESULT, heterodox_social_view: { title: 'Vide', points: [] } }} assertion="x" />)
    expect(screen.getByText(/Aucun élément étayé/)).toBeInTheDocument()
  })

  it('copie le résultat dans le presse-papiers', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    render(<VerdictPanel result={RESULT} assertion="Mon affirmation" />)
    await userEvent.click(screen.getByRole('button', { name: 'Copier le résultat' }))
    expect(writeText).toHaveBeenCalledOnce()
    expect(writeText.mock.calls[0]![0]).toContain('Verdict : À NUANCER')
    expect(writeText.mock.calls[0]![0]).toContain('https://www.insee.fr/x')
  })

  it('survit à un presse-papiers indisponible', async () => {
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: vi.fn().mockRejectedValue(new Error('refusé')) }, configurable: true })
    render(<VerdictPanel result={RESULT} assertion="x" />)
    await userEvent.click(screen.getByRole('button', { name: 'Copier le résultat' }))
    expect(await screen.findByText('Copie impossible')).toBeInTheDocument()
  })
})

const PENDING: MessageCheck = { status: 'pending', badge_type: 'gray', badge_text: 'VÉRIFICATION EN COURS', note: '', sources: [] }

const message = (over: Partial<RoomMessage> = {}, check: Partial<MessageCheck> = {}): RoomMessage => ({
  id: 1,
  speaker: 1,
  speaker_name: 'Participant 1',
  text: 'Selon l’INSEE, 12 %.',
  timestamp: '2026-11-05T10:00:00+00:00',
  check: { ...PENDING, ...check },
  ...over,
})

describe('MessageCard', () => {
  it('un message en attente affiche un état de vérification', () => {
    render(<ul><MessageCard message={message()} /></ul>)
    expect(screen.getByRole('status')).toHaveTextContent('VÉRIFICATION EN COURS')
  })

  it('affiche badge, note, source et variation de score', () => {
    const m = message({}, {
      status: 'verified',
      badge_type: 'green',
      badge_text: 'VÉRIFIÉ',
      note: 'Confirmé par l’INSEE.',
      sources: [{ title: 'INSEE', url: 'https://insee.fr/a', domain: 'insee.fr' }],
    })
    render(<ul><MessageCard message={m} delta={6} /></ul>)
    expect(screen.getByText('[VÉRIFIÉ]')).toBeInTheDocument()
    expect(screen.getByText('Confirmé par l’INSEE.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /insee\.fr/ })).toHaveAttribute('href', 'https://insee.fr/a')
    expect(screen.getByLabelText(/en hausse de 6 points/)).toHaveTextContent('+6')
  })

  it('variation négative : signe moins et libellé « en baisse »', () => {
    render(<ul><MessageCard message={message()} delta={-3} /></ul>)
    expect(screen.getByLabelText(/en baisse de 3 points/)).toHaveTextContent('−3')
  })

  it('le texte d’un participant est affiché tel quel (pas de HTML interprété)', () => {
    const m = message({ text: '<script>alert(1)</script><img src=x onerror=alert(2)>' })
    const { container } = render(<ul><MessageCard message={m} /></ul>)
    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('img')).toBeNull()
    expect(screen.getByText(/<script>alert\(1\)<\/script>/)).toBeInTheDocument()
  })

  it('une source au lien dangereux n’est pas cliquable', () => {
    const m = message({}, { sources: [{ title: 'Piège', url: 'javascript:alert(1)', domain: 'evil.example' }] })
    render(<ul><MessageCard message={m} /></ul>)
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    expect(screen.getByText('evil.example')).toBeInTheDocument()
  })
})

describe('TrustMeter', () => {
  it('sans donnée : « — », aucune valeur de jauge, jamais 0', () => {
    render(<TrustMeter score={null} />)
    const bar = screen.getByRole('progressbar')
    expect(bar).not.toHaveAttribute('aria-valuenow')
    expect(bar).toHaveAttribute('aria-valuetext', 'Pas encore de donnée')
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('avec un score : valeur accessible et largeur proportionnelle', () => {
    render(<TrustMeter score={78} />)
    const bar = screen.getByRole('progressbar')
    expect(bar).toHaveAttribute('aria-valuenow', '78')
    expect(screen.getByText('78 / 100')).toBeInTheDocument()
    expect(bar.firstElementChild).toHaveStyle({ width: '78%' })
  })
})

describe('Composer', () => {
  let onSend: ReturnType<typeof vi.fn<(text: string) => boolean>>
  beforeEach(() => {
    onSend = vi.fn<(text: string) => boolean>().mockReturnValue(true)
  })
  const type = async (text: string) => userEvent.type(screen.getByRole('textbox'), text)

  it('un spectateur ne peut pas écrire', () => {
    render(<Composer role="spectator" status="open" onSend={onSend} />)
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    expect(screen.getByText(/en spectateur/)).toBeInTheDocument()
  })

  it('Entrée envoie et vide le champ', async () => {
    render(<Composer role="A" status="open" onSend={onSend} />)
    await type('Mon argument{Enter}')
    expect(onSend).toHaveBeenCalledWith('Mon argument')
    expect(screen.getByRole('textbox')).toHaveValue('')
  })

  it('Maj+Entrée ajoute une ligne sans envoyer', async () => {
    render(<Composer role="B" status="open" onSend={onSend} />)
    await type('ligne 1{Shift>}{Enter}{/Shift}ligne 2')
    expect(onSend).not.toHaveBeenCalled()
    expect(screen.getByRole('textbox')).toHaveValue('ligne 1\nligne 2')
  })

  it('refuse d’envoyer un texte vide ou blanc', async () => {
    render(<Composer role="A" status="open" onSend={onSend} />)
    await type('   {Enter}')
    expect(onSend).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: /Envoyer/ })).toBeDisabled()
  })

  it.each(['connecting', 'reconnecting', 'closed'] as const)('désactive l’envoi quand le salon est « %s »', async (status) => {
    render(<Composer role="A" status={status} onSend={onSend} />)
    await type('Texte')
    expect(screen.getByRole('button', { name: /Envoyer/ })).toBeDisabled()
    await userEvent.keyboard('{Enter}')
    expect(onSend).not.toHaveBeenCalled()
  })

  it('si l’envoi échoue, le texte est conservé et une alerte s’affiche', async () => {
    onSend.mockReturnValue(false)
    render(<Composer role="A" status="open" onSend={onSend} />)
    await type('Important{Enter}')
    expect(screen.getByRole('textbox')).toHaveValue('Important')
    expect(screen.getByRole('alert')).toHaveTextContent(/Votre texte est conservé/)
  })

  it('affiche l’aide à la rédaction : chiffre sans source, puis source reconnue', async () => {
    render(<Composer role="A" status="open" onSend={onSend} />)
    await type('Le chômage est de 12 %')
    expect(screen.getByText(/Chiffre sans source citée/)).toBeInTheDocument()
    await userEvent.clear(screen.getByRole('textbox'))
    await type('Selon l’INSEE, le chômage est de 7 %')
    expect(screen.getByText(/l’agent va le contrôler/)).toBeInTheDocument()
  })

  it('limite la saisie à 500 caractères', () => {
    render(<Composer role="A" status="open" onSend={onSend} />)
    expect(screen.getByRole('textbox')).toHaveAttribute('maxlength', '500')
  })
})

describe('MessageCard : signalement et message retiré', () => {
  it('propose « Signaler » seulement quand un gestionnaire est fourni, et l’appelle avec l’id', async () => {
    const onReport = vi.fn()
    const { rerender } = render(<ul><MessageCard message={message({ id: 7 })} /></ul>)
    expect(screen.queryByRole('button', { name: /Signaler/ })).not.toBeInTheDocument()
    rerender(<ul><MessageCard message={message({ id: 7 })} onReport={onReport} /></ul>)
    await userEvent.click(screen.getByRole('button', { name: /Signaler le message de Participant 1/ }))
    expect(onReport).toHaveBeenCalledWith(7)
  })

  it('un message retiré n’affiche ni badge, ni source, ni bouton de signalement', () => {
    const removed = message({ removed: true, text: '[Message retiré par la modération]' }, { status: 'no_claim', badge_text: 'RETIRÉ', note: 'x' })
    render(<ul><MessageCard message={removed} onReport={vi.fn()} /></ul>)
    expect(screen.getByText('[Message retiré par la modération]')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Signaler/ })).not.toBeInTheDocument()
    expect(screen.getByText('[RETIRÉ]').closest('.hidden')).not.toBeNull() // masqué visuellement
  })
})

describe('MessageCard : numéros stables', () => {
  const side = () => screen.getByRole('listitem').className

  it('« vous » sur mes messages, aligné à droite ; les autres à gauche', () => {
    const { rerender } = render(<ul><MessageCard message={message({ speaker: 2, speaker_name: 'Participant 2' })} mine /></ul>)
    expect(screen.getByText('vous')).toBeInTheDocument()
    expect(side()).toContain('ml-6')
    rerender(<ul><MessageCard message={message({ speaker: 1 })} /></ul>)
    expect(screen.queryByText('vous')).not.toBeInTheDocument()
    expect(side()).toContain('mr-6')
  })

  it('le numéro (pas la lettre d’un siège) est affiché dans l’avatar', () => {
    render(<ul><MessageCard message={message({ speaker: 7, speaker_name: 'Participant 7' })} /></ul>)
    expect(screen.getByText('7')).toBeInTheDocument()
  })

  it('un auteur parti est marqué « absent » ; jamais sur mes propres messages', () => {
    const { rerender } = render(<ul><MessageCard message={message()} absent /></ul>)
    expect(screen.getByText('absent')).toBeInTheDocument()
    rerender(<ul><MessageCard message={message()} absent mine /></ul>)
    expect(screen.queryByText('absent')).not.toBeInTheDocument()
  })

  it('un spectateur voit les numéros impairs à gauche et pairs à droite', () => {
    const { rerender } = render(<ul><MessageCard message={message({ speaker: 1 })} viewerIsSpectator /></ul>)
    expect(side()).toContain('mr-6')
    rerender(<ul><MessageCard message={message({ speaker: 2 })} viewerIsSpectator /></ul>)
    expect(side()).toContain('ml-6')
  })
})

describe('Composer : numéro de participant', () => {
  it('affiche le numéro stable, pas la lettre du siège', () => {
    render(<Composer role="A" number={2} status="open" onSend={vi.fn()} />)
    expect(screen.getByText('Vous êtes Participant 2')).toBeInTheDocument()
  })
})
