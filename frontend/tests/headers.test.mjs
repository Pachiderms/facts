import { describe, expect, it } from 'vitest'
import { apiOrigins, buildHeaders } from '../scripts/headers.mjs'

describe('apiOrigins', () => {
  it('dérive l’origine HTTP et WebSocket (https -> wss)', () => {
    expect(apiOrigins('https://facts-api.onrender.com/')).toEqual({
      http: 'https://facts-api.onrender.com',
      ws: 'wss://facts-api.onrender.com',
    })
  })

  it('http -> ws, en conservant le port', () => {
    expect(apiOrigins('http://localhost:8000')).toEqual({ http: 'http://localhost:8000', ws: 'ws://localhost:8000' })
  })

  it.each(['', 'pas une url', 'javascript:alert(1)', 'ftp://x.org', 'data:text/html,x'])('refuse %j', (value) => {
    expect(() => apiOrigins(value)).toThrow()
  })
})

describe('buildHeaders', () => {
  const headers = buildHeaders('https://api.example.com')

  it('autorise la connexion à l’API et à son WebSocket, et à rien d’autre', () => {
    expect(headers).toContain("connect-src 'self' https://api.example.com wss://api.example.com")
    expect(headers).not.toMatch(/connect-src[^;]*\*/)
  })

  it('verrouille les scripts, les objets, les cadres et la base', () => {
    expect(headers).toContain("script-src 'self'")
    expect(headers).not.toMatch(/script-src[^;]*unsafe/)
    expect(headers).toContain("object-src 'none'")
    expect(headers).toContain("frame-ancestors 'none'")
    expect(headers).toContain("base-uri 'self'")
    expect(headers).toContain("default-src 'self'")
  })

  it('n’autorise les styles inline que pour les attributs (jauge), pas pour les feuilles', () => {
    expect(headers).toMatch(/style-src 'self'(;|\s)/)
    expect(headers).toContain("style-src-attr 'unsafe-inline'")
  })

  it('autorise le micro uniquement pour le site lui-même (saisie vocale), jamais la caméra', () => {
    expect(headers).toMatch(/Permissions-Policy: [^\n]*microphone=\(self\)/)
    expect(headers).toMatch(/Permissions-Policy: [^\n]*camera=\(\)/)
  })

  it('ajoute les en-têtes de durcissement et le cache des assets', () => {
    for (const h of ['X-Content-Type-Options: nosniff', 'X-Frame-Options: DENY', 'Referrer-Policy:', 'Permissions-Policy:', 'Strict-Transport-Security:']) {
      expect(headers).toContain(h)
    }
    expect(headers).toMatch(/\/assets\/\*\s+Cache-Control: public, max-age=31536000, immutable/)
  })

  it('ne laisse pas une valeur malveillante casser la CSP (retours à la ligne, point-virgule)', () => {
    const evil = buildHeaders('https://api.example.com/\nX-Evil: 1;script-src *')
    expect(evil).not.toContain('X-Evil')
    expect(evil).toContain("script-src 'self'")
  })
})

describe('CSP et connexion Google', () => {
  const csp = () => {
    const out = buildHeaders('https://facts-api-eu.onrender.com')
    return Object.fromEntries(
      out
        .match(/Content-Security-Policy: (.*)/)[1]
        .split('; ')
        .map((d) => [d.split(' ')[0], d.split(' ').slice(1)]),
    )
  }

  it('autorise Google Identity Services uniquement sur ses chemins précis', () => {
    const c = csp()
    expect(c['script-src']).toEqual(["'self'", 'https://accounts.google.com/gsi/client'])
    expect(c['style-src']).toEqual(["'self'", 'https://accounts.google.com/gsi/style'])
    expect(c['frame-src']).toEqual(['https://accounts.google.com/gsi/'])
    expect(c['connect-src']).toContain('https://accounts.google.com/gsi/')
  })

  it('n’ouvre aucun joker : pas de unsafe-inline/eval dans les scripts, pas de domaine Google entier', () => {
    const out = buildHeaders('https://facts-api-eu.onrender.com')
    expect(csp()['script-src'].join(' ')).not.toMatch(/unsafe-inline|unsafe-eval|\*/)
    expect(out).not.toMatch(/https:\/\/\*\.google|https:\/\/accounts\.google\.com[ ;]/)
    expect(csp()['frame-ancestors']).toEqual(["'none'"])
  })
})
