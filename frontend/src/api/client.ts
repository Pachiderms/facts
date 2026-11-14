import { getParticipantToken } from '../lib/identity'
import { getSession } from '../lib/session'
import { CREATABLE_THEMES } from '../lib/presentation'
import { ROOM_TITLE_MAX, ROOM_TITLE_MIN, type CheckResponse, type CreatedRoom, type CreateRoomInput, type RoomLookup, type RoomSummary, type Verdict } from './types'

/** Erreur d'API déjà formulée en français pour l'utilisateur : jamais de détail technique. */
export class ApiError extends Error {
  readonly status: number
  readonly retryAfter: number | null

  constructor(status: number, message: string, retryAfter: number | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.retryAfter = retryAfter
  }
}

const DEFAULT_API_URL = 'http://localhost:8000'
/** Un démarrage à froid d'un hébergeur gratuit peut durer environ une minute. */
const CHECK_TIMEOUT_MS = 90_000

export function apiBase(): string {
  const raw = (import.meta.env.VITE_API_URL as string | undefined) || DEFAULT_API_URL
  return raw.replace(/\/+$/, '')
}

export function wsBase(): string {
  return apiBase().replace(/^http/i, 'ws')
}

const VERDICTS: readonly Verdict[] = ['VRAI', 'FAUX', 'À NUANCER', 'NON VÉRIFIABLE']

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null

function isView(v: unknown): boolean {
  return isRecord(v) && typeof v.title === 'string' && Array.isArray(v.points) && v.points.every((p) => typeof p === 'string')
}

/** Garde-fou : une réponse hors contrat produit une erreur claire plutôt qu'un écran cassé. */
export function isCheckResponse(v: unknown): v is CheckResponse {
  return (
    isRecord(v) &&
    VERDICTS.includes(v.verdict as Verdict) &&
    typeof v.confidence_score === 'number' &&
    typeof v.summary === 'string' &&
    isView(v.liberal_institutional_view) &&
    isView(v.heterodox_social_view) &&
    Array.isArray(v.verified_sources) &&
    v.verified_sources.every(
      (s) =>
        isRecord(s) &&
        typeof s.title === 'string' &&
        typeof s.url === 'string' &&
        typeof s.domain === 'string' &&
        typeof s.trust_score === 'number',
    )
  )
}

const FALLBACK_MESSAGES: Record<number, string> = {
  413: 'La requête est trop volumineuse.',
  429: 'Trop de requêtes. Réessayez dans un instant.',
  502: "L'analyse est momentanément indisponible. Réessayez dans un instant.",
  503: 'Service momentanément saturé. Réessayez plus tard.',
}

async function toApiError(
  response: Response,
  invalidMessage = 'Affirmation invalide : saisissez entre 10 et 500 caractères.',
): Promise<ApiError> {
  const retry = Number(response.headers.get('retry-after'))
  const retryAfter = Number.isFinite(retry) && retry > 0 ? retry : null
  let detail: unknown
  try {
    detail = ((await response.json()) as { detail?: unknown }).detail
  } catch {
    /* corps non JSON : message de repli */
  }
  // Les `detail` en chaîne viennent de nos messages serveur (génériques). Un `detail` en liste
  // est une erreur de validation Pydantic : technique, donc remplacée par un message clair.
  if (response.status === 422 && typeof detail !== 'string') {
    return new ApiError(422, invalidMessage)
  }
  const message =
    (typeof detail === 'string' && detail) || FALLBACK_MESSAGES[response.status] || 'Une erreur est survenue. Réessayez.'
  return new ApiError(response.status, message, retryAfter)
}

async function request(path: string, init: RequestInit, timeoutMs: number): Promise<Response> {
  const controller = new AbortController()
  const external = init.signal
  const onExternalAbort = () => controller.abort()
  external?.addEventListener('abort', onExternalAbort)
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch(`${apiBase()}${path}`, { ...init, signal: controller.signal })
  } catch {
    if (external?.aborted) throw new DOMException('Annulé', 'AbortError')
    throw new ApiError(0, controller.signal.aborted ? "Le serveur met trop de temps à répondre. Réessayez." : 'Serveur injoignable. Vérifiez votre connexion.')
  } finally {
    clearTimeout(timer)
    external?.removeEventListener('abort', onExternalAbort)
  }
}

