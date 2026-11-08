/** Routage par fragment (#/...) : fonctionne sur un hébergement statique sans règle de redirection. */
export type Route = { name: 'check' } | { name: 'arena' } | { name: 'room'; id: string }

export const ROOM_ID_RE = /^[a-z0-9-]{1,64}$/

export function parseHash(hash: string): Route {
  const path = hash.replace(/^#/, '')
  if (path === '/arena' || path === '/arena/') return { name: 'arena' }
  const match = /^\/arena\/([^/?#]+)\/?$/.exec(path)
  if (match) {
    let id: string
    try {
      id = decodeURIComponent(match[1] ?? '').toLowerCase()
    } catch {
      return { name: 'arena' } // pourcentage mal formé
    }
    return ROOM_ID_RE.test(id) ? { name: 'room', id } : { name: 'arena' }
  }
  if (path.startsWith('/arena/')) return { name: 'arena' } // chemin inattendu sous /arena : la liste
  return { name: 'check' }
}

export const roomHref = (id: string): string => `#/arena/${id}`
