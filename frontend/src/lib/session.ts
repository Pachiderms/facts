/**
 * Session de compte : un jeton opaque gardé dans le navigateur (localStorage), envoyé en en-tête `Authorization`.
 * Pas de cookie : le site et l'API sont sur deux domaines. Le jeton est révocable côté serveur (déconnexion,
 * « partout », suppression du compte). Sans stockage disponible, la session ne dure que le temps de la page.
 */
const KEY = 'facts.session'
export const SESSION_RE = /^[A-Za-z0-9_-]{43}$/

let memory: string | null = null

export function getSession(): string | null {
  try {
    const stored = localStorage.getItem(KEY)
    if (stored && SESSION_RE.test(stored)) return stored
    if (stored) localStorage.removeItem(KEY) // valeur étrangère ou corrompue
  } catch {
    /* stockage indisponible : repli mémoire */
  }
  return memory && SESSION_RE.test(memory) ? memory : null
}

export function setSession(token: string): void {
  if (!SESSION_RE.test(token)) return
  memory = token
  try {
    localStorage.setItem(KEY, token)
  } catch {
    /* mémoire seulement */
  }
}

export function clearSession(): void {
  memory = null
  try {
    localStorage.removeItem(KEY)
  } catch {
    /* rien à faire */
  }
}