export async function checkAssertion(
  assertion: string,
  institutionalFilter: boolean,
  signal?: AbortSignal,
): Promise<CheckResponse> {
  const response = await request(
    '/api/v1/check',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...quotaHeaders() }, // compte : quota par compte, suivi par navigateur
      body: JSON.stringify({ assertion, institutional_filter: institutionalFilter }),
      signal,
    },
    CHECK_TIMEOUT_MS,
  )
  if (!response.ok) throw await toApiError(response)
  const data: unknown = await response.json().catch(() => null)
  if (!isCheckResponse(data)) throw new ApiError(502, 'Réponse inattendue du serveur.')
  return data
}

const isVisibility = (v: unknown): v is 'public' | 'private' => v === 'public' || v === 'private'

export function isRoomSummary(v: unknown): v is RoomSummary {
  return (
    isRecord(v) &&
    typeof v.id === 'string' &&
    typeof v.title === 'string' &&
    typeof v.category === 'string' &&
    typeof v.theme_category === 'string' &&
    isVisibility(v.visibility) &&
    typeof v.max_participants === 'number' &&
    typeof v.spectators_allowed === 'boolean' &&
    (v.trust_score === null || typeof v.trust_score === 'number') &&
    typeof v.message_count === 'number' &&
    typeof v.participants === 'number' &&
    typeof v.spectators === 'number'
  )
}

const BAD_RESPONSE = () => new ApiError(502, 'Réponse inattendue du serveur.')

export async function listRooms(query = '', signal?: AbortSignal): Promise<RoomSummary[]> {
  const q = query.trim()
  const path = q ? `/api/v1/rooms?q=${encodeURIComponent(q.slice(0, 60))}` : '/api/v1/rooms'
  const response = await request(path, { signal }, 20_000)
  if (!response.ok) throw await toApiError(response)
  const data: unknown = await response.json().catch(() => null)
  if (!Array.isArray(data) || !data.every(isRoomSummary)) throw BAD_RESPONSE()
  return data
}

/** Recherche par ID. 404 si inconnu. Un salon privé répond seulement `requires_code`. */
export async function lookupRoom(id: string, signal?: AbortSignal): Promise<RoomLookup> {
  const response = await request(`/api/v1/rooms/${encodeURIComponent(id)}`, { signal }, 20_000)
  if (!response.ok) throw await toApiError(response)
  const data: unknown = await response.json().catch(() => null)
  if (
    !isRecord(data) ||
    typeof data.id !== 'string' ||
    !isVisibility(data.visibility) ||
    typeof data.requires_code !== 'boolean' ||
    !(data.room === null || isRoomSummary(data.room))
  ) {
    throw BAD_RESPONSE()
  }
  return data as unknown as RoomLookup
}

export async function createRoom(input: CreateRoomInput, signal?: AbortSignal): Promise<CreatedRoom> {
  const response = await request(
    '/api/v1/rooms',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...optionalAuth() },
      body: JSON.stringify({ ...input, participant_token: getParticipantToken() }),
      signal,
    },
    30_000,
  )
  if (!response.ok) throw await toApiError(response, 'Titre ou thème invalide : le titre doit faire entre 10 et 120 caractères.')
  const data: unknown = await response.json().catch(() => null)
  if (
    !isRecord(data) ||
    typeof data.id !== 'string' ||
    !isVisibility(data.visibility) ||
    !(data.access_code === null || typeof data.access_code === 'string')
  ) {
    throw BAD_RESPONSE()
  }
  return data as unknown as CreatedRoom
}

export interface Reformulation {
  title: string
  theme_category: string
}

