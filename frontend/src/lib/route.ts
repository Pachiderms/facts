/** Routage par fragment (#/...) : fonctionne sur un hébergement statique sans règle de redirection. */
export type LegalDoc = 'mentions' | 'confidentialite' | 'cgu'
export const LEGAL_PATHS: Record<LegalDoc, string> = { mentions: '/mentions-legales', confidentialite: '/confidentialite', cgu: '/cgu' }

export type Route =
  | { name: 'check' }
  | { name: 'arena' }
  | { name: 'pricing' }
  | { name: 'legal'; doc: LegalDoc }
  | { name: 'room'; id: string; code?: string; watch?: true }

export const ROOM_ID_RE = /^[a-z0-9-]{1,64}$/
const INVITE_CODE_RE = /^[A-Za-z0-9]{1,16}$/

export function parseHash(hash: string): Route {
  const path = hash.replace(/^#/, '')
  if (path === '/tarifs' || path === '/tarifs/') return { name: 'pricing' }
  for (const [doc, legalPath] of Object.entries(LEGAL_PATHS) as [LegalDoc, string][]) {
    if (path === legalPath || path === `${legalPath}/`) return { name: 'legal', doc }
  }
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

export const PRICING_HREF = '#/tarifs'
export const legalHref = (doc: LegalDoc): string => `#${LEGAL_PATHS[doc]}`
export const roomHref = (id: string, watch = false): string => `#/arena/${id}${watch ? '?watch=1' : ''}`

/** Lien à partager : adresse du site + salon (+ code pour un salon privé). */
export function inviteUrl(id: string, code?: string): string {
  const base = `${window.location.origin}${window.location.pathname}${roomHref(id)}`
  return code ? `${base}?code=${encodeURIComponent(code)}` : base
}

/**
 * Saisie « Rejoindre un salon » : un identifiant (`mon-salon`) ou un lien d'invitation collé tel quel
 * (`https://…/#/arena/mon-salon?code=AB12`). Renvoie `null` si rien d'exploitable.
 */
export function parseJoinInput(raw: string, codeField = ''): { id: string; code?: string } | null {
  const text = raw.trim()
  if (!text) return null
  let id: string
  let code: string | undefined
  const hashAt = text.indexOf('#')
  if (hashAt >= 0) {
    const route = parseHash(text.slice(hashAt))
    if (route.name !== 'room') return null
    id = route.id
    code = route.code
  } else {
    id = text.toLowerCase()
    if (!ROOM_ID_RE.test(id)) return null
  }
  const typed = codeField.trim()
  if (typed) {
    if (!INVITE_CODE_RE.test(typed)) return null
    code = typed.toUpperCase()
  }
  return code ? { id, code } : { id }
}
