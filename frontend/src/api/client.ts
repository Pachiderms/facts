import { getParticipantToken } from '../lib/identity'
import type { CheckResponse, CreatedRoom, CreateRoomInput, RoomLookup, RoomSummary, Verdict } from './types'

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
      headers: { 'Content-Type': 'application/json' },
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
      headers: { 'Content-Type': 'application/json' },
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
      headers: { 'Content-Type': 'application/json' },
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
