import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TOKEN_RE, forgetCode, getParticipantToken, recallCode, rememberCode } from '../src/lib/identity'

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
})
afterEach(() => vi.restoreAllMocks())

describe('getParticipantToken', () => {
  it('génère un jeton conforme au contrat serveur et le garde', () => {
    const token = getParticipantToken()
    expect(token).toMatch(TOKEN_RE)
    expect(getParticipantToken()).toBe(token)
    expect(localStorage.getItem('facts.participant')).toBe(token)
  })

  it('deux navigateurs vierges n’ont pas le même jeton (aléatoire)', () => {
    const first = getParticipantToken()
    localStorage.clear()
    expect(getParticipantToken()).not.toBe(first)
  })

  it.each(['court', 'a b '.repeat(10), '<script>alert(1)</script>', 'é'.repeat(30)])('remplace un jeton stocké invalide : %s', (bad) => {
    localStorage.setItem('facts.participant', bad)
    const token = getParticipantToken()
    expect(token).not.toBe(bad)
    expect(token).toMatch(TOKEN_RE)
  })

  it('stockage indisponible : jeton valide, stable le temps de la page, sans planter', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('bloqué')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('bloqué')
    })
    const token = getParticipantToken()
    expect(token).toMatch(TOKEN_RE)
    expect(getParticipantToken()).toBe(token)
  })
})

describe('code d’accès mémorisé', () => {
  it('survit au rechargement de l’onglet (sessionStorage), par salon', () => {
    rememberCode('abcd2345', 'k7m2xq')
    expect(recallCode('abcd2345')).toBe('k7m2xq')
    expect(recallCode('autre-salon')).toBeUndefined()
    expect(localStorage.length).toBe(0) // jamais conservé au-delà de l'onglet
  })

  it('un code refusé peut être oublié', () => {
    rememberCode('abcd2345', 'faux')
    forgetCode('abcd2345')
    expect(recallCode('abcd2345')).toBeUndefined()
  })

  it('stockage indisponible : aucune exception', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('bloqué')
    })
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('bloqué')
    })
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new Error('bloqué')
    })
    expect(() => rememberCode('a', 'b')).not.toThrow()
    expect(recallCode('a')).toBeUndefined()
    expect(() => forgetCode('a')).not.toThrow()
  })
})
