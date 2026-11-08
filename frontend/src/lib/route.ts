/** Routage par fragment (#/...) : fonctionne sur un hébergement statique sans règle de redirection. */
export type Route = { name: 'check' } | { name: 'arena' } | { name: 'room'; id: string; code?: string; watch?: true }

export const ROOM_ID_RE = /^[a-z0-9-]{1,64}$/
const INVITE_CODE_RE = /^[A-Za-z0-9]{1,16}$/

export function parseHash(hash: string): Route {
  const path = hash.replace(/^#/, '')
  if (path === '/arena' || path === '/arena/') return { name: 'arena' }
  const match = /^\/arena\/([^/?#]+)\/?(?:\?(.*))?$/.exec(path)
  if (match) {
    let id: string
    try {
      id = decodeURIComponent(match[1] ?? '').toLowerCase()
    } catch {
      return { name: 'arena' } // pourcentage mal formé
    }
    if (!ROOM_ID_RE.test(id)) return { name: 'arena' }
    // Lien d'invitation : `#/arena/<id>?code=<code>`. Le fragment n'est jamais envoyé au serveur.
    const params = new URLSearchParams(match[2] ?? '')
    const code = params.get('code')
    return {
      name: 'room',
      id,
      ...(code && INVITE_CODE_RE.test(code) ? { code } : {}),
      // `?watch=1` : entrer en spectateur sans prendre de siège d'intervenant.
      ...(params.get('watch') === '1' ? { watch: true as const } : {}),
    }
  }
  if (path.startsWith('/arena/')) return { name: 'arena' } // chemin inattendu sous /arena : la liste
  return { name: 'check' }
}

export const roomHref = (id: string, watch = false): string => `#/arena/${id}${watch ? '?watch=1' : ''}`

/** Lien à partager : adresse du site + salon (+ code pour un salon privé). */
export function inviteUrl(id: string, code?: string): string {
  const base = `${window.location.origin}${window.location.pathname}${roomHref(id)}`
  return code ? `${base}?code=${encodeURIComponent(code)}` : base
}
