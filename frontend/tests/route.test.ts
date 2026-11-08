import { describe, expect, it } from 'vitest'
import { parseHash, roomHref } from '../src/lib/route'

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
