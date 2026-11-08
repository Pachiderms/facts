import { beforeEach, describe, expect, it } from 'vitest'
import { HISTORY_MAX, historyCode, loadHistory, recordVisit, removeEntry, togglePin } from '../src/lib/history'

const visit = (id: string, extra = {}) => ({ id, title: `Salon ${id}`, visibility: 'public' as const, ...extra })

beforeEach(() => localStorage.clear())

describe('historique « Mes salons »', () => {
  it('enregistre, remonte la dernière visite en tête et ne duplique pas', () => {
    recordVisit(visit('aaaa2222'), 1)
    recordVisit(visit('bbbb2222'), 2)
    recordVisit(visit('aaaa2222'), 3)
    expect(loadHistory().map((e) => e.id)).toEqual(['aaaa2222', 'bbbb2222'])
  })

  it('garde le code d’un salon privé sur l’appareil, et le statut de créateur', () => {
    recordVisit(visit('aaaa2222', { visibility: 'private', code: 'k7m2xq', owner: true }), 1)
    recordVisit(visit('aaaa2222', { visibility: 'private' }), 2) // revisite sans code : on le garde
    expect(historyCode('aaaa2222')).toBe('k7m2xq')
    expect(loadHistory()[0]!.owner).toBe(true)
  })

  it('un salon public ne stocke jamais de code', () => {
    recordVisit(visit('aaaa2222', { code: 'k7m2xq' }), 1)
    expect(historyCode('aaaa2222')).toBeUndefined()
  })

  it('épingler fait passer devant ; retirer supprime', () => {
    recordVisit(visit('aaaa2222'), 1)
    recordVisit(visit('bbbb2222'), 2)
    togglePin('aaaa2222')
    expect(loadHistory().map((e) => e.id)).toEqual(['aaaa2222', 'bbbb2222'])
    removeEntry('aaaa2222')
    expect(loadHistory().map((e) => e.id)).toEqual(['bbbb2222'])
  })

  it(`limité à ${HISTORY_MAX} entrées : les plus anciennes non épinglées partent d’abord`, () => {
    recordVisit(visit('pinned22'), 0)
    togglePin('pinned22')
    for (let i = 1; i <= HISTORY_MAX + 3; i++) recordVisit(visit(`room${i}`), i)
    const ids = loadHistory().map((e) => e.id)
    expect(ids).toHaveLength(HISTORY_MAX)
    expect(ids).toContain('pinned22')
    expect(ids).not.toContain('room1')
  })

  it('stockage corrompu ou piégé : jamais d’exception, entrées invalides ignorées', () => {
    localStorage.setItem('facts.history', '{pas du json')
    expect(loadHistory()).toEqual([])
    localStorage.setItem(
      'facts.history',
      JSON.stringify([
        { id: '../etc', title: 'x', visibility: 'public', lastVisit: 1 },
        { id: 'aaaa2222', title: 'ok', visibility: 'private', code: '<script>', lastVisit: 1 },
        { id: 'bbbb2222', title: '', visibility: 'public', lastVisit: 1 },
        'nimporte quoi',
      ]),
    )
    const entries = loadHistory()
    expect(entries.map((e) => e.id)).toEqual(['aaaa2222'])
    expect(entries[0]!.code).toBeUndefined()
  })
})
