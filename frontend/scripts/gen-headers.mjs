import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { buildHeaders } from './headers.mjs'

/** Lit VITE_API_URL dans l'environnement, sinon dans .env.production / .env.local / .env. */
function resolveApiUrl() {
  if (process.env.VITE_API_URL) return process.env.VITE_API_URL
  for (const file of ['.env.production.local', '.env.production', '.env.local', '.env']) {
    if (!existsSync(file)) continue
    const match = readFileSync(file, 'utf8').match(/^VITE_API_URL=(.+)$/m)
    if (match) return match[1].trim().replace(/^["']|["']$/g, '')
  }
  return undefined
}

const apiUrl = resolveApiUrl()
if (!apiUrl) {
  console.error('VITE_API_URL est absente : impossible de générer une CSP correcte (définissez-la pour le build).')
  process.exit(1)
}

writeFileSync('dist/_headers', buildHeaders(apiUrl))
console.log(`dist/_headers généré (API autorisée : ${new URL(apiUrl).origin})`)