/** L'IA propose une question neutre et un thème. Un refus (sujet illégal, hors débat) arrive en 422 avec sa raison. */
export async function reformulateTitle(title: string, signal?: AbortSignal): Promise<Reformulation> {
  const response = await request(
    '/api/v1/rooms/reformulate',
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }), signal },
    30_000,
  )
  if (!response.ok) throw await toApiError(response, 'Sujet invalide : saisissez entre 1 et 400 caractères.')
  const data: unknown = await response.json().catch(() => null)
  // La réponse est revalidée : thème dans la liste connue, titre de taille raisonnable.
  if (
    !isRecord(data) ||
    typeof data.title !== 'string' ||
    data.title.length < ROOM_TITLE_MIN ||
    data.title.length > ROOM_TITLE_MAX ||
    typeof data.theme_category !== 'string' ||
    !(CREATABLE_THEMES as readonly string[]).includes(data.theme_category)
  ) {
    throw BAD_RESPONSE()
  }
  return { title: data.title, theme_category: data.theme_category }
}

/** Parmi ces salons (historique), lesquels existent encore ? Une seule requête pour toute la liste. */
export async function roomsStatus(ids: string[], signal?: AbortSignal): Promise<string[]> {
  if (ids.length === 0) return []
  const response = await request(`/api/v1/rooms/status?ids=${encodeURIComponent(ids.join(','))}`, { signal }, 20_000)
  if (!response.ok) throw await toApiError(response)
  const data: unknown = await response.json().catch(() => null)
  if (!isRecord(data) || !Array.isArray(data.existing) || !data.existing.every((i) => typeof i === 'string')) throw BAD_RESPONSE()
  return data.existing as string[]
}

/** Suppression par le créateur (le serveur refuse si d'autres personnes sont connectées). */
export async function deleteRoom(id: string, signal?: AbortSignal): Promise<void> {
  const response = await request(
    `/api/v1/rooms/${encodeURIComponent(id)}/delete`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...optionalAuth() },
      body: JSON.stringify({ participant_token: getParticipantToken() }),
      signal,
    },
    20_000,
  )
  if (!response.ok) throw await toApiError(response)
}

/** Réveille un hébergeur gratuit en veille dès l'ouverture de l'application (réponse ignorée). */
export function warmUp(): void {
  void fetch(`${apiBase()}/health`).catch(() => undefined)
}

export interface Features {
  voice: boolean
  accounts: boolean
  /** Identifiant client Google : PUBLIC (il figure dans le bouton de connexion), jamais un secret. */
  googleClientId: string | null
}

const NO_FEATURES: Features = { voice: false, accounts: false, googleClientId: null }

/** Fonctions optionnelles du serveur. Toute erreur = fonction absente : l'interface se replie sur le texte. */
export async function fetchFeatures(signal?: AbortSignal): Promise<Features> {
  try {
    const response = await request('/api/v1/features', { signal }, 10_000)
    const data: unknown = response.ok ? await response.json().catch(() => null) : null
    if (!isRecord(data)) return NO_FEATURES
    const id = typeof data.google_client_id === 'string' && data.google_client_id ? data.google_client_id : null
    return { voice: data.voice === true, accounts: data.accounts === true && id !== null, googleClientId: id }
  } catch {
    return NO_FEATURES
  }
}

let featuresPromise: Promise<Features> | null = null

/** Une seule requête par chargement de page, partagée par tous les composants. Un échec n'est pas mémorisé. */
export function getFeatures(): Promise<Features> {
  featuresPromise ??= fetchFeatures().then((f) => {
    if (f === NO_FEATURES) featuresPromise = null
    return f
  })
  return featuresPromise
}

export function resetFeaturesCache(): void {
  featuresPromise = null
}

const TRANSCRIBE_TIMEOUT_MS = 40_000

/** Envoie l'enregistrement (audio brut) et renvoie le texte transcrit. L'audio n'est jamais conservé côté serveur. */
export async function transcribeAudio(audio: Blob, signal?: AbortSignal): Promise<string> {
  const response = await request(
    '/api/v1/transcribe',
    {
      method: 'POST',
      headers: { 'Content-Type': audio.type || 'audio/webm', 'X-Participant-Token': getParticipantToken() },
      body: audio,
      signal,
    },
    TRANSCRIBE_TIMEOUT_MS,
  )
  if (!response.ok) throw await toApiError(response, 'Enregistrement invalide.')
  const data: unknown = await response.json().catch(() => null)
  if (!isRecord(data) || typeof data.text !== 'string' || !data.text.trim()) throw BAD_RESPONSE()
  return data.text
}

