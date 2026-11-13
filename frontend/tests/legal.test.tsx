import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const legal = vi.hoisted(() => ({
  PUBLISHER: { name: '', address: '', email: '', siret: '', director: '', updated: '1er janvier 2027' },
}))
vi.mock('../src/lib/legal', async (orig) => ({ ...(await orig<typeof import('../src/lib/legal')>()), PUBLISHER: legal.PUBLISHER }))

import { LegalPage } from '../src/pages/LegalPage'

const todo = () => document.querySelectorAll('mark[data-todo]').length

describe('pages légales', () => {
  it.each([
    ['mentions', 'Mentions légales'],
    ['confidentialite', 'Politique de confidentialité'],
    ['cgu', 'Conditions générales d’utilisation'],
  ] as const)('%s : titre, date de mise à jour et renvoi vers les deux autres documents', (doc, title) => {
    render(<LegalPage doc={doc} />)
    expect(screen.getByRole('heading', { level: 1, name: title })).toBeInTheDocument()
    expect(screen.getByText(/Dernière mise à jour : 1er janvier 2027/)).toBeInTheDocument()
    const others = screen.getByRole('navigation', { name: 'Autres documents' }).querySelectorAll('a')
    expect(others).toHaveLength(2)
  })

  it('informations de l’éditeur manquantes : chaque champ vide est signalé « À compléter » (jamais omis en silence)', () => {
    render(<LegalPage doc="mentions" />)
    expect(todo()).toBe(6) // nom, SIRET, adresse, e-mail (contact), directeur, e-mail (signalement)
  })

  it('un champ rempli d’espaces compte comme vide', () => {
    Object.assign(legal.PUBLISHER, { name: '   ', address: '\t', email: ' ', siret: '  ', director: ' ' })
    try {
      render(<LegalPage doc="mentions" />)
      expect(todo()).toBe(6)
    } finally {
      Object.assign(legal.PUBLISHER, { name: '', address: '', email: '', siret: '', director: '' })
    }
  })

  it('informations renseignées : plus aucun marqueur, valeurs affichées', () => {
    Object.assign(legal.PUBLISHER, { name: 'Jeanne Martin', address: '1 rue Exemple, 75000 Paris', email: 'contact@cafaitdebat.fr', siret: '123 456 789 00012', director: 'Jeanne Martin' })
    try {
      render(<LegalPage doc="mentions" />)
      expect(todo()).toBe(0)
      expect(screen.getAllByText('Jeanne Martin').length).toBeGreaterThan(0)
      expect(screen.getByText('123 456 789 00012')).toBeInTheDocument()
    } finally {
      Object.assign(legal.PUBLISHER, { name: '', address: '', email: '', siret: '', director: '' })
    }
  })

  it('les mentions listent les hébergeurs ; la confidentialité cite les sous-traitants et les droits ; les CGU encadrent l’abonnement', () => {
    const { unmount } = render(<LegalPage doc="mentions" />)
    for (const host of [/Cloudflare/, /Render/, /Neon/]) expect(screen.getByText(host)).toBeInTheDocument()
    unmount()
    const priv = render(<LegalPage doc="confidentialite" />)
    for (const word of [/Groq/, /Lemon Squeezy/, /Google/, /CNIL/, /supprimer votre compte/]) expect(screen.getAllByText(word).length).toBeGreaterThan(0)
    priv.unmount()
    render(<LegalPage doc="cgu" />)
    for (const word of [/rétractation/, /résiliation/, /Lemon Squeezy/]) expect(screen.getAllByText(word).length).toBeGreaterThan(0)
    expect(screen.getByRole('link', { name: 'Tarifs' })).toHaveAttribute('href', '#/tarifs')
  })
})
