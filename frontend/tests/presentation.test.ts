import { describe, expect, it } from 'vitest'
import { badgeTone, composeHint, formatScore, formatTime, safeHref, themeBadge, trustTone, verdictTone } from '../src/lib/presentation'

describe('safeHref (sécurité des liens)', () => {
  it.each([
    ['https://www.insee.fr/fr/statistiques', 'https://www.insee.fr/fr/statistiques'],
    ['http://example.org/a', 'http://example.org/a'],
  ])('accepte %s', (input, expected) => expect(safeHref(input)).toBe(expected))

  it.each([
    'javascript:alert(1)',
    'JaVaScRiPt:alert(1)',
    ' javascript:alert(1)',
    'data:text/html,<script>alert(1)</script>',
    'file:///etc/passwd',
    'vbscript:msgbox(1)',
    'ftp://x.org/a',
    '//evil.example/x',
    '/chemin/relatif',
    '',
    'pas une url',
  ])('refuse %j', (input) => expect(safeHref(input)).toBeNull())
})

describe('composeHint', () => {
  it('ne dit rien sur un champ vide', () => {
    expect(composeHint('   ')).toBeNull()
  })

  it('argument sans fait chiffré : information', () => {
    expect(composeHint('Je pense que la mesure est injuste.')).toMatchObject({ kind: 'info' })
  })

  it('chiffre sans source : avertissement prudent (« risque »)', () => {
    const hint = composeHint("L'inflation est de 12 % cette année.")
    expect(hint?.kind).toBe('warning')
    expect(hint?.text).toMatch(/risque/)
  })

  it.each([
    "Selon l'INSEE, l'inflation est de 2 %.",
    "D'après le rapport du COR, le déficit est de 10 milliards.",
    'Le Trésor estime 100 000 emplois menacés.',
    'Cette étude montre 15 % de hausse.',
    'La Cour des comptes cite 3 milliards.',
  ])('chiffre avec source reconnue : %s', (text) => expect(composeHint(text)?.kind).toBe('success'))

  it('reconnaît les mots accentués (régression : \\b JavaScript ignore les accents)', () => {
    expect(composeHint('Une étude récente existe.')?.kind).toBe('success')
    expect(composeHint('Le Trésor a publié une note.')?.kind).toBe('success')
  })

  it('ne confond pas un mot qui contient une source (« recorder » ne contient pas COR)', () => {
    expect(composeHint('Il faut 12 recorders.')?.kind).toBe('warning')
  })
})

describe('tons et formats', () => {
  it('chaque verdict a un style distinct pour VRAI / FAUX / À NUANCER', () => {
    const tones = (['VRAI', 'FAUX', 'À NUANCER', 'NON VÉRIFIABLE'] as const).map((v) => verdictTone(v).badge)
    expect(new Set(tones).size).toBe(4)
  })

  it('badgeTone retombe sur gris pour un type inconnu', () => {
    // @ts-expect-error valeur volontairement hors contrat
    expect(badgeTone('violet')).toEqual(badgeTone('gray'))
  })

  it('trustTone : seuils 75 / 50 et null neutre', () => {
    expect(trustTone(75).bar).toContain('emerald')
    expect(trustTone(74).bar).toContain('amber')
    expect(trustTone(50).bar).toContain('amber')
    expect(trustTone(49).bar).toContain('red')
    expect(trustTone(null).bar).toContain('neutral')
  })

  it('formatScore : null s’affiche « — », jamais 0', () => {
    expect(formatScore(null)).toBe('—')
    expect(formatScore(0)).toBe('0')
    expect(formatScore(78)).toBe('78')
  })

  it('themeBadge : thème inconnu -> repli neutre', () => {
    expect(themeBadge('inconnu')).toEqual(themeBadge('techno'))
    expect(themeBadge('social').name).toMatch(/sociale/)
  })

  it('formatTime : date invalide -> chaîne vide', () => {
    expect(formatTime('pas une date')).toBe('')
    expect(formatTime('2026-11-05T10:30:00+00:00')).toMatch(/\d{2}:\d{2}/)
  })
})
