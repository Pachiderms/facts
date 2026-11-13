import { describe, expect, it } from 'vitest'
import { parseHash, parseJoinInput, roomHref } from '../src/lib/route'

describe('parseHash', () => {
  it.each([
    ['', { name: 'check' }],
    ['#/check', { name: 'check' }],
    ['#/inconnu', { name: 'check' }],
    ['#/arena', { name: 'arena' }],
    ['#/arena/', { name: 'arena' }],
    ['#/arena/room-1', { name: 'room', id: 'room-1' }],
    ['#/arena/abcd2345/', { name: 'room', id: 'abcd2345' }],
    ['#/arena/ABCD2345', { name: 'room', id: 'abcd2345' }], // casse ignorée : l'ID serveur est en minuscules
  ])('%s', (hash, expected) => expect(parseHash(hash)).toEqual(expected))

  it.each([
    '#/arena/%E0%A4%A', // pourcentage mal formé
    '#/arena/a b',
    '#/arena/../etc',
    '#/arena/<script>',
    '#/arena/a/b',
    `#/arena/${'a'.repeat(65)}`,
    '#/arena/%00',
  ])('identifiant invalide ou hostile -> retour à la liste : %s', (hash) => {
    expect(parseHash(hash)).toEqual({ name: 'arena' })
  })

  it('roomHref et parseHash sont inverses', () => {
    expect(parseHash(roomHref('abcd2345'))).toEqual({ name: 'room', id: 'abcd2345' })
  })
})

describe('lien d’invitation', () => {
  it('lit le code d’un salon privé depuis ?code=', () => {
    expect(parseHash('#/arena/abcd2345?code=k7m2xq')).toEqual({ name: 'room', id: 'abcd2345', code: 'k7m2xq' })
  })

  it('ignore un code hostile', () => {
    expect(parseHash('#/arena/abcd2345?code=<script>')).toEqual({ name: 'room', id: 'abcd2345' })
  })

  it('inviteUrl contient le code uniquement s’il est fourni', async () => {
    const { inviteUrl } = await import('../src/lib/route')
    expect(inviteUrl('abcd2345')).toMatch(/#\/arena\/abcd2345$/)
    expect(inviteUrl('abcd2345', 'k7m2xq')).toMatch(/#\/arena\/abcd2345\?code=k7m2xq$/)
  })
})

describe('mode spectateur (?watch=1)', () => {
  it('lit watch, avec ou sans code', () => {
    expect(parseHash('#/arena/abcd2345?watch=1')).toEqual({ name: 'room', id: 'abcd2345', watch: true })
    expect(parseHash('#/arena/abcd2345?code=k7m2xq&watch=1')).toEqual({ name: 'room', id: 'abcd2345', code: 'k7m2xq', watch: true })
  })
  it('toute autre valeur est ignorée', () => {
    expect(parseHash('#/arena/abcd2345?watch=0')).toEqual({ name: 'room', id: 'abcd2345' })
    expect(parseHash('#/arena/abcd2345?watch=<x>')).toEqual({ name: 'room', id: 'abcd2345' })
  })
  it('roomHref construit le lien spectateur', async () => {
    const { roomHref } = await import('../src/lib/route')
    expect(roomHref('abcd2345', true)).toBe('#/arena/abcd2345?watch=1')
    expect(roomHref('abcd2345')).toBe('#/arena/abcd2345')
  })
})

describe('parseJoinInput (Rejoindre un salon)', () => {
  it.each([
    ['mon-salon', '', { id: 'mon-salon' }],
    ['  Mon-Salon  ', '', { id: 'mon-salon' }],
    ['mon-salon', 'ab12', { id: 'mon-salon', code: 'AB12' }],
    ['https://cafaitdebat.fr/#/arena/mon-salon', '', { id: 'mon-salon' }],
    ['https://cafaitdebat.fr/#/arena/mon-salon?code=Zx9', '', { id: 'mon-salon', code: 'Zx9' }],
    ['https://cafaitdebat.fr/#/arena/mon-salon?code=Zx9', 'k7', { id: 'mon-salon', code: 'K7' }], // le champ code prime
  ])('%j + %j', (raw, code, expected) => expect(parseJoinInput(raw, code)).toEqual(expected))

  it.each([
    ['', ''],
    ['   ', ''],
    ['mon salon', ''], // espace
    ['MON_SALON', ''], // underscore
    ['../etc/passwd', ''],
    ['<script>alert(1)</script>', ''],
    ['a'.repeat(65), ''],
    ['mon-salon', 'pas valide!'], // code avec caractères interdits
    ['mon-salon', 'a'.repeat(17)],
    ['https://exemple.fr/#/autre/chose', ''], // lien qui n'est pas un salon
    ['https://exemple.fr/#/arena', ''], // liste, pas un salon
  ])('refuse %j (code %j)', (raw, code) => expect(parseJoinInput(raw, code)).toBeNull())
})
