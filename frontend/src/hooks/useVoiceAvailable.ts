import { useEffect, useState } from 'react'
import { fetchFeatures } from '../api/client'
import { voiceSupported } from '../lib/voice'

/** Vrai si le navigateur sait enregistrer ET si le serveur propose la transcription. */
export function useVoiceAvailable(): boolean {
  const [available, setAvailable] = useState(false)
  useEffect(() => {
    if (!voiceSupported()) return // navigateur sans micro : inutile d'interroger le serveur
    const controller = new AbortController()
    void fetchFeatures(controller.signal).then((f) => {
      if (!controller.signal.aborted) setAvailable(f.voice)
    })
    return () => controller.abort()
  }, [])
  return available
}
