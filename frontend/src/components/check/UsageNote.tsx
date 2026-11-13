import { useEffect, useState } from 'react'
import { fetchUsage, type Usage } from '../../api/client'
import { useAuth } from '../../hooks/useAuth'

/** Quota du jour (lecture seule) et état du service. Discret : absent tant que le serveur n'a pas répondu. */
export function UsageNote({ refreshKey, kind = 'checks' }: { refreshKey: unknown; kind?: 'checks' | 'debate' }) {
  const { user, enabled } = useAuth()
  const [usage, setUsage] = useState<Usage | null>(null)
  const userId = user?.id ?? null

  useEffect(() => {
    const controller = new AbortController()
    fetchUsage(controller.signal)
      .then(setUsage)
      .catch(() => setUsage(null)) // statut inconnu : on n'affiche rien plutôt qu'un faux chiffre
    return () => controller.abort()
  }, [refreshKey, userId])

  if (!usage) return null
  const { remaining, limit } = kind === 'debate' ? usage.debate : usage.checks
  const plural = remaining > 1 ? 's' : ''
  return (
    <div className="mt-2 space-y-1 text-[11px] text-neutral-500" aria-live="polite">
      <p>
        {remaining === 0
          ? 'Limite du jour atteinte. Revenez demain.'
          : kind === 'debate'
            ? `${remaining} message${plural} vérifié${plural} possible${plural} aujourd’hui sur ${limit} (au-delà, vos messages restent publiés sans vérification).`
            : `${remaining} vérification${plural} restante${plural} aujourd’hui sur ${limit}.`}
        {usage.plan === 'anonymous' && enabled && ' Un compte gratuit augmente cette limite.'}
      </p>
      {usage.degraded && <p>Le service est très sollicité : les réponses peuvent être un peu moins précises ou plus lentes.</p>}
    </div>
  )
}