// ---------- comptes (facultatifs) ----------
export interface AccountUser {
  id: string
  email: string
  created_at: string
}

const authHeader = (token: string) => ({ Authorization: `Bearer ${token}` })

/** Session éventuelle : le serveur rattache alors le salon (création, suppression) au compte. */
function optionalAuth(): Record<string, string> {
  const token = getSession()
  return token ? authHeader(token) : {}
}

/** Session éventuelle + jeton du navigateur : le quota suit la personne entre anonyme et compte. */
function quotaHeaders(): Record<string, string> {
  return { ...optionalAuth(), 'X-Participant-Token': getParticipantToken() }
}

const isUser = (v: unknown): v is AccountUser =>
  isRecord(v) && typeof v.id === 'string' && typeof v.email === 'string' && typeof v.created_at === 'string'

const SESSION_RE = /^[A-Za-z0-9_-]{43}$/

/** Échange le jeton Google contre une session. Le jeton anonyme est rattaché au compte (historique conservé). */
export async function loginWithGoogle(credential: string): Promise<{ sessionToken: string; user: AccountUser }> {
  const response = await request(
    '/api/v1/auth/google',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ credential, participant_token: getParticipantToken() }),
    },
    20_000,
  )
  if (!response.ok) throw await toApiError(response, 'Connexion impossible. Réessayez.')
  const data: unknown = await response.json().catch(() => null)
  if (!isRecord(data) || typeof data.session_token !== 'string' || !SESSION_RE.test(data.session_token) || !isUser(data.user)) {
    throw BAD_RESPONSE()
  }
  return { sessionToken: data.session_token, user: data.user }
}

export async function fetchMe(token: string, signal?: AbortSignal): Promise<AccountUser> {
  const response = await request('/api/v1/auth/me', { headers: authHeader(token), signal }, 20_000)
  if (!response.ok) throw await toApiError(response)
  const data: unknown = await response.json().catch(() => null)
  if (!isRecord(data) || !isUser(data.user)) throw BAD_RESPONSE()
  return data.user
}

