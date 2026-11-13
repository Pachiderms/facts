/**
 * Génère le fichier `_headers` de Cloudflare Pages (en-têtes de sécurité et CSP).
 *
 * La CSP doit autoriser la connexion à l'API (HTTP et WebSocket), dont l'adresse dépend du
 * déploiement : elle est donc produite au build à partir de VITE_API_URL.
 */

/** @param {string} apiUrl */
export function apiOrigins(apiUrl) {
  let url
  try {
    url = new URL(apiUrl)
  } catch {
    throw new Error(`VITE_API_URL invalide : ${JSON.stringify(apiUrl)}`)
  }
  if (url.protocol !== 'https:' && url.protocol !== 'http:') {
    throw new Error('VITE_API_URL doit commencer par http:// ou https://')
  }
  const wsProtocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  return { http: url.origin, ws: `${wsProtocol}//${url.host}` }
}

/** @param {string} apiUrl */
export function buildHeaders(apiUrl) {
  const { http, ws } = apiOrigins(apiUrl)
  const csp = [
    "default-src 'self'",
    // « Se connecter avec Google » (Google Identity Services) : uniquement ces chemins précis, jamais tout le domaine.
    "script-src 'self' https://accounts.google.com/gsi/client",
    "style-src 'self' https://accounts.google.com/gsi/style",
    "style-src-attr 'unsafe-inline'", // largeur de la jauge (style={{ width }}) ; aucun style de page inline
    "img-src 'self' data:",
    `connect-src 'self' ${http} ${ws} https://accounts.google.com/gsi/`,
    'frame-src https://accounts.google.com/gsi/',
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join('; ')

  return `/*
  Content-Security-Policy: ${csp}
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: camera=(), microphone=(self), geolocation=()
  Strict-Transport-Security: max-age=31536000

/assets/*
  Cache-Control: public, max-age=31536000, immutable
`
}
