import { useEffect, useRef, useState } from 'react'
import { loadGoogle } from '../lib/google'

/** Bouton officiel « Se connecter avec Google » (rendu par Google). Le jeton reçu est vérifié par NOTRE serveur. */
export function GoogleSignInButton({ clientId, onCredential }: { clientId: string; onCredential: (credential: string) => void }) {
  const holder = useRef<HTMLDivElement>(null)
  const [failed, setFailed] = useState(false)
  const callback = useRef(onCredential)
  callback.current = onCredential

  useEffect(() => {
    let alive = true
    loadGoogle()
      .then((id) => {
        if (!alive || !holder.current) return
        id.initialize({
          client_id: clientId,
          callback: (r) => {
            if (r.credential) callback.current(r.credential)
          },
          auto_select: false,
        })
        id.renderButton(holder.current, { type: 'standard', theme: 'outline', size: 'medium', text: 'signin_with', shape: 'rectangular', locale: 'fr' })
      })
      .catch(() => alive && setFailed(true))
    return () => {
      alive = false
    }
  }, [clientId])

  if (failed) {
    return <span className="text-xs text-neutral-500">Connexion Google indisponible (bloquée par le navigateur ?).</span>
  }
  return <div ref={holder} aria-label="Se connecter avec Google" className="min-h-[32px]" />
}
