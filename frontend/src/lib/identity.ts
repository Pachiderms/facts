/**
 * Identité anonyme : un jeton aléatoire gardé dans le navigateur (jamais affiché, jamais dans l'URL).
 * Le serveur n'en conserve qu'une empreinte : il désigne le propriétaire d'un salon et empêche une
 * même personne d'occuper deux sièges. Vider le navigateur crée une nouvelle identité.
 */
const TOKEN_KEY = 'facts.participant'
export const TOKEN_RE = /^[A-Za-z0-9_-]{22,64}$/

let memoryToken: string | null = null

function generateToken(): string {
  const bytes = new Uint8Array(24) // 24 octets -> 32 caractères base64url
  crypto.getRandomValues(bytes)
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '')
}

export function getParticipantToken(): string {
  try {
    const stored = localStorage.getItem(TOKEN_KEY)
    if (stored && TOKEN_RE.test(stored)) return stored
    const fresh = generateToken()
    localStorage.setItem(TOKEN_KEY, fresh)
    return fresh
  } catch {
    // Stockage indisponible (navigation privée, blocage) : identité valable pour cette page seulement.
    return (memoryToken ??= generateToken())
  }
}

/** Code d'un salon privé : gardé le temps de l'onglet pour survivre à un rechargement. */
const codeKey = (roomId: string) => `facts.code.${roomId}`

export function rememberCode(roomId: string, code: string): void {
  try {
    sessionStorage.setItem(codeKey(roomId), code)
  } catch {
    /* sans stockage : le code sera redemandé */
  }
}

export function recallCode(roomId: string): string | undefined {
  try {
    return sessionStorage.getItem(codeKey(roomId)) ?? undefined
  } catch {
    return undefined
  }
}

export function forgetCode(roomId: string): void {
  try {
    sessionStorage.removeItem(codeKey(roomId))
  } catch {
    /* rien à faire */
  }
}
