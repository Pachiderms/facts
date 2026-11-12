import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, transcribeAudio } from '../api/client'
import { pickMimeType, VOICE_MAX_SECONDS } from '../lib/voice'

export type VoiceState = 'idle' | 'recording' | 'transcribing'

/**
 * Enregistre au micro puis transcrit côté serveur. Le texte est remis à `onText` pour relecture :
 * il n'est jamais envoyé automatiquement. Le micro est libéré dès la fin de l'enregistrement.
 */
export function useVoiceRecorder(onText: (text: string) => void) {
  const [state, setState] = useState<VoiceState>('idle')
  const [secondsLeft, setSecondsLeft] = useState(VOICE_MAX_SECONDS)
  const [error, setError] = useState<string | null>(null)

  const recorder = useRef<MediaRecorder | null>(null)
  const stream = useRef<MediaStream | null>(null)
  const chunks = useRef<Blob[]>([])
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)
  const discard = useRef(false)
  const abort = useRef<AbortController | null>(null)
  const alive = useRef(true)
  const onTextRef = useRef(onText)
  onTextRef.current = onText

  const release = useCallback(() => {
    if (timer.current) clearInterval(timer.current)
    timer.current = null
    stream.current?.getTracks().forEach((t) => t.stop())
    stream.current = null
  }, [])

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
      discard.current = true
      if (recorder.current?.state === 'recording') recorder.current.stop()
      abort.current?.abort()
      release()
    }
  }, [release])

  const finish = useCallback(async (type: string) => {
    release()
    if (discard.current || !alive.current) {
      if (alive.current) setState('idle')
      return
    }
    const blob = new Blob(chunks.current, { type })
    chunks.current = []
    if (blob.size === 0) {
      setError("Aucun son enregistré. Vérifiez votre micro.")
      setState('idle')
      return
    }
    setState('transcribing')
    abort.current = new AbortController()
    try {
      const text = await transcribeAudio(blob, abort.current.signal)
      if (alive.current && !discard.current) onTextRef.current(text)
    } catch (e) {
      if (alive.current && !discard.current) {
        setError(e instanceof ApiError ? e.message : 'La transcription a échoué. Réessayez.')
      }
    } finally {
      if (alive.current) setState('idle')
    }
  }, [release])

  const start = useCallback(async () => {
    if (state !== 'idle') return
    setError(null)
    discard.current = false
    let media: MediaStream
    try {
      media = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (e) {
      const denied = e instanceof DOMException && (e.name === 'NotAllowedError' || e.name === 'SecurityError')
      setError(denied ? "Accès au micro refusé. Autorisez-le dans votre navigateur." : 'Micro introuvable.')
      return
    }
    if (!alive.current) {
      media.getTracks().forEach((t) => t.stop())
      return
    }
    stream.current = media
    const mime = pickMimeType()
    let rec: MediaRecorder
    try {
      rec = mime ? new MediaRecorder(media, { mimeType: mime }) : new MediaRecorder(media)
    } catch {
      release()
      setError("L'enregistrement n'est pas pris en charge par ce navigateur.")
      return
    }
    recorder.current = rec
    chunks.current = []
    rec.ondataavailable = (e) => {
      if (e.data.size > 0) chunks.current.push(e.data)
    }
    rec.onstop = () => void finish(rec.mimeType || mime || 'audio/webm')
    rec.start()
    setSecondsLeft(VOICE_MAX_SECONDS)
    setState('recording')
    let left = VOICE_MAX_SECONDS
    timer.current = setInterval(() => {
      left -= 1
      setSecondsLeft(left)
      if (left <= 0 && rec.state === 'recording') rec.stop() // arrêt automatique au plafond
    }, 1000)
  }, [state, finish, release])

  /** Termine l'enregistrement et lance la transcription. */
  const stop = useCallback(() => {
    if (recorder.current?.state === 'recording') recorder.current.stop()
  }, [])

  /** Abandonne : rien n'est envoyé au serveur. */
  const cancel = useCallback(() => {
    discard.current = true
    abort.current?.abort()
    if (recorder.current?.state === 'recording') recorder.current.stop()
    else {
      release()
      setState('idle')
    }
  }, [release])

  return { state, secondsLeft, error, start, stop, cancel, clearError: () => setError(null) }
}