async function authPost(path: string, token: string, body?: unknown): Promise<unknown> {
  const response = await request(
    path,
    {
      method: 'POST',
      headers: { ...authHeader(token), ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
      body: body === undefined ? undefined : JSON.stringify(body),
    },
    20_000,
  )
  if (!response.ok) throw await toApiError(response)
  return response.json().catch(() => null)
}

export const logoutSession = (token: string) => authPost('/api/v1/auth/logout', token)
export const logoutEverywhere = (token: string) => authPost('/api/v1/auth/logout-all', token)
export const deleteAccount = (token: string) => authPost('/api/v1/auth/delete', token, { confirm: true })

/** Toutes les données conservées sur le compte, en JSON (droit d'accès). */
export async function exportAccount(token: string): Promise<Blob> {
  const response = await request('/api/v1/auth/export', { headers: authHeader(token) }, 20_000)
  if (!response.ok) throw await toApiError(response)
  return new Blob([await response.text()], { type: 'application/json' })
}

/** Entrée de l'historique côté serveur (jamais de code d'accès). */
export interface RemoteHistoryEntry {
  id: string
  title: string
  visibility: 'public' | 'private'
  owner: boolean
  pinned: boolean
  lastVisit: number
}

function parseRemoteHistory(data: unknown): RemoteHistoryEntry[] {
  if (!isRecord(data) || !Array.isArray(data.entries)) throw BAD_RESPONSE()
  return data.entries.flatMap((e: unknown) =>
    isRecord(e) &&
    typeof e.id === 'string' &&
    typeof e.title === 'string' &&
    isVisibility(e.visibility) &&
    typeof e.owner === 'boolean' &&
    typeof e.pinned === 'boolean' &&
    typeof e.lastVisit === 'number'
      ? [{ id: e.id, title: e.title, visibility: e.visibility, owner: e.owner, pinned: e.pinned, lastVisit: e.lastVisit }]
      : [],
  )
}

export async function fetchHistory(token: string, signal?: AbortSignal): Promise<RemoteHistoryEntry[]> {
  const response = await request('/api/v1/me/history', { headers: authHeader(token), signal }, 20_000)
  if (!response.ok) throw await toApiError(response)
  return parseRemoteHistory(await response.json().catch(() => null))
}

export async function pushHistory(token: string, entries: RemoteHistoryEntry[], signal?: AbortSignal): Promise<RemoteHistoryEntry[]> {
  const response = await request(
    '/api/v1/me/history',
    { method: 'POST', headers: { ...authHeader(token), 'Content-Type': 'application/json' }, body: JSON.stringify({ entries }), signal },
    20_000,
  )
  if (!response.ok) throw await toApiError(response)
  return parseRemoteHistory(await response.json().catch(() => null))
}

export interface Usage {
  plan: 'anonymous' | 'free' | 'pro' | 'edu'
  checks: { used: number; limit: number; remaining: number }
  /** Messages de débat vérifiés (budget distinct de celui du chatbot). */
  debate: { used: number; limit: number; remaining: number }
  /** Le service tourne avec un modèle de secours ou à capacité réduite. */
  degraded: boolean
}

export async function fetchUsage(signal?: AbortSignal): Promise<Usage> {
  const response = await request('/api/v1/usage', { headers: quotaHeaders(), signal }, 15_000)
  if (!response.ok) throw await toApiError(response)
  const d: unknown = await response.json().catch(() => null)
  const c = isRecord(d) && isRecord(d.checks) ? d.checks : null
  const b = isRecord(d) && isRecord(d.debate) ? d.debate : null
  const isCount = (v: Record<string, unknown>) => typeof v.used === 'number' && typeof v.limit === 'number' && typeof v.remaining === 'number'
  if (
    !isRecord(d) ||
    !c ||
    !b ||
    !isCount(b) ||
    (d.plan !== 'anonymous' && d.plan !== 'free' && d.plan !== 'pro' && d.plan !== 'edu') ||
    typeof d.degraded !== 'boolean' ||
    typeof c.used !== 'number' ||
    typeof c.limit !== 'number' ||
    typeof c.remaining !== 'number'
  ) {
    throw BAD_RESPONSE()
  }
  return {
    plan: d.plan,
    checks: { used: c.used, limit: c.limit, remaining: c.remaining },
    debate: { used: b.used as number, limit: b.limit as number, remaining: b.remaining as number },
    degraded: d.degraded,
  }
}

// ---------- abonnement Pro ----------
export interface Billing {
  /** Le paiement est ouvert (sinon : « bientôt disponible »). */
  enabled: boolean
  priceLabel: string
  plan: 'free' | 'pro'
  status: string | null
  currentPeriodEnd: string | null
  /** Lien du prestataire pour gérer / résilier l'abonnement (https uniquement). */
  portalUrl: string | null
}

const isHttps = (v: unknown): v is string => typeof v === 'string' && v.startsWith('https://') && v.length <= 2048

export async function fetchBilling(signal?: AbortSignal): Promise<Billing> {
  const response = await request('/api/v1/billing', { headers: optionalAuth(), signal }, 15_000)
  if (!response.ok) throw await toApiError(response)
  const d: unknown = await response.json().catch(() => null)
  if (!isRecord(d) || typeof d.enabled !== 'boolean' || (d.plan !== 'free' && d.plan !== 'pro')) throw BAD_RESPONSE()
  return {
    enabled: d.enabled,
    priceLabel: typeof d.price_label === 'string' ? d.price_label.slice(0, 60) : '',
    plan: d.plan,
    status: typeof d.status === 'string' ? d.status : null,
    currentPeriodEnd: typeof d.current_period_end === 'string' ? d.current_period_end : null,
    portalUrl: isHttps(d.portal_url) ? d.portal_url : null,
  }
}

/** Adresse de paiement du prestataire pour le compte connecté (jamais ouverte sans validation https). */
export async function startCheckout(signal?: AbortSignal): Promise<string> {
  const response = await request('/api/v1/billing/checkout', { method: 'POST', headers: optionalAuth(), signal }, 20_000)
  if (!response.ok) throw await toApiError(response, 'Paiement indisponible pour le moment.')
  const d: unknown = await response.json().catch(() => null)
  if (!isRecord(d) || !isHttps(d.url)) throw BAD_RESPONSE()
  return d.url
}
