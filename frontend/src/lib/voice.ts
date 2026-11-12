/** Saisie vocale : choix du format d'enregistrement et consentement. */

/** Durée maximale d'un message vocal (alignée sur le plafond du serveur). */
export const VOICE_MAX_SECONDS = 30

const CONSENT_KEY = 'facts.voice-consent'

/** Formats essayés dans l'ordre : Chrome/Firefox (webm/ogg opus), Safari (mp4). Tous acceptés par le serveur. */
const MIME_CANDIDATES = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4'] as const

export function voiceSupported(): boolean {
  return typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== 'undefined'
}

export function pickMimeType(): string | undefined {
  if (typeof MediaRecorder === 'undefined' || typeof MediaRecorder.isTypeSupported !== 'function') return undefined
  return MIME_CANDIDATES.find((m) => MediaRecorder.isTypeSupported(m))
}

export function hasVoiceConsent(): boolean {
  try {
    return localStorage.getItem(CONSENT_KEY) === '1'
  } catch {
    return false
  }
}

export function giveVoiceConsent(): void {
  try {
    localStorage.setItem(CONSENT_KEY, '1')
  } catch {
    /* sans stockage : le consentement sera redemandé */
  }
}
