import { useEffect, useState } from 'react'
import { getFeatures } from '../api/client'
import { voiceSupported } from '../lib/voice'

/** Vrai si le navigateur sait enregistrer ET si le serveur propose la transcription. */
export function useVoiceAvailable(): boolean {
  const [available, setAvailable] = useState(false)
  useEffect(() => {
    if (!voiceSupported()) return // navigateur sans micro : inutile d'interroger le serveur
    let alive = true
    void getFeatures().then((f) => {
      if (alive) setAvailable(f.voice)
    })
    return () => {
      alive = false
    }
  }, [])
  return available
}
